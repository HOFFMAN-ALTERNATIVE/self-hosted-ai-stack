"""Generate an API key and its SHA-256 hash: python -m app.keygen"""

import secrets

from app.auth import hash_key

if __name__ == "__main__":
    key = "sk-" + secrets.token_urlsafe(32)
    print(f"API key (give to client):  {key}")
    print(f"Hash (put in API_KEY_HASHES): {hash_key(key)}")
