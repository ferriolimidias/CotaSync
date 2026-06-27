# Relatorio - Fix External URL Preservation And Config UI

## Auditoria da URL

1. A URL digitada e salva em `data/external_systems/current.json` no campo `external_login_url`, via `backend.services.external_systems.save_current_external_system`.
2. Ela era alterada em pontos que chamavam `_safe_page_url`, funcao que remove query string e fragmento. O impacto principal era em `_target_url_for_saved_session`, nos eventos de aprendizado e em `_expected_replay_url`.
3. A tela de Configuracoes cria sessao via `POST /api/demo/sessions`; `DemoSessionManager.create` abre `external_login_url`.
4. O aprendizado guarda a acao em `DemoSessionManager.save_action`; antes gravava `url_inicial` com a URL da pagina final sem query.
5. O replay desktop seleciona/navega pela pagina em `select_desktop_page_for_action`, usando `action.url_inicial`.
6. A queda em `m365.cloud.microsoft/search` e consistente com abrir uma URL Microsoft incompleta, sem parametros como `client_id`, `redirect_uri`, `state` e `prompt`. Esses parametros eram removidos por `_safe_page_url` em caminhos de navegacao.
7. O round-trip exato agora e garantido preservando `external_login_url` sem normalizar e usando a URL completa para navegacao.

## Onde a URL era alterada

- `backend/services/external_systems.py`: `external_login_url` era salvo/carregado com `.strip()`.
- `backend/services/demo_session.py`: `_target_url_for_saved_session` retornava `_safe_page_url(session.external_login_url)`.
- `backend/services/demo_session.py`: `_expected_replay_url` removia query string.
- `backend/services/demo_session.py`: eventos `url_before` e `url_after` eram gravados sem query.
- `backend/services/demo_session.py`: `url_inicial` da acao era salvo a partir de `session.page.url` normalizado e sem query.

## Correcao aplicada

- `external_login_url` agora e persistido e carregado como string exata.
- Validacao HTTP/HTTPS usa uma copia com `.strip()`, mas o valor salvo continua intocado.
- `_target_url_for_saved_session` retorna `session.external_login_url` completo.
- `_expected_replay_url` retorna a URL salva completa quando valida.
- Eventos de aprendizado preservam `url_before` e `url_after` completos.
- `url_inicial` da acao agora vem de:
  - `external_login_url` completo, quando a gravacao comecou nessa URL;
  - senao `learning_events[0].url_before`;
  - senao `robust_steps[0].expected_url_before`;
  - senao a URL atual da pagina.

## Nova UI simplificada

Campos principais visiveis:

- Nome do sistema
- URL inicial completa do sistema
- Nome da conta
- Identificador/e-mail da conta

Botoes preservados:

- Salvar sistema externo
- Abrir navegador para login
- Salvar sessao do navegador
- Testar sessao salva
- Limpar sessao salva

## Campos avancados

Movidos para `Avancado / Diagnostico`, somente leitura:

- validation
- auth_success_text
- auth_success_selector
- access_profile_name
- expected_system_host
- microsoft_hosts
- microsoft_saved_account_selector

Esses campos podem continuar sendo usados internamente, mas nao substituem `external_login_url`.

## Impacto no aprendizado

- Acoes aprendidas preservam `url_inicial` com query string quando o aprendizado comeca pela URL configurada.
- Quando o usuario grava a partir da tela atual, `url_inicial` passa a ser a URL real inicial do primeiro evento gravado, tambem completa.

## Impacto no replay

- O replay desktop continua usando `select_desktop_page_for_action`.
- Como `action.url_inicial` agora e completa, o `page.goto` antes do passo 0 recebe a URL ensinada, nao um host simplificado.
- `m365.cloud.microsoft` nao e fallback automatico; so sera usado se a acao tiver sido ensinada nessa URL.

## Testes

- `python3 -m compileall backend frontend scripts`
- `docker compose -f docker-compose.test.yml --env-file .env.test up -d --build`
- `docker compose -f docker-compose.test.yml --env-file .env.test ps`
- `curl -sS http://127.0.0.1:8100/health`
- `docker exec cotasync_test_backend python -m unittest tests.test_operational_summary tests.test_guided_learning_outputs tests.test_desktop_action_runner tests.test_access_profile_demo_flow`
- `docker exec cotasync_test_backend python scripts/test_desktop_browser_connection.py`

## Validacao manual

Pendente com o sistema externo real:

1. Colar a URL completa em Configuracoes.
2. Salvar.
3. Atualizar a pagina e confirmar string identica.
4. Abrir navegador para login e confirmar URL completa.
5. Ensinar nova rotina.
6. Confirmar `action.url_inicial`.
7. Executar replay e confirmar que nao inicia em `m365.cloud.microsoft/search`, salvo se essa tiver sido a URL ensinada.

## Limites

- Nao foi feita automacao de senha, MFA ou consentimento.
- Campos avancados continuam disponiveis internamente e via API para testes/diagnostico.
- `data/external_systems/current.json`, storage/cookies e PNGs locais nao foram incluidos no commit.
