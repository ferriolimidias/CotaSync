#!/usr/bin/env bash
set -euo pipefail

API_URL="${COTASYNC_API_BASE_URL:-http://127.0.0.1:8100}"
FRONTEND_URL="${COTASYNC_FRONTEND_URL:-http://127.0.0.1:3100}"
FRONTEND_CONTAINER="${COTASYNC_FRONTEND_CONTAINER:-cotasync_test_frontend}"
EXPECTED_INTERNAL_API_URL="http://cotasync_test_backend:8000"

actions_body="$(mktemp)"
frontend_headers="$(mktemp)"
frontend_logs="$(mktemp)"
trap 'rm -f "$actions_body" "$frontend_headers" "$frontend_logs"' EXIT

curl -fsS "$API_URL/api/actions" -o "$actions_body"
python3 - "$actions_body" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload.get("status") == "ok"
assert isinstance(payload.get("actions"), list)
PY

curl -fsSI "$FRONTEND_URL" -o "$frontend_headers"
grep -Eq '^HTTP/[0-9.]+ 200' "$frontend_headers"

configured_url="$(docker exec "$FRONTEND_CONTAINER" printenv COTASYNC_API_BASE_URL)"
test "$configured_url" = "$EXPECTED_INTERNAL_API_URL"

docker exec -i "$FRONTEND_CONTAINER" python3 - <<'PY'
from frontend.api_client import get_actions_for_ui

result = get_actions_for_ui()
assert result.source == "api", result
assert result.fallback_error is None, result
PY

docker logs --tail=120 "$FRONTEND_CONTAINER" >"$frontend_logs" 2>&1
if grep -Eiq 'Traceback|ActionsCatalogError|API de acoes indisponivel|Resposta invalida da API de acoes' "$frontend_logs"; then
  echo "Erro critico relacionado ao catalogo de acoes encontrado nos logs do frontend." >&2
  exit 1
fi

echo "Integracao Streamlit/API actions validada."
