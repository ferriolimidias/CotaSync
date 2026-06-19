#!/usr/bin/env bash
set -euo pipefail

cd /app

seed_file() {
  local source_file="$1"
  local target_file="$2"
  local label="$3"

  mkdir -p "$(dirname "$target_file")"
  if [ -f "$target_file" ]; then
    echo "[entrypoint] Seed preservado: $target_file ja existe."
    return
  fi

  if [ -f "$source_file" ]; then
    cp "$source_file" "$target_file"
    echo "[entrypoint] Seed aplicado para $label: $target_file"
    return
  fi

  case "$label" in
    ui_map)
      printf '{"acoes_conhecidas": {}}\n' > "$target_file"
      ;;
    usuarios_autorizados)
      printf '{"numeros_permitidos": []}\n' > "$target_file"
      ;;
    *)
      printf '{}\n' > "$target_file"
      ;;
  esac
  echo "[entrypoint] Seed minimo criado para $label: $target_file"
}

mkdir -p data logs downloads
seed_file "/app/ui_map.json" "/app/data/ui_map.json" "ui_map"
seed_file "/app/usuarios_autorizados.json" "/app/data/usuarios_autorizados.json" "usuarios_autorizados"

case "${1:-all}" in
  backend)
    exec uvicorn backend.main:app --host 0.0.0.0 --port 8000
    ;;
  frontend)
    exec streamlit run frontend/app.py --server.port=8501 --server.address=0.0.0.0
    ;;
  all)
    uvicorn backend.main:app --host 0.0.0.0 --port 8000 &
    exec streamlit run frontend/app.py --server.port=8501 --server.address=0.0.0.0
    ;;
  *)
    exec "$@"
    ;;
esac
