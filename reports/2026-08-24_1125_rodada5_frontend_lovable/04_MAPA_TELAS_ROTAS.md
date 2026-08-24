# Mapa Telas Rotas

Página: Dashboard
Rota: `/`
Estado original: cards e execuções mock.
Mocks encontrados: números, alertas, execuções.
API utilizada: `/api/v1/dashboard`, `/api/v1/reports/runs`.
Componentes alterados: `routes/index.tsx`.
Backend alterado: não.
Estado final: dados reais, polling leve, empty states.
Funcional: sim. Parcial: não. Pendente: não. Teste: Playwright smoke.

Página: Clientes
Rota: `/clientes`
Estado original: tabela mock e botões inertes.
Mocks encontrados: clientes Alfa/Beta/Gama, listas fixas.
API utilizada: `/api/v1/clients`.
Componentes alterados: `routes/clientes.tsx`.
Backend alterado: não.
Estado final: listar, buscar, filtrar, criar, editar e desativar.
Funcional: sim. Parcial: CSV. Pendente: preview/import CSV v1. Teste: typecheck/build/smoke.

Página: Ações
Rota: `/acoes`
Estado original: cards de `mockActions` e JSON técnico.
API utilizada: `/api/v1/actions`, `/api/v1/actions/{id}/versions`.
Estado final: cards reais, status, versão publicada, atenção/legado.
Funcional: sim.

Página: Ensinar ação
Rota: `/ensinar-acao`
Estado original: wizard visual com navegador fake e IA opcional.
API utilizada: `/api/v1/learning`, `/api/v1/browser`, operator endpoints.
Estado final: sessão, gravação, noVNC, assistente, finalizar e publicar.
Funcional: parcial por depender da sessão externa real. IA removida.

Página: Execução em massa
Rota: `/execucao`
Estado original: preview e progresso mock.
API utilizada: `/api/v1/actions`, `/api/v1/clients`, `/api/v1/batches`.
Estado final: batch real, idempotência, polling e cancel-after-current.
Funcional: sim.

Página: Relatórios
Rota: `/relatorios`
API utilizada: `/api/v1/reports/runs`, `/api/v1/reports/batches`.
Estado final: histórico paginado e filtros básicos.
Funcional: sim. Parcial: exportação geral CSV.

Página: Configurações
Rota: `/configuracoes`
API utilizada: `/api/v1/external-session`, `/api/v1/browser`.
Estado final: conta, sessão externa manual, browser.
Funcional: parcial.

Página: Diagnóstico técnico
Rota: `/diagnostico`
API utilizada: `/api/v1/diagnostics/system`, `/api/v1/worker/status`, `/api/v1/browser/status`.
Estado final: admin técnico, operador recebe 403 amigável.
Funcional: sim para admin.

Página: Agendamentos
Rota: `/agendamentos`
Estado final: indisponível em breve; scheduler não reintroduzido.

Contexto: Rodada 5 importou `/home/joseadmin/front.zip` para `frontend-react/`, preservando o Streamlit em `frontend/` durante a transição.

