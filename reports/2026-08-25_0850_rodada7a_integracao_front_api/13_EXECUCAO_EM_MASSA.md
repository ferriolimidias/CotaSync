# Execução em Massa

Endpoints:
- `POST /api/v1/batches`.
- `GET /api/v1/batches`.
- `GET /api/v1/batches/{id}`.
- `POST /api/v1/batches/{id}/cancel`.
- `GET /api/v1/batches/{id}/results.csv`.

Payload de criação: `action_id`, `client_group`, `client_ids`, `requested_by=react`, `delay_between_rows_seconds`; header `Idempotency-Key`.

Regra de concorrência: UI informa processamento de 1 cliente por vez e não expõe controle de paralelismo.

Status: OK técnico, mutação real não executada.
