# Relatorio - Fix learned Microsoft steps replay

Data: 2026-06-26 19:32
Projeto: CotaSync demo

## Causa do bloqueio

A execucao desktop ainda tratava telas Microsoft como bloqueio de sessao antes de concluir a decisao pelo proximo passo aprendido. O caminho principal ja chamava `learned_microsoft_step_diagnostic()`, mas a compatibilidade dependia quase exclusivamente de `locator(selector).is_visible()`. Quando a tela Microsoft consent era classificada como `microsoft_consent_required` e o seletor gravado nao batia exatamente ou o host esperado estava salvo como URL OAuth, a rotina parava com `operator_action_required=true`.

Tambem havia uma recuperacao antiga em `SessionGuardian.ensure_authenticated()` que podia clicar conta Microsoft configurada por perfil fixo. Isso contrariava a nova arquitetura, na qual o clique de conta e o clique de Accept devem vir do replay mecanico aprendido.

## Respostas da auditoria

1. O bloqueio em `microsoft_consent_required` ocorria no Guardiao de Sessao, chamado por `run_session_checkpoint()` em `backend/motor_browser.py` e `backend/services/demo_session.py`.
2. Sim. O checkpoint `before_action_auth_check` roda antes do loop de passos; checkpoints `before_step_auth_check` e `after_step_stability_check` tambem podiam bloquear entre passos.
3. Parcialmente. O runner ja chamava diagnostico de passo aprendido, mas a regra era estreita: dependia do seletor visivel e nao tratava texto/label/host gravados de forma suficiente.
4. Sim. A acao recente em `data/ui_map.json` contem cliques Microsoft em `passos_playwright`, `robust_steps` e `learning_events`, incluindo conta salva e `input[name="idSIButton9"]`, com `url_before`, `title_before`, `target_text/target_label` e `source`.
5. Sim. O Guardiao ainda podia agir como recuperador operacional por conta configurada em `ensure_authenticated()`. Agora ele monitora/diagnostica Microsoft e nao escolhe conta no replay sem passo aprendido.
6. Senha/MFA continuam bloqueadas porque `microsoft_password_required` e `microsoft_mfa_required` retornam `operator_action_required=true` antes de qualquer liberacao por passo aprendido.

## Correcao

- `SessionGuardian.learned_microsoft_step_diagnostic()` agora valida o proximo passo aprendido por:
  - tipo `clicar`;
  - seletor gravado;
  - host/URL esperado compatível com Microsoft atual;
  - seletor visivel ou `target_text/target_label` gravado visivel.
- `microsoft_pick_account`, `microsoft_consent_required`, `microsoft_signed_out` e `unknown_microsoft_auth` so liberam o replay quando o proximo passo aprendido é compativel.
- `SessionGuardian.ensure_authenticated()` deixou de clicar conta configurada; para telas Microsoft de pick/consent/unknown ele retorna monitoramento com intervencao manual ou passo aprendido requerido.
- `demo_session.py` e `motor_browser.py` preservam o replay por seletor e adicionam fallback por `target_text/target_label` apenas para cliques aprendidos.
- `action_pages.py`, `actions_repository.py` e o salvamento em `demo_session.py` normalizam `expected_system_host` para nao aceitar URL Microsoft/OAuth como host final de negocio.
- `action_runner.py` e `frontend/app.py` passam a expor diagnosticos: `current_host`, `current_url`, `session_state`, proximo seletor/host/texto esperado, flag de clique Microsoft aprendido, compatibilidade e motivo.

## Pick Account e Accept aprendidos

Pick Account e Accept agora sao passos mecanicos normais quando foram gravados. O CotaSync nao escolhe conta por perfil fixo e nao clica Accept por regra global. O clique so acontece se o proximo passo da rotina aprendida for compativel com a tela atual.

## Comportamento de consentimento

Consentimento com passo aprendido compativel continua o replay. Consentimento sem passo compativel falha com:

`Esta tela exige intervenção manual ou não corresponde ao passo ensinado.`

## Garantias de seguranca

Continuam bloqueados:

- senha Microsoft;
- MFA/Authenticator;
- tela Microsoft desconhecida sem passo aprendido compativel;
- consentimento sem passo aprendido compativel;
- pagina final fora do host de negocio.

Nao ha automacao de senha, MFA ou Accept sem clique gravado.

## Variaveis e async

A arquitetura de variaveis foi preservada:

- inputs continuam virando variaveis;
- operator fill continua virando variavel;
- select continua virando variavel;
- valores demonstrados nao foram reintroduzidos como fixos.

O fluxo async/polling foi preservado:

- `POST /api/actions/{id}/run` com `mode=async`;
- polling em `/api/runs/{run_id}`;
- execucoes longas continuam fora do timeout curto do Streamlit.

## Testes

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
- `docker compose ps`: servicos ativos; desktop browser healthy
- `/health`: `{"status":"ok","service":"cotasync"}`
- unit tests: 94 testes OK
- desktop browser smoke: OK

Cobertura adicionada/atualizada:

- Pick Account aprendido nao depende de perfil fixo.
- Guardiao nao clica conta configurada como recuperacao operacional.
- Accept aprendido pode casar por texto gravado quando o seletor mudou.
- Consentimento sem passo compativel continua bloqueado.
- Senha/MFA continuam bloqueadas.
- Host esperado Microsoft/OAuth salvo nao vira host de negocio aceito.
- Async e extracao generica seguem cobertos pela suite existente.

## Validacao manual

Nao executei a validacao manual completa contra o Microsoft/sistema externo real, porque exige operador interativo e sessao/credenciais reais. O roteiro permanece:

1. Salvar sessao em Configuracoes.
2. Abrir Demo.
3. Criar nova acao começando na tela Microsoft.
4. Gravar clique no usuario, clique em Accept, navegacao, preenchimentos e alvo de extracao.
5. Salvar.
6. Executar acao rapida.
7. Confirmar que nao para em `microsoft_consent_required` quando Accept foi passo gravado.
8. Confirmar retorno do dado extraido.

## Limites

- Se a Microsoft mostrar senha ou MFA, a execucao para sempre.
- Se a tela Microsoft nao corresponder ao proximo clique aprendido, a execucao para com diagnostico.
- O fallback por texto/label so roda para clique aprendido com metadado gravado.
- Arquivos locais ja sujos antes desta alteracao (`data/external_systems/current.json` e PNG em `data/runs`) nao foram incluidos no commit.
