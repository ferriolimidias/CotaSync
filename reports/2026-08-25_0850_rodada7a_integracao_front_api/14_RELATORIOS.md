# Relatórios

Endpoints:
- `GET /api/v1/reports/runs`.
- `GET /api/v1/reports/runs.csv`.
- `GET /api/v1/reports/batches`.

Correção:
- Filtro `run_origin` adicionado ao service.
- Tela usa `operational` por padrão.
- Origens técnicas (`validation`, `automated_test`, `migration`, `smoke`) ficam acessíveis por seleção explícita.

Status: corrigido.
