# CSV Exports

Clientes: `GET /api/v1/clients/export.csv`.

Colunas: `id,name,group,active,grupo,cota,versao,notes`. Não exporta metadados internos nem dados técnicos.

Resultados de batch: `GET /api/v1/batches/{batch_id}/results.csv` foi adicionado como alias v1 amigável. O endpoint existente `/api/v1/batches/{batch_id}/results` permanece compatível.

Relatórios: `GET /api/v1/reports/runs.csv` exporta histórico filtrado por ação, status, cliente, data inicial e data final.

Teste: contrato backend passou; smoke HTTP via React/proxy confirmou cabeçalhos CSV de clientes e relatórios.
