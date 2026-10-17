# 0003. Rate-limit with an in-process token bucket per key

Status: accepted
Date: 2026-10-17

## Context
On a CPU-only box one generation can hold all cores for many seconds, so a single
client can starve everyone else. The stack runs one gateway replica, and adding a
datastore only for rate limiting would double the moving parts on the API path.

## Options
1. No limit, rely on Ollama's queue: fair to nobody, one script floods the queue.
2. Redis-backed limiter: correct across replicas and restarts, but one more service
   to run and secure for a single-replica deployment.
3. A token bucket per key in the gateway's memory: refill of `RATE_LIMIT_RPM / 60`
   tokens per second, capacity `RATE_LIMIT_BURST`, `429` with `Retry-After` when empty.

## Decision
Option 3. With one replica, in-memory state gives the same behaviour as Redis with
no extra service.

## Consequences
- Defaults are 60 requests per minute with a burst of 10 per key.
- Limits reset when the gateway restarts.
- Running several replicas multiplies the effective limit. That is the trigger to move
  the bucket to Redis.
- The limit counts requests, not tokens generated. A long completion costs the same as
  a short one.
