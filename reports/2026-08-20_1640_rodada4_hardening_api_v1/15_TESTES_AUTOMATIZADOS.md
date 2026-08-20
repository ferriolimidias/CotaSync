# Testes Automatizados

Comando:
`sudo -n docker exec cotasync_test_backend python -m unittest discover -v`

Resultado:
- total: 183
- ok: 183
- failed: 0
- skipped: 0

Arquivo: `tests/test_batch_runner.py`
Mudança: adicionados testes de idempotência multiusuário, payload conflict e race.
Resultado: OK.

Arquivo: `tests/test_api_v1_contract.py`
Mudança: novo contrato v1 para auth, dashboard, clients, actions, learning, browser, external-session, batches, worker, reports e diagnostics.
Resultado: OK.

Runs operacionais:
- antes da suíte: 10.
- depois da suíte: 10.
