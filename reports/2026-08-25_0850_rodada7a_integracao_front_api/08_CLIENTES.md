# Clientes

Funcionalidades auditadas:
- Listar, buscar e filtrar: `GET /api/v1/clients`.
- Criar: `POST /api/v1/clients`.
- Editar: `PATCH /api/v1/clients/{id}`.
- Desativar: `DELETE /api/v1/clients/{id}`.
- CSV preview/import/export: `/api/v1/clients/import/preview`, `/api/v1/clients/import`, `/api/v1/clients/export.csv`.

Campos: `group`, `variables.grupo`, `variables.cota`, `variables.versao`, `display_variables`, `notes`, `active`.

Status: OK técnico. Mutações invalidam `clients` e `dashboard`.

Risco residual: mutações E2E em DB isolado não executadas porque PostgreSQL/compose indisponível.
