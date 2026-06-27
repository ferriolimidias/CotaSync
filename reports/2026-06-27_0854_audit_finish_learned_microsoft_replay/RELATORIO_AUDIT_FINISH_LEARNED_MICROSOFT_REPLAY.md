# Auditoria e finalizacao do replay Microsoft aprendido

Data: 2026-06-27 08:54
Projeto: CotaSync demo
Repositorio: `/opt/cotasync-test/src`

## Auditoria do estado atual

- `git status --short` antes da correcao indicava alteracoes ja staged em `backend/motor_browser.py`, `backend/services/action_pages.py`, `backend/services/action_runner.py`, `backend/services/actions_repository.py`, `backend/services/demo_session.py`, `backend/services/session_guardian.py`, `frontend/app.py`, `tests/test_desktop_action_runner.py` e um relatorio anterior.
- Tambem havia arquivos locais fora do escopo de commit: `data/external_systems/current.json` modificado e `data/runs/145d80f2-5278-4deb-bacc-b0b95a96ebc6_step_0_clicar_error.png` nao rastreado.
- `git log --oneline -8` mostrou o commit recente `ab38b5b Executa passos Microsoft aprendidos no replay`.

## Implementacao anterior

A ultima implementacao existia e havia commit. Ela ja tinha a direcao correta:

- o guardiao passou a diagnosticar o proximo passo aprendido antes de bloquear telas Microsoft;
- Pick Account e consentimento passaram a depender do passo gravado, nao de clique global;
- senha e MFA continuaram sendo estados de credencial bloqueados;
- metadados `target_text` e `target_label` passaram a ser preservados no aprendizado.

Ela ainda estava incompleta em dois pontos:

- o diagnostico de bloqueio nao expunha todos os campos pedidos no contrato (`next_step_index`, `next_step_type`, `next_step_selector`, `next_step_url_before`, `next_step_host_before`);
- o replay assistido em `DemoSessionManager` ainda dependia de haver seletor para executar clique, mesmo quando o clique aprendido possuia texto/label gravado.

## Correcoes aplicadas

- `backend/services/session_guardian.py`: adicionados campos padronizados do proximo passo no diagnostico e `current_url` no diagnostico de recuperacao.
- `backend/motor_browser.py` e `backend/services/demo_session.py`: os checkpoints agora enriquecem o passo atual/proximo com indice antes de chamar o guardiao.
- `backend/services/demo_session.py`: clique aprendido pode localizar o alvo por `target_text`/`target_label` quando o seletor estiver ausente ou nao resolver.
- `backend/services/action_runner.py`: payloads de sucesso/erro preservam os novos campos de diagnostico.
- `frontend/app.py`: painel de diagnostico mostra os novos campos.
- `tests/test_desktop_action_runner.py`: adicionadas assercoes para Pick Account aprendido, Accept aprendido, bloqueio com proximo passo incompativel e persistencia dos novos diagnosticos.

## Comportamento final

- Pick Account aprendido: executado como clique normal aprendido quando o proximo passo gravado e compativel com a tela atual. Nao depende de perfil fixo Priscila.
- Accept aprendido: executado como clique normal aprendido quando existe passo gravado compativel. Nao ha regra global para clicar Accept.
- Consentimento sem passo gravado compativel: bloqueia com `operator_action_required=true`, `retryable=true`, host/estado atual e diagnostico do proximo passo.
- Senha/MFA: continuam bloqueadas sempre; nao ha automacao de senha ou MFA.
- Variaveis: preservadas, incluindo preenchimento de operador e select como variavel.
- Async: preservado; runs async continuam persistindo estado `running` e resultado final.
- Extracao por rotulo: preservada; testes de aprendizado e saida operacional continuam passando.

## Respostas objetivas

1. A ultima implementacao existe? Sim.
2. Ha commit dela? Sim: `ab38b5b Executa passos Microsoft aprendidos no replay`.
3. O guardiao ainda bloqueia `microsoft_consent_required` antes do replay tentar passos aprendidos? Nao, quando o proximo passo aprendido e compativel.
4. O runner verifica o proximo passo aprendido antes de bloquear? Sim, nos checkpoints antes/depois de passo e ao abrir nova pagina.
5. Pick Account gravado e executado como clique normal? Sim.
6. Accept gravado e executado como clique normal? Sim.
7. Consentimento sem passo gravado continua bloqueando? Sim.
8. Senha/MFA continuam bloqueadas? Sim.
9. Variaveis e execucao async foram preservadas? Sim.
10. O que faltava e foi corrigido nesta rodada? Diagnostico completo do proximo passo e fallback de replay por texto/label aprendido no fluxo assistido.

## Testes executados

- `python3 -m compileall backend frontend scripts` - OK.
- `python3 -m unittest tests.test_operational_summary tests.test_guided_learning_outputs tests.test_desktop_action_runner tests.test_access_profile_demo_flow` - falhou no host por dependencias ausentes (`pydantic`/`fastapi`), esperado fora do container.
- `docker compose -f docker-compose.test.yml --env-file .env.test up -d --build` - OK.
- `docker compose -f docker-compose.test.yml --env-file .env.test ps` - OK; servicos backend, frontend, browserless, desktop browser, postgres e redis ativos.
- `curl -sS http://127.0.0.1:8100/health` - primeira tentativa retornou reset durante estabilizacao do backend; repeticao OK: `{"status":"ok","service":"cotasync"}`.
- `docker exec cotasync_test_backend python -m unittest tests.test_operational_summary tests.test_guided_learning_outputs tests.test_desktop_action_runner tests.test_access_profile_demo_flow` - OK, 96 testes.
- `docker exec cotasync_test_backend python scripts/test_desktop_browser_connection.py` - OK.

## Pendencias de validacao manual

- Validar em navegador real uma rotina gravada que contenha Pick Account, Accept, navegacao ao sistema, consulta e extracao de resultado.
- Confirmar visualmente que, sem passo Accept gravado, a tela bloqueia com diagnostico claro em vez de clicar por heuristica.

## Arquivos locais nao commitados

- `data/external_systems/current.json`: permanece local sujo e nao deve ser commitado.
- `data/runs/145d80f2-5278-4deb-bacc-b0b95a96ebc6_step_0_clicar_error.png`: permanece nao rastreado e nao deve ser commitado.
