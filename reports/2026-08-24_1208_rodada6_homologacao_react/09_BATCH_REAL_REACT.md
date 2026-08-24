# Batch Real React

Rota: `/execucao`.

Estado: fluxo de batch da Rodada 5 foi mantido e recebeu exportação CSV final por `/api/v1/batches/{id}/results.csv`.

Regra visual: UI continua explicitando `1 cliente por vez`, sem concorrência configurável.

Teste: contratos de batch, idempotência, polling e CSV passaram. Batch real operacional de 2 ou 3 clientes não foi executado porque as ações seguras disponíveis não cobrem os clientes operacionais sem risco/sem sessão externa.
