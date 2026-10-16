import hashlib
import hmac

from fastapi import HTTPException, Request, status


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def extract_key(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("x-api-key")


def verify_api_key(request: Request, allowed_hashes: frozenset[str]) -> str:
    """Validate the API key; returns its hash (used as the rate-limit identity)."""
    raw = extract_key(request)
    if not raw:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Missing API key", headers={"WWW-Authenticate": "Bearer"}
        )
    digest = hash_key(raw)
    # compare against every hash in constant time to avoid timing side channels
    valid = False
    for allowed in allowed_hashes:
        valid |= hmac.compare_digest(digest, allowed)
    if not valid:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid API key", headers={"WWW-Authenticate": "Bearer"}
        )
    return digest
