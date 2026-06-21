# Relatório Fase 1D — Streamlit consumindo API de ações

## Resumo executivo

O catálogo e a sidebar de ações aprendidas do Streamlit passaram a consumir `GET /api/actions`. A resposta é normalizada em um client HTTP isolado, com timeout de 5 segundos. Quando a API falha, a interface usa temporariamente `data/ui_map.json`; quando ambas as fontes falham, exibe erro controlado sem stack trace.

Os fluxos de chat, aprendizado, execução rápida e lote não foram reescritos. A execução rápida continua chamando `executar_acao_fast_track` com a chave legada da ação, e o lote permanece com a leitura local existente.

## Commit base

- `1c51ffa8bf3f837414efc47e9b34a07e3dc7b56d`

## Arquivos alterados

- `frontend/api_client.py`: client de `GET /api/actions`, normalização, fallback local e resultado com origem.
- `frontend/app.py`: catálogo e sidebar passam a usar o resultado do client; mensagens controladas; exclusão continua local.
- `docker-compose.test.yml`: configuração de `COTASYNC_API_BASE_URL` no frontend.
- `scripts/test_streamlit_actions_api_integration.sh`: smoke test da integração.
- Este relatório.

## Leitura anterior de `ui_map.json` no Streamlit

Antes desta fase, `frontend/app.py` lia diretamente o arquivo nos seguintes pontos:

- inicialização global da lista de ações, via `_carregar_ui_map()`;
- sidebar de execução rápida, com uma nova leitura local a cada execução do script;
- fluxo de operação em lote;
- Catálogo de Ações, com leitura e parsing próprios;
- exclusão de uma ação no catálogo.

Nesta fase, somente a leitura/listagem global, a sidebar e o catálogo foram migrados. A leitura do lote foi mantida por estar explicitamente fora do escopo. A exclusão continua gravando localmente e só lê o arquivo quando o usuário aciona o botão.

## Consumo de `GET /api/actions`

`get_actions_from_api()` consulta `${API_BASE_URL}/api/actions` com timeout de 5 segundos, valida o envelope `actions` e normaliza cada item para os campos usados pela interface: chave, nome, descrição, variáveis, contagem de passos e metadados.

`get_actions_for_ui()` tenta a API primeiro e retorna `source="api"` em caso de sucesso. O Streamlit indexa essa lista pela chave legada, preservando o identificador usado pelo fluxo atual de execução rápida.

O catálogo apresenta nome, descrição, variáveis e contagem de passos fornecidos pela API. Catálogo vazio e sidebar vazia usam a mensagem `Nenhuma ação aprendida ainda.`

## Fallback local

`get_actions_fallback_local()` mantém a leitura de `data/ui_map.json` e converte o formato legado para o mesmo formato normalizado da API.

Quando a API falha e o arquivo local é válido, a interface exibe discretamente `API indisponível, usando leitura local temporária.` Quando API e arquivo falham, exibe `Não foi possível carregar as ações aprendidas no momento.` sem detalhes técnicos ou stack trace.

## Variável de ambiente

- Nome: `COTASYNC_API_BASE_URL`
- Valor no compose de teste: `http://cotasync_test_backend:8000`
- Fallback do client: `http://cotasync_test_backend:8000`
- Compatibilidade mantida com `st.secrets["API_BASE_URL"]` quando a variável de ambiente não estiver definida.

Não é usado `localhost` para comunicação frontend → backend dentro do container.

## Validações executadas

- `python3 -m compileall backend frontend scripts`: passou.
- Teste direto do client com resposta API simulada, fallback local válido e fallback local inválido: passou.
- `bash -n scripts/test_streamlit_actions_api_integration.sh`: passou.
- `docker compose -f docker-compose.test.yml --env-file .env.test up -d --build`: passou.
- `docker compose -f docker-compose.test.yml --env-file .env.test ps`: cinco serviços em execução; PostgreSQL saudável.
- `scripts/test_streamlit_actions_api_integration.sh`: passou.
- `Streamlit AppTest`: script executado sem exceções, título e configuração da API confirmados.
- Fixture local segura: API retornou uma ação; client a consumiu com origem `api`; sidebar renderizou a ação; arquivo original foi restaurado ao final.
- `git diff --check`: passou.

## Resultados dos curls

- `GET http://127.0.0.1:8100/health`: HTTP 200, `{"status":"ok","service":"cotasync"}`.
- `GET http://127.0.0.1:8100/api/health/browserless`: HTTP 200, `status=ok`, conexão pelo hostname interno do Browserless.
- `GET http://127.0.0.1:8100/api/actions`: HTTP 200, `status=ok`, `count=0`, `actions=[]` no estado original do workspace.
- `GET http://127.0.0.1:8100/api/runs`: HTTP 200, `status=ok`, `count=0`, `runs=[]`.
- `HEAD http://127.0.0.1:3100`: HTTP 200, `content-type: text/html; charset=utf-8`.
- Verificação textual de `GET http://127.0.0.1:3100`: shell HTML do Streamlit retornado.

## Logs relevantes

- Frontend: entrypoint preservou os arquivos de dados; Streamlit/Uvicorn iniciou em `0.0.0.0:8501`; nenhum traceback ou erro do client de actions nos 120 registros recentes.
- Backend: startup completo; requisições a `/health`, `/api/health/browserless`, `/api/actions` e `/api/runs` responderam 200; nenhum erro nos 120 registros recentes.

## Limitações

- `GET /api/actions` fornece resumo e contagem de passos, não os seletores e valores completos anteriormente lidos diretamente do arquivo. O catálogo mostra a contagem segura retornada pela API.
- A exclusão ainda é uma operação local, pois não existe endpoint de exclusão e sua migração não pertence a esta fase.
- O lote continua lendo `data/ui_map.json`, conforme escopo.
- O client é síncrono e roda a cada rerun do Streamlit; uma indisponibilidade da API pode aguardar até 5 segundos antes do fallback.

## Riscos

- Se frontend e backend deixarem de compartilhar o mesmo volume, a exclusão local poderá divergir temporariamente do catálogo servido pela API.
- Mudanças futuras no contrato de `/api/actions` exigirão ajuste da normalização do client.
- Catálogos muito grandes podem justificar cache curto do Streamlit em fase posterior.

## Próximos passos

- Considerar cache curto com invalidação após aprendizado/exclusão.
- Definir endpoint de exclusão antes de migrar a escrita do catálogo.
- Em fase futura, avaliar detalhe de ação via API para enriquecer a visualização dos passos sem leitura direta do arquivo.
- Migrar o seletor do lote somente em fase própria, com teste específico do fluxo.
