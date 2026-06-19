#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${COTASYNC_API_BASE_URL:-http://127.0.0.1:8100}"

curl -fsS "$BASE_URL/health" | python3 -m json.tool
curl -fsS "$BASE_URL/api/actions" | python3 -m json.tool
curl -fsS "$BASE_URL/api/runs" | python3 -m json.tool

RUN_404_BODY="$(mktemp)"
RUN_404_STATUS="$(curl -sS -o "$RUN_404_BODY" -w "%{http_code}" "$BASE_URL/api/runs/nao-existe")"
python3 -m json.tool "$RUN_404_BODY"
test "$RUN_404_STATUS" = "404"

ACTION_404_BODY="$(mktemp)"
ACTION_404_STATUS="$(
  curl -sS -o "$ACTION_404_BODY" -w "%{http_code}" \
    -H "Content-Type: application/json" \
    -d '{"variables":{"cpf":"12345678900"},"mode":"sync","requested_by":"api"}' \
    "$BASE_URL/api/actions/nao-existe/run"
)"
python3 -m json.tool "$ACTION_404_BODY"
test "$ACTION_404_STATUS" = "404"

if [ -n "${COTASYNC_RUN_FIXTURE_ACTION_ID:-}" ]; then
  RUN_BODY="$(mktemp)"
  curl -fsS -o "$RUN_BODY" \
    -H "Content-Type: application/json" \
    -d "${COTASYNC_RUN_FIXTURE_PAYLOAD:-{\"variables\":{\"cpf\":\"12345678900\"},\"mode\":\"sync\",\"requested_by\":\"api\"}}" \
    "$BASE_URL/api/actions/$COTASYNC_RUN_FIXTURE_ACTION_ID/run"
  python3 -m json.tool "$RUN_BODY"
  RUN_ID="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["run"]["id"])' "$RUN_BODY")"
  curl -fsS "$BASE_URL/api/runs/$RUN_ID" | python3 -m json.tool
fi
