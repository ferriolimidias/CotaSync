# API Progresso e Worker

Arquivo: `backend/services/batch_runner.py`
Classe/função: `load_batch`
Antes: retorno focava lista de rows e status antigo.
Depois: inclui `total_items`, `processed_items`, `success_items`, `error_items`, `interrupted_items`, `cancelled_items`, `current_position`, `current_client_id`, `heartbeat_at`.
Motivo: polling sem depender do processo frontend.
Banco/estado afetado: leitura de `batches` e `batch_items`.
Transação: leitura com recount em transação curta.
Recovery: progresso reflete item `interrupted` sem inventar resultado.
Teste: batch real `f55bb4b9-8bff-4be0-88a9-c563243dc4b0`.
Resultado: `completed|2|2|0|0|0`.
Risco restante: endpoint segue sob auth geral da API.

Arquivo: `backend/api/batches.py`
Classe/função: `get_worker_status_endpoint`
Antes: não havia status de worker.
Depois: `/api/batches/worker/status` retorna status autenticado do worker.
Teste direto: `latest_worker_status()`.
Resultado: `online=True`, `status=idle`, `browser_lock=True`.
