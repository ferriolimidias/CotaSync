# Dashboard Relatórios

Dashboard: smoke HTTP via React/proxy retornou `clients=4`, `actions=4`, `runs_today=1`, confirmando dados reais e não mocks.

Relatórios: filtros reais por ação, status, cliente, data inicial e data final foram integrados no React e no backend.

Exportação: botão de CSV na tela de relatórios usa `/api/v1/reports/runs.csv` com os mesmos filtros.

Teste: E2E validou a tela de relatórios e o botão de exportação; contrato backend validou export CSV.
