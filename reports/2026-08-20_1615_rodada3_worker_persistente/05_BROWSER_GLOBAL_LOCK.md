# Browser Global Lock

Arquivo: `backend/worker.py`
Classe/função: `BrowserAdvisoryLock`
Antes: lock exclusivo era `asyncio.Lock` em `backend/services/batch_runner.py`.
Depois: lock é `pg_try_advisory_lock(76003001)` em conexão PostgreSQL dedicada.
Motivo: proteger o Chromium persistente entre processos/containers.
Banco/estado afetado: lock advisory de sessão PostgreSQL, sem tabela adicional.
Transação: lock fica preso à conexão enquanto o batch controla o browser.
Recovery: se processo/conexão morre, PostgreSQL libera o advisory lock automaticamente.
Teste: `test_browser_advisory_lock_blocks_second_executor`.
Resultado: primeiro executor adquiriu; segundo foi bloqueado.
Risco restante: a chave `76003001` é constante documentada; se outro módulo usar a mesma chave indevidamente, haverá contenção.
