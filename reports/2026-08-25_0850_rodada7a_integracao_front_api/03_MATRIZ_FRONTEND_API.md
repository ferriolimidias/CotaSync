# Matriz Frontend API

| Tela | Elemento | Ação | Endpoint | Método | Payload | Resposta | React mapper | Backend source | Status |
|---|---|---|---|---|---|---|---|---|---|
| Login | Entrar | autentica | `/api/v1/auth/login` | POST | username/password | user/csrf | `login` | auth | OK |
| Dashboard | Cards | carregar resumo | `/api/v1/dashboard` | GET | nenhum | dashboard | `DashboardPayload` | DB + worker + external config | CORRIGIDO |
| Dashboard | Últimas execuções | listar operacionais | `/api/v1/reports/runs?run_origin=operational` | GET | filtros | page runs | `ApiRun` | runs | CORRIGIDO |
| Clientes | Tabela | listar | `/api/v1/clients` | GET | page/page_size | page clients | `ApiClient` | PostgreSQL | OK |
| Clientes | Form | criar/editar/desativar | `/api/v1/clients` e `/{id}` | POST/PATCH/DELETE | client payload | client | `ApiClient` | PostgreSQL | OK |
| Clientes | CSV | preview/import/export | `/api/v1/clients/import*`, `/export.csv` | POST/GET | csv_text | preview/result/csv | CSV types | PostgreSQL | OK |
| Ações | Cards | listar | `/api/v1/actions` | GET | page/page_size | page actions | `ApiAction` | actions/action_versions | CORRIGIDO |
| Ações | Modal | versões | `/api/v1/actions/{id}/versions` | GET | id | versions | `ApiActionVersion` | action_versions | OK |
| Ensino | Sessão | criar/status | `/api/v1/learning/sessions*` | POST/GET | metadata | session | `LearningSession` | demo_session_manager | PENDENTE OPERADOR |
| Ensino | Gravação | start/stop/publicar | `/api/v1/learning/sessions/{id}/...` | POST | form/action | session/action | `LearningSession`/`ApiAction` | demo_session_manager | PENDENTE OPERADOR |
| Operador | Botões | inserir/limpar/teclas | `/api/v1/learning/sessions/{id}/operator/*` | POST | value/key | operator | unknown sanitizado | demo_session_manager | OK técnico |
| Execução | Individual | run/poll | `/api/v1/actions/{id}/run`, `/api/v1/runs/{id}` | POST/GET | variables | run | `ApiRun` | runs/worker | PENDENTE OPERADOR |
| Execução | Massa | batch/poll/cancel/csv | `/api/v1/batches*` | POST/GET | action/client/filter | batch/csv | `ApiBatch` | batches | OK técnico |
| Relatórios | Histórico | filtros/csv | `/api/v1/reports/runs*` | GET | filtros | page/csv | `ApiRun` | runs | CORRIGIDO |
| Configurações | Sistema externo | status/open/validate | `/api/v1/external-session/*` | GET/POST | nenhum | external_session | `ExternalSessionStatus` | external_systems | CORRIGIDO |
| Browser | Workspace | status/token/ensure | `/api/v1/browser/*` | GET/POST | nenhum | browser/token | `BrowserStatus` | desktop_browser_health | CORRIGIDO |
| Diagnóstico | Cards | status técnico | `/api/v1/diagnostics/system`, worker/browser/session | GET | nenhum | diagnostics | typed | DB/browser/worker | CORRIGIDO |
| Agendamentos | Tela | nenhuma | nenhum | - | - | - | - | - | SEM BACKEND |
