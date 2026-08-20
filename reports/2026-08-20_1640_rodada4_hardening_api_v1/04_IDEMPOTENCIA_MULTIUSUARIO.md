# Idempotência Multiusuário

Arquivo: `alembic/versions/0004_scoped_batch_idempotency.py`
Função/endpoint: `upgrade`
Antes: `batches.idempotency_key` tinha unicidade global.
Depois: unicidade composta `uq_batches_idempotency_scope` em `idempotency_user_id`, `idempotency_operation`, `idempotency_key`.
Motivo: usuários diferentes podem enviar a mesma key.
Impacto: PostgreSQL protege condição de corrida.
Teste: `test_idempotency_race_same_user_same_payload_creates_one_batch`.
Resultado: duas chamadas simultâneas geraram 1 batch e 1 item.
Risco restante: `idempotency_user_id` usa username autenticado; tenant formal futuro pode ampliar escopo.

Arquivo: `backend/services/batch_runner.py`
Função/endpoint: `batch_idempotency_fingerprint`
Antes: mesma key sempre retornava batch existente.
Depois: fingerprint SHA-256 do payload relevante.
Motivo: mesma key com payload diferente deve ser conflito.
Impacto: erro `BatchIdempotencyConflict`.
Teste: `test_idempotency_same_key_different_payload_conflicts`.
Resultado: conflito seguro.
