# Fix Learning Variables Regression

Data: 2026-06-25 16:12

## Regression Audit

- `git status` antes da alteracao: branch `master` ahead de `origin/master` por 26 commits; havia alteracao local em `data/external_systems/current.json` e um PNG novo em `data/runs/`. Esses arquivos nao foram revertidos nem incluidos no commit.
- Commits recentes auditados depois do ponto de aprendizado guiado: `321e26c`, `f234a75`, `1dcf04d`, `a907d77`, `bafcc12`, `d825cca`.
- Arquivos auditados: `backend/services/demo_session.py`, `backend/services/ai_observer.py`, `backend/services/actions_repository.py`, `backend/services/action_runner.py`, `backend/services/session_guardian.py`, `backend/api/demo.py`, `frontend/app.py`, `frontend/api_client.py`, `data/ui_map.json`, testes de aprendizado guiado, replay desktop e perfil de acesso.
- `data/ui_map.json` confirmou a falha real: a acao "Consultar quantidade de parcelas pagas" foi salva com apenas um passo `clicar`, um unico `learning_event` de click, `variaveis_necessarias: []` e `variable_schema: []`.

## Audit Answers

1. Fill/input events ainda podiam ser recebidos pelo backend quando o recorder estava instalado no documento correto.
2. No caso observado, eles nao aparecem em `session.steps`/`learning_events`; a perda ocorreu antes do save.
3. Normalizacao nao era a causa: `_append_step` aceita `preencher` e `save_action` converte fills para variaveis.
4. Conversao de recorded steps para action nao era a causa quando existia `preencher`.
5. Persistencia em `data/ui_map.json` nao era a causa: variaveis existentes sao salvas.
6. `/api/actions` nao era a causa: `actions_repository._friendly_variables()` expoe `variaveis_necessarias`/`variable_schema`.
7. Recording nao era robusto para frames existentes ou navegados depois do inicio; agora instala em frames atuais e futuros quando acessiveis.
8. Popups/novas paginas eram detectados depois de eventos, mas o recorder nao era reaplicado ativamente durante a gravacao; agora novas paginas recebem watcher e instalacao.
9. Session Guardian afetava replay e revalidacao, nao a serializacao de variaveis. Foi ajustado apenas para consentimento Microsoft manual.
10. A acao salvou so um click porque os campos digitados ocorreram fora do documento efetivamente instrumentado, provavelmente em frame/pagina alvo apos o click inicial no desktop browser. Como nenhum `fill` chegou ao backend, a UI nao criou variaveis e o save persistiu lista vazia.

## Exact Cause

A regressao estava na captura ao vivo: o recorder era garantido no `session.page` e por `context.add_init_script`, mas o fluxo real desktop podia mover a interacao para frame/pagina ja existente, navegada ou criada depois. O stop da gravacao tambem inspecionava somente `session.page`. Assim, digitacoes em inputs/selects fora do documento principal nao geravam `event_type=fill`.

Um segundo gap reforcava a falha: `operator_fill()` informava `recorded=True`, mas dependia do listener JS para criar o passo. Se o listener nao estivesse instalado naquele frame/pagina, nenhum fill era persistido.

## Fix Applied

- `start_recording()` agora instala o recorder em todas as paginas e frames acessiveis da sessao.
- Novas paginas e frames navegados durante a gravacao recebem instalacao do recorder.
- Eventos capturados por frame registram `frame_url` e `frame_name`.
- `stop_recording()` coleta outputs/candidatos em todos os frames acessiveis.
- `operator_fill()` grava diretamente um passo `preencher` como fallback se o listener JS nao capturar o fill.
- Passos `preencher` salvos agora incluem `value_template: "{{variavel}}"`.
- `learning_warnings` foi adicionado ao schema/API/UI quando `input_description` menciona entradas como grupo/cota/cpf e nenhum fill foi detectado.
- UI de revisao mostra o aviso: "Não identifiquei os campos digitados. Revise a gravação ou configure os campos manualmente."
- Alvos de extracao preservam metadados de frame quando selecionados na UI.
- Replay procura seletores no frame gravado primeiro e depois nos demais frames.

## Variable Capture Behavior

Quando o usuario digita em `input`, `textarea` ou `select`, o fluxo esperado volta a ser:

- `learning_events`: `event_type=fill`, `value_template`, `variable_key` apos save.
- `passos_playwright`: passo `preencher` com `variavel`, `valor: ""` e `value_template`.
- `variaveis_necessarias`: objetos `{key, label, required}`.
- `variable_schema`: objetos com label editavel/friendly.
- `/api/actions`: `variables` preenchido.
- Quick execution: campos de entrada renderizados a partir de `variables`.

Heuristicas friendly mantidas/reforcadas:

- `edtGrupo`, `grupo`, `Gr.`, `Grupo` -> `grupo`.
- `edtCota`, `cota` -> `cota`.
- `select` sem melhor label -> `tipo_consulta`.

## Frame Or Popup Handling

- Frames atuais: recorder instalado ao iniciar gravacao.
- Frames navegados: listener `framenavigated` reinstala recorder quando possivel.
- Novas paginas/popups: watcher de contexto instala recorder e mantem a pagina ativa quando eventos indicam troca.
- Replay: se o passo tem `frame_url`/`frame_name`, o seletor e procurado nesse frame antes do fallback.
- Limite: frames bloqueados/inacessiveis pelo navegador continuam sujeitos a falha de inspecao; nesse caso a UI/backend mostram aviso e o operador pode configurar seletor/campo manualmente.

## Extraction Behavior For Qtd. Pcls. Pagas

- Quando `Qtd. Pcls. Pagas` retorna valor, o resumo deterministico usa: `Quantidade de parcelas pagas: 032`.
- Quando o alvo configurado nao e encontrado ou vem vazio, retorna: `A ação foi executada, mas não encontrei o campo Qtd. Pcls. Pagas na tela final.`
- Isso evita cair em resumo vago quando ha alvo especifico configurado.

## Microsoft Consent

- Session Guardian continua nao automatizando senha, MFA ou consentimento.
- Para consentimento Microsoft, a mensagem operacional agora instrui aceite manual: `A Microsoft solicitou aceite/consentimento. Abra o navegador desktop, clique em Accept e depois continue.`

## Tests Run

- `python3 -m compileall backend frontend scripts` - OK.
- `docker compose -f docker-compose.test.yml --env-file .env.test up -d --build` - OK.
- `docker compose -f docker-compose.test.yml --env-file .env.test ps` - OK.
- `curl -sS http://127.0.0.1:8100/health` - primeira tentativa durante startup teve reset; segunda tentativa OK: `{"status":"ok","service":"cotasync"}`.
- `docker exec cotasync_test_backend python -m unittest tests.test_operational_summary tests.test_guided_learning_outputs tests.test_desktop_action_runner tests.test_access_profile_demo_flow` - OK, 60 tests.
- `docker exec cotasync_test_backend python scripts/test_desktop_browser_connection.py` - OK.

## Manual Validation Steps

1. Resetar catalogo demo se necessario.
2. Abrir CotaSync.
3. Login/confirmar sessao.
4. Ensinar "Consultar quantidade de parcelas pagas".
5. Durante aprendizado, digitar grupo e cota.
6. Parar gravacao.
7. Confirmar variaveis detectadas como `grupo` e `cota`.
8. Salvar acao.
9. Confirmar quick execution com campos `grupo` e `cota`.
10. Executar acao.
11. Confirmar retorno `Quantidade de parcelas pagas: 032` ou mensagem precisa de nao encontrado.
12. Confirmar `/api/actions` com variaveis e `/api/runs` com diagnosticos.

## Remaining Limits

- Frames que o navegador/CDP nao permite avaliar ainda nao podem ser instrumentados automaticamente.
- Se o usuario digitar em componente customizado que nao dispara `input/change` e nao usa campo nativo, pode ser necessario modo operador ou configuracao manual.
- O catalogo antigo com a acao quebrada nao foi migrado; para demo, a acao deve ser reensinada.

## Next

- Reensinar a acao real no desktop browser e validar `/api/actions` com `grupo`, `cota` e, se aplicavel, `tipo_consulta`.
- Se o sistema Newcon usar frames cross-origin inacessiveis, registrar o diagnostico e usar fallback de seletor/manual mapping.
