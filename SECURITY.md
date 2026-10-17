# Security

## Reporting

Use GitHub's private "Report a vulnerability" button on this repository. I aim to reply within 72 hours.

## Threat model

- **Assets:** prompts and completions (often confidential), server CPU and RAM, API keys.
- **Actors:** internet scanners looking for open Ollama ports, holders of leaked API keys, abusive authenticated clients.
- **Entry points:** Caddy on 80/443, the gateway behind it, Open WebUI when the `ui` profile is on.
- **Defaults that matter:** Ollama publishes no ports and sits on a backend network; the gateway requires an API key (stored only as SHA-256, compared in constant time), rate-limits per key, proxies inference endpoints only (`pull`, `delete`, `create`, `copy`, `push` are unreachable), enforces an optional model allow-list and a streamed body-size limit, and runs read-only, non-root, with all capabilities dropped; Caddy terminates TLS with automatic certificates.
- **Verification:** unit tests for auth, rate limits, allow-lists and body limits; CI boots the full stack and streams a completion through TLS.

## Not provided

- Per-tenant isolation. Every valid key can use every allowed model.
- Prompt or output filtering.
- Persistence or audit logging of prompts. Add it deliberately if you need it, and treat those logs as sensitive.
