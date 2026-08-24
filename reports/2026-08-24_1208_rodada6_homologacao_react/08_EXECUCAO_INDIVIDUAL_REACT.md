# Execução Individual React

Rota: `/execucao`.

Alteração: criada seção de execução individual com seleção de ação e cliente ativo, envio por `/api/v1/actions/{action_id}/run` e polling por `GET /api/v1/runs/{run_id}`.

Estados visuais: `Na fila`, `Executando`, `Concluído`, `Erro`, com resultado amigável.

Teste automatizado: contrato backend de execução individual e consulta de run passou. Execução operacional real não foi disparada no E2E para não acionar sistema externo sem ação segura.
