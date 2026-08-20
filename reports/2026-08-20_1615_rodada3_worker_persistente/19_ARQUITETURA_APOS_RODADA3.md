# Arquitetura Após Rodada 3

Fluxo:
Frontend/Streamlit -> FastAPI -> PostgreSQL -> CotaSync Worker -> BrowserController/serviço existente -> desktop_browser_replay -> CDP/Playwright -> Chromium persistente.

Regra operacional:
- 1 browser operacional.
- 1 worker controlando o browser.
- 1 cliente por vez.
- execução estritamente sequencial.

Garantias:
- fila: PostgreSQL.
- lock: advisory lock PostgreSQL `76003001`.
- heartbeat: `worker_instances` e `batches.heartbeat_at`.
- recovery: item running stale vira `interrupted`, pending seguro continua.
- cancelamento: cancel-after-current.
- idempotência: `Idempotency-Key` persistido em `batches.idempotency_key`.

Não introduzido:
- Redis.
- Celery.
- RabbitMQ.
- Kafka.
- Browserless.
- fast-track.
- scheduler novo.
- IA de reparo.
