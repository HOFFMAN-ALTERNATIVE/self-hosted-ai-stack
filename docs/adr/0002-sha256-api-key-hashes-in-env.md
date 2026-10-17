# 0002. API keys as SHA-256 hashes in the environment

Status: accepted
Date: 2026-10-17

## Context
The gateway needs to recognise a handful of clients: a few apps and scripts per
server. The config should not contain raw keys, and the check runs on every request,
including each streamed completion.

## Options
1. Raw keys in `.env`: simplest, and anyone who reads the file or a backup holds
   working keys.
2. bcrypt or argon2 hashes: right for human passwords, but adds tens of milliseconds
   per request and protects nothing extra when the key is already random.
3. SHA-256 of a key with 32 random bytes (`sk-` plus `token_urlsafe(32)`), stored in
   `API_KEY_HASHES`, compared in constant time.

## Decision
Option 3. The keys are generated with high entropy, so a fast hash is enough to make
a leaked hash useless, and the check costs microseconds.

## Consequences
- `python -m app.keygen` prints a key for the client and the hash for `.env`.
- The check compares against every stored hash with `hmac.compare_digest`, so timing
  does not reveal which key nearly matched.
- The key hash doubles as the rate-limit identity.
- An empty `API_KEY_HASHES` rejects every request and logs a warning at startup.
- Rotation means editing `.env` and restarting the gateway. There is no key
  management UI and no per-key expiry. Revisit if the number of clients grows past a few.
