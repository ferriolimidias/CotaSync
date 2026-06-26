# Reformulate Mechanical Learning Flow

Data: 2026-06-26 14:23

## Audit Findings

Arquivos auditados:

- `frontend/app.py`
- `frontend/api_client.py`
- `backend/services/demo_session.py`
- `backend/api/demo.py`
- `backend/services/action_runner.py`
- `backend/services/operational_summary.py`
- `backend/services/session_guardian.py`
- `backend/services/actions_repository.py`
- `tests/*`
- `data/ui_map.json` por contrato de leitura/escrita do catalogo

O fluxo antigo juntava aprendizado, login, perfil de acesso, perguntas guiadas, opcao de IA, timeouts e confirmacao manual na mesma tela. A captura mecanica existia, mas o salvamento dependia demais do formulario guiado e de nomes de variaveis enviados pela UI. Se a UI nao enviasse `variable_names`, campos digitados podiam ficar sem variavel apesar de haver evento de preenchimento.

## Old Flow Problems

- O aprendizado bloqueava em perfil de acesso do operador antes de gravar.
- A tela exigia objetivo, entradas, resultado esperado, criterio de sucesso, tipo de retorno, opcao de IA e timeout antes da demonstracao.
- O botao `Login concluido` ficava no fluxo de chat/demo e parecia parte da rotina aprendida.
- A IA era chamada por passo durante a gravacao, misturando revisao com captura.
- Variaveis eram confiaveis apenas quando a UI mandava o mapeamento final.
- O resumo final podia cair em mensagem generica quando havia um alvo especifico de extracao.

## New Simplified Flow

Frase-guia aplicada:

> Eu ensino fazendo. O CotaSync grava mecanicamente. Depois a IA revisa, organiza e melhora o replay.

Na tela de ensino, o fluxo basico agora pede apenas:

- Nome da rotina
- Iniciar gravacao

Depois de parar:

- Mostra contadores de passos, cliques, campos, selects, abas, downloads e pagina final.
- Mostra variaveis detectadas para renomear.
- Pede o alvo simples de retorno por texto, por exemplo `Qtd. Pcls. Pagas`.
- Exige confirmacao explicita se nenhum campo digitado/select foi capturado.

## Login/Session Config Behavior

Login saiu do fluxo de chat/demo e foi movido para Configuracoes.

Controles adicionados/expostos:

- Sistema externo
- URL inicial
- Abrir navegador para login
- Salvar sessao do navegador
- Testar sessao salva
- Limpar sessao salva

O login continua manual. O CotaSync nao salva senha, nao automatiza MFA e nao clica consentimento Microsoft por padrao. A sessao salva usa `storage_state.json` por sistema externo, sem apagar perfil persistente, cookies externos fora do escopo, `.env` ou credenciais.

## Mechanical Recording Behavior

O recorder agora captura mecanicamente:

- `click`
- `fill`
- `select`
- tecla Enter como evento de espera/replay
- mudanca de pagina/nova aba via metadados do evento
- downloads
- frames acessiveis
- snapshot de texto/HTML da pagina final

A captura mecanica nao depende de IA. A IA roda depois da gravacao ou no salvamento final.

## Automatic Variable Detection

Todo `preencher` e `selecionar` gera variavel automaticamente quando a acao e salva, mesmo que a UI nao envie `variable_names`.

Persistido por campo/select:

- `selector`
- `field_metadata`
- `variable_key`
- `value_template`
- `variavel`
- `valor` vazio
- `learning_events[].variable_key`
- `robust_steps`
- `variaveis_necessarias`
- `variable_schema`

Valores digitados de exemplo nao sao usados como replay fixo. O replay usa `{{grupo}}`, `{{cota}}`, `{{tipo_consulta}}` etc.

Regras de nome amigavel:

- `edtGrupo`, `txtGrupo`, `Grupo` -> `grupo`
- `edtCota`, `txtCota`, `Cota` -> `cota`
- `CPF` -> `cpf`
- `Cliente` -> `cliente`
- primeiro select sem nome melhor -> `tipo_consulta`
- fallback -> `campo_N`

## Frame/New Page Handling

O recorder tenta instalar em todas as paginas e frames acessiveis. Frames inacessiveis registram erro em `recorder_errors`.

Eventos salvos incluem:

- `frame_url`
- `frame_name`
- `opened_new_page`
- `active_page_changed`

Replay procura o seletor no frame gravado quando possivel e recai para outros frames acessiveis.

## Extraction Target Behavior

O alvo simples digitado e salvo como estrategia `near_label` quando nao ha seletor.

Exemplo salvo:

- alvo: `Qtd. Pcls. Pagas`
- replay busca o label na pagina final/frames acessiveis
- extrai o valor vizinho, por exemplo `032`

Resumo esperado:

`Quantidade de parcelas pagas: 032`

Se nao encontrar:

`A ação foi executada, mas não encontrei o campo Qtd. Pcls. Pagas na tela final.`

## AI Post-Review Behavior

IA nao e necessaria antes da gravacao e nao substitui os passos mecanicos.

Ela pode sugerir:

- nomes/rotulos
- esperas/checkpoints
- riscos de popup, nova aba ou download
- estrategia de extracao
- descricao concisa
- instrucao de resumo final

Ela nao remove passos mecanicos nem transforma valores digitados em fixos.

## Final Summary Behavior

Resumo operacional continua ligado por padrao, com fallback deterministico quando OpenAI nao esta configurada ou falha.

Para dados extraidos especificos, o resumo usa apenas o dado extraido e nao inventa conteudo.

## What CotaSync Can Read

CotaSync pode ler:

- DOM/HTML renderizado no navegador
- texto visivel
- inputs/selects
- valores e atributos de elementos
- frames acessiveis
- URL/titulo atuais
- downloads
- eventos do navegador

CotaSync nao le diretamente:

- codigo backend do sistema externo
- banco de dados
- regras server-side escondidas
- dados que nao foram enviados ao navegador

## Files Changed

- `backend/api/demo.py`
- `backend/services/demo_session.py`
- `backend/services/actions_repository.py`
- `backend/services/operational_summary.py`
- `frontend/app.py`
- `frontend/api_client.py`
- `tests/test_access_profile_demo_flow.py`
- `tests/test_guided_learning_outputs.py`
- `tests/test_operational_summary.py`
- `scripts/test_desktop_browser_connection.py`
- este relatorio

## Tests Run

- `python3 -m compileall backend frontend scripts` - OK
- `docker compose -f docker-compose.test.yml --env-file .env.test up -d --build` - OK
- `docker compose -f docker-compose.test.yml --env-file .env.test ps` - OK
- `curl -sS http://127.0.0.1:8100/health` - OK apos retry; primeira chamada ocorreu durante startup e recebeu reset de conexao
- `docker exec cotasync_test_backend python -m unittest tests.test_operational_summary tests.test_guided_learning_outputs tests.test_desktop_action_runner tests.test_access_profile_demo_flow` - OK, 66 tests
- `docker exec cotasync_test_backend python scripts/test_desktop_browser_connection.py` - OK

Observacao: `python -m unittest ...` no host falhou porque `python` nao existe e `python3` no host nao tem dependencias (`pydantic`, `fastapi`). A validacao completa foi feita no container de teste.

## Manual Validation Steps

Checklist recomendado:

1. Resetar catalogo demo se necessario.
2. Ir para Configuracoes.
3. Configurar Sistema externo e URL inicial.
4. Abrir navegador para login.
5. Fazer login manualmente.
6. Salvar sessao do navegador.
7. Testar sessao salva.
8. Ir para Chat & Acoes > Demo v0.1.
9. Informar apenas `Consultar quantidade de parcelas pagas`.
10. Iniciar gravacao.
11. Executar o fluxo real manualmente.
12. Digitar grupo e cota.
13. Parar gravacao.
14. Confirmar `fill_event_count > 0`.
15. Confirmar variaveis `grupo` e `cota`.
16. Definir alvo `Qtd. Pcls. Pagas`.
17. Salvar.
18. Executar a rotina.
19. Confirmar campos rapidos `grupo` e `cota`.
20. Confirmar resposta `Quantidade de parcelas pagas: 032`.

## Limits

- A validacao manual contra o sistema real nao foi executada nesta alteracao.
- Frames cross-origin inacessiveis sao reportados, mas nao podem ser instrumentados pelo browser.
- A extracao `near_label` e propositalmente simples para o demo; telas muito irregulares podem precisar de seletor manual em uma iteracao futura.
- Session Guardian permanece como recuperacao, mas nao deve ser requisito de ensino basico.

## Next

- Adicionar UI de selecao/click do campo de retorno na tela final.
- Adicionar mapeamento manual assistido apenas para frames inacessiveis.
- Persistir historico de diagnostico por gravacao para auditoria posterior.
- Criar limpeza opcional de catalogo demo quebrado via botao seguro, preservando configuracoes e sessoes.
