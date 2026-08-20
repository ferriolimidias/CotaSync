# Estados Batch e Items

Batch:
- `queued`
- `running`
- `cancel_requested`
- `cancelled`
- `completed`
- `completed_with_errors`
- `interrupted`
- `failed`

Batch item:
- `pending`
- `running`
- `success`
- `error`
- `interrupted`
- `cancelled`

Arquivo: `backend/services/batch_runner.py`
Classe/função: constantes de estado e `_normalize_*`
Antes: coexistiam `pending`, `success`, `partial_success`, `canceled`, `skipped`.
Depois: estados novos são emitidos; compatibilidade de leitura normaliza legados.
Motivo: máquina de estados explícita para worker persistente.
Banco/estado afetado: `batches.status`, `batch_items.status`.
Transação: mudanças de estado sempre persistidas em `SessionLocal.begin`.
Recovery: status final considera `error/interrupted/cancelled` como lote `completed_with_errors`, exceto cancelamento explícito.
Teste: `test_row_error_does_not_stop_batch_and_sets_partial_success`, `test_external_session_expired_interrupts_batch_without_next_item`.
Resultado: misto vira `completed_with_errors`; sessão expirada vira `interrupted`.
Risco restante: nomes legados ainda podem existir em dados históricos, mas são migrados/normalizados.
