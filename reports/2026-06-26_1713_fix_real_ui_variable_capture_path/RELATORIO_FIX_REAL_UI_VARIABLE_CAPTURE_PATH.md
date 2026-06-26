# Fix real UI variable capture path

Data: 2026-06-26 17:13

## Causa

O caminho real do Streamlit ainda podia enviar `record_action=false` para o backend no Modo operador. O backend obedecia esse booleano do frontend e tratava o preenchimento como helper, mesmo quando a sessao ja estava com `recording=true`.

Consequencia no review real:

- `operator_attempts=0`, porque o contador so era incrementado quando `record_action=true and session.recording`.
- `Campos=0`, porque o operador com `record_action=false` chamava `_prepare_operator_utility`, suprimia os eventos do listener e nao criava evento direto.
- a mensagem "Durante o login, estas acoes nao entram no aprendizado" reforcava o comportamento errado.

## Respostas da auditoria

1. `operator_attempts=0` aparecia porque o endpoint recebia ou podia receber `record_action=false`; nesse caminho o backend nao incrementava tentativas.
2. O botao "Preencher seletor" chama `/api/demo/sessions/{session_id}/operator/fill`.
3. A UI usa o `session_id` de `st.session_state.demo_session_id`; agora tambem envia `operator_request_session_id` e `active_recording_session_id`.
4. Antes, o backend nao usava `recording_active` como fonte de verdade. Agora, se `session.recording=true`, operador grava sempre.
5. Antes, um operador ativo podia virar helper e nao escrever na sessao revisada. Agora o evento inclui `session_id` e o endpoint rejeita mismatch.
6. O review vinha do retorno de `/recording/stop`; ele nao buscava outro estado, mas podia receber uma sessao sem evento porque o operador nao gravou. Agora o stop devolve diagnosticos finais da mesma sessao.
7. O rerun do Streamlit podia manter callbacks/payloads dependentes de estado antigo. A correcao reduz esse risco porque o backend ignora `record_action=false` durante gravacao ativa.
8. Foi adicionada garantia de mesma sessao com `active_recording_session_id`, `operator_request_session_id`, `reviewed_session_id` e `last_recorded_event_session_id`.
9. A mensagem de login foi removida. Durante gravacao ativa, operador por seletor entra no aprendizado mesmo em tela Microsoft/login.
10. O smoke anterior passou porque chamava o backend com `record_action=true` ou testava eventos sinteticos; nao cobria o payload real/stale da UI nem a supressao helper.

## Fix aplicado

- Backend:
  - `operator_fill` e `operator_click` usam `session.recording` como fonte de verdade.
  - Durante gravacao ativa, o preenchimento por seletor sempre incrementa tentativa e grava evento direto `source=operator_mode`.
  - O evento gravado carrega `session_id`.
  - O endpoint retorna `recorded`, `event_id`, `event_type`, `recording_active`, ids de sessao e ultimo evento.
  - Se houver mismatch de sessao, o backend rejeita a operacao.
  - Se um endpoint fosse retornar sucesso sem evento na sessao ativa, ele falha.
  - `insert-active` nao suprime mais o listener durante gravacao ativa.

- Frontend:
  - guarda `demo_active_recording_session_id` ao iniciar gravacao.
  - envia `operator_request_session_id` e `active_recording_session_id` nos requests de operador.
  - bloqueia sucesso falso se o operador nao retornar `recorded=true` durante gravacao.
  - remove a mensagem de que login nao entra no aprendizado.
  - mostra diagnosticos vivos e finais com contadores e ids de sessao.

## Diagnosticos adicionados

- `active_recording_session_id`
- `operator_request_session_id`
- `reviewed_session_id`
- `last_recorded_event_session_id`
- `raw_event_count`
- `click_event_count`
- `fill_event_count`
- `select_event_count`
- `operator_fill_attempt_count`
- `operator_fill_count`
- `last_operator_result`
- `last_backend_recorded_event`
- `direct_typing_capture_status`

## Testes adicionados/atualizados

- operador com gravacao ativa grava evento na mesma sessao mesmo se a UI mandar `record_action=false`.
- operador incrementa tentativas e eventos variaveis.
- review de stop devolve os contadores mais recentes.
- mismatch de sessao e rejeitado.
- operador durante tela de login grava se `recording=true`.
- operador fora de gravacao continua helper.
- UI envia `active_recording_session_id` e mostra diagnosticos.
- input sintetico direto continua gerando variavel.
- acao salva apos operador expoe variavel para execucao rapida.

## Comandos executados

- `python3 -m compileall backend frontend scripts`: passou.
- `docker compose -f docker-compose.test.yml --env-file .env.test up -d --build`: passou.
- `docker compose -f docker-compose.test.yml --env-file .env.test ps`: containers em execucao.
- `curl -sS http://127.0.0.1:8100/health`: primeiro retorno vazio enquanto backend subia; segunda tentativa passou com `{"status":"ok","service":"cotasync"}`.
- `docker exec cotasync_test_backend python -m unittest tests.test_operational_summary tests.test_guided_learning_outputs tests.test_desktop_action_runner tests.test_access_profile_demo_flow`: os testes do patch passaram; a suite ficou com 2 failures por `data/external_systems/current.json` pre-existente conter URL de login nos campos `microsoft_saved_account_identifier` e `expected_system_host`.
- `docker exec cotasync_test_backend python scripts/test_desktop_browser_connection.py`: passou.

## Validacao manual obrigatoria

Ainda precisa ser validado no Streamlit real:

1. Abrir `http://127.0.0.1:3100`.
2. Abrir sessao de navegador.
3. Iniciar gravacao.
4. Em Modo operador, preencher seletor de campo real.
5. Conferir diagnostico vivo: `operator_fill_attempt_count > 0`, `fill_event_count > 0`, `operator_fill_count > 0`.
6. Parar gravacao.
7. Review deve mostrar `Campos > 0`.
8. Variavel deve aparecer em "Revisar variaveis".
9. Salvar acao.
10. Execucao rapida deve mostrar o campo da variavel.

## Limites restantes

- Nao alterei extracao nem login.
- A digitacao direta depende de o recorder estar instalado no frame correto; quando nao estiver, a UI agora mostra motivo em `direct_typing_capture_status`.
- A suite completa depende de `data/external_systems/current.json` estar em estado valido. Esse arquivo ja estava modificado antes do patch e nao foi incluido no commit.
