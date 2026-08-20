# Restart Backend e Worker

Arquivo: `backend/services/batch_runner.py`
Função/endpoint: fila PostgreSQL.
Antes: backend restart não tinha validação real pós-worker.
Depois: validado com batch running e restart de `cotasync_test_backend`.
Motivo: confirmar que FastAPI não segura execução.
Impacto: worker continuou e batch terminou.
Teste: batch `319838f5-098b-4af5-a448-6b5445542375`.
Resultado: `completed|2|2`.
Risco restante: teste local fixture.

Worker entre clientes:
- Batch: `6fa9610e-6e28-4a02-82b0-f6862f87b9fc`.
- Estado antes do kill: `1:success,2:pending`.
- Worker morto durante delay.
- Recovery: item 2 permaneceu `pending`, depois `success`.
- Resultado: `completed|2|2|0`.

Restart do stack:
- Batch queued antes do down/up: `6e0b69f4-3429-4446-adcd-04799e2bb03e`.
- `docker compose down` sem remover volumes.
- `docker compose up -d`.
- PostgreSQL preservou fila; browser voltou healthy; worker consumiu.
- Resultado: `completed|1|1`.
