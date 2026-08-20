# Pendências Rodada 3

P1: worker persistente de batches com recuperação e heartbeat.
Evidência: `batch_runner` ainda é síncrono/in-process.
Impacto: sem isso, a retomada pós-restart fica incompleta.

P1: saneamento do legado JSON auxiliar fora do núcleo operacional.
Evidência: `backend/agente.py`, `backend/demo_session.py`, `backend/main.py` e scripts de apoio ainda escrevem/lem JSON.
Impacto: o código operacional principal já não depende disso, mas a base ainda guarda rotas antigas.

P2: `learning_sessions` não foi criada nesta rodada.
Evidência: schema aplicado sem essa tabela.
Impacto: pode ser adicionada depois, se houver valor operacional real.

P2: limpeza dos dados de validação que ficaram no banco compartilhado.
Evidência: `runs` cresceu de 31 para 38 após suíte e smoke.
Impacto: comparação histórica fica menos limpa até a próxima etapa.
