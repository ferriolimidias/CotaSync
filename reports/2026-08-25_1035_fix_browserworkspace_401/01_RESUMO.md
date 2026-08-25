# Resumo

Status: corrigido e validado.

Problema observado: BrowserWorkspace renderizava o iframe do desktop, mas o Nginx do subdominio retornava `401 Authorization Required`.

Causa raiz: o Nginx do desktop validava o acesso em `/api/desktop-browser/validate-view-token`, endpoint legado sob `/api/`. O middleware global exige cookie de sessao CotaSync para caminhos `/api/` que nao estao explicitamente publicos. O subrequest `auth_request` do Nginx envia apenas `X-Desktop-View-Token`, sem cookie de sessao principal, entao a requisicao era bloqueada com `401 Authentication required` antes de validar o token do desktop.

Correcao: criado endpoint tecnico v1 `/api/v1/browser/validate-view-token`, liberado no middleware publico apenas para validacao por token desktop, usando o mesmo storage PostgreSQL da emissao `/api/v1/browser/view-token`. Nginx real e template versionado migrados para o endpoint v1.

Validacao principal:
- Token valido via header: `204`.
- Token invalido: `401 DESKTOP_VIEW_TOKEN_INVALID`.
- Primeiro acesso ao desktop com token: `200`, sem pagina 401/403/502.
- Cookie `cotasync_desktop_view`: emitido.
- Acesso subsequente por cookie: `200`, sem pagina 401/403/502.
- Acesso direto protegido sem token/cookie: `401`.
- E2E React publico: `react-e2e-smoke-ok`.
- Backend: `188 passed`.

