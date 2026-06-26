# Relatorio - Fix learned Microsoft steps replay

Data: 2026-06-26 19:09
Projeto: CotaSync demo

## Causa do bloqueio

A execucao desktop chamava o Guardiao de Sessao como bloqueador antes de tentar os passos aprendidos:

- `backend/motor_browser.py`: `run_session_checkpoint(... "before_action_auth_check")` antes do loop de `passos_playwright`.
- `backend/services/demo_session.py`: `await run_session_checkpoint("before_action_auth_check")` antes do loop de `steps`.

Quando a pagina atual era Microsoft consent, `SessionGuardian.ensure_authenticated()` classificava como `microsoft_consent_required` e retornava `operator_action_required=true`, sem verificar se o proximo passo gravado era justamente clicar em `Accept`.

## Respostas da auditoria

1. O bloqueio acontecia em `SessionGuardian.ensure_authenticated()`, chamado por `run_session_checkpoint()` no fast-track e no replay de sessao.
2. Sim. O bloqueio acontecia antes do replay dos passos aprendidos, em `before_action_auth_check`, e tambem podia acontecer entre passos em `before_step_auth_check` / `after_step_stability_check`.
3. Nao. Antes deste fix, o runner nao verificava se havia passo aprendido compativel com a tela Microsoft atual.
4. Sim. A acao recente em `data/ui_map.json` continha cliques Microsoft em `passos_playwright`/`robust_steps`, incluindo `div[aria-label="Sign in with ..."]` e `input[name="idSIButton9"]`, com URLs Microsoft nos waits/metadados.
5. Sim. O Guardiao estava operando como bloqueador absoluto para consentimento, e tambem podia selecionar conta configurada por perfil fixo no recovery.
6. Senha e MFA continuam bloqueadas porque `microsoft_password_required` e `microsoft_mfa_required` nunca sao liberados pelo novo diagnostico de passo aprendido.

## Fix

- Adicionado `SessionGuardian.learned_microsoft_step_diagnostic()`.
- Pick Account, consent/Accept, signed-out e Microsoft desconhecido so deixam o replay continuar quando o proximo passo aprendido:
  - e um clique;
  - tem selector gravado;
  - o selector esta presente e visivel na pagina atual.
- Senha e MFA continuam bloqueadas antes de qualquer clique.
- `motor_browser.executar_acao_rapida()` passou a passar o passo atual/proximo para os checkpoints.
- `DemoSessionManager.execute_action()` recebeu a mesma regra para execucoes com `session_id`.
- Validacao de host de negocio agora chama o guardiao como monitor quando a pagina atual e Microsoft e ha proximo passo aprendido compativel.
- Eventos de aprendizagem passaram a preservar `target_text` e `target_label`, e esses metadados sao propagados para `robust_steps`.
- Normalizacao de configuracao externa passou a descartar URL OAuth em campos de identificador/host e a normalizar `microsoft_hosts` quando o arquivo persistido contem URL inteira.

## Pick Account e Accept aprendidos

O CotaSync nao escolhe conta nem clica Accept por heuristica global.

O replay apenas permite continuar ate a execucao normal do passo quando o selector aprendido esta visivel. O clique efetivo continua acontecendo no executor de passos, usando o selector gravado.

Com isso:

- clicar no usuario Microsoft gravado vira clique normal;
- clicar em Accept gravado vira clique normal;
- Pick Account aprendido nao depende de perfil fixo Priscila;
- consentimento sem passo compativel continua pedindo intervencao.

## Garantias de seguranca

Continuam bloqueados:

- `microsoft_password_required`;
- `microsoft_mfa_required`;
- tela Microsoft sem proximo passo de clique compativel;
- consentimento sem selector aprendido visivel;
- pagina final fora do host de negocio.

Mensagem operacional para incompatibilidade:

`Esta tela exige intervenção manual ou não corresponde ao passo ensinado.`

## Diagnosticos

Quando bloqueia, a run preserva:

- `current_host`;
- `session_state`;
- `next_step_expected_selector`;
- `next_step_expected_url_or_host`;
- `whether_next_step_was_microsoft_click`;
- `learned_microsoft_step_compatible`;
- `reason`;
- `checkpoint_diagnostics`;
- `step_diagnostics`, quando aplicavel.

## Variaveis preservadas

Nao houve mudanca na arquitetura de variaveis:

- inputs continuam virando variaveis;
- operator fill continua virando variavel;
- select continua virando variavel;
- valores demonstrados continuam removidos dos passos e substituidos por `{{variavel}}`.

## Async preservado

O fluxo async/polling do fix anterior foi preservado:

- `POST /api/actions/{id}/run` aceita `mode="async"`;
- a UI faz polling em `/api/runs/{run_id}`;
- acoes longas nao dependem do timeout curto do Streamlit.

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
- `docker compose ps`: backend, frontend, browserless, desktop browser, postgres e redis ativos; desktop browser healthy
- `/health`: `{"status":"ok","service":"cotasync"}`
- unit tests: 91 testes OK
- desktop browser smoke: OK

Cobertura adicionada/atualizada:

- Pick Account aprendido compativel nao depende de perfil fixo.
- Accept aprendido compativel continua.
- Consentimento sem selector aprendido compativel bloqueia.
- Senha/MFA nunca viram clique aprendido permitido.
- Metadados de clique Microsoft sao preservados em `robust_steps`.
- Async existente continua testado.
- Extracao generica por rotulo continua coberta pela suite existente.

## Validacao manual

Nao executei a validacao manual completa contra o sistema externo real, porque ela exige operador interativo e credenciais/sessao reais:

1. Salvar sessao em Configuracoes.
2. Abrir Demo.
3. Gravar a rotina com Pick Account, Accept, navegacao, preenchimentos e extracao.
4. Salvar.
5. Executar acao rapida.
6. Confirmar que nao para em `microsoft_consent_required` quando Accept foi passo gravado.

O smoke automatizado validou CDP/noVNC/alvo local/modo operador/aprendizado/replay.

## Limites

- O replay so permite Microsoft como passo normal quando o selector aprendido esta visivel; se a Microsoft alterar DOM/texto/selector, a run falha com diagnostico.
- Nao ha clique automatico de Accept sem passo gravado.
- Nao ha automacao de senha ou MFA.
- A compatibilidade e avaliada por estado atual e selector gravado, nao por decisao semantica livre.
- A configuracao persistida local ainda pode conter dados historicos invalidos em `data/`, mas a leitura normaliza esses campos em runtime.

## Proximo passo sugerido

Adicionar um teste end-to-end com fixture HTML simulando Pick Account -> Accept -> sistema para validar o caminho completo sem depender do Microsoft real.
