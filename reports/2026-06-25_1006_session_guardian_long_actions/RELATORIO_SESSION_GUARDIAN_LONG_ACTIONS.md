# Relatorio Session Guardian e Acoes Longas

Data: 2026-06-25 10:06
Commit base auditado: 1dcf04ddb545794c4ecf84149282df5e502c459f

## Auditoria

1. Autenticacao antes desta mudanca:
   - `backend/services/demo_session.py` validava autenticacao em `_page_is_authenticated`, `_find_authenticated_live_page`, `_restore_storage_state`, `_revalidate_for_replay` e `confirm_login`.
   - `execute_action` chamava `_revalidate_for_replay` antes de cada passo, mas recebia apenas booleano e nao tinha estado operacional detalhado.
   - `backend/services/action_pages.py` validava host final com `validate_action_page_url`.

2. Redirecionamentos Microsoft:
   - `backend/services/action_pages.py` detectava hosts como `login.microsoftonline.com`, `login.live.com`, `m365.cloud.microsoft` e caminhos de login/auth.
   - A deteccao gerava erro de reautenticacao, mas nao diferenciava Pick account, senha, MFA, consentimento ou conta salva.

3. Wrong page e reauth:
   - `ActionPageError` emitia `reauthentication_required` para Microsoft/login e `unexpected_page_host` para host inesperado.
   - `run_action_sync` convertia isso em `operational_summary`, mas sem payload de sessao completo.

4. Timeouts existentes:
   - Step timeout: `COTASYNC_STEP_TIMEOUT_SECONDS`, default 30s.
   - Action timeout: `COTASYNC_ACTION_TIMEOUT_SECONDS`, default 180s.
   - Navigation timeout: `COTASYNC_NAVIGATION_TIMEOUT_SECONDS`, default 45s.
   - `step_diagnostics`, popup/nova aba, downloads, friendly variables e `/api/runs` na execucao rapida ja estavam ativos.

5. Antes/depois:
   - Antes havia check antes de cada passo, mas nao havia monitor de estado durante checkpoints especificos nem recuperacao Microsoft dirigida.
   - Agora ha checkpoints antes da acao, antes/depois de passos, apos nova aba, antes de extracao e no final.

## O que Faltava

- Estado padronizado da sessao para desktop_browser.
- Diferenciar Pick account de senha/MFA/consentimento.
- Clicar somente conta salva configurada.
- Refresh/retry controlado para loading/travamento.
- Diagnostico de recuperacao persistido em `/api/runs`.
- UI para diagnostico de sessao sem expor seletores no chat principal.
- Metadados de timeout e sessao autenticada por acao.

## Comportamento do Session Guardian

Arquivo: `backend/services/session_guardian.py`.

Estados suportados:
- `authenticated_system`
- `microsoft_pick_account`
- `microsoft_password_required`
- `microsoft_mfa_required`
- `microsoft_consent_required`
- `microsoft_signed_out`
- `blocked_or_access_denied`
- `wrong_host`
- `system_loading`
- `system_unresponsive`
- `unknown`

Sinais usados:
- host, URL sanitizada, titulo, `document.readyState`, texto visivel limitado, host esperado, marcadores de autenticacao existentes e textos conhecidos de Microsoft/login.

## Conta Salva Microsoft

- Novos metadados: `access_profile_name`, `access_profile_email_or_identifier`, `microsoft_saved_account_selector`, `microsoft_saved_account_text`.
- Para demo externa, defaults: `Priscila Susin` e `D0004267@rdmz.com.br`.
- O guardian clica apenas se o texto/identificador configurado estiver visivel.
- Se a conta configurada nao aparece, falha com `operator_action_required=true`.
- Nao digita senha, MFA ou consentimento e nao armazena credenciais.

## Politica de Recuperacao

Defaults:
- `COTASYNC_SESSION_CHECK_TIMEOUT_SECONDS=20`
- `COTASYNC_SESSION_RECOVERY_ATTEMPTS=3`
- `COTASYNC_SESSION_REFRESH_ATTEMPTS=2`
- `COTASYNC_SESSION_RECOVERY_BACKOFF_SECONDS=3`
- `COTASYNC_LONG_ACTION_MAX_SECONDS=300`

Regras:
- Pick account: tenta selecionar conta salva configurada.
- Password/MFA/consent/signed out: solicita intervencao manual.
- Loading/unresponsive/unknown: refresh limitado e novo check.
- Wrong host: tenta URL inicial quando configurada; caso contrario falha seguro.
- Access denied: falha seguro.

## Acoes Longas

Checkpoints implementados:
- `before_action_auth_check`
- `before_step_auth_check`
- `after_step_stability_check`
- `after_new_page_check`
- `before_extraction_check`
- `final_auth_check`

Cada checkpoint persiste:
- nome
- estado da sessao
- `elapsed_ms`
- recuperacao tentada
- resultado
- host atual e titulo seguro

## Batch Readiness

O payload de run agora inclui campos reutilizaveis por batch:
- `status`
- `retryable`
- `operator_action_required`
- `recovery_attempted`
- `variables_used`
- `dados_extraidos`
- `downloaded_files`
- `evidence`
- `step_diagnostics`
- `checkpoint_diagnostics`
- `session_state`
- `recovery_attempts`
- `recovery_steps`

Nao foi criada UI de lote nova.

## Frontend

- Execucao rapida continua usando `/api/actions/{id}/run`.
- Chat mostra `operational_summary`.
- Diagnostico de sessao aparece recolhido em "Ver diagnostico de sessao" quando houve recuperacao ou falha.
- Mensagem padrao para login manual:
  "A sessão precisa de login manual. Abra o Navegador Desktop, conclua o login e clique em Login concluído."
- Pos-aprendizado mostra quantidade de passos, alerta de seletores frageis, variaveis, alvos de extracao, download/nova aba, checkpoints sugeridos, timeout por acao e toggle de sessao autenticada.

## Arquivos Alterados

- `backend/services/session_guardian.py`
- `backend/services/demo_session.py`
- `backend/services/action_runner.py`
- `backend/services/operational_summary.py`
- `backend/services/actions_repository.py`
- `backend/services/external_systems.py`
- `backend/schemas/actions.py`
- `backend/api/demo.py`
- `backend/api/external_systems.py`
- `frontend/app.py`
- `frontend/api_client.py`
- `tests/test_desktop_action_runner.py`

## Testes

Executados:
- `python3 -m compileall backend frontend scripts`
- `docker compose -f docker-compose.test.yml --env-file .env.test up -d --build`
- `docker compose -f docker-compose.test.yml --env-file .env.test ps`
- `curl -sS http://127.0.0.1:8100/health`
- `docker exec cotasync_test_backend python -m unittest tests.test_operational_summary tests.test_guided_learning_outputs tests.test_desktop_action_runner`
- `docker exec cotasync_test_backend python scripts/test_desktop_browser_connection.py`

Resultado:
- Compileall: ok.
- Compose: ok.
- Health: ok.
- Unitarios: 44 testes ok.
- Desktop browser smoke: ok.

Observacao:
- A tentativa de rodar unitarios diretamente no host falhou por ausencia de dependencias (`pydantic`, `fastapi`) fora do container; a validacao oficial no container passou.

## Validacao Manual Recomendada

1. Abrir CotaSync.
2. Abrir Navegador Desktop.
3. Deixar a tela Microsoft "Pick an account" aparecer.
4. Configurar acao/perfil com `Priscila Susin` ou `D0004267@rdmz.com.br`.
5. Executar a acao e confirmar clique na conta salva, retorno ao host do sistema e execucao.
6. Forcar logout ou redirecionar para Microsoft e confirmar pedido de login manual em senha/MFA/consentimento.
7. Verificar `/api/runs` mais recente com `session_state`, `recovery_attempts` e `checkpoint_diagnostics`.

## Limites

- O guardian nao resolve senha, MFA, consentimento ou CAPTCHA.
- A classificacao depende de sinais visiveis e pode precisar de novos textos para telas Microsoft/localizadas futuras.
- A selecao de conta salva exige configuracao textual/selector compativel com o DOM exibido.
- Recuperacao por refresh/navegacao e limitada por politica para evitar loops longos.
- Batch UI nao foi implementada.

## Recomendacoes de Producao

- Configurar perfil de acesso por sistema/acao via UI administrativa dedicada.
- Adicionar auth markers especificos por sistema quando possivel.
- Enviar metricas de `session_state` e `recovery_attempts` para observabilidade.
- Registrar evidencias de falha em storage controlado com retencao.
- Definir timeouts por categoria de acao longa.
- Criar fluxo operacional claro para "Login concluido" apos intervencao manual.
