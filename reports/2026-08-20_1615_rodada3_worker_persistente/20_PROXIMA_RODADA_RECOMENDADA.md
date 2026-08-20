# Próxima Rodada Recomendada

Rodada 4 recomendada: hardening operacional do worker e preparação do frontend definitivo.

Escopo recomendado:
- teste de kill real do container worker durante uma ação longa controlada.
- painel autenticado para histórico de workers e batches interrompidos.
- normalização das ações antigas sem `initial_url`/`robust_steps`.
- revisar uso de IA no resumo do batch real local para evitar custo em smoke quando não necessário.
- preparar integração com frontend React/Lovable sem mudar o contrato da fila.

Não iniciar automaticamente:
esta rodada termina com worker persistente, migrations, testes, regressão, relatórios, commit, push e tag.
