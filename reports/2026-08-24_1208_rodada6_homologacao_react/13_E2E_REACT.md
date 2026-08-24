# E2E React

Arquivo criado: `scripts/test_react_frontend_e2e.py`.

Cobertura segura: login real por cookie/CSRF, dashboard, clientes, ações, execução, relatórios, configurações, CSV preview pela UI, diagnóstico admin, ensino com sessão/gravação e BrowserWorkspace/noVNC.

Execução: container Playwright com `COTASYNC_REACT_BASE_URL=http://127.0.0.1:3300`.

Resultado: `react-e2e-smoke-ok`.

Limite consciente: não executa ação externa, importação confirmada operacional ou lote real para não poluir dados nem acionar sistema externo sem caso seguro.
