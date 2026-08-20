# Testes Automatizados

Comando:
`sudo -n docker exec cotasync_test_backend python -m unittest discover -v`

Resultado:
- total: 174
- ok: 174
- falhas: 0
- skips: 0

Arquivo: `tests/test_batch_runner.py`
Antes: 10 testes de batch focados no runner em memória.
Depois: 16 testes cobrindo fila PostgreSQL, worker, advisory lock, recovery, cancelamento e idempotência.
Motivo: validar a Rodada 3 sem sistema externo real.
Banco/estado afetado: `cotasync_test`.
Transação: testes limpam `BatchItem`, `Batch`, `WorkerInstance` e runs `automated_test`.
Recovery: teste stale simula worker morto por heartbeat antigo.
Risco restante: testes de crash são por fixture/estado controlado, não kill real de container durante click.

Contagem de runs operacionais:
- antes da suíte automatizada: 0.
- depois da suíte automatizada: 0.
- depois dos smokes reais: 2, criadas pelo batch real seguro.
