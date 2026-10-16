#!/usr/bin/env bash
# End-to-end test through Caddy (TLS) -> gateway (auth, rate limit) -> Ollama (real tiny model).
set -euo pipefail
API_HOST=${API_DOMAIN:-api.localhost}
KEY=${E2E_API_KEY:?E2E_API_KEY required}
MODEL=${E2E_MODEL:-qwen2.5:0.5b}
CURL=(curl -sS -k --resolve "$API_HOST:443:127.0.0.1" --max-time 300)
URL="https://$API_HOST"

step() { printf '\n\e[36m== %s\e[0m\n' "$*"; }

step "TLS + health through Caddy"
for _ in $(seq 30); do "${CURL[@]}" -fo /dev/null "$URL/healthz" && break; sleep 2; done
"${CURL[@]}" -f "$URL/healthz"
"${CURL[@]}" -sI "$URL/healthz" | grep -qi '^strict-transport-security' || { echo "missing HSTS"; exit 1; }

step "auth required"
code=$("${CURL[@]}" -o /dev/null -w '%{http_code}' "$URL/api/tags")
[[ "$code" == 401 ]] || { echo "expected 401, got $code"; exit 1; }

step "list models"
"${CURL[@]}" -f -H "Authorization: Bearer $KEY" "$URL/api/tags" | jq -e --arg m "$MODEL" '.models[] | select(.name == $m)' >/dev/null

step "streaming chat (native API)"
chunks=$("${CURL[@]}" -fN -H "Authorization: Bearer $KEY" "$URL/api/chat" \
  -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with one word: hello\"}],\"options\":{\"num_predict\":16}}" | wc -l)
echo "received $chunks NDJSON chunks"
(( chunks > 2 )) || { echo "expected streamed chunks"; exit 1; }

step "OpenAI-compatible endpoint"
"${CURL[@]}" -f -H "Authorization: Bearer $KEY" -H 'content-type: application/json' "$URL/v1/chat/completions" \
  -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Say hi\"}],\"max_tokens\":8}" \
  | jq -e '.choices[0].message.content | length > 0' >/dev/null

step "admin endpoints blocked"
code=$("${CURL[@]}" -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $KEY" -d '{"model":"x"}' "$URL/api/pull")
[[ "$code" == 404 ]] || { echo "expected 404 for /api/pull, got $code"; exit 1; }

echo; echo "E2E passed."
