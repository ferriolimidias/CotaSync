#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${COTASYNC_API_BASE_URL:-http://127.0.0.1:8100}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UI_MAP="$ROOT_DIR/data/ui_map.json"
FIXTURE="$ROOT_DIR/tests/fixtures/ui_map_local_action.json"
RUNS_FILE="$ROOT_DIR/data/runs/runs.json"
TEST_CPF="123456789""00"
ACTION_KEY="Teste Local Eco CPF"
RUNS_EXISTED=0

TMP_DIR="$(mktemp -d)"
UI_MAP_BACKUP="$TMP_DIR/ui_map.backup.json"

cleanup() {
  if [ -f "$UI_MAP_BACKUP" ]; then
    cp "$UI_MAP_BACKUP" "$UI_MAP"
  fi
  cleanup_test_runs || true
  remove_empty_generated_runs_file || true
  rm -rf "$TMP_DIR"
}

cleanup_test_runs() {
  if [ ! -f "$RUNS_FILE" ]; then
    return
  fi
  python3 - "$RUNS_FILE" "$ACTION_KEY" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
action_key = sys.argv[2]
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except json.JSONDecodeError:
    raise SystemExit("runs.json invalido; limpeza abortada")

runs = payload.get("runs", [])
if not isinstance(runs, list):
    raise SystemExit("runs.json sem lista runs; limpeza abortada")

payload["runs"] = [
    run for run in runs
    if not (
        isinstance(run, dict)
        and run.get("requested_by") == "test"
        and run.get("action_key") == action_key
    )
]
path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
}

remove_empty_generated_runs_file() {
  if [ "$RUNS_EXISTED" = "1" ] || [ ! -f "$RUNS_FILE" ]; then
    return
  fi
  python3 - "$RUNS_FILE" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
if payload == {"runs": []}:
    path.unlink()
PY
}

json_value() {
  python3 -c 'import json,sys; data=json.load(open(sys.argv[1])); print(eval(sys.argv[2], {}, {"data": data}))' "$1" "$2"
}

assert_no_clear_cpf() {
  local file="$1"
  if grep -Fq "$TEST_CPF" "$file"; then
    echo "CPF em claro encontrado em $file" >&2
    return 1
  fi
}

trap cleanup EXIT

mkdir -p "$(dirname "$UI_MAP")" "$(dirname "$RUNS_FILE")"
if [ -f "$RUNS_FILE" ]; then
  RUNS_EXISTED=1
fi
if [ -f "$UI_MAP" ]; then
  cp "$UI_MAP" "$UI_MAP_BACKUP"
else
  printf '{"acoes_conhecidas": {}}\n' > "$UI_MAP_BACKUP"
fi

cleanup_test_runs
cp "$FIXTURE" "$UI_MAP"

ACTIONS_BODY="$TMP_DIR/actions.json"
curl -fsS "$BASE_URL/api/actions" -o "$ACTIONS_BODY"
python3 -m json.tool "$ACTIONS_BODY" >/dev/null
ACTION_ID="$(
  python3 - "$ACTIONS_BODY" "$ACTION_KEY" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
for action in payload.get("actions", []):
    if action.get("key") == sys.argv[2]:
        print(action["id"])
        break
else:
    raise SystemExit("fixture action not found")
PY
)"

RUN_BODY="$TMP_DIR/run.json"
python3 - "$TEST_CPF" > "$TMP_DIR/run_payload.json" <<'PY'
import json
import sys

print(json.dumps({
    "variables": {"cpf": sys.argv[1]},
    "mode": "sync",
    "requested_by": "test",
}))
PY
curl -fsS \
  -H "Content-Type: application/json" \
  -d @"$TMP_DIR/run_payload.json" \
  "$BASE_URL/api/actions/$ACTION_ID/run" \
  -o "$RUN_BODY"
python3 -m json.tool "$RUN_BODY" >/dev/null
assert_no_clear_cpf "$RUN_BODY"

python3 - "$RUN_BODY" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
run = payload["run"]
assert payload["status"] == "ok"
assert run["status"] == "success"
assert run["result_summary"] == run["operational_summary"]
assert "Nenhum resultado final foi configurado" in run["operational_summary"]
assert run["technical_summary"]
assert run["variables"]["cpf"] == "*********00"
assert run["result_payload"]["echo"]["cpf"] == "*********00"
assert run["result_payload"]["fixture"] is True
PY

RUN_ID="$(json_value "$RUN_BODY" 'data["run"]["id"]')"

RUNS_BODY="$TMP_DIR/runs.json"
curl -fsS "$BASE_URL/api/runs?action_id=$ACTION_ID&status=success&limit=10" -o "$RUNS_BODY"
python3 -m json.tool "$RUNS_BODY" >/dev/null
assert_no_clear_cpf "$RUNS_BODY"

DETAIL_BODY="$TMP_DIR/run_detail.json"
curl -fsS "$BASE_URL/api/runs/$RUN_ID" -o "$DETAIL_BODY"
python3 -m json.tool "$DETAIL_BODY" >/dev/null
assert_no_clear_cpf "$DETAIL_BODY"

python3 - "$DETAIL_BODY" "$RUN_ID" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
run = payload["run"]
assert payload["status"] == "ok"
assert run["id"] == sys.argv[2]
assert run["status"] == "success"
assert run["requested_by"] == "test"
assert run["variables"]["cpf"] == "*********00"
assert run["result_payload"]["echo"]["cpf"] == "*********00"
PY

MISSING_BODY="$TMP_DIR/missing.json"
MISSING_STATUS="$(
  curl -sS -o "$MISSING_BODY" -w "%{http_code}" \
    -H "Content-Type: application/json" \
    -d '{"variables":{},"mode":"sync","requested_by":"test"}' \
    "$BASE_URL/api/actions/$ACTION_ID/run"
)"
test "$MISSING_STATUS" = "422"
python3 - "$MISSING_BODY" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload["detail"]["message"] == "Variaveis obrigatorias ausentes."
assert "cpf" in payload["detail"]["missing_variables"]
PY

NOT_FOUND_BODY="$TMP_DIR/not_found.json"
NOT_FOUND_STATUS="$(
  curl -sS -o "$NOT_FOUND_BODY" -w "%{http_code}" \
    -H "Content-Type: application/json" \
    -d @"$TMP_DIR/run_payload.json" \
    "$BASE_URL/api/actions/acao-inexistente/run"
)"
test "$NOT_FOUND_STATUS" = "404"
python3 - "$NOT_FOUND_BODY" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload["detail"] == "Acao nao encontrada."
PY

if [ -f "$RUNS_FILE" ]; then
  assert_no_clear_cpf "$RUNS_FILE"
fi

printf 'Contrato actions/runs validado com run_id=%s action_id=%s\n' "$RUN_ID" "$ACTION_ID"
