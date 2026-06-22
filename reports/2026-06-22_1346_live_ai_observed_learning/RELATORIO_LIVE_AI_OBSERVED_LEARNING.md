# Relatório — aprendizado demonstrado com observação IA em tempo real

Data/hora: 2026-06-22 13:46 (America/Sao_Paulo)
Base: `3135d0edaa48f9e1ebbb00ec6fdf2a3e7fce8c1e`

## O que mudou

O fluxo principal continua humano: o operador abre a sessão, faz login e demonstra a rotina. O CotaSync não pede para a IA navegar nem decidir cliques. Durante a gravação, cada evento significativo recebe telemetria antes/depois, screenshot e uma revisão não bloqueante. No salvamento, os mesmos passos humanos viram `robust_steps`; a síntese final usa a observação ao vivo e mantém replay determinístico.

O modo persistido é `learning_mode="human_demo_live_ai_observed"`.

## Observador ao vivo

`observe_learning_step_with_ai(step_event, context)` é chamado em tarefa assíncrona após cada evento. Antes da chamada, uma análise determinística já preenche `wait_hint`, `replay_hint`, nota, robustez do seletor e riscos. Assim, ausência de chave, timeout ou erro da OpenAI nunca interrompe a gravação.

Com `OPENAI_API_KEY`, o stack existente `langchain-openai` usa `OPENAI_MODEL` (default `gpt-4o-mini`), temperatura zero, timeout de cinco segundos e sem retry. A IA recebe somente telemetria sanitizada; valores preenchidos, cookies, storage state e credenciais não entram no prompt.

Sem chave, o resumo final inclui `IA não configurada; ação salva com análise local básica.`

## Telemetria persistida por evento

- `step_index`, `event_type`, `selector`;
- `value_template` ou `variable_key`, sem o valor demonstrado;
- timestamps antes/depois e `elapsed_ms`;
- URL e título antes/depois;
- resumos DOM estruturais antes/depois, sem texto nem valores de inputs;
- paths de screenshots antes/depois na pasta runtime da sessão;
- flags de nova página, mudança de página ativa e download;
- `wait_hint`, `replay_hint` e `ai_note`.

O recorder suporta os tipos `fill`, `click`, `extract`, `download`, `navigation`, `popup`, `new_tab`, `modal` e `wait`. O alvo local exercita fill/click/extract; os demais tipos e flags ficam disponíveis para evolução em sistemas reais.

## Síntese final e replay

A ação salva contém:

- `ai_observer_summary` e `ai_reviewed`;
- `learning_events`;
- `robust_steps`;
- `variable_schema`;
- `replay_hints` e `wait_strategies`;
- `risks_detected`, `slow_system_notes` e `new_tab_or_popup_notes`.

O replay prefere `robust_steps`, revalida página/autenticação antes de cada passo, aguarda DOM e seletor acionável, rola antes de clicar, respeita o tempo observado com limite, verifica URL e próximo seletor, detecta página nova e muda o target ativo. Falhas geram screenshot e payload diagnóstico seguro com URL, título, seletor, count/visible/enabled e resumo DOM.

## Configuração OpenAI

- `OPENAI_API_KEY`: lida somente do ambiente.
- `OPENAI_MODEL`: lido do ambiente; default `gpt-4o-mini`.
- Streamlit > **Configurações** mostra apenas `OpenAI configurada: sim/não` e o modelo.
- Não existe campo que persista chave; a chave nunca é mostrada nem registrada.
- Nenhum `.env`, cookie, storage state ou segredo faz parte do commit.

## Arquivos alterados

- `backend/services/ai_observer.py`
- `backend/services/demo_session.py`
- `backend/services/action_runner.py`
- `backend/services/actions_repository.py`
- `backend/schemas/actions.py`
- `frontend/api_client.py`
- `frontend/app.py`
- `scripts/test_demo_v01_cycle.py`
- `scripts/test_human_demo_replay.py`
- Este relatório.

## Testes executados

- `python3 -m compileall backend frontend scripts`: passou.
- `git diff --check`: passou.
- `docker compose -f docker-compose.test.yml --env-file .env.test up -d --build`: passou.
- `docker compose ... ps`: cinco serviços ativos; PostgreSQL saudável.
- `/health`: `status=ok`.
- `/api/health/browserless`: `status=ok`.
- `docker exec cotasync_test_backend python scripts/test_demo_v01_cycle.py`: três ciclos passaram, incluindo fallback sem chave, telemetria, síntese, replay, screenshot, revalidação viva e restauração de storage state.
- `docker exec cotasync_test_backend python scripts/test_human_demo_replay.py`: passou com live view concorrente e substituição da página CDP.
- `curl -I http://127.0.0.1:3100`: HTTP 200.

Os testes verificam `elapsed_ms`, URLs, resumos DOM, screenshots, hints, ausência do valor `PED-1001` no JSON, modo de aprendizado, resumo do observador, `robust_steps` e uso dos hints no diagnóstico do clique.

## Passos da demo

1. Abrir uma sessão de navegador.
2. Fazer login manual na live view e confirmar o login.
3. Iniciar gravação.
4. Demonstrar preenchimento, clique e leitura do resultado.
5. Parar a gravação e revisar os passos capturados.
6. Nomear a variável e salvar; o observador sintetiza o plano robusto.
7. Conferir na UI o resumo de IA ou o fallback local.
8. Executar com outro valor e mostrar run `success`, extração, hints e screenshot.

## Limitações do MVP

- A chamada OpenAI por passo é assíncrona; o fallback local é aplicado imediatamente e pode permanecer se a resposta chegar depois do salvamento.
- A demo valida fill/click/extract. Download, modal e nova aba possuem sinais e caminhos de replay, mas ainda precisam de fixtures específicas.
- A autenticação genérica usa confirmação humana e ausência de formulário de senha visível; integrações reais devem fornecer marcadores próprios mais fortes.
- Screenshots de aprendizado vivem na pasta runtime da sessão e são removidos ao encerrar a sessão; a evidência final da ação/run permanece no fluxo atual.
- Não há interpretação visual multimodal dos screenshots neste MVP; eles são evidência e contexto disponível para evolução.

## Próximo passo para sistemas externos

Adicionar adaptadores declarativos por sistema para sinais de autenticação, seletor de sucesso, modal/download e política de URL, e criar fixtures de popup/download. Depois, permitir que a síntese use screenshots multimodais redigidos, mantendo aprovação humana e os passos determinísticos como fonte de verdade.
