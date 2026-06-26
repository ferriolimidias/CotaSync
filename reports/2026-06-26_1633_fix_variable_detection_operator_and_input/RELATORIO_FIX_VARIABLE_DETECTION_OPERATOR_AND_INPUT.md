# Relatorio - Fix variable detection operator and input

Data: 2026-06-26 16:33 America/Sao_Paulo

## Audit findings

1. Variaveis eram detectadas principalmente no `save_action`: passos `preencher` e `selecionar` eram varridos, recebiam nome sugerido e eram convertidos para `value_template`.
2. Antes da correcao, eventos que podiam virar variaveis eram `input`/`textarea` via listener JS, `select` via listener JS e fallback de `operator_fill`.
3. Digitacao normal no browser gerava evento `fill` somente quando o listener injetado estava instalado em frame acessivel.
4. Select/dropdown gerava evento `select` somente pelo listener JS; operador nao tratava `select` diretamente.
5. `operator_fill` tinha fallback direto, mas ainda passava por `_record_live_step` sem fonte clara e podia depender da janela de supressao usada para helpers.
6. `operator_fill` nao precisava apenas do listener, mas o evento direto ainda nao era a fonte central de variavel e chegava com template generico `{{input_value}}`.
7. `Modo operador > Preencher seletor` podia produzir `Campos: 0` quando o listener nao emitia e o fallback era suprimido/nao contabilizado como evento de campo na gravacao ativa.
8. A perda estava no backend, entre API de operador, armazenamento da sessao e normalizacao do evento. `/api/actions` serializava variaveis corretamente quando elas chegavam ao salvamento.
9. Estado de gravacao existe em `session.recording` e `session.status == "gravando"` quando o operador grava acao.
10. O operador se comporta diferente durante login: com `record_action=False`, ele apenas ajuda a preencher/clicar e nao deve poluir o aprendizado.

## Current variable detection criteria

Durante gravacao ativa, qualquer evento de campo `preencher` ou `selecionar` vira variavel imediatamente. O passo recebe `variavel`, `value_template="{{variavel}}"` e `valor=""`. O evento de aprendizado recebe `variable_key`, `value_template` e `source`.

## Cause

A regra de variavel estava tarde demais no fluxo. A revisao dependia de passos crus e o preenchimento do operador ainda podia ficar sem um evento `fill/select` confiavel quando o listener JS nao registrava a interacao.

## Fix

- Criado `record_field_variable_event(...)` e normalizacao central em `DemoSessionManager`.
- `_record_live_step` normaliza `preencher/selecionar` antes de persistir.
- `_append_step` grava `variavel`, zera `valor` e preserva `value_template`.
- `save_action` respeita variavel ja detectada e ainda permite edicao pela UI.
- Nomes amigaveis: `grupo`, `cota`, `cpf`, `cliente`, `codigo`, `data`, `tipo_consulta`; desconhecido vira `campo_1`, `campo_2`.

## Operator mode before/after

Antes: `operator_fill` preenchia a tela e tentava depender do listener, com fallback fragil e sem diagnostico suficiente.

Depois: `operator_fill` registra diretamente quando a gravacao esta ativa, marca `source=operator_mode`, incrementa diagnosticos e suporta `select` pelo mesmo endpoint. Fora da gravacao, continua apenas helper.

## Input/select behavior before/after

Antes: input/textarea/select dependiam do listener e eram convertidos para variavel no salvamento.

Depois: o listener continua capturando input, textarea e select, mas o backend transforma o evento em variavel na entrada da gravacao, sem salvar o valor demonstrado como valor fixo.

## Quick execution behavior

A acao salva expoe `variables` via `/api/actions`. A execucao rapida mostra os campos dessas variaveis e o replay usa os valores de runtime em `preencher`/`selecionar`.

## Tests run

- `python3 -m compileall backend frontend scripts`
- `python3 -m compileall backend frontend scripts tests`
- `docker compose -f docker-compose.test.yml --env-file .env.test up -d --build`
- `docker compose -f docker-compose.test.yml --env-file .env.test ps`
- `curl -v --max-time 5 http://127.0.0.1:8100/health` -> 200 OK
- Focused variable tests in `tests.test_guided_learning_outputs` -> OK
- `docker exec cotasync_test_backend python scripts/test_desktop_browser_connection.py` -> OK
- Full requested unittest command -> failed only in 2 access-profile tests because `data/external_systems/current.json` is already modified with a Microsoft identifier set to an OAuth URL.

## Manual validation steps

1. Start new learning with only action name.
2. Start recording.
3. Use Modo operador > Preencher seletor.
4. Stop recording.
5. Confirm `Campos: 1` and detected variable.
6. Save action.
7. Confirm quick execution shows the variable field.
8. Repeat with two fields and confirm two variables.
9. Repeat with real routine and confirm `grupo`/`cota`.
10. Execute quick action and confirm runtime values are used.

## Limits

The full suite is currently blocked by pre-existing dirty `data/external_systems/current.json`, not by variable detection. I did not revert or edit that file because it is outside this bug and appears user/environment-owned.

## Next

Clean or correct `data/external_systems/current.json` in a separate change, then rerun the full unittest command to get a fully green suite.
