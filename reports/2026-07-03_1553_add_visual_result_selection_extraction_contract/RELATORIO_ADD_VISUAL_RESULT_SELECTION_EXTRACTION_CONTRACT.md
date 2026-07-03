# Relatorio - Seletor visual de resultado e contrato de extracao

Data: 2026-07-03 15:53

## Auditoria

Arquivos revisados antes da alteracao:

- `frontend/app.py`: UI Streamlit do aprendizado, validacao, replay e exibicao de dados extraidos.
- `frontend/api_client.py`: normalizacao do catalogo de acoes, ja expondo `reviewed_overlay`, `extraction_review` e `final_summary_instruction`.
- `backend/api/actions.py`: endpoints de catalogo e validacao de review.
- `backend/api/demo.py`: endpoints de sessao assistida, operador e salvamento de aprendizado.
- `backend/services/demo_session.py`: sessao atual do browser, recorder, replay assistido e captura da tela final.
- `backend/services/action_runner.py`: orquestracao de run rapida, sanitizacao do payload e resumo operacional.
- `backend/motor_browser.py`: replay desktop/browserless e extracao final durante execucao rapida.
- `backend/services/extraction_targets.py`: extrator generico por proximidade de label.
- `backend/services/actions_repository.py`: leitura do `data/ui_map.json` e campos persistidos da acao.
- `backend/services/operational_summary.py`: resumo deterministico/IA usando dados extraidos e overlay.
- `data/ui_map.json`: formato atual das acoes aprendidas, incluindo mapa mecanico e overlays.
- Testes indicados: `tests/test_guided_learning_outputs.py`, `tests/test_desktop_action_runner.py`, `tests/test_operational_summary.py`, `tests/test_access_profile_demo_flow.py`.

## Causa da extracao errada

A extracao atual usa `extract_value_near_label`, que percorre linhas/celulas e pega o valor proximo ao texto procurado. Em telas com tabela grande, esse algoritmo nao sabe diferenciar label de rodape, cabecalho de coluna e celula de dados. Para `% Pagar`, ele pode encontrar um texto parecido no contexto da tabela e retornar a proxima celula/cabecalho, como `Ocorrência`, porque nao ha contrato visual nem validacao de tipo antes do fallback generico.

## Novo modo seletor de resultado

Foi adicionado o modo "Selecionar resultado na tela":

- UI em `frontend/app.py` com campos `O que esta rotina deve retornar?` e `Rotulo visivel, se souber`.
- Botao para ativar selecao visual no browser atual.
- Botao para detectar candidatos automaticamente.
- Captura do proximo clique selecionado.
- Lista de candidatos para confirmacao pelo operador.
- Confirmacao que salva contrato de extracao.
- Exibicao do contrato salvo na tela.

Endpoints adicionados:

- `POST /api/actions/{action_id}/result-selection/start`
- `POST /api/actions/{action_id}/result-selection/capture`
- `POST /api/actions/{action_id}/result-selection/confirm`
- `POST /api/actions/{action_id}/extraction-candidates`

## Formato do contrato

O contrato e salvo em:

- `action.reviewed_overlay.extraction`
- `action.extraction_review`
- `action.final_summary_instruction`

O mapa mecanico existente e preservado: `passos_playwright`, `robust_steps`, `learning_events`, `variable_schema`, `url_inicial` e campos anteriores do overlay nao sao apagados fora da extracao atualizada.

Campos principais:

- `selection_type`
- `target_name`
- `screen_label`
- `selected_text`
- `example_value`
- `value_type`
- `selector_hint`
- `label_selector`
- `value_selector`
- `region_selector`
- `table_headers`
- `row_context`
- `nearby_text`
- `avoid_labels`
- `return_format`
- `summary_instruction`
- `needs_attention`
- `validation`
- `source=visual_result_selection`

## Candidatos deterministicos

Foi criado `backend/services/result_selection.py` com:

- parser deterministico de tabelas HTML;
- deteccao de pares label/valor em texto;
- deteccao de celulas e colunas;
- distincao entre cabecalho e rodape;
- classificacao inicial em `field_value`, `table_footer_total`, `table_cell` e `block_text`;
- validacao de tipo numerico/percentual/monetario;
- rejeicao de cabecalhos comuns como `Ocorrência`, `Valor Pagar`, `Parcela Paga`, `NA`, `PR`, `RT`.

## Suporte por tipo

- `field_value`: campo simples proximo a um rotulo, como `Qtd. Pcls. Pagas -> 038`.
- `table_footer_total`: totalizadores/rodape de tabela, como `% Pagar -> 0,0000`.
- `table_cell`: celula especifica de tabela com linha, coluna e cabecalhos.
- `block_text`: bloco/regiao textual selecionado pelo operador.

## Uso na execucao rapida

A prioridade agora e:

1. contrato visual em `reviewed_overlay.extraction`;
2. `reviewed_overlay.extraction` nao visual;
3. `extraction_review`;
4. alvo por rotulo nos passos aprendidos;
5. fallback generico existente.

No replay desktop em `backend/motor_browser.py` e no replay assistido em `backend/services/demo_session.py`, o DOM/texto final e capturado e o contrato e aplicado antes do retorno final. Se o contrato encontra valor valido, ele sobrescreve o resultado generico para o alvo contratado. Se o valor nao bate com o tipo esperado, o payload recebe `extraction_attention.needs_attention=true`.

## Como evitar quebrar Qtd. Pcls. Pagas

O extrator generico por proximidade foi preservado. O contrato visual so entra quando existe overlay/review salvo. O detector tambem aceita `field_value` e continua encontrando `Qtd. Pcls. Pagas -> 038`, coberto por teste.

## Como tabela, linha, coluna e rodape sao detectados

O detector parseia `table/tr/th/td`, identifica cabecalhos pela primeira linha com `th` ou primeira linha da tabela, calcula `table_row_index`, `table_col_index`, `column_header`, `table_headers` e `row_context`. Rodape e considerado quando a linha nao e cabecalho e esta nas ultimas linhas ou contem termos de totalizacao como `total`, `totais` ou `% Cont.`. Cabecalhos nao viram rodape.

## Como o modo selecao conversa com o browser atual

`DemoSessionManager.start_result_selection` injeta JavaScript na `page` ativa da sessao. O script destaca elementos no hover e intercepta o proximo clique. `capture_result_selection` le `window.__cotasyncResultSelection.captured`, complementa URL/titulo/host e gera candidatos com base no DOM final da mesma pagina.

## Testes

Executados:

- `python3 -m compileall backend frontend scripts`
- `docker compose -f docker-compose.test.yml --env-file .env.test up -d --build`
- `docker compose -f docker-compose.test.yml --env-file .env.test ps`
- `curl -sS --retry 10 --retry-delay 2 --retry-all-errors http://127.0.0.1:8100/health`
- `docker exec cotasync_test_backend python -m unittest tests.test_operational_summary tests.test_guided_learning_outputs tests.test_desktop_action_runner tests.test_access_profile_demo_flow`
- `docker exec cotasync_test_backend python scripts/test_desktop_browser_connection.py`

Resultado:

- Compile OK.
- Health OK.
- 119 testes OK no container.
- Smoke do desktop browser OK.

Coberturas adicionadas:

- contrato visual salvo sem apagar mapa mecanico;
- candidato selecionado vira `extraction_review`;
- `final_summary_instruction` gerada a partir do contrato;
- execucao rapida prioriza contrato visual sobre resultado generico errado;
- `field_value` simples continua funcionando;
- `table_footer_total` para `% Pagar` rejeita `Ocorrência`;
- mismatch de tipo marca `needs_attention`;
- detector identifica label/value proximos;
- detector distingue coluna `Valor Pagar` de totalizador `% Pagar`;
- `Qtd. Pcls. Pagas` continua extraindo `038`.

As suites existentes continuam cobrindo variaveis, async, replay desktop, validacao/replay real simulado e sem dependencia de sistema externo real.

## Validacao manual

Passos para validar com a acao real:

1. Abrir a acao "Porcentagem a pagar".
2. Usar a tela final ja aberta ou executar a rotina.
3. Preencher `O que esta rotina deve retornar?` com `porcentagem a pagar`.
4. Preencher `Rotulo visivel, se souber` com `% Pagar`.
5. Clicar `Selecionar resultado na tela`.
6. No navegador desktop, clicar no totalizador correto do rodape.
7. Clicar `Capturar clique selecionado`.
8. Escolher o candidato correto, preferencialmente `table_footer_total`.
9. Salvar contrato de extracao.
10. Executar a acao rapida novamente.
11. Confirmar que `dados_extraidos` retorna somente o valor de `% Pagar` e nao `Ocorrência`.

## Limites

- PDF/download/impressao nao foram alterados.
- Nao houve automacao de consentimento, senha ou MFA.
- A selecao visual usa o DOM disponivel na pagina atual; paginas com shadow DOM fechado ou canvas puro podem exigir evolucao posterior.
- A heuristica de rodape e deterministica, mas ainda conservadora; se uma tela tiver totalizadores sem termos de totalizacao e longe das ultimas linhas, o operador deve confirmar o candidato correto.

## Proximos passos

- Melhorar destaque visual com painel flutuante de confirmacao no proprio browser.
- Persistir multiplos contratos por acao quando a rotina retornar mais de um campo.
- Adicionar modo de recaptura/edicao de contrato sem reexecutar a rotina.
- Ampliar suporte a iframes na selecao visual.
