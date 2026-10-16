import json
from collections.abc import AsyncIterator

import httpx
import pytest
from asgi_lifespan import LifespanManager

from app.auth import hash_key
from app.config import Settings
from app.main import create_app
from app.ratelimit import TokenBucketLimiter

KEY = "sk-test-key"
AUTH = {"Authorization": f"Bearer {KEY}"}


async def _astream(data: bytes) -> AsyncIterator[bytes]:
    yield data


def _json(data: object, status: int = 200) -> httpx.Response:
    # Real upstream responses are streams; mimic that so the proxy's aiter_raw() works.
    return httpx.Response(
        status,
        headers={"content-type": "application/json"},
        content=_astream(json.dumps(data).encode()),
    )


def ollama_mock(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/version":
        return _json({"version": "0.12.0"})
    if request.url.path == "/api/tags":
        return _json({"models": [{"name": "tiny:latest"}]})
    if request.url.path == "/api/chat":
        body = json.loads(request.content)
        chunks = [
            json.dumps({"message": {"content": w}, "done": False}) + "\n" for w in ["Hel", "lo"]
        ] + [json.dumps({"done": True, "model": body["model"]}) + "\n"]
        return httpx.Response(
            200,
            headers={"content-type": "application/x-ndjson"},
            content=_astream("".join(chunks).encode()),
        )
    return _json({"error": "not found"}, 404)


def make(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "ollama_url": "http://ollama",
        "api_key_hashes": hash_key(KEY),
        "rate_limit_rpm": 600,
        "rate_limit_burst": 50,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async with make_client(make()) as c:
        yield c


def make_client(settings: Settings) -> "_Ctx":
    return _Ctx(settings)


class _Ctx:
    def __init__(self, settings: Settings) -> None:
        self.app = create_app(settings, transport=httpx.MockTransport(ollama_mock))

    async def __aenter__(self) -> httpx.AsyncClient:
        self.lm = LifespanManager(self.app)
        await self.lm.__aenter__()
        self.c = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="http://gw"
        )
        return self.c

    async def __aexit__(self, *exc: object) -> None:
        await self.c.aclose()
        await self.lm.__aexit__(None, None, None)


async def test_health(client: httpx.AsyncClient) -> None:
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "ollama": "0.12.0"}


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}, {"x-api-key": "nope"}])
async def test_rejects_missing_or_invalid_key(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    r = await client.get("/api/tags", headers=headers)
    assert r.status_code == 401


async def test_accepts_x_api_key_header(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/tags", headers={"x-api-key": KEY})
    assert r.status_code == 200
    assert r.json()["models"][0]["name"] == "tiny:latest"


async def test_streams_chat(client: httpx.AsyncClient) -> None:
    body = {"model": "tiny", "messages": [{"role": "user", "content": "hi"}]}
    lines = []
    async with client.stream("POST", "/api/chat", json=body, headers=AUTH) as r:
        assert r.status_code == 200
        assert r.headers["x-accel-buffering"] == "no"
        async for line in r.aiter_lines():
            if line:
                lines.append(json.loads(line))
    text = "".join(c["message"]["content"] for c in lines if not c["done"])
    assert text == "Hello"
    assert lines[-1]["done"] is True


async def test_blocks_admin_endpoints(client: httpx.AsyncClient) -> None:
    for path in ("/api/pull", "/api/delete", "/api/create"):
        assert (await client.post(path, json={}, headers=AUTH)).status_code == 404


async def test_model_allow_list() -> None:
    async with make_client(make(allowed_models="tiny")) as c:
        ok = await c.post("/api/chat", json={"model": "tiny", "messages": []}, headers=AUTH)
        assert ok.status_code == 200
        no = await c.post("/api/chat", json={"model": "huge", "messages": []}, headers=AUTH)
        assert no.status_code == 403


async def test_body_limit() -> None:
    async with make_client(make(max_body_bytes=10)) as c:
        r = await c.post("/api/chat", content=b"x" * 100, headers=AUTH)
        assert r.status_code == 413


async def test_rate_limit_returns_429() -> None:
    async with make_client(make(rate_limit_rpm=1, rate_limit_burst=2)) as c:
        codes = [(await c.get("/api/tags", headers=AUTH)).status_code for _ in range(3)]
        assert codes == [200, 200, 429]
        r = await c.get("/api/tags", headers=AUTH)
        assert int(r.headers["retry-after"]) >= 1


async def test_upstream_down_is_502_and_health_degraded() -> None:
    def boom(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    app = create_app(make(), transport=httpx.MockTransport(boom))
    async with (
        LifespanManager(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gw") as c,
    ):
        assert (await c.get("/api/tags", headers=AUTH)).status_code == 502
        assert (await c.get("/healthz")).status_code == 503


async def test_token_bucket_refills() -> None:
    now = [0.0]
    rl = TokenBucketLimiter(rpm=60, burst=1, clock=lambda: now[0])
    assert (await rl.acquire("k"))[0]
    allowed, retry = await rl.acquire("k")
    assert not allowed
    assert retry == pytest.approx(1.0)
    now[0] = 1.0
    assert (await rl.acquire("k"))[0]
