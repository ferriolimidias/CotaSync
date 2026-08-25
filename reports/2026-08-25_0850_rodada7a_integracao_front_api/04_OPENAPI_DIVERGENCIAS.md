# OpenAPI Divergências

OpenAPI local extraído via `uv run --with-requirements requirements.txt python`.

Endpoints v1 confirmados: 37 únicos, incluindo auth, dashboard, clients, actions, learning, browser, external-session, batches, reports, diagnostics e worker.

Divergências:
- `DashboardPayload` não tinha `external_session`; corrigido.
- `ExternalSessionStatus` não tinha `external_system_configured`, `session_status`, `login_mode`, `validation_mode`; corrigido.
- Backend não expunha estes campos; corrigido em `_external_session_payload`.
- Dashboard reportava `session_status=authenticated` fixo; corrigido para fonte `external_systems` e status `unknown/not_configured`.
- `reports/runs` aceitava `run_origin`, mas frontend não enviava; corrigido.

Não corrigido nesta rodada por ausência de backend real:
- Validação viva da sessão externa ainda não classifica página atual do browser como autenticada/expirada. Status permanece `unknown` quando configurado.
