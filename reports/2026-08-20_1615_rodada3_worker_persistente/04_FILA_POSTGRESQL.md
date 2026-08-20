# Fila PostgreSQL

Arquivo: `backend/services/batch_runner.py`
Classe/função: `claim_next_batch`
Antes: `find_running_batch` bloqueava criação e `asyncio.create_task` executava imediatamente.
Depois: batches ficam `queued`; worker faz claim FIFO com `FOR UPDATE SKIP LOCKED`.
Motivo: PostgreSQL é a fila e impede claim duplicado mesmo com dois workers.
Banco/estado afetado: `batches.status`, `batches.worker_id`, `batches.heartbeat_at`.
Transação: `select ... for update skip locked limit 1` e update no mesmo `SessionLocal.begin`.
Recovery: batch running stale volta para `queued` se há pending seguro.
Teste: `test_two_workers_do_not_claim_same_batch`.
Resultado: worker A claimou; worker B recebeu `None`.
Risco restante: não há prioridade; FIFO por `created_at, id`.

Arquivo: `backend/services/batch_runner.py`
Classe/função: `claim_next_item`
Antes: loop Python sobre lista em memória/JSON compatível.
Depois: próximo item vem de `batch_items` por `position ASC`, também com `FOR UPDATE SKIP LOCKED`.
Motivo: um item por vez, estado persistente.
Teste: `test_worker_executes_rows_sequentially_and_waits_delay`.
Resultado: não houve dois itens `running`.
