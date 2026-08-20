# Schema Migration

Arquivo: `alembic/versions/0003_persistent_batch_worker.py`
Classe/função: `upgrade`
Antes: `batches` já tinha `status`, `cancel_requested`, `idempotency_key`, `heartbeat_at`; não havia tabela de worker.
Depois: adiciona `batches.worker_id`, `interrupted_items`, `cancelled_items`, índices e `worker_instances`.
Motivo: permitir lock/estado/recovery persistentes sem Redis/Celery.
Banco/estado afetado: `batches`, `worker_instances`.
Transação: Alembic PostgreSQL transacional.
Recovery: `worker_instances` registra heartbeat e item atual; `batches.worker_id` preserva executor anterior para diagnóstico.
Teste: `alembic upgrade head`, `alembic current`, `alembic heads`.
Resultado: `0003_persistent_batch_worker (head)`.
Risco restante: constraints formais de enum/check de estados ficaram fora para evitar quebra de dados legados; estados são consolidados no código.

Compatibilidade:
- `pending` -> `queued`.
- `success` -> `completed`.
- `partial_success` -> `completed_with_errors`.
- `canceled` -> `cancelled`.
- item `skipped` -> `cancelled`.
