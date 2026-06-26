# Relatorio - Fix quick action timeout handling

Data: 2026-06-26 18:15
Commit base informado: 8811724
Projeto: CotaSync demo

## Causa

A execucao rapida do Streamlit chamava `POST /api/actions/{id}/run` em modo `sync` com `timeout=60`.
As rotinas aprendidas contra sistemas reais continuam executando no backend por 2 a 5 minutos, mas o cliente HTTP do frontend transformava qualquer `requests.RequestException`, incluindo timeout, em `DemoApiError("API da demonstracao indisponivel.")`.

Com isso, a API estava saudavel e a acao seguia rodando, mas a UI mostrava indisponibilidade da API.

## Respostas da auditoria

1. A requisicao que estava expirando era `POST /api/actions/{action_id}/run` disparada pela sidebar de acoes aprendidas em `frontend/app.py`.
2. O timeout usado nessa execucao era `60` segundos. O fluxo de demo tambem tinha uma execucao aprendida em `sync` com `timeout=30`.
3. O backend ja criava a run antes da automacao e atualizava a run no `finally`, mas o modo sincronizado deixava a persistencia final dependente da requisicao longa continuar viva no servidor apos o timeout do cliente.
4. A UI mostrava API indisponivel porque `frontend/api_client.py` capturava timeout junto com erro de conexao e emitia a mesma mensagem generica.
5. `[FAST-TRACK]` ainda e o caminho usado para execucao sem `session_id`: `/api/actions/{id}/run` chama `backend.services.action_runner`, que chama `backend.agente.executar_acao_fast_track`, que delega para `backend.motor_browser.executar_acao_rapida`. Ele nao foi removido nesta correcao; agora continua persistindo a run pelo `action_runner` e os diagnosticos retornados por esse caminho sao preservados em `result_payload`.

## Fix

- `demo_api_request` agora distingue `requests.Timeout` de indisponibilidade real e levanta `DemoApiTimeout` com a mensagem:
  `A ação ainda está em execução ou demorou mais que o esperado. Vou buscar o resultado mais recente.`
- `ActionRunRequest.mode` aceita `async`.
- O backend separou a criacao da run (`start_action_run`) da finalizacao (`finish_action_run`).
- `POST /api/actions/{id}/run` com `mode="async"` grava a run como `running`, retorna imediatamente e finaliza em task de background.
- A sidebar de acoes aprendidas usa `mode="async"` e faz polling de `/api/runs/{run_id}` por ate 300 segundos.
- O fluxo "Executar ação aprendida" da demo tambem passou a usar o mesmo polling assíncrono, preservando `session_id`.
- Ao esgotar o tempo de polling, a UI busca `/api/runs?action_id={id}&limit=1` e mostra o resultado mais recente quando disponivel.
- O botao de execucao rapida fica desabilitado enquanto a execucao esta em andamento no processo Streamlit.
- A normalizacao do perfil externo descarta URL OAuth gravada por engano em campos de identificador/host, evitando contaminar os defaults usados nos testes de perfil.

## Comportamento de timeout

- Timeout de inicio da execucao async: 20 segundos.
- Timeout de cada consulta de polling: 10 segundos.
- Janela maxima de espera da UI: 300 segundos.
- Timeout nao mostra mais "API da demonstracao indisponivel".
- Em timeout, a UI informa que a acao ainda pode estar rodando e tenta buscar a run mais recente.

## Persistencia de runs

O backend persiste a run antes da automacao:

- `pending`
- `running`
- `success` ou `error`

Ao finalizar, a run continua preenchendo:

- `status`
- `operational_summary`
- `result_payload`
- `variables`
- `step_diagnostics` quando retornado pelo caminho de execucao
- `technical_summary`

`/api/runs` continua retornando a lista ordenada pela run mais recente.

## Fast-track

O fast-track ainda e um caminho ativo, nao apenas legado morto:

- com `session_id`, o runner usa `demo_session_manager.execute_action`;
- sem `session_id`, o runner usa `executar_acao_fast_track`;
- `executar_acao_fast_track` chama `executar_acao_rapida`, que gera logs `[FAST-TRACK]`.

Nesta correcao, o quick execution continua passando pelo `action_runner`; portanto nao bypassa persistencia de runs. A troca principal foi retirar a execucao longa da conexao HTTP do Streamlit.

## Testes e validacao

Comandos executados:

```bash
python3 -m compileall backend frontend scripts
docker compose -f docker-compose.test.yml --env-file .env.test up -d --build
docker compose -f docker-compose.test.yml --env-file .env.test ps
curl -sS http://127.0.0.1:8100/health
docker exec cotasync_test_backend python -m unittest tests.test_operational_summary tests.test_guided_learning_outputs tests.test_desktop_action_runner tests.test_access_profile_demo_flow
docker exec cotasync_test_backend python scripts/test_desktop_browser_connection.py
```

Resultados:

- `compileall`: OK
- `docker compose ps`: containers backend, frontend, browserless, desktop browser, postgres e redis ativos; desktop browser healthy
- `/health`: `{"status":"ok","service":"cotasync"}`
- unit tests: 87 testes OK
- desktop browser smoke: OK

Observacao: a execucao local fora do container nao foi usada como validacao final porque o host nao possui dependencias Python do projeto (`pydantic`/`fastapi`). A validacao final foi feita no container backend.

## Limites

- Tasks async em memoria dependem do processo backend continuar vivo; nao ha fila persistente externa para retomada apos restart.
- O fast-track ainda contem uma falha operacional possivel quando um passo `extrair_texto` vem sem seletor; essa condicao ja aparece como run `error` com `operational_summary` e `result_payload`, mas nao foi escopo deste fix.
- Historico existente em `data/runs` pode conter execucoes antigas em `sync`; a mudanca vale para novos disparos da UI.

## Proximo passo sugerido

Persistir execucoes async em uma fila duravel quando o demo precisar tolerar restart do backend durante a automacao.
