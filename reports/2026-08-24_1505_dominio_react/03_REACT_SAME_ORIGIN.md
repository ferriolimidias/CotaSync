# React Same Origin

Auditoria:

- `frontend-react/src/services/api.ts` usa `VITE_API_BASE_URL` com fallback vazio.
- As chamadas do frontend usam caminhos relativos como `/api/v1/auth/login`, `/api/v1/auth/me` e `/api/v1/browser/view-token`.
- `docker-compose.test.yml` passa `VITE_API_BASE_URL: ${FRONTEND_REACT_API_BASE_URL:-}` para o build do React.
- Nao foram encontrados `127.0.0.1:8100`, `localhost:8100` ou host publico com porta `8100` no codigo do frontend.

Conclusao: com `VITE_API_BASE_URL` vazio, o navegador chama a API em same origin: `https://cotasync.ferriolimidias.com.br/api/v1/...`.

