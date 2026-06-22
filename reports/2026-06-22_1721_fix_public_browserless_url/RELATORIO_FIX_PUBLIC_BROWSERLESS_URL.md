# Relatorio: URL publica do Browserless

Data: 2026-06-22 17:21 (America/Sao_Paulo)

## Resultado

A URL de inspeção agora usa exclusivamente `COTASYNC_BROWSERLESS_PUBLIC_URL` no navegador do usuário. Para uma base HTTPS, o frontend do Chrome recebe `wss=host/devtools/page/<id>`; para a demo local HTTP, recebe `ws=localhost:porta/devtools/page/<id>`. O endpoint interno `BROWSERLESS_URL` continua inalterado para Playwright/CDP.

Exemplo validado em sessão externa real:

```text
https://browserless-cotasync.ferriolimidias.com.br/devtools/inspector.html?wss=browserless-cotasync.ferriolimidias.com.br/devtools/page/5F5764FED9571D924195A22B39C8A1B9
```

O `/json/list` público informou o mesmo target com `webSocketDebuggerUrl` interno em `ws://0.0.0.0:3000/devtools/page/5F5764FED9571D924195A22B39C8A1B9`, comprovando a substituição do host sem alterar o identificador da página.

## Alterações

- Helper dedicado para converter WebSocket interno em URL pública do DevTools.
- Uso de `wss=` em bases HTTPS e `ws=` em bases HTTP.
- Host público seguro adicionado ao status da sessão, diagnóstico do operador e UI.
- Defaults locais alterados de `127.0.0.1` para `localhost`; hosts internos não aparecem no link.
- Teste unitário para conversão pública e teste da variante local.
- Smoke local passou a preservar e suspender temporariamente a configuração externa durante o ciclo declarado como local.

## Validações

- `python3 -m compileall backend frontend scripts tests`: passou.
- `python3 -m unittest tests.test_browserless_urls`: 2 testes passaram.
- `docker compose -f docker-compose.test.yml --env-file .env.test up -d --build`: passou.
- `docker compose -f docker-compose.test.yml --env-file .env.test ps`: todos os serviços ativos; Postgres saudável.
- `curl http://127.0.0.1:8100/health`: `status=ok`.
- `curl http://127.0.0.1:8100/api/health/browserless`: `status=ok`, backend em `ws://cotasync_test_browserless:3000`.
- `docker exec cotasync_test_backend python scripts/test_demo_v01_cycle.py`: passou em 3 ciclos e revalidação. Uma execução anterior encontrou flake preexistente no terceiro ciclo (`learning_events`); a repetição completa passou.
- `curl https://browserless-cotasync.ferriolimidias.com.br/json/list`: target externo e WebSocket interno observados durante sessão temporária.
- GET da URL pública do inspector gerada: passou.
- `curl -I https://cotasync.ferriolimidias.com.br`: HTTP 200.
- `git diff --check`: passou.

## Preservação de escopo

Não foram adicionados autenticação, Postgres, frameworks, segredos, arquivos `.env`, cookies ou `storage_state`. `data/external_systems/current.json` já estava alterado antes do trabalho e foi preservado fora do commit.
