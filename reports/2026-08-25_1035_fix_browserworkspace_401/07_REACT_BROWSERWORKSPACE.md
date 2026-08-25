# React BrowserWorkspace

Componente auditado:
- `frontend-react/src/components/cotasync/BrowserWorkspace.tsx`.

Servico usado:
- `frontend-react/src/services/api.ts::createBrowserViewToken`.
- Endpoint: `POST /api/v1/browser/view-token`.

Fluxo:
- Botao `Abrir navegador` chama `ensureBrowserReady`.
- Em sucesso, invalida query `browser` e chama `createBrowserViewToken`.
- Com `view_url`, renderiza iframe `title="Navegador CotaSync"`.
- Botao passa a `Renovar acesso` e emite novo token em nova chamada.

Alteracao React runtime:
- Nenhuma alteracao de componente foi necessaria para corrigir o 401.
- A falha estava na autorizacao backend/Nginx.

Teste E2E:
- Script `scripts/test_react_frontend_e2e.py` agora abre o BrowserWorkspace em Configuracoes.
- Falha se o iframe contiver `401 Authorization Required`, `403`, `502` ou pagina de erro Nginx.
- Mantida excecao documentada para `404 /package.json` auxiliar do noVNC.

