# Testes

Testes planejados:

- `docker compose -f docker-compose.test.yml --env-file .env.test ps`
- `ss -ltnp` nas portas `3100`, `3200`, `3300`, `8100`, `9222`
- `curl` local em `127.0.0.1:3300/`
- `curl` local em `127.0.0.1:8100/api/v1/auth/me`
- `sudo nginx -t`
- `curl -I https://cotasync.ferriolimidias.com.br/`
- `curl https://cotasync.ferriolimidias.com.br/api/v1/auth/me`
- `bun run typecheck`
- `bun run lint`
- `bun run build`

Resultados:

- `docker compose -f docker-compose.test.yml --env-file .env.test ps`: sucesso via `sudo`; todos os servicos principais em execucao.
- `ss -ltnp`: portas `3100`, `3200`, `3300`, `8100`, `9222` escutando somente em `127.0.0.1`.
- `curl http://127.0.0.1:3300/`: `200`, HTML React/TanStack Start com titulo `Dashboard - CotaSync`.
- `curl http://127.0.0.1:8100/api/v1/auth/me`: `401` JSON `AUTH_REQUIRED`.
- `sudo nginx -t`: sucesso.
- `sudo systemctl reload nginx`: sucesso.
- `curl -I https://cotasync.ferriolimidias.com.br/`: `200`, `Content-Type: text/html; charset=utf-8`.
- `curl https://cotasync.ferriolimidias.com.br/`: HTML React/TanStack Start. Nao houve ocorrencia de `Streamlit`, `ModuleNotFoundError`, `psycopg` ou `/app/frontend/app.py`.
- `curl https://cotasync.ferriolimidias.com.br/api/v1/auth/me`: `401` JSON `AUTH_REQUIRED`.
- `curl https://cotasync.ferriolimidias.com.br/api/v1/browser/view-token`: `401` JSON `AUTH_REQUIRED` sem sessao, esperado.
- `curl https://desktop-cotasync.ferriolimidias.com.br/`: `302` para dominio principal.
- `curl https://desktop-cotasync.ferriolimidias.com.br/vnc.html` sem token: `401` do Nginx, esperado.
- `bun run typecheck`: sucesso, executado dentro do container `cotasync_test_frontend_react`.
- `bun run lint`: sucesso, 7 warnings de `react-refresh/only-export-components`.
- `bun run build`: sucesso, executado dentro do container `cotasync_test_frontend_react`.

Nao foram executados testes de login com credenciais reais do usuario.
