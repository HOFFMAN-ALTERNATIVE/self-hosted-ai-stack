# 0001. Put a small gateway in front of Ollama instead of exposing it

Status: accepted
Date: 2026-10-17

## Context
Ollama's HTTP API has no authentication. The same API that runs inference can also
pull, delete and create models, so anyone who reaches it can fill the disk or wipe
the models. Apps still need to call it over HTTPS, with streaming, from outside the host.

## Options
1. Publish Ollama's port behind a firewall rule: no code, but one mistake exposes
   model management to the internet, and there is no per-client identity.
2. Basic auth or a static header check in Caddy: cheap, but one shared secret, no
   per-key rate limit, and no way to block management endpoints by model or path.
3. A FastAPI gateway on the same private network: per-key auth, a token bucket per
   key, an endpoint allow-list, a model allow-list and a body size limit, with raw
   byte streaming back to the client.

## Decision
Option 3. Ollama publishes no ports at all, and the gateway is the only API path in.
The extra service is small and fully under test.

## Consequences
- `pull`, `delete`, `create`, `copy` and `push` are unreachable from outside.
- Native Ollama and OpenAI-compatible endpoints both pass through, so existing SDKs work.
- Caddy proxies with `flush_interval -1` and a 10 minute read timeout so tokens stream
  as they are generated.
- The gateway trusts `X-Forwarded-For` from any peer. That holds only while it
  publishes no ports and sits behind Caddy.
- One more component to upgrade when Ollama changes its API.
