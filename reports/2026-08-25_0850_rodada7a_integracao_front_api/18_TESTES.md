# Testes

Executado:
- `uv run --link-mode=copy --with-requirements requirements.txt python -m py_compile backend/api/v1.py tests/test_api_v1_contract.py scripts/test_react_frontend_e2e.py`
- Resultado: OK.
- `sudo docker run --rm -v /opt/cotasync-test/src/frontend-react:/app -w /app oven/bun:1.2.21 bun run typecheck`
- Resultado: OK.
- `sudo docker run --rm -v /opt/cotasync-test/src/frontend-react:/app -w /app oven/bun:1.2.21 bun run lint`
- Resultado: OK, 7 warnings Fast Refresh conhecidos.
- `sudo docker run --rm -v /opt/cotasync-test/src/frontend-react:/app -w /app oven/bun:1.2.21 bun run build`
- Resultado: OK.
- `sudo docker compose -f docker-compose.test.yml --env-file .env.test run --rm --no-deps cotasync_test_backend sh -lc 'pip install -q pytest && python -m pytest tests'`
- Resultado: `187 passed, 1 warning in 33.98s`.
- E2E público com Playwright containerizado.
- Resultado: `react-e2e-smoke-ok`.

Isolamento de banco:
- Testes usam `cotasync_pytest` em `tests/__init__.py`.
- Banco operacional é `cotasync_test`.
- Runs operacionais antes: `operational|10`.
- Runs operacionais depois: `operational|10`.

Observação:
- `pytest` sem alvo coleta `scripts/test_human_demo_replay.py`, que é script manual fora da suíte e depende de `test_demo_v01_cycle`. Suíte válida executada em `tests/`.
