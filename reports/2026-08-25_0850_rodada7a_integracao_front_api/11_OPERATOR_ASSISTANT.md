# Operator Assistant

Endpoints:
- Inserir: `POST /api/v1/learning/sessions/{id}/operator/insert-active`.
- Tab/Enter: `POST /api/v1/learning/sessions/{id}/operator/press`.
- Limpar: `POST /api/v1/learning/sessions/{id}/operator/clear-active`.

Payloads:
- `insert-active`: `value`, `sensitive`, `variable_key`.
- `press`: `key`.

Status: OK técnico. Botões ficam desabilitados sem `sessionId`.

Pendente: validação manual no browser real.
