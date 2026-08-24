# Estado Final

status: dominio principal publicado com React.

domain: `https://cotasync.ferriolimidias.com.br`
domain_frontend: `https://cotasync.ferriolimidias.com.br/` -> `127.0.0.1:3300`
domain_api: `https://cotasync.ferriolimidias.com.br/api/` -> `127.0.0.1:8100`

nginx_before: dominio principal apontava `/` para `127.0.0.1:3100`.
nginx_after: dominio principal aponta `/api/` para FastAPI e `/` para React.
nginx_test: sucesso.
nginx_reload: sucesso.

react_local: `200` em `http://127.0.0.1:3300/`.
react_public: `200` em `https://cotasync.ferriolimidias.com.br/`, HTML React/TanStack Start.

api_local: `401` JSON em `http://127.0.0.1:8100/api/v1/auth/me`.
api_public: `401` JSON em `https://cotasync.ferriolimidias.com.br/api/v1/auth/me`.

auth_me_public_status: `401 AUTH_REQUIRED`, esperado sem sessao.
csrf_status: habilitado no backend; nao desabilitado.
cookie_status: `COTASYNC_COOKIE_SECURE=true` carregado no backend; cookies esperados com `Secure`, sessao `HttpOnly`, `SameSite=Lax`, `Path=/`, host-only.

frontend_api_base_before: `VITE_API_BASE_URL` vazio por padrao; chamadas relativas.
frontend_api_base_after: mantido same-origin com chamadas `/api/v1/...`.

desktop_domain: `https://desktop-cotasync.ferriolimidias.com.br`
desktop_novnc: mantido via Nginx para `127.0.0.1:3200`; sem token retorna `401`.
desktop_token_validation_endpoint: mantido temporariamente em `/api/desktop-browser/validate-view-token` para o subrequest interno do Nginx.

streamlit_running: sim, em `127.0.0.1:3100`.
streamlit_publicly_accessible: nao pelo dominio principal.

port_3100: `127.0.0.1:3100`
port_3300: `127.0.0.1:3300`
port_8100: `127.0.0.1:8100`
port_3200: `127.0.0.1:3200`
port_9222: `127.0.0.1:9222`

frontend_typecheck: sucesso.
frontend_lint: sucesso com 7 warnings.
frontend_build: sucesso.
backend_tests: nao executados; nao houve alteracao de codigo backend.

commit: `d4ce0a6` (`Configura React no dominio oficial de homologacao`).
push_status: enviado para `origin/master`.

reports_dir: `reports/2026-08-24_1505_dominio_react/`

remaining_blockers: validacao manual de login pelo operador.

operator_action_required: operador deve abrir o dominio e fazer login manualmente.
