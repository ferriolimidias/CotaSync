# Pendencias para Rodada 2

## P0 remanescente

Nenhum P0 tecnico novo ficou aberto dentro do escopo desta rodada.

## P1 remanescente

1. Migrar fonte de verdade para PostgreSQL.

Estado atual:
- PostgreSQL 15.18 esta provisionado.
- Banco `cotasync_test` possui 0 tabelas publicas.
- Nenhum schema de clients/actions/runs/batches/schedules foi criado nesta rodada.

Proxima acao:
- desenhar schema minimo.
- migrar usuarios auth para tabela.
- migrar clients/actions/runs/batches com plano de rollback Git + backup operacional fora do repo.

2. Integrar mais chamadas ao `BrowserController`.

Estado atual:
- controller criado como interface incremental.
- motor funcional nao foi reescrito.

Proxima acao:
- migrar chamadas de demo session e operadores para o controller em pequenos commits.
- manter testes de replay e aprendizado como guarda.

3. Reverse proxy final para noVNC.

Estado atual:
- CDP e noVNC estao bindados em localhost no teste.
- token/view protegido na API.

Proxima acao:
- desenhar proxy autenticado para BrowserWorkspace.
- garantir que CDP 9222 e VNC 5900 nunca sejam publicos em producao.

4. Usuarios e segredos.

Estado atual:
- usuarios admin/operator por env; hash PBKDF2-SHA256 suportado.
- `.env` e segredos nao foram commitados.

Proxima acao:
- armazenar usuarios em PostgreSQL.
- definir politica de rotacao.
- remover uso de senha direta por env em producao, mantendo apenas hash/secret manager.

5. Frontend React/Lovable.

Estado atual:
- Streamlit temporario recebeu login/logout e cookies de API.

Proxima acao:
- conectar React ao contrato `/api/v1/auth/*`.
- nao usar localStorage/sessionStorage para token.

## P2

- Tratar warnings de teste (`httpx`/Starlette e Streamlit bare mode).
- Adicionar teste explicito de expiracao de sessao.
- Expandir relatorio endpoint-permissao quando o frontend React entrar.

