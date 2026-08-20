# Resumo Executivo

Status: Rodada 3 implementada e validada.

Commit base: `2af75318b2cd19c03b9bf1ebd2fd35b33b17c8a3`.

Arquitetura entregue:
Frontend/Streamlit -> FastAPI -> PostgreSQL -> `python -m backend.worker` -> `run_action_sync` -> `desktop_browser_replay` -> CDP/Playwright -> Chromium persistente.

Arquivo: `backend/api/batches.py`
Classe/função: `create_batch_endpoint`
Antes: criava batch com `auto_start=True`.
Depois: cria batch `queued`, commita no PostgreSQL e retorna.
Motivo: remover execução dependente do processo FastAPI.
Banco/estado afetado: `batches`, `batch_items`.
Transação: criação atomizada em `create_batch`.
Recovery: batch fica disponível para worker mesmo se frontend/backend cair.
Teste: `python -m unittest discover -v`.
Resultado: `174/174 OK`.
Risco restante: endpoint ainda é a API temporária do Streamlit, não um frontend React final.

Arquivo: `backend/worker.py`
Classe/função: `PersistentBatchWorker`
Antes: inexistente.
Depois: processo persistente com heartbeat, startup recovery, claim FIFO e advisory lock do browser.
Motivo: execução sequencial fora do FastAPI.
Banco/estado afetado: `worker_instances`, `batches`, `batch_items`, `runs`.
Transação: claim de batch/item usa `FOR UPDATE SKIP LOCKED`; execução longa roda fora da transação.
Recovery: item running stale vira `interrupted`; pending posterior pode seguir.
Teste: `tests.test_batch_runner`.
Resultado: `16/16 OK`.
Risco restante: ação individual real `quantidade-de-parcelas` não foi executada por falta de `initial_url` e passos robustos.

Validações:
- `alembic current`: `0003_persistent_batch_worker`.
- `alembic heads`: `0003_persistent_batch_worker`.
- `compileall`: OK.
- suíte completa: `174` testes, `0` falhas.
- smoke desktop browser: `desktop_browser_replay`, `status=success`.
- batch real seguro: 2 clientes, `completed`, 2 success.
