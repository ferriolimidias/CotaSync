# CotaSync Frontend API Contract

Status: contrato inicial para o frontend React/Lovable definitivo.

Base: `/api/v1`

Auth:
- `POST /api/v1/auth/login` recebe `{ "username": "...", "password": "..." }`.
- Resposta define cookie HttpOnly de sessão e retorna `csrf_token`.
- O frontend deve guardar o CSRF em memória/estado de app e enviar `X-CSRF-Token` em `POST`, `PATCH`, `PUT`, `DELETE`.
- Não usar localStorage para token de sessão.
- `GET /api/v1/auth/me` retorna usuário autenticado.
- `POST /api/v1/auth/logout` encerra sessão.

Erro padrão v1:
```json
{
  "error": {
    "code": "BATCH_IDEMPOTENCY_CONFLICT",
    "message": "Idempotency-Key ja utilizada com payload diferente."
  }
}
```

Paginação:
- Listas usam `page`, `page_size`.
- Resposta contém `total` e `items`.

Dashboard:
- `GET /api/v1/dashboard`
- Retorna `session_status`, `clients_active`, `actions_ready`, `runs_today`, `last_run`, `worker_status`, `queue_status`, `alerts`.

Clients:
- `GET /api/v1/clients`
- `POST /api/v1/clients`
- `GET /api/v1/clients/{id}`
- `PATCH /api/v1/clients/{id}`
- `DELETE /api/v1/clients/{id}` desativa o cliente.
- Campos preservados: `grupo`, `cota`, `versao`, `variables`, `group`, `active`, `notes`.

Actions:
- `GET /api/v1/actions`
- `GET /api/v1/actions/{id}`
- `GET /api/v1/actions/{id}/versions`
- Resposta de detalhe inclui `published_version`, `last_run`, `needs_attention`.

Learning:
- `GET /api/v1/learning/capabilities`
- `POST /api/v1/learning/sessions`
- `GET /api/v1/learning/sessions/{session_id}`
- `POST /api/v1/learning/sessions/{session_id}/recording/start`
- `POST /api/v1/learning/sessions/{session_id}/recording/stop`
- `POST /api/v1/learning/sessions/{session_id}/actions`
- OperatorAssistant:
  - `POST /api/v1/learning/sessions/{session_id}/operator/insert-active`
  - `POST /api/v1/learning/sessions/{session_id}/operator/press`
  - `POST /api/v1/learning/sessions/{session_id}/operator/clear-active`
- Variáveis canônicas: `grupo`, `cota`, `versao`.
- Valores sensíveis não devem ser renderizados nem persistidos pelo frontend.

Browser/noVNC:
- `GET /api/v1/browser/status`
- `POST /api/v1/browser/view-token`
- `POST /api/v1/browser/ensure-ready`
- `view_url` tem TTL curto. CDP continua interno.

External Session:
- `GET /api/v1/external-session/status`
- `POST /api/v1/external-session/open-login`
- `POST /api/v1/external-session/validate`
- Login, senha e MFA continuam operação manual do usuário.

Batches:
- `POST /api/v1/batches`
- `GET /api/v1/batches`
- `GET /api/v1/batches/{id}`
- `POST /api/v1/batches/{id}/cancel`
- `GET /api/v1/batches/{id}/results`
- Enviar `Idempotency-Key` em criação.
- Mesma key + mesmo payload + mesmo usuário retorna o batch existente.
- Mesma key + payload diferente retorna `409`.
- Polling deve usar `GET /api/v1/batches/{id}`.

Worker:
- `GET /api/v1/worker/status`
- Retorna `online`, `status`, `heartbeat_at`, `current_batch_id`, `browser_lock`.

Reports:
- `GET /api/v1/reports/runs`
- `GET /api/v1/reports/batches`

Diagnostics:
- `GET /api/v1/diagnostics/system`
- `GET /api/v1/diagnostics/runs/{id}`
- Área técnica/admin. Não usar como resposta principal de UX.

Integração Lovable:
- O frontend visual existente é base visual, não contrato técnico imutável.
- Na importação, componentes, hooks, services, rotas e estados podem ser alterados para este contrato.
- Preservar identidade visual e qualidade gráfica aprovada.
