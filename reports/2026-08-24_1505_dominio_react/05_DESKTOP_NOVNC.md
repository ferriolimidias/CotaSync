# Desktop noVNC

Auditoria:

- `desktop-cotasync.ferriolimidias.com.br` aponta para noVNC em `127.0.0.1:3200`.
- O virtual host usa `auth_request` para validar token antes de proxy para noVNC.
- Endpoint atual de validacao: `http://127.0.0.1:8100/api/desktop-browser/validate-view-token`.
- O frontend React solicita token por `/api/v1/browser/view-token`.
- O endpoint v1 de emissao reutiliza a mesma geracao de token do endpoint legado.

Decisao:

- Mantido temporariamente o endpoint legado interno de validacao do noVNC, porque nao existe endpoint v1 equivalente de validacao e a mudanca precipitada poderia quebrar o desktop.
- O endpoint legado fica usado apenas no subrequest interno do Nginx.

