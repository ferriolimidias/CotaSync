# Mapa de Rotas Frontend

Rotas reais em `frontend-react/src/routes`:

| Rota | Componente | Hooks | Services/API | Polling | Estado atual | Problemas |
|---|---|---|---|---|---|---|
| `/` | `Dashboard` | `useQuery` | `getDashboard`, `getReportsRuns` | dashboard 3s | Corrigido | removido `Manual` fixo e enum cru |
| `/clientes` | `ClientesPage` | `useQuery`, `useMutation` | clients CRUD, CSV preview/import/export | não | OK | sem legacy React |
| `/acoes` | `AcoesPage` | `useQuery` | `getActions`, `getActionVersions` | não | Corrigido | ações legadas não aparecem como prontas |
| `/ensinar-acao` | `EnsinarPage` | `useQuery`, `useMutation` | learning sessions/recording/actions | sessão 2.5s | Parcial seguro | cria sessão se operador iniciar; não iniciado nesta rodada |
| `/execucao` | `ExecucaoPage` | `useQuery`, `useMutation` | actions, clients, runs, batches | batch/run 2.5s; batches 3s | Corrigido | selects agora filtram ações executáveis |
| `/relatorios` | `RelatoriosPage` | `useQuery` | reports runs/batches CSV | não | Corrigido | padrão agora `run_origin=operational` |
| `/configuracoes` | `ConfigPage` | `useQuery`, `useMutation` | external-session, BrowserWorkspace | external 5s | Corrigido | separa sistema, login e sessão |
| `/agendamentos` | `AgendamentosPage` | nenhum | nenhum | não | OK | tela informativa sem backend fake |
| `/diagnostico` | `DiagPage` | `useQuery` | diagnostics, worker, browser, external-session | 3s/5s | Corrigido | API não é mais badge verde fixo |

Todas as rotas ficam sob `AuthGate`; sem usuário, renderizam `LoginScreen`.
