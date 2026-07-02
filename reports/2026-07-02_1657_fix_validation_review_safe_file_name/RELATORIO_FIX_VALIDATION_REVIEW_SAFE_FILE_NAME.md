# Correção `_safe_file_name` na validação com IA

## Causa

`backend/motor_browser.py` chamava `_safe_file_name(step_type)` ao tentar salvar screenshot de erro do replay, mas esse helper não existia nesse módulo nem era importado. O helper com esse nome existia apenas em `backend/services/demo_session.py`, como função local.

Na prática, quando o replay real usado por `POST /api/actions/{id}/validate-review` encontrava um erro ou precisava montar evidência de diagnóstico, o tratamento de erro podia gerar `NameError: name '_safe_file_name' is not defined`, mascarando a causa real do replay.

## Onde quebrava

- `backend/motor_browser.py`, dentro de `executar_acao_rapida()`, em `capture_error_screenshot()`.
- O caminho era acionado durante replay `desktop_browser_replay`, usado tanto por `validation_review` quanto por execuções reais de ações desktop quando há falha de passo.

Também havia um bug adjacente no mesmo tratamento de erro: `except ActionPageError:` usava a variável `e` sem capturá-la. Isso foi corrigido para `except ActionPageError as e:`.

## Por que action_run funcionava e validate-review falhava

A ação rápida real funcionava porque o caminho de sucesso não passava por `capture_error_screenshot()`. O `validate-review` executa o replay real novamente e, na falha reportada, entrou no caminho de diagnóstico/evidência no passo `#ctl00_img_Atendimento`; ali a tentativa de montar o nome do screenshot chamou `_safe_file_name` inexistente e derrubou a validação.

Assim, não era problema da extração, variáveis, URL, replay Microsoft ou ação rápida em si. Era falha no caminho de registro de evidência/diagnóstico.

## Helper equivalente

Existiam helpers próximos, mas nenhum central para nome de arquivo:

- `backend/services/demo_session.py::_safe_file_name`, local ao módulo e sem remoção de acentos.
- `backend/services/actions_repository.py::slugify_action_id`, voltado a IDs de ação, não a nomes de arquivo e sem preservação de extensão.

A correção criou `backend/services/file_names.py::safe_file_name()` como helper central para arquivos.

## Correção aplicada

- Criado `safe_file_name()` centralizado em `backend/services/file_names.py`.
- O helper remove acentos, troca espaços por underscore, remove caracteres perigosos, limita tamanho e preserva extensão quando aplicável.
- `backend/motor_browser.py` agora usa `safe_file_name()` para:
  - nomes de screenshots de mapeamento;
  - nomes de evidência de execução;
  - screenshots de erro por passo.
- `backend/services/demo_session.py::_safe_file_name()` agora delega ao helper central.
- Falhas ao salvar screenshot/evidência foram transformadas em warning e não derrubam a execução principal quando possível.
- Corrigido `except ActionPageError as e` no replay para evitar novo `NameError` no mesmo caminho.

## Testes

Executados:

```bash
python3 -m compileall backend frontend scripts
docker compose -f docker-compose.test.yml --env-file .env.test up -d --build
docker compose -f docker-compose.test.yml --env-file .env.test ps
curl -sS http://127.0.0.1:8100/health
docker exec cotasync_test_backend python -m unittest tests.test_operational_summary tests.test_guided_learning_outputs tests.test_desktop_action_runner tests.test_access_profile_demo_flow
docker exec cotasync_test_backend python scripts/test_desktop_browser_connection.py
```

Resultado:

- `compileall`: OK.
- compose build/up: OK.
- `ps`: serviços principais ativos; desktop browser healthy.
- `/health`: OK após segunda tentativa. A primeira tentativa ocorreu enquanto o backend ainda estabilizava e retornou reset de conexão.
- unittest: 111 testes OK.
- desktop browser connection script: OK.

Testes adicionados/cobertos:

- nome seguro aceita acentos, caracteres especiais e preserva extensão;
- validate-review aceita ação com nome acentuado `"número de parcelas pagas"`;
- variables `grupo`, `grupo_2`, `grupo_3` preservadas;
- extração por rótulo `"Qtd. Pcls. Pagas"` preservada;
- `reviewed_overlay` salvo em validação bem-sucedida;
- falha de screenshot/evidência não gera `NameError` nem payload genérico vazio;
- action_run e async continuam cobertos pela suíte existente.

## Validação manual

Comando executado:

```bash
curl -s -X POST "http://127.0.0.1:8100/api/actions/numero-de-parcelas-pagas/validate-review" \
  -H "Content-Type: application/json" \
  --data '{"variables":{"grupo":"935","grupo_2":"111","grupo_3":"00"},"mode":"async","requested_by":"manual-validation-review"}' \
  | python3 -m json.tool
```

Run criada:

- `id`: `3334192f-5c49-41cc-9a02-ba29b74a7f0b`
- `run_type`: `validation_review`
- status final: `success`
- `result_payload.validation_review`: `true`
- `dados_extraidos`: `{"Qtd. Pcls. Pagas": "038"}`
- `runner`: `desktop_browser_replay`
- `whether_fast_track_used`: `false`
- `screenshot_path`: `data/execucao_numero_de_parcelas_pagas.png`
- `extraction_candidates`: gerados
- `reviewed_overlay`: presente no payload
- `operational_summary`: `Quantidade de parcelas pagas: 038.`

Persistência confirmada em `/app/data/ui_map.json` no container:

- `review_status`: `needs_attention`
- `review_last_run_id`: `3334192f-5c49-41cc-9a02-ba29b74a7f0b`
- `reviewed_overlay`: salvo
- `expected_example`: `038`
- `summary_instruction`: presente

## Limites

- A revisão final ficou `needs_attention` porque o caminho determinístico foi usado para overlay quando a revisão IA ficou indisponível naquele ponto; o replay real e a extração concluíram com sucesso.
- Não foram alterados senha, MFA, consentimento, URL externa, lógica de variáveis, extração genérica por rótulo, replay Microsoft, `desktop_browser_replay`, `reviewed_overlay` ou `summary_instruction`.
- Artefatos locais em `data/` não devem ser commitados.
