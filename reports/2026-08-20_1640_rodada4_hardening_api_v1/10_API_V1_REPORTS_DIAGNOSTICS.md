# API V1 Reports e Diagnostics

Arquivo: `backend/api/v1.py`
Função/endpoint: `/api/v1/reports/runs`, `/api/v1/reports/batches`
Antes: runs e batches tinham listagens separadas sem contrato de reports.
Depois: reports v1 paginados.
Motivo: frontend futuro consultar histórico sem BI completo.
Impacto: filtros básicos para runs e status.
Teste: `test_dashboard_clients_actions_reports_and_worker_contracts`.
Resultado: 200.
Risco restante: filtros `date_from/date_to` documentados para evolução, ainda não completos.

Arquivo: `backend/api/v1.py`
Função/endpoint: `/api/v1/diagnostics/system`, `/api/v1/diagnostics/runs/{id}`
Antes: diagnóstico misturado em respostas normais.
Depois: área técnica admin.
Motivo: não poluir UX normal.
Impacto: operator recebe 403.
Teste: `test_diagnostics_requires_admin`.
Resultado: operator 403, admin 200.
