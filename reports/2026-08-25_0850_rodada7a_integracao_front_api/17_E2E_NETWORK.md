# E2E Network

Arquivo atualizado: `scripts/test_react_frontend_e2e.py`.

Cobertura adicionada:
- Navegação por Dashboard, Clientes, Ações, Ensinar ação, Execução, Relatórios, Configurações, Agendamentos e Diagnóstico.
- Captura de console errors e page errors.
- Falha em HTTP >= 400 inesperado.
- Falha se houver request operacional legado para `/api/clients`, `/api/actions`, `/api/batches`, `/api/browser`, `/api/demo`, `/api/runs`.
- Checagem de loading persistente.

Execução 7A.1:
- Ambiente: container `mcr.microsoft.com/playwright/python:v1.56.0-noble`, `--network host`.
- Base URL: `https://cotasync.ferriolimidias.com.br`.
- Autenticação: cookie temporário assinado pelo backend, sem imprimir token.
- Resultado: `react-e2e-smoke-ok`.
- Não iniciou gravação, ação real ou batch real.

Domínio real:
- `GET /` retornou 200.
- `GET /api/v1/dashboard` sem sessão retornou 401 `AUTH_REQUIRED`, esperado.

Network assertions:
- Nenhum request operacional legado detectado.
- Nenhum HTTP >= 400 inesperado detectado.
- Nenhum console error/page error detectado.
- Loading persistente não detectado.
