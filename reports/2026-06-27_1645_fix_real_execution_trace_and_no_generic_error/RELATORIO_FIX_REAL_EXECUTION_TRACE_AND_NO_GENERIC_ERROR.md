# Relatorio - Fix Real Execution Trace And No Generic Error

## Auditoria do runner

- A execucao rapida via `/api/actions/{action_id}/run` entrava em `backend.services.action_runner.finish_action_run`.
- Sem `session_id`, o caminho anterior chamava `backend.agente.executar_acao_fast_track`, mesmo para acao aprendida com `browser_mode=desktop_browser`.
- O chat tambem podia chamar `backend.agente.executar_acao_fast_track` diretamente quando a mensagem batia com a chave da acao.
- O replay assistido com `session_id` usava `backend.services.demo_session.DemoSessionManager.execute_action`.

## Causa do erro generico vazio

- A camada `action_runner` filtrava o `result_payload` e nao preservava campos tecnicos novos como `step_trace`, `screenshot_path`, `exception_type`, `exception_message`, `runner` e flags de browser.
- Quando uma excecao chegava sem `diagnostics`, o payload era reduzido a `input_variables` e `retryable`.
- O resumo operacional ainda tinha fallback generico: "Nao foi possivel concluir a acao no sistema...".
- No caminho direto do chat, erro de desktop devolvia `page_diagnostics` fora de `result_payload`, o que fazia a UI perder dados uteis.

## Fast-track

- Para acoes `desktop_browser`, o `action_runner` agora usa explicitamente `desktop_browser_replay`.
- O fast-track legado continua disponivel para acoes browserless antigas.
- O payload registra `whether_fast_track_used` e `whether_desktop_browser_used`.
- Para acoes desktop aprendidas, o esperado agora e `whether_desktop_browser_used=true` e `whether_fast_track_used=false`.

## Forca do desktop_browser

- A decisao fica em `_is_desktop_learned_action`.
- A configuracao real da acao e carregada de `data/ui_map.json`.
- O replay usa `robust_steps` quando existir, senao `passos_playwright`.
- O runner marcado no payload e `desktop_browser_replay`.

## Step trace

- `backend/motor_browser.py` cria `step_trace` com estado antes/depois de cada passo.
- `backend/services/demo_session.py` tambem registra `step_trace` para execucoes com `session_id`.
- Cada item registra `step_index`, `step_type`, `selector`, `variable_key`, `value_template`, URL, host, titulo, timestamp, status e `elapsed_ms`.
- Em erro, o item recebe `error_message` e `screenshot_path` quando disponivel.

## Screenshot de erro

- Falhas de passo salvam screenshot em `data/runs/<run_id>_step_<index>_<tipo>_error.png`.
- O caminho e colocado em `screenshot_path`.
- O frontend renderiza o screenshot em um expander quando o arquivo existe dentro de `data/runs`.

## Frontend

- A UI agora mostra uma mensagem objetiva: "Parei no passo X ao tentar ...".
- O expander "Diagnostico resumido" inclui runner, browser_mode, flags, URL, host, titulo, passo, excecao e screenshot.
- O expander "Passos executados" mostra `step_trace`.
- O JSON completo segue disponivel em `Ver JSON/result_payload`.

## Variaveis

- `input_variables` continua no payload de sucesso e erro.
- Valores de runtime seguem sendo usados no replay; os testes cobrem preservacao no payload.
- Nao houve hardcode de alvo como "Qtd. Pcls. Pagas".

## Async

- O fluxo async continua persistindo `RunRecord` como `running` e depois atualiza com o resultado final.
- `/api/runs/{run_id}` preserva `result_payload` completo via schema `RunRecord`.

## Testes executados

- `python3 -m compileall backend frontend scripts`
- `docker compose -f docker-compose.test.yml --env-file .env.test up -d --build`
- `docker compose -f docker-compose.test.yml --env-file .env.test ps`
- `curl -sS http://127.0.0.1:8100/health`
- `docker exec cotasync_test_backend python -m unittest tests.test_operational_summary tests.test_guided_learning_outputs tests.test_desktop_action_runner tests.test_access_profile_demo_flow`
- `docker exec cotasync_test_backend python scripts/test_desktop_browser_connection.py`

## Validacao manual pendente

- Pendente executar a rotina real do sistema externo com as variaveis `grupo`, `grupo_2` e `grupo_3`.
- O smoke automatizado validou CDP, noVNC, alvo local, operador fill/click, aprendizado e replay.

## Limites

- Nao foi feita intervencao em sistemas externos.
- O navegador desktop nao e fechado em erro quando o provider preserva sessao, permitindo correcao manual.
- Nao foi implementada uma fila completa de pausar/continuar; o estado do navegador fica preservado para reexecucao quando aplicavel.
