# Ações

Endpoints:
- `GET /api/v1/actions`.
- `GET /api/v1/actions/{id}`.
- `GET /api/v1/actions/{id}/versions`.

Correções:
- Frontend usa `actionIsExecutable`: `steps_count > 0`, `has_url`, sem `legacy_unconfigured`.
- Dashboard usa regra equivalente para `actions_ready`.
- Card mostra `Não executável` quando ação não pode rodar com segurança.
- Execução filtra selects para ações executáveis.

Status: corrigido.

Pendente: enum formal de status de ação no backend pode ser ampliado futuramente; nesta rodada não foi criado scheduler/IA.
