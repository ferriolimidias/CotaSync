#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${COTASYNC_API_BASE_URL:-http://127.0.0.1:8100}"

curl -fsS "$BASE_URL/health" | python3 -m json.tool
curl -fsS "$BASE_URL/api/actions" | python3 -m json.tool
curl -fsS "$BASE_URL/api/actions/raw" | python3 -m json.tool
