# API V1 Batches e Worker

Arquivo: `backend/api/v1.py`
Função/endpoint: `/api/v1/batches`
Antes: batches oficiais estavam em `/api/batches`.
Depois: v1 cria, lista, consulta, cancela e baixa resultados.
Motivo: frontend não precisa saber worker internals.
Impacto: progresso amigável e idempotência scoped.
Teste: `test_batches_v1_idempotency_conflict_and_polling`.
Resultado: create 200, same payload 200, payload diferente 409, polling 200.
Risco restante: resultado v1 ainda é CSV por compatibilidade.

Arquivo: `backend/api/v1.py`
Função/endpoint: `/api/v1/worker/status`
Antes: status existia em `/api/batches/worker/status`.
Depois: contrato próprio.
Motivo: separar worker de batch API.
Impacto: retorna online/status/heartbeat/browser_lock.
Teste: contrato v1 e consulta real após restart.
Resultado: `online=True`, `status=idle`.
