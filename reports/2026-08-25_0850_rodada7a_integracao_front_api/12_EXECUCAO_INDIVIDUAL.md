# Execução Individual

Endpoints:
- Criar: `POST /api/v1/actions/{id}/run`.
- Polling: `GET /api/v1/runs/{id}` até `success/error`.

Payload: variáveis canônicas extraídas do cliente (`grupo`, `cota`, `versao`), `mode=async`, `requested_by=react`, `run_origin=operational`.

Correção: selects passam a listar somente ações executáveis.

Status: OK técnico, PENDENTE OPERADOR para execução real.
