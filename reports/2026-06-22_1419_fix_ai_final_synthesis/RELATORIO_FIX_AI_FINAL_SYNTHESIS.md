# Relatório — correção da síntese final por IA

Data: 2026-06-22 14:19 (America/Sao_Paulo)

## Resultado

A síntese final executada por `POST /api/demo/sessions/{session_id}/actions` voltou a usar a OpenAI com sucesso. Com `OPENAI_API_KEY` configurada, a ação é persistida e retornada com `ai_reviewed=true`, resumo da IA e metadados de replay. O fallback local permanece disponível quando não há chave ou quando a chamada/resposta realmente falha.

## Causa raiz

`analyze_recorded_action_with_ai` chamava `ChatOpenAI.with_structured_output(ObserverReview)`. O schema Pydantic da revisão contém coleções de objetos flexíveis e produzia um schema incompatível com o structured output aceito pela OpenAI/LangChain, levando a HTTP 400 mesmo com chave e conectividade válidas.

## Correção

- Removido `with_structured_output` somente da síntese final.
- Mantidas as chamadas OpenAI do observador ao vivo por evento.
- A síntese final agora usa `ChatOpenAI.ainvoke` normal, com instrução explícita para JSON.
- Adicionado parser defensivo para JSON puro, bloco `json` Markdown, texto com objeto JSON e conteúdo textual segmentado do LangChain.
- Campos ausentes ou inválidos usam os valores da análise local; JSON totalmente inválido mantém o fallback.
- `wait_strategies` passou a integrar o retorno do salvamento e o catálogo normalizado.
- A UI pós-salvamento e o catálogo exibem, em caso de sucesso:
  - `Observador IA ativo`
  - `Síntese IA: ...`
  - `Modo: aprendizado demonstrado observado por IA`
- O timeout do salvamento na UI foi ampliado de 15 para 30 segundos para cobrir a revisão final sem timeout prematuro no cliente.

## Testes adicionados/atualizados

- Regressão mockada com `OPENAI_API_KEY` presente:
  - simula resposta JSON cercada por Markdown;
  - exige `ai_reviewed=true` e resumo não-fallback;
  - faz o teste falhar se `with_structured_output` for chamado na síntese final.
- Regressão sem chave preservada e validada com `ai_reviewed=false` e análise local.
- Ciclo pelo endpoint real passou a exigir, quando a chave está configurada, `ai_reviewed=true`, resumo sem “indisponível” e `wait_strategies` preenchido.

## Validação executada

- `python3 -m compileall backend frontend scripts` — passou.
- `docker compose -f docker-compose.test.yml --env-file .env.test up -d --build` — passou.
- `docker compose -f docker-compose.test.yml --env-file .env.test ps` — backend, frontend, Browserless, Redis e Postgres ativos; Postgres saudável.
- `curl -s http://127.0.0.1:8100/health` — `status=ok`.
- `curl -s http://127.0.0.1:8100/api/health/browserless` — `status=ok`.
- `docker exec cotasync_test_backend python scripts/test_demo_v01_cycle.py` — passou:
  - fallback sem chave validado;
  - JSON defensivo sem structured output validado;
  - três ciclos completos de gravação, síntese OpenAI, salvamento e replay validados;
  - revalidação CDP/storage state validada.
- Logs da execução verificados sem `400 Bad Request`, warning de structured output ou falha da revisão final.

Observação: uma tentativa adicional de executar o teste diretamente no host não iniciou porque Playwright não está instalado no Python do host. A execução exigida dentro do container, que contém as dependências do projeto, passou integralmente.

## Arquivos alterados

- `backend/services/ai_observer.py`
- `backend/services/demo_session.py`
- `backend/schemas/actions.py`
- `backend/services/actions_repository.py`
- `frontend/api_client.py`
- `frontend/app.py`
- `scripts/test_demo_v01_cycle.py`
