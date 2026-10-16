import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask

from app.auth import verify_api_key
from app.config import Settings, get_settings
from app.ratelimit import TokenBucketLimiter

log = logging.getLogger("gateway")

# Upstream endpoints the gateway exposes. Anything else (pull/delete/create) is blocked.
PROXIED = {
    ("POST", "api/chat"),
    ("POST", "api/generate"),
    ("POST", "api/embed"),
    ("POST", "api/embeddings"),
    ("GET", "api/tags"),
    ("POST", "api/show"),
    ("POST", "v1/chat/completions"),
    ("POST", "v1/completions"),
    ("POST", "v1/embeddings"),
    ("GET", "v1/models"),
}
HOP_BY_HOP = {"connection", "keep-alive", "transfer-encoding", "content-length", "content-encoding"}


def create_app(
    settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None
) -> FastAPI:
    s = settings or get_settings()
    limiter = TokenBucketLimiter(s.rate_limit_rpm, s.rate_limit_burst)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.client = httpx.AsyncClient(
            base_url=s.ollama_url,
            transport=transport,
            timeout=httpx.Timeout(s.upstream_timeout, connect=5.0),
        )
        if not s.key_hashes:
            log.warning("API_KEY_HASHES is empty — every request will be rejected")
        yield
        await app.state.client.aclose()

    app = FastAPI(
        title="AI gateway", version="1.0.0", lifespan=lifespan, docs_url=None, redoc_url=None
    )

    async def rate_limited_key(request: Request) -> str:
        key_hash = verify_api_key(request, s.key_hashes)
        allowed, retry = await limiter.acquire(key_hash)
        if not allowed:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Rate limit exceeded",
                headers={"Retry-After": str(max(1, round(retry)))},
            )
        return key_hash

    @app.get("/healthz")
    async def healthz(request: Request) -> Response:
        try:
            r = await request.app.state.client.get("/api/version", timeout=3.0)
            upstream = r.json().get("version", "unknown") if r.is_success else None
        except httpx.HTTPError:
            upstream = None
        code = 200 if upstream else 503
        return JSONResponse(
            {"status": "ok" if upstream else "degraded", "ollama": upstream}, status_code=code
        )

    @app.api_route("/{path:path}", methods=["GET", "POST"])
    async def proxy(
        path: str, request: Request, _: Annotated[str, Depends(rate_limited_key)]
    ) -> Response:
        if (request.method, path) not in PROXIED:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

        body = await request.body()
        if len(body) > s.max_body_bytes:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Request body too large")
        if body and s.models:
            try:
                payload: Any = json.loads(body)
            except json.JSONDecodeError:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid JSON") from None
            model = payload.get("model") if isinstance(payload, dict) else None
            if model not in s.models:
                raise HTTPException(status.HTTP_403_FORBIDDEN, f"Model not allowed: {model}")

        client: httpx.AsyncClient = request.app.state.client
        upstream_req = client.build_request(
            request.method,
            f"/{path}",
            content=body,
            params=request.query_params,
            headers={"content-type": request.headers.get("content-type", "application/json")},
        )
        try:
            upstream = await client.send(upstream_req, stream=True)
        except httpx.HTTPError as e:
            log.warning("upstream error: %s", e)
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Upstream unavailable") from None

        headers = {k: v for k, v in upstream.headers.items() if k.lower() not in HOP_BY_HOP}
        headers["x-accel-buffering"] = "no"  # disable proxy buffering for token streaming
        return StreamingResponse(
            upstream.aiter_raw(),
            status_code=upstream.status_code,
            headers=headers,
            background=BackgroundTask(upstream.aclose),
        )

    return app


app = create_app()
