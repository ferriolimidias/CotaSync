# Relatorio - Fila de execucao em massa

## Auditoria

Arquivos revisados antes da alteracao:

- `frontend/app.py`: UI Streamlit, menu lateral, execucao rapida individual e tela legada de agendamentos/lote.
- `frontend/api_client.py`: cliente HTTP da API e normalizacao do catalogo de acoes.
- `backend/api/actions.py`: endpoints de catalogo, validacao e selecao visual.
- `backend/api/runs.py`: endpoint de execucao individual e consulta de runs.
- `backend/services/action_runner.py`: ponto central de execucao individual, criacao de `run_id`, status, resumo operacional e payload.
- `backend/services/actions_repository.py`: leitura das acoes aprendidas e `variable_schema`.
- `backend/services/demo_session.py`: execucao em sessao de demonstracao.
- `backend/motor_browser.py`: replay desktop/noVNC/Playwright.
- `backend/services/result_selection.py`: contrato de selecao visual.
- `backend/services/extraction_targets.py`: extracao de valores.
- Testes existentes de aprendizado guiado, desktop runner, resumo operacional e perfil de acesso.

Conclusao da auditoria:

- Ja existia estrutura de `runs` assinc/sync para execucao individual.
- A execucao em massa deve chamar a mesma camada de execucao individual para preservar replay, extracao, resumo operacional e historico por `run_id`.
- A tela legada "Agendamentos e Filas" usa caminho antigo com concorrencia. Ela foi preservada, mas a nova arquitetura correta foi criada em aba propria: "Execucao em massa".

## Arquitetura da fila

Foi criado `backend/services/batch_runner.py`.

O batch e persistido em `data/batches/{batch_id}.json` com:

- `batch_id`
- `action_id`
- `action_key`
- `status`
- `requested_by`
- `delay_between_rows_seconds`
- `created_at`
- `started_at`
- `finished_at`
- `cancel_requested`
- `rows`

Cada linha guarda:

- `index`
- `variables`
- `status`
- `run_id`
- `operational_summary`
- `result_payload`
- `dados_extraidos`
- `error_message`
- `started_at`
- `finished_at`

## Por que sequencial

A fila foi implementada como padrao do produto, nao como limitacao temporaria. O CotaSync opera sistemas externos sem API, usando navegador desktop/noVNC/Playwright como uma pessoa. Executar em paralelo no mesmo ambiente pode disputar sessao, trocar telas durante a consulta, quebrar o fluxo aprendido e aumentar risco operacional.

O fluxo implementado e:

1. pega uma linha pendente;
2. marca como `running`;
3. executa a acao individual completa via `run_action_sync`;
4. salva `run_id`, resumo, payload e erro/sucesso;
5. aguarda `delay_between_rows_seconds`, padrao 3;
6. inicia a proxima linha.

## Endpoints criados

Arquivo: `backend/api/batches.py`

- `POST /api/batches`: cria lote, valida dados e inicia worker sequencial assincrono.
- `GET /api/batches`: lista lotes recentes.
- `GET /api/batches/{batch_id}`: retorna status geral e linhas.
- `GET /api/batches/{batch_id}/results.csv`: exporta CSV final.
- `POST /api/batches/{batch_id}/cancel`: marca cancelamento e para antes da proxima linha segura.

## UI criada

Arquivo: `frontend/app.py`

Nova aba no menu lateral:

- "Execucao em massa"

Componentes:

- selectbox de acao;
- painel de variaveis obrigatorias;
- textarea para CSV;
- file uploader CSV;
- botao "Validar lote";
- botao "Executar lote";
- delay configuravel, padrao 3 segundos;
- progress bar;
- tabela de resultados;
- download do CSV final;
- historico recente.

## Formato do CSV

Entrada aceita:

```csv
grupo,grupo_2,grupo_3
935,110,00
935,111,00
```

Exportacao final:

```text
batch_id
row_index
action_id
status
run_id
variables_json
operational_summary
dados_extraidos_json
error_message
started_at
finished_at
```

## Validacao de variaveis

A validacao usa as variaveis obrigatorias vindas do catalogo da acao (`variables` normalizado a partir de `variable_schema`/`variaveis_necessarias`).

Erros tratados:

- CSV vazio;
- coluna obrigatoria ausente;
- valor obrigatorio vazio por linha;
- acao inexistente.

## Preservacao de zeros a esquerda

O parser usa `csv.DictReader` sobre texto e nao converte campos para numero. Assim valores como `"00"` permanecem string `"00"` tanto no frontend quanto no backend.

Tambem aceita BOM UTF-8 e ignora linhas vazias.

## Execucao sequencial

O worker chama `run_action_sync(action, request)` para cada linha. A proxima linha so inicia depois que a anterior conclui com `success` ou `error`, e depois do delay configurado.

Se uma linha falha, o lote continua. O status final e:

- `success`: todas passaram;
- `partial_success`: houve sucesso e erro;
- `error`: todas falharam;
- `canceled`: cancelamento solicitado;
- `running`: em execucao.

## Bloqueio de paralelismo

O servico usa:

- lock global em memoria para o worker do desktop/session;
- checagem de batch persistido em `pending` ou `running` antes de criar outro lote.

Se ja houver lote em execucao ou pendente no mesmo ambiente, `POST /api/batches` retorna conflito com mensagem clara.

## Salvamento de resultados

Cada atualizacao relevante regrava o JSON do batch:

- criacao;
- inicio do batch;
- inicio da linha;
- fim da linha;
- fim do batch;
- cancelamento.

Os resultados tambem continuam associados ao historico normal de `runs`, pois cada linha cria seu proprio `run_id`.

## Testes

Novo arquivo:

- `tests/test_batch_runner.py`

Coberturas:

- parse de CSV colado;
- BOM UTF-8;
- linhas vazias;
- preservacao de zeros a esquerda;
- validacao de colunas obrigatorias;
- validacao no cliente Streamlit;
- criacao e persistencia de lote;
- bloqueio de dois batches simultaneos;
- execucao sequencial;
- delay entre linhas;
- erro em uma linha sem interromper o lote;
- status `partial_success`;
- exportacao CSV.

Validacoes executadas:

```bash
python3 -m compileall backend frontend scripts
docker compose -f docker-compose.test.yml --env-file .env.test up -d --build
docker compose -f docker-compose.test.yml --env-file .env.test ps
sleep 5 && curl -sS http://127.0.0.1:8100/health
docker exec cotasync_test_backend python -m unittest tests.test_batch_runner tests.test_operational_summary tests.test_guided_learning_outputs tests.test_desktop_action_runner tests.test_access_profile_demo_flow
docker exec cotasync_test_backend python scripts/test_desktop_browser_connection.py
curl -sS http://127.0.0.1:8100/api/batches
```

Resultado:

- compileall OK;
- build Docker OK;
- containers OK;
- healthcheck OK;
- 128 testes unitarios OK;
- desktop browser/noVNC/CDP/replay OK;
- `GET /api/batches` OK.

Observacao: os testes unitarios no Python do host nao rodaram por ausencia de dependencias (`pydantic`, `fastapi`). A validacao foi feita no container oficial de teste.

## Validacao manual

Validacao de infraestrutura concluida. A validacao manual pela UI deve seguir:

1. Abrir CotaSync em `http://localhost:3100`.
2. Entrar em "Execucao em massa".
3. Escolher "numero de parcelas pagas".
4. Colar:

```csv
grupo,grupo_2,grupo_3
935,110,00
935,111,00
```

5. Validar lote.
6. Executar lote.
7. Confirmar progresso linha a linha.
8. Confirmar pausa entre linhas.
9. Confirmar resultados por linha.
10. Baixar CSV final.

## Limitacoes

- O lock global e em memoria do processo backend; a persistencia impede criacao de novo batch enquanto existir batch `pending`/`running` salvo.
- A fila nao retoma automaticamente uma linha interrompida se o processo backend for reiniciado no meio da execucao.
- Cancelamento nao mata a linha corrente para evitar risco operacional; ele para antes da proxima linha.
- A tela legada "Agendamentos e Filas" foi preservada e ainda contem fluxo antigo separado.
- Nao foi implementado PDF/download.
- Nao foi implementado paralelismo.
- Nao foram criadas sessoes ou navegadores multiplos.

## Proximos passos

- Adicionar retomada controlada de batches interrompidos.
- Expor cancelamento na UI.
- Adicionar reprocessamento de linhas com erro.
- Adicionar agendamento noturno e divisao por lotes.
- Adicionar controle mais explicito por desktop/session se houver multiplos ambientes isolados no futuro.
