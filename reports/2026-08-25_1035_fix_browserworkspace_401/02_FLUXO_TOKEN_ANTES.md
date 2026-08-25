# Fluxo Antes

Emissao:
- Endpoint usado pelo React: `POST /api/v1/browser/view-token`.
- Implementacao: `backend/api/v1.py::browser_view_token`.
- Geracao: `backend/services/desktop_view_tokens.py::create_token`.
- Storage: PostgreSQL, tabela `desktop_view_tokens`, campo `digest` com SHA-256 do token.
- TTL: `1800` segundos por `COTASYNC_DESKTOP_VIEW_TOKEN_TTL_SECONDS`.

Validacao do Nginx:
- Endpoint configurado: `GET /api/desktop-browser/validate-view-token`.
- Header enviado: `X-Desktop-View-Token`.
- Implementacao alvo: `backend/api/desktop_browser.py::validate_desktop_view_token`.
- Problema efetivo: antes de chegar ao handler legado, `backend/main.py::cotasync_auth_middleware` bloqueava o caminho `/api/desktop-browser/validate-view-token` por falta de cookie CotaSync.

Resultado antes:
- Emissor gravava o token corretamente no PostgreSQL.
- Validador configurado no Nginx nao conseguia executar a validacao operacional.
- `auth_request` recebia `401` e negava o noVNC.

