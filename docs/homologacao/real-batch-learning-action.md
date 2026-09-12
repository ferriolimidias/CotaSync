# CotaSync - Baseline real de Action aprendida executada em lote

## Escopo da evidencia

`Quantidade de parcelas` foi criada pelo Criador de Aprendizado do CotaSync a
partir de uma demonstracao humana. Ela nao e uma rotina hardcoded do produto.
Este documento registra uma baseline parcial de producao para preservar o
comportamento generico de Actions futuras criadas pelo mesmo mecanismo.

Snapshot coletado em `2026-09-12T14:27:35Z`, enquanto o batch ainda estava em
execucao.

## Identificacao

- Batch: `99c6b9af-2768-4de3-8d37-1986fcf1c9a2`
- Status no snapshot: `running`
- ActionVersion: `quantidade-de-parcelas-v1` (`published`)
- LearningSession de origem: `25399489-09db-4137-a53a-0ace173c8829`
- ExternalAccessProfile: `a62075ab-d24f-48d4-b446-e947337fa3c9`
- Lista: `Priscila` (`81322df7-3418-4a33-a95c-25eae6c6aff6`)
- Planilha do sistema: `Clientes teste`
  (`54502481-d371-48a7-a719-72303015aedf`)
- Total: `392`
- Processados: `19`
- Sucesso: `19`
- Erros: `0`
- Interrompidos: `0`
- Cancelados: `0`
- Intervalo configurado: `5` segundos
- `run_start_strategy`: `external_entry_each_run`

Esta e evidencia real de producao, nao um teste sintetico. O batch continuava
rodando no momento do snapshot; portanto esta e uma baseline parcial em
execucao.

## Cadeia do aprendizado

| Estagio | Estado | Evidencia real |
|---|---|---|
| LearningSession | IMPLEMENTED e USED | Sessao `25399489...` esta `stopped`/`published`, com 4 `recorded_steps`, 2 `variable_bindings` e 1 output. |
| Recorder | IMPLEMENTED e USED | `recorded_steps` persistidos na LearningSession e 4 `action_steps` publicados. |
| Revisao/normalizacao por IA | IMPLEMENTED e USED | `diagnostics.ai_review` registra `ai_reviewed=true`, modelo e replay hints. |
| Validacao deterministica | IMPLEMENTED e USED | Publication registrada como `published`; ActionVersion e contratos de output persistidos. |
| Publicacao | IMPLEMENTED e USED | `published_action_version_id=quantidade-de-parcelas-v1`, perfil requerido persistido. |
| Executor | IMPLEMENTED e USED | 19 Runs reais `success`, cada uma com variaveis, resultado e `same_run_reentry`. |

Nao ha um contador separado persistido chamado `normalized_steps`; a evidencia
normalizada publicada e o conjunto de 4 `action_steps` da ActionVersion.

Variaveis aprendidas: `grupo` e `cota`, ambas texto. A definicao de resultado
possui um contrato persistido para `Quantidade de parcelas`.

## Comportamento generico comprovado

- Uma demonstracao humana origina uma LearningSession.
- O Recorder persiste passos e variaveis, separados do acesso externo.
- A revisao pode produzir diagnosticos e orientacoes, mas a ActionVersion e
  publicada como artefato deterministico.
- A execucao resolve a ActionVersion publicada e recebe variaveis do cliente.
- O executor percorre o graph aprendido e persiste o resultado associado ao
  cliente e a Run.
- Cada cliente do batch e uma unidade logica propria.
- Cada cliente possui seu AccessCycle, iniciando pela entry URL canonica.
- A sessao persistente do mesmo ExternalAccessProfile e reutilizada; isso nao
  implica compartilhar a identidade entre perfis.
- O processamento observado e sequencial, com intervalo entre clientes.
- Resultados internos sao persistidos independentemente do downstream Google.

## Este documento nao define uma Action fixa

Os itens abaixo sao apenas evidencia desta Action aprendida e nao devem virar
regras especiais do produto:

- nome `Quantidade de parcelas`;
- selectors de Atendimento, Grupo, Cota e Localizar;
- campos `grupo` e `cota`;
- caminho de telas do sistema externo;
- selector e label do resultado;
- valores retornados nesta execucao.

Actions futuras devem continuar sendo definidas pela demonstracao, pelo
Recorder, pela revisao/validacao e pela ActionVersion correspondente. Nenhum
detalhe desta tabela deve ser hardcoded no executor.

## Clientes e resultados persistidos

Os 19 itens concluidos no snapshot estavam associados a Runs `success` e a
resultados internos persistidos:

| # | Run | Grupo | Cota | Resultado |
|---:|---|---:|---:|---:|
| 1 | `0b63bf07-8734-4f9a-a97c-184adb4692ef` | 955 | 377 | 013 |
| 2 | `5bffabfb-afaa-4872-b30c-fa2b9d948068` | 900 | 222 | 019 |
| 3 | `c2c69387-26db-4bf7-be0d-8e26bd74217e` | 935 | 438 | 006 |
| 4 | `8ff685db-6122-4944-bc62-50214470f6ab` | 910 | 197 | 010 |
| 5 | `df3eb5df-0aaf-40fe-b2fc-305838e61191` | 955 | 344 | 013 |
| 6 | `01de2eed-a5c4-459c-af87-d6afee9fa0b2` | 910 | 218 | 009 |
| 7 | `e699d9c4-fdb4-4840-af21-6fd1c7786549` | 955 | 289 | 007 |
| 8 | `5bfa54e5-c0a3-4609-8849-68405dd5de38` | 960 | 104 | 002 |
| 9 | `946885c1-8f22-44b6-822c-414535ae16bc` | 915 | 476 | 009 |
| 10 | `acc1105c-d29a-4983-8337-37a1ac417bf9` | 915 | 474 | 015 |
| 11 | `243a6ed6-7c67-41c1-9a4b-ae829b099540` | 945 | 226 | 014 |
| 12 | `ec9ad4c9-bbd0-4076-8966-7005cd4e4239` | 945 | 429 | 015 |
| 13 | `df513e27-0ccb-41f9-9027-e3a561c1dc85` | 945 | 192 | 006 |
| 14 | `bdf66f8a-baed-401b-b1e0-6a733a0329a6` | 935 | 461 | 016 |
| 15 | `44d5f0f8-1792-4f62-9ca6-6164b402335f` | 945 | 250 | 006 |
| 16 | `a70668cb-6cbe-44fe-be94-9385dfb4f635` | 945 | 582 | 009 |
| 17 | `2fbd7829-baba-458e-9cd7-735e1c058285` | 915 | 872 | 014 |
| 18 | `349ee3ed-a09e-467b-9e7d-b925c798f243` | 945 | 572 | 015 |
| 19 | `8b5991f7-5b96-469d-9043-f23b776910e5` | 945 | 335 | 009 |

Cada resultado foi persistido em `runs.extracted_data` com o nome do contrato
e associado ao cliente pela Run/batch item. Os valores de entrada observados
foram preservados como strings.

## Sequenciamento e acesso

Os 19 AccessCycles criados no intervalo do batch estavam no perfil esperado,
com estado `ready`/`external_system_ready`. Todos registraram os eventos
canônicos de entrada, Account Picker, seleção do perfil, bootstrap, verificação
de identidade e sistema pronto. Os 19 usaram o mesmo browser context persistente
do perfil, sem indicar troca de identidade.

As Runs foram estritamente sequenciais: `MAX_CONCURRENT_CLIENT_RUNS=1`.
Nenhuma Run seguinte iniciou antes do terminal da anterior. Entre Runs
consecutivas, o intervalo observado variou de `5.268795s` a `6.039866s`, com
média de `5.383937s`, compatível com o intervalo configurado de 5 segundos.

O primeiro, segundo e terceiro clientes confirmam respectivamente `955/377 ->
013`, `900/222 -> 019` e `935/438 -> 006`. Não houve vazamento observado de
grupo/cota ou resultado entre clientes.

## Coleta e downstream

As Runs reutilizaram o ResultDefinition/contrato publicado da ActionVersion e
persistiram os resultados internamente. A pendencia observada no downstream
Google era de 19 itens `pending` em `google_sync_pending` no snapshot.
Isso nao bloqueou o navegador: as Runs permaneceram `success` e o batch
continuou processando o proximo cliente. O mecanismo de sincronizacao pode
reprocessar o downstream sem repetir a Action.

## Invariantes comprovadas neste snapshot

- Action criada pelo aprendizado, sem evidencia de rotina hardcoded.
- ActionVersion publicada vinculada a LearningSession e AccessProfile.
- AccessCycle antes da Action para cada cliente observado.
- Entry URL canonica por cliente.
- Identidade verificada antes do graph.
- Uma Run por vez, com intervalo configurado.
- Variaveis isoladas por cliente e preservadas como texto.
- Resultado associado ao cliente correto e persistido internamente.
- Pendencia Google separada da execução do browser.

## Runtime e Git

- HEAD antes deste documento: `54f95e6cfeebb56bbb1c7e5a2032c1f1215e3d46`
- Backend e worker usam o bind mount do worktree em `/app`.
- Os processos observados foram `uvicorn backend.main:app` e `python -m backend.worker`.
- O worktree nao estava limpo antes do documento.
- Existe uma alteracao de runtime nao commitada em
  `backend/services/session_guardian.py`, que altera o click do Account Picker
  para `no_wait_after=True`. Por isso nenhuma tag de homologacao e criada nesta
  rodada.

Nenhum runtime foi alterado para produzir esta baseline.
