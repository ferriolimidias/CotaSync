# Endpoint De Validacao

Endpoint novo: `GET /api/v1/browser/validate-view-token`.

Arquivo: `backend/api/v1.py`.

Entrada:
- Header `X-Desktop-View-Token`.
- Sem token em body.
- Sem dependencia de cookie `cotasync_session`.

Saidas:
- Token valido: `204 No Content`, header `Cache-Control: no-store`.
- Token ausente, invalido ou expirado: `401`, erro v1 `DESKTOP_VIEW_TOKEN_INVALID`.

Middleware:
- `backend/main.py` inclui apenas `/api/v1/browser/validate-view-token` em `_PUBLIC_API_PATHS`.
- A emissao `/api/v1/browser/view-token` continua protegida por `require_user`.

Endpoint legado:
- `/api/desktop-browser/validate-view-token` foi mantido no codigo, mas nao e mais usado pelo Nginx do desktop.

