# Cancel After Current

Arquivo: `backend/services/batch_runner.py`
Classe/função: `cancel_batch`, `claim_next_item`
Antes: cancelamento marcava flag e o worker antigo pulava linhas como `skipped`.
Depois: se há item running, batch vira `cancel_requested`; item atual termina; pending viram `cancelled`; batch vira `cancelled`.
Motivo: não matar Playwright/Chromium no meio de ação externa.
Banco/estado afetado: `batches.cancel_requested`, `batches.status`, `batch_items.status`.
Transação: cancelamento da flag e dos pending ocorre em transações curtas.
Recovery: se cair após pedido de cancelamento, pending continuam canceláveis no próximo claim.
Teste: `test_cancel_after_current_finishes_running_item_and_cancels_pending`.
Resultado: `success`, `success`, `cancelled`; batch `cancelled`.
Risco restante: não há abort hard administrativo nesta rodada.
