# Riscos e Pendências

P0:
- Nenhum bloqueio P0 conhecido após Rodada 3.

P1:
- Criar teste de kill real de container durante execução longa, além da fixture controlada.
- Formalizar escopo de idempotência por usuário/tenant quando modelo de usuário do batch for ampliado.
- Criar endpoint/admin mais rico para inspeção histórica de workers offline.

P2:
- Converter estados para check constraints quando dados históricos estiverem totalmente normalizados.
- Evoluir frontend definitivo React/Lovable em rodada própria.
- Reavaliar ações antigas sem `initial_url`/`robust_steps`, como `quantidade-de-parcelas`.

Decisão de segurança:
`quantidade-de-parcelas` não foi executada individualmente porque a action version publicada tem `passos_playwright` legado com `#consultar`, sem URL inicial e sem `robust_steps`. Executar poderia clicar na página atual sem contexto seguro.
