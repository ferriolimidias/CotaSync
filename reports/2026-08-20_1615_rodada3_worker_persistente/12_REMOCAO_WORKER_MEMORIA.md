# Remoção Worker Memória

Arquivo: `backend/services/batch_runner.py`
Classe/função: removidas `_desktop_batch_lock`, `_worker_tasks`, `_run_batch_worker`, `schedule_batch_worker`.
Antes: `asyncio.Lock` e `asyncio.create_task` executavam batches dentro do FastAPI.
Depois: batch runner não cria task de execução; apenas persiste fila/estado.
Motivo: processo FastAPI não deve controlar o browser para batches.
Banco/estado afetado: todos os estados de batch/item agora são fonte PostgreSQL.
Transação: execução antiga em memória removida.
Recovery: delegada ao worker persistente.
Teste: busca textual por `_worker_tasks`, `_run_batch_worker`, `schedule_batch_worker`.
Resultado: não existem mais.
Risco restante: há `asyncio.create_task` legítimo em runs async, validação e demo session; não são worker de batch.
