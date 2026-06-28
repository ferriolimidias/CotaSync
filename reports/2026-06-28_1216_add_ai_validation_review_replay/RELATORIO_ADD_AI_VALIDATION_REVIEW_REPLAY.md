# Relatorio - Validacao real do aprendizado com IA

Data: 2026-06-28

## Auditoria

1. Onde o mapa mecanico e salvo?
   - `backend/services/demo_session.py`, em `DemoSessionManager.save_action`, grava `data/ui_map.json` via `_save_ui_map`.
   - A fonte mecanica existente fica em `passos_playwright`, `robust_steps`, `learning_events`, `variable_schema` e `url_inicial`.
   - A implementacao adicionou `original_steps` e `mechanical_map` para novas acoes, sem remover os campos antigos.

2. Onde o replay desktop retorna `step_trace`?
   - `backend/motor_browser.py`, em `executar_acao_rapida`, monta `step_trace`.
   - `backend/services/action_runner.py`, em `_run_desktop_browser_replay`, chama esse replay e preserva `runner=desktop_browser_replay`, `whether_desktop_browser_used=true` e `whether_fast_track_used=false`.

3. Onde a extracao por rotulo acontece?
   - `backend/services/extraction_targets.py`, em `extract_value_near_label`.
   - O replay agora tambem usa essa funcao quando o passo `extrair_texto` tem `extraction_strategy=near_label` ou seletor vazio.

4. Onde o resumo final por IA acontece?
   - `backend/services/operational_summary.py`, em `build_operational_summary_result`.
   - O fallback deterministico fica em `deterministic_operational_summary`.

5. Como adicionar `reviewed_overlay` sem quebrar o formato atual?
   - Os campos novos sao opcionais nos schemas e normalizadores: `review_status`, `review_last_run_id`, `reviewed_overlay`, `ai_review_summary`, `final_summary_instruction`, `extraction_review`.
   - A persistencia atual em `ui_map.json` continua usando a mesma chave da acao e preserva os campos mecanicos.

6. Como rodar validacao real apos salvar acao?
   - Novo endpoint: `POST /api/actions/{action_id}/validate-review`.
   - O endpoint cria uma run `run_type=validation_review` e usa o mesmo `finish_action_run`, portanto a acao desktop segue pelo replay desktop real.

7. Como usar overlay na execucao rapida?
   - `backend/motor_browser.py` aplica `reviewed_overlay.waits` depois do passo indicado.
   - `backend/services/operational_summary.py` usa `reviewed_overlay.extraction` e `summary_instruction` para priorizar o alvo confirmado e evitar resumo da tela inteira.

## Nova arquitetura

- `mechanical_map` / passos originais continuam sendo a fonte da verdade.
- `reviewed_overlay` e uma camada complementar: waits, alvo de extracao, formato de resposta, riscos e notas.
- A IA revisora observa somente o pacote do replay real; ela nao clica, nao navega e nao altera passos.

## Endpoint criado

`POST /api/actions/{action_id}/validate-review`

Body:

```json
{
  "variables": {},
  "requested_by": "streamlit-review",
  "mode": "async"
}
```

Retorno: `ActionRunResponse` com a run criada. Em modo async, a revisao roda em background.

## Fluxo de validacao

1. Carrega a acao salva em `ui_map.json`.
2. Completa variaveis com exemplos seguros quando existirem.
3. Cria run `validation_review`.
4. Executa o replay real do mapa mecanico.
5. Coleta `step_trace`, URL/titulo/final_page, DOM/texto final, screenshot, downloads e dados extraidos.
6. Gera candidatos deterministicos de extracao.
7. Chama IA revisora quando disponivel.
8. Salva `reviewed_overlay`; se a IA estiver indisponivel, salva fallback `needs_attention`.
9. Se o replay falhar, salva `review_status=failed` com diagnostico.

## Formato do reviewed_overlay

Inclui:

- `review_status`
- `reviewed_at`
- `review_run_id`
- `target_user_request`
- `extraction`
- `summary_instruction`
- `waits`
- `selector_alternatives`
- `risks`
- `notes`

## IA observando replay real

O payload para IA e estruturado e limitado:

- nome da acao;
- pedido do usuario;
- variaveis;
- resumo dos passos;
- `step_trace`;
- candidatos de extracao;
- texto/DOM final limitados;
- screenshot como caminho/metadado;
- downloads.

Nao ha ferramenta para a IA clicar, abrir URL ou substituir passos.

## Resumo final

`summary_instruction` e prioritaria. Para alvo como "numero de parcelas pagas", o overlay pode gerar:

`Retorne somente a quantidade de parcelas pagas encontrada no campo Qtd. Pcls. Pagas. Nao inclua outros dados da tela.`

Com `return_format` indicando "somente o numero", o resumo deterministico retorna apenas `032`.

## Preservacao do mapa mecanico

A revisao salva campos novos na acao e nao altera:

- `passos_playwright`;
- `robust_steps`;
- `learning_events`;
- `variable_schema`;
- `url_inicial`;
- `extraction_target` original.

Os testes verificam que `robust_steps` e `learning_events` permanecem intactos apos a validacao.

## Testes

Executados:

- `python3 -m compileall backend frontend scripts`
- `docker compose -f docker-compose.test.yml --env-file .env.test up -d --build`
- `docker compose -f docker-compose.test.yml --env-file .env.test ps`
- `curl -v --max-time 10 http://127.0.0.1:8100/health`
- `docker exec cotasync_test_backend python -m unittest tests.test_operational_summary tests.test_guided_learning_outputs tests.test_desktop_action_runner tests.test_access_profile_demo_flow`
- `docker exec cotasync_test_backend python scripts/test_desktop_browser_connection.py`

Resultado:

- compileall OK;
- health OK;
- 108 testes OK;
- desktop browser connection OK.

Observacao: o Python do host nao tem dependencias `pydantic`/`fastapi`; a suite foi validada no container de teste.

## Validacao manual

Fluxo esperado:

1. Configurar URL completa.
2. Salvar sessao.
3. Ensinar nova rotina.
4. Informar objetivo de retorno, por exemplo `numero de parcelas pagas`.
5. Salvar aprendizado.
6. Clicar `Testar rotina e revisar com IA`.
7. Confirmar replay real.
8. Confirmar overlay salvo.
9. Conferir `summary_instruction`.
10. Executar acao rapida.
11. Confirmar que a resposta traz apenas o dado alvo.

## Limites

- Sem `OPENAI_API_KEY`, a validacao ainda roda e salva candidatos deterministicos, mas o status fica `needs_attention`.
- O overlay nao reordena nem remove passos.
- Senha/MFA/consentimento continuam bloqueados pelas regras existentes de recorder/session guardian.
- A captura de DOM/texto final e truncada para evitar payload excessivo.

## Proximos passos

- Exibir historico de revisoes por run.
- Melhorar ranking deterministico de candidatos com contexto visual/posicional.
- Adicionar visualizacao dedicada dos candidatos de extracao na UI.
