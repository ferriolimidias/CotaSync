# Batches e Batch Items

Contagem no banco:
- batches: 1
- batch_items: 4

Conclusão: o lote e seus itens foram migrados para PostgreSQL com vínculo por `batch_id`.
Evidência: `backend/services/batch_runner.py`, contagens do banco e importador.
Estado: concluído.
Impacto: a Rodada 3 poderá usar `batch_items` para recuperação e progresso.
