# Teste Cancelamento

Arquivo: `tests/test_batch_runner.py`
Classe/função: `test_cancel_after_current_finishes_running_item_and_cancels_pending`
Antes: cancelamento antigo marcava `skipped`.
Depois: pedido durante item 2 não interrompe o item; item 3 vira `cancelled`.
Motivo: evitar estado externo imprevisível.
Banco/estado afetado: `batches.cancel_requested`, `batch_items.status`.
Transação: `cancel_batch` e `claim_next_item`.
Recovery: se reiniciar após cancel request, pending não são iniciados.
Teste: 3 itens fixture.
Resultado: `success`, `success`, `cancelled`; batch `cancelled`.
Risco restante: não foi testado cancelamento via UI manual, apenas serviço/API.
