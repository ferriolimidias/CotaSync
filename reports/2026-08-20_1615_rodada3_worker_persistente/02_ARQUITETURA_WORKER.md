# Arquitetura Worker

Arquivo: `backend/worker.py`
Classe/função: `PersistentBatchWorker.run`
Antes: batch era executado por tarefa em memória dentro do processo FastAPI.
Depois: processo separado executa loop de consumo PostgreSQL.
Motivo: execução sobrevive ao fechamento do frontend e ao restart do backend.
Banco/estado afetado: `worker_instances.status`, `worker_instances.heartbeat_at`.
Transação: heartbeat e mudança de status são commits curtos.
Recovery: startup chama `recover_stale_batches`.
Teste: `test_worker_executes_rows_sequentially_and_waits_delay`.
Resultado: worker processou itens na ordem `110`, `111`.
Risco restante: não há orquestrador externo além do Docker restart policy.

Processo:
`python -m backend.worker`

Serviços:
- teste: `cotasync_test_worker`.
- operacional: `cotasync_worker`.

O worker não expõe porta pública. O `docker compose ps` mostra portas internas da imagem, mas não há bind de host para o serviço worker.
