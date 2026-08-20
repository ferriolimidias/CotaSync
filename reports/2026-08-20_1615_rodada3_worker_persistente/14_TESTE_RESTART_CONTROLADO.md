# Teste Restart Controlado

Arquivo: `tests/test_batch_runner.py`
Classe/função: `test_stale_running_item_interrupted_and_pending_resume`
Antes: não havia teste de restart/stale.
Depois: simula batch com item 1 `success`, item 2 `running` stale, item 3 `pending`.
Motivo: garantir que item em execução não seja repetido.
Banco/estado afetado: `batches.heartbeat_at`, `batch_items.status`.
Transação: recovery marca item running em transação única.
Recovery: item 2 vira `interrupted`; item 3 permanece `pending`; batch volta `queued`.
Teste: `python -m unittest tests.test_batch_runner -v`.
Resultado: passou.
Risco restante: cenário de 5 itens pedido foi representado com 3 itens no teste unitário; a política é a mesma e o batch real validou sequência com 2 itens.
