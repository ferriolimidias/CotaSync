# Imagem única do CotaSync: FastAPI (8000) + Streamlit (8501).
# O Playwright aqui é apenas cliente CDP; o Chromium roda no serviço Browserless.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Não instalamos browsers locais: `connect_over_cdp` usa o Browserless.
COPY backend ./backend
COPY frontend ./frontend
COPY ui_map.json usuarios_autorizados.json ./

COPY scripts/docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 8000 8501

ENTRYPOINT ["/docker-entrypoint.sh"]
