# Heartbeat e Stale

Arquivo: `backend/worker.py`
Classe/função: `heartbeat_seconds`, `stale_seconds`, `heartbeat_loop`
Antes: não havia heartbeat completo de worker.
Depois: worker atualiza `worker_instances.heartbeat_at` e `batches.heartbeat_at`.
Motivo: detectar abandono sem depender de memória FastAPI.
Banco/estado afetado: `worker_instances`, `batches`.
Transação: commit curto a cada heartbeat.
Recovery: startup usa threshold contra heartbeat stale.
Teste: consulta PostgreSQL após subir `cotasync_test_worker`.
Resultado: worker `idle`, heartbeat recente, `online=True`.
Risco restante: heartbeat usa uma task asyncio interna para metadado; não executa clientes em paralelo.

Configuração:
- `COTASYNC_WORKER_HEARTBEAT_SECONDS=10`.
- `COTASYNC_WORKER_STALE_SECONDS=60`.

Razão do stale de 60s: seis heartbeats de 10s toleram pequenas pausas de runtime/rede sem marcar crash prematuramente.
