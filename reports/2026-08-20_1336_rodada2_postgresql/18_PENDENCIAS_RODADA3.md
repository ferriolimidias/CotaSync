# Pendências Rodada 3

P1: worker persistente de batches com recuperação e heartbeat.
Evidência: `batch_runner` ainda é síncrono/in-process.
Impacto: sem isso, a retomada pós-restart fica incompleta.

P2: `learning_sessions` não foi criada nesta rodada.
Evidência: schema aplicado sem essa tabela.
Impacto: pode ser adicionada depois, se houver valor operacional real.

P2: legado JSON apenas como compatibilidade/migração.
Evidência: `ui_map.json`, `runs.json`, `clients.json` e `current.json` ainda existem fisicamente.
Impacto: não são mais fonte de verdade operacional, mas podem ser limpos mais tarde.
