#!/usr/bin/env bash
set -euo pipefail

# Sobe API e UI na mesma imagem (adequado ao esqueleto; produção pode separar serviços).
cd /app

uvicorn backend.main:app --host 0.0.0.0 --port 8000 &
exec streamlit run frontend/app.py --server.port=8501 --server.address=0.0.0.0
