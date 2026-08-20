# Recovery Restart

Arquivo: `backend/services/batch_runner.py`
Classe/função: `recover_stale_batches`
Antes: restart durante item running não tinha política segura persistente.
Depois: item `running` com batch heartbeat stale vira `interrupted`; pending posterior permanece elegível.
Motivo: não repetir automaticamente uma operação externa de resultado incerto.
Banco/estado afetado: `batch_items.status`, `batch_items.error_data`, `batches.status`.
Transação: todos os itens stale de um batch são marcados em uma transação.
Recovery: idempotente; segunda execução não encontra item `running` já interrompido.
Teste: `test_stale_running_item_interrupted_and_pending_resume`.
Resultado: `success`, `interrupted`, `pending` e batch `queued`.
Risco restante: recovery não decide se o sistema externo concluiu a operação; isso é intencional.

Cenário A: backend cai, worker continua.
Comportamento: FastAPI não controla o batch; worker mantém heartbeat, advisory lock e execução. API volta depois e lê progresso do PostgreSQL.

Cenário B: worker cai entre clientes.
Comportamento: último item já persistido fica `success`/`error`; se nenhum item está `running`, pending seguem elegíveis após recovery e batch volta a `queued`.

Cenário C: worker cai durante cliente.
Comportamento: item `running` vira `interrupted` com `previous_worker_id`, `last_heartbeat_at` e `recovered_at`; o item não é reexecutado automaticamente. Pending posteriores podem continuar.
