# CotaSync - Baseline de execucao real bem-sucedida

## Evidencia

- Data: 2026-09-12
- Run: `39ea9c45-cc0d-4102-acb1-f2c5188e29ae`
- Status: `success`
- Action: Quantidade de parcelas
- ActionVersion: `quantidade-de-parcelas-v1`
- LearningSession de origem: `25399489-09db-4137-a53a-0ace173c8829`
- Cliente: `0485f7f0-11c3-4314-8c02-674e41759bcb` (A G TRANSPORTE)
- Variaveis: `grupo=955`, `cota=377`
- AccessProfile: `a62075ab-d24f-48d4-b446-e947337fa3c9` (Priscila)
- AccessCycle: `c60a9ee5-e15e-40e2-b3ee-f9c0e1bd1157`
- Inicio: `2026-09-12T12:38:36.768901Z`
- Conclusao: `2026-09-12T12:39:09.199313Z`
- Resultado persistido: `013`

Esta e evidencia de operacao real em producao, nao um teste sintetico.
Nenhuma credencial, token, cookie ou query OAuth e registrada neste documento.

## Timeline real

| Timestamp UTC | Componente | Evento | Estado/resultado |
|---|---|---|---|
| 12:38:36.762 | Run | `RUN_CREATED` | Run criada |
| 12:38:36.784 | Run | `RUN_STARTED` | `external_entry_each_run` |
| 12:38:39.597 | AccessCycle | `ACCESS_CYCLE_CREATED` | Entry source: `ExternalSystem.entry_url` |
| 12:38:40.756 | AccessCycle | `ACCESS_CYCLE_STARTED` | ciclo iniciado |
| 12:38:40.853 | AccessCycle | `CANONICAL_ENTRY_NAVIGATION_STARTED` | entrada externa |
| 12:38:42.461 | AccessCycle | `CANONICAL_ENTRY_NAVIGATION_COMPLETED` | `login.microsoftonline.com/common/oauth2/v2.0/authorize` |
| 12:38:42.881 | AccessCycle | `ACCOUNT_PICKER_OBSERVED` | picker observado |
| 12:38:42.888 | AccessCycle | `ACCESS_PROFILE_SELECTION_STARTED` | perfil selecionado por identificador |
| 12:38:46.802 | AccessCycle | `ACCESS_PROFILE_SELECTION_COMPLETED` | sucesso |
| 12:38:46.809 | AccessCycle | `ACCESS_BOOTSTRAP_STARTED` | bootstrap sem eventos adicionais |
| 12:38:46.819 | AccessCycle | `ACCESS_BOOTSTRAP_COMPLETED` | sucesso |
| 12:38:46.828 | AccessCycle | `ACCESS_IDENTITY_VERIFICATION_STARTED` | verificação iniciada |
| 12:38:46.862 | AccessCycle | `ACCESS_IDENTITY_VERIFIED` | evidencia: `PRISCILA SUSIN (0000708747)` |
| 12:38:46.870 | AccessCycle | `EXTERNAL_SYSTEM_READY` | `nwcweb.randonconsorcios.com.br/frmMain.aspx` |
| 12:38:46.876 | AccessCycle | `ACCESS_CYCLE_COMPLETED` | pronto |
| 12:38:47.408 | ActionRunner | `MAIN_GRAPH_STARTED` | primeiro step: `step_d3f0ea3f9520e937` |
| 12:38:47.551 | ActionRunner | step 0 iniciado | click `#ctl00_img_Atendimento` |
| 12:38:52.835 | ActionRunner | step 0 concluido | estado `state_20c82e77b24cfaaa` |
| 12:38:52.867 | ActionRunner | step 1 iniciado | fill `#ctl00_Conteudo_edtGrupo` |
| 12:38:53.102 | ActionRunner | step 1 concluido | `grupo` preenchido |
| 12:38:53.133 | ActionRunner | step 2 iniciado | fill `#ctl00_Conteudo_edtCota` |
| 12:39:09.199 | Run | `RUN_SUCCEEDED` | sucesso |

O trace persistido confirma o step 2 concluido no botao `#ctl00_Conteudo_btnLocalizar`
e a consulta confirmada antes da leitura do resultado.

## Action executada

| Index | Tipo | Step | Seletor | Variavel | Estados | Status |
|---:|---|---|---|---|---|---|
| 0 | clicar | `step_d3f0ea3f9520e937` | `#ctl00_img_Atendimento` | - | `state_74ef8a5ce0812120 -> state_20c82e77b24cfaaa` | success |
| 1 | preencher | `step_f6b64731fdf68585` | `#ctl00_Conteudo_edtGrupo` | `grupo` | `state_20c82e77b24cfaaa -> state_20c82e77b24cfaaa` | success |
| 2 | preencher | `step_9d1ee17f9879629b` | `#ctl00_Conteudo_edtCota` | `cota` | `state_20c82e77b24cfaaa -> state_20c82e77b24cfaaa` | success |
| 3 | clicar | `step_302c40e9b89ca06f` | `#ctl00_Conteudo_btnLocalizar` | - | `state_20c82e77b24cfaaa -> state_01a5e6e5d81d0acc` | success |

O trace operacional possui tres itens de execucao porque o primeiro clique
de acesso e representado separadamente no plano do graph. Os valores de
entrada foram mantidos como strings: `"955"` e `"377"`.

## Resultado

- Nome: `Quantidade de parcelas`
- Contrato: `quantidade-de-parcelas-v1-contract-1`
- Field: `field-b6ff6e9576098d65d0738b33`
- Selector: `#ctl00_Conteudo_lblQT_Pcls_Paga`
- Metodo: leitura textual do elemento (`inner_text`)
- Valor bruto: `013`
- Normalizacao: `digits_only`
- Valor final: `013`
- Pagina: `nwcweb.randonconsorcios.com.br/CONAT/frmConAtCnsAtendimento.aspx`

O contrato usa o selector tecnico como fonte primaria e tambem conserva
contexto semantico/estrutural: label da tela, texto proximo e texto do pai.
Assim, a dependencia observada nesta Run e **D: combinacao de selector
tecnico e contexto semantico/estrutural**, embora a leitura efetiva tenha
usado o selector primario.

## Esperas e invariantes comprovadas

- A entrada foi iniciada pelo `ExternalSystem.entry_url`.
- O Account Picker foi observado e a selecao do perfil foi concluida.
- A identidade foi verificada antes do main graph.
- Houve espera/stabilizacao de navegacao no clique de Atendimento.
- O graph avancou de `state_74ef8a5ce0812120` para
  `state_20c82e77b24cfaaa` antes dos preenchimentos.
- A consulta foi confirmada antes da extracao.
- `FALSE_REAUTH_PASSWORD_WORD=NÃO`.
- `ACCESS_IDENTITY_MISMATCH=NÃO`.
- `ACCESS_BOOTSTRAP_MISSING=NÃO`.
- `PROFILE_SESSION_SWAP=NÃO`.
- `BROWSER_CONTEXT_SWAP=NÃO`.
- `STEP0_ABORT=NÃO`.

## Limite da evidência

O AccessCycle persistiu `browser_target_id` e `browser_context_id`, mas a Run
nao persistiu esses mesmos identificadores no handoff. Portanto a identidade
do perfil e o caminho de acesso estao comprovados, mas a igualdade direta de
contexto/pagina entre AccessCycle e ActionRunner nao pode ser afirmada apenas
pelos artefatos desta Run.

## Preservar

- AccessCycle concluido antes da Action.
- Identidade verificada pelo perfil correto.
- Entrada externa canonica por unidade logica.
- Estabilizacao pos-navegacao do graph.
- Variaveis de cliente preservadas como strings.
- Extracao somente apos a consulta confirmada.
- Persistencia do resultado interno antes de qualquer downstream.
- Contrato de resultado com selector, contexto e normalizacao documentados.

