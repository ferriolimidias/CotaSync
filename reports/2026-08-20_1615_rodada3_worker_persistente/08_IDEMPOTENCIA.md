# Idempotência

Arquivo: `backend/api/batches.py`
Classe/função: `create_batch_endpoint`
Antes: não lia `Idempotency-Key`.
Depois: header `Idempotency-Key` é repassado para `create_batch`.
Motivo: duplo clique com mesma intenção retorna o mesmo batch.
Banco/estado afetado: `batches.idempotency_key`.
Transação: busca por chave antes da criação; constraint única existente protege duplicidade.
Recovery: idempotência é persistente, não em memória.
Teste: `test_idempotency_key_returns_existing_batch_without_duplicate_items`.
Resultado: mesmo `batch_id`, 1 batch, 1 item.
Risco restante: escopo atual é chave global; usuários finais ainda não têm escopo multi-tenant formal para batches.
