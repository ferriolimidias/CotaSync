# Dashboard

Endpoint: `GET /api/v1/dashboard`.

Cards:
- Sessão externa: antes `Manual` fixo + `authenticated` cru. Agora usa `dashboard.external_session.session_status` e label humano.
- Clientes ativos: `clients_active`, PostgreSQL `clients where active = true`.
- Ações prontas: antes contava todo catálogo. Agora conta apenas ações com passos, URL e sem `legacy_unconfigured`.
- Execuções hoje: `runs_today`.
- Última execução: `last_run`.
- Sistema de execução: `worker_status`.
- Fila atual: `queue_status`.
- Alertas: `alerts`.

Evidência:
- Tela: Dashboard.
- Elemento: Sessão externa.
- Sintoma: `Manual / authenticated`.
- Request: `GET /api/v1/dashboard`.
- Response: `session_status` era hardcoded.
- Causa: backend fixo + frontend enum cru.
- Frontend file: `frontend-react/src/routes/index.tsx`.
- Backend file: `backend/api/v1.py`.
- Correção: `external_session` agregado + labels centralizados.
- Teste: `py_compile` OK; pytest bloqueado por PostgreSQL.
- Resultado: corrigido em código.
