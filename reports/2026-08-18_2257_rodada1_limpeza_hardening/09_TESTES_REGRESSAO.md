# Testes de Regressao

## Comandos executados

Host:

```bash
python3 -m compileall backend frontend scripts
```

Resultado: OK.

Container:

```bash
docker exec cotasync_test_backend python -m compileall backend frontend scripts
```

Resultado: OK.

Build:

```bash
docker compose -f docker-compose.test.yml --env-file .env.test up -d --build
```

Resultado: OK.

Status:

```bash
docker compose -f docker-compose.test.yml --env-file .env.test ps
```

Resultado: backend, frontend, desktop_browser e postgres UP; sem Browserless e sem Redis.

Health:

```bash
sleep 5 && curl -sS http://127.0.0.1:8100/health
```

Resultado:

```json
{"status":"ok","service":"cotasync"}
```

Suite:

```bash
docker exec cotasync_test_backend python -m unittest discover
```

Resultado:

```text
Ran 164 tests in 11.734s
OK
```

Smoke real:

```bash
docker exec cotasync_test_backend python scripts/test_desktop_browser_connection.py
```

Resultado:

```text
run_id=d6caf738-4c26-403d-ad1f-5a5445b5bd23
runner=desktop_browser_replay
whether_desktop_browser_used=True
status=success
resultado=status_pedido:Enviado
```

## Observacoes

`python3 -m pytest -q` no host nao foi utilizado como resultado final porque o host nao possui `pytest`. `python3 -m unittest discover` no host tambem falha por ausencia de dependencias runtime (`fastapi`, `pydantic`). A suite valida foi executada dentro do container `cotasync_test_backend`, que contem o ambiente real da aplicacao.

Warnings observados:

- `StarletteDeprecationWarning` sobre `httpx`/`TestClient`.
- warnings do Streamlit sobre `ScriptRunContext` em modo bare.

Esses warnings nao bloquearam a rodada.

