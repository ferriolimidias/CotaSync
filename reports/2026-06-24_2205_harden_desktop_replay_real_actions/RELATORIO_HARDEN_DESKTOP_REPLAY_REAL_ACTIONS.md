# Harden Desktop Replay para Ações Reais

## Contexto

Projeto: CotaSync demo  
Commit base informado: `f234a750bfa8a8823055f19dd735676abb954541`  
Data local do relatório: `2026-06-24 22:05`

## Auditoria

1. Onde o replay esperava:
   - `backend/services/demo_session.py` aguardava `domcontentloaded`, seletor visível/habilitado e, após clique, um `wait_for_timeout` derivado do tempo gravado, limitado entre 500 ms e 5000 ms.
   - `backend/motor_browser.py` no fast-track legado já tinha esperas por seletor, popup e `networkidle`, mas ainda com limites curtos e pós-clique fixo.
   - `backend/services/operational_summary.py` gerava resumo estável, mas timeout caía em mensagem genérica.

2. Por que sistemas reais lentos podiam estourar:
   - O replay assistido usava `_REPLAY_STEP_TIMEOUT_MS = 5000`.
   - Após cliques, a próxima tela precisava aparecer em poucos segundos, mesmo em fluxos WebForms/ERP com postback lento.
   - O erro perdia parte do contexto estruturado ao chegar em `/api/runs`.

3. Nova aba/popup:
   - Já havia detecção simples por diferença em `context.pages` no replay assistido e `expect_popup` no fast-track.
   - Agora o replay assistido cria listener de `context.wait_for_event("page")`, valida host e troca a página ativa quando permitido.

4. Downloads:
   - Já existiam `runtime_download_path`, `runtime_file_metadata`, `_extrator_universal_de_download` e renderização segura de download na UI.
   - O replay agora também escuta evento de download em cliques comuns e preserva `downloaded_files`/`main_file`.

5. Variáveis:
   - Antes `save_action` persistia `variaveis_necessarias` como strings e a UI mostrava nomes técnicos como `conteudo_edtgrupo`.
   - Agora a aprendizagem gera objetos `{key,label,required}`, sugere `grupo`, `cota`, `tipo_consulta` e a UI mostra "Revisar variáveis" antes de salvar.

6. Alvos de extração:
   - Já existiam `extraction_targets`, `output_schema`, `output_candidates` e síntese do observador.
   - Agora candidatos são priorizados pelo objetivo, especialmente `valor`, `parcela`, `valor da parcela`, `parcela atual`, `vencimento`, número de parcelas e status.

7. Causa provável do timeout em "Consultar valor da parcela atual":
   - A ação dependia de navegação/consulta real com tela lenta após clique.
   - O replay aguardava no máximo 5s por próximo seletor/URL e retornava erro genérico quando a próxima tela não chegava a tempo.

8. Reuso:
   - Foram reaproveitados `desktop_browser`/CDP, `demo_session`, `action_runner`, `motor_browser` download helper, `runtime_files`, `operational_summary`, `runs_repository`, `result_payload`, screenshots/evidências, metadados de guided learning e observador/síntese IA.

## Melhorias

### Replay e waits

- Defaults configuráveis:
  - `COTASYNC_STEP_TIMEOUT_SECONDS`, default `30`.
  - `COTASYNC_ACTION_TIMEOUT_SECONDS`, default `180`.
  - `COTASYNC_NAVIGATION_TIMEOUT_SECONDS`, default `45`.
- Espera pós-clique priorizada:
  - `expected_selector_after`.
  - `expected_url_after`.
  - nova página/popup.
  - download.
  - DOM/network idle.
  - fallback delay configurado pelo tempo gravado.
- Novo `step_diagnostics` com índice, tipo, label seguro, estratégia, tempo, resultado, host e título.

### Timeout

- Timeout agora retorna `status=error`, `retryable` quando aplicável e diagnóstico em `result_payload`.
- Resumo operacional para timeout de tela lenta:
  - "Não consegui concluir a ação porque o sistema demorou para abrir a próxima tela. Tente novamente ou reautentique a sessão se necessário."

### Nova aba/popup

- Clique arma listener de nova página antes da ação.
- Nova aba é selecionada quando passa pela validação de host da ação.
- Host inesperado continua falhando com diagnóstico seguro.
- `final_page` usa a página ativa final.

### Download/PDF

- Eventos de download em cliques são capturados e salvos em `data/runs/downloads`.
- `downloaded_files` e `main_file` são propagados no payload.
- UI mantém botão de download seguro sem expor caminho local no chat principal.

### Variáveis

- UI adicionou seção "Revisar variáveis".
- Sugestões:
  - `edtgrupo`/`conteudo_edtgrupo` -> `grupo` / "Grupo".
  - `edtcota`/`conteudo_edtcota` -> `cota` / "Cota".
  - `select_1` -> `tipo_consulta` / "Tipo Consulta".
- `actions_repository` e fallback local passam a carregar labels amigáveis de `variable_schema`.

### Extração por objetivo

- UI prioriza candidatos compatíveis com "valor da parcela atual".
- Extração configurada que não encontra valor retorna resumo específico:
  - "A ação foi executada, mas não encontrei o valor da parcela atual na tela final."
- Fallback de texto visível permanece disponível, marcado como menos preciso.

### Persistência de runs

- Replay via `/api/actions/{id}/run` já persistia runs.
- Barra lateral de execução rápida agora usa `/api/actions/{id}/run` em vez de chamar o agente diretamente.
- `result_payload` inclui `input_variables`, `step_diagnostics`, `selector_diagnostics`, `final_page`, downloads e `retryable`.

### Preparação para lote

- O runner de ação única agora expõe variáveis de entrada, status, erro, evidência, payload por execução, downloads e `retryable`, suficiente para um worker de lote reutilizar depois.

## Arquivos alterados

- `backend/services/demo_session.py`
- `backend/services/action_runner.py`
- `backend/services/operational_summary.py`
- `backend/services/actions_repository.py`
- `frontend/api_client.py`
- `frontend/app.py`
- `tests/test_desktop_action_runner.py`
- `tests/test_guided_learning_outputs.py`
- `tests/test_operational_summary.py`

## Testes executados

- `python3 -m compileall backend frontend scripts` passou.
- `docker compose -f docker-compose.test.yml --env-file .env.test up -d --build` passou.
- `docker compose -f docker-compose.test.yml --env-file .env.test ps` mostrou serviços ativos.
- `curl -sS http://127.0.0.1:8100/health` retornou `{"status":"ok","service":"cotasync"}`.
- `docker exec cotasync_test_backend python -m unittest tests.test_operational_summary tests.test_guided_learning_outputs tests.test_desktop_action_runner` passou: 37 testes.
- `docker exec cotasync_test_backend python scripts/test_desktop_browser_connection.py` passou.

## Validação manual

Validação real no sistema externo "Consultar valor da parcela atual" não foi executada neste ambiente, pois depende de sessão e dados reais. Roteiro a executar:

1. Reautenticar a sessão desktop se necessário.
2. Ensinar "Consultar valor da parcela atual".
3. Preencher grupo, cota e tipo de consulta.
4. Confirmar labels amigáveis na revisão.
5. Selecionar alvo preciso de extração para valor da parcela atual, ou fallback de texto final se não houver candidato.
6. Executar ação rápida.
7. Verificar resumo, downloads se houver e `/api/runs?limit=1` com `step_diagnostics`.

## Limites restantes

- `motor_browser.py` fast-track legado ainda tem parte das esperas históricas; o caminho recomendado de quick execution da UI agora passa por `/api/runs`.
- Detecção de download em clique comum cobre evento Playwright; fluxos que geram PDF em viewer sem evento de download ainda dependem do passo `download_pdf`.
- Extração por objetivo prioriza candidatos e selector manual, mas não implementa visão/LLM para localizar valor arbitrário sem seletor configurado.
- Validação real contra ERP externo precisa de sessão autenticada e dados de negócio.

## Recomendações para produção

- Persistir runs e evidências em storage durável quando sair do demo local.
- Padronizar `robust_steps` com schema versionado.
- Adicionar retries controlados por passo somente para falhas classificadas como `retryable`.
- Separar worker de lote consumindo o mesmo contrato de `result_payload`.
- Monitorar percentis de `waited_ms` por sistema para calibrar timeout por ação.
