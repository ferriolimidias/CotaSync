# Relatorio - Melhoria do fluxo de aprendizado e extracao

## Diagnostico

O replay mecanico ja estava funcionando. A run informada para `Quantidade de parcelas` concluiu com:

- `runner`: `desktop_browser_replay`
- `browser_mode`: `desktop_browser`
- `session_state`: `authenticated_system`
- `operator_action_required`: `false`
- `retryable`: `false`
- `recovery_attempts`: `0`
- ultimo passo bem-sucedido: `7`
- resultado exibido ao usuario: `032`

Conclusao: o problema nao era o aprendizado mecanico nem o login. O problema estava na experiencia posterior de configurar resultado, testar extracao e interpretar revisao com IA.

## Prova de que replay/aprendizado funcionava

O valor `032` saiu de uma execucao real bem-sucedida. Isso prova:

- caminho mecanico gravado;
- replay desktop funcional;
- sessao autenticada;
- sem necessidade de operador;
- resultado final disponivel.

Por isso, a UI agora trata replay OK como estado proprio, sem depender da IA.

## Problema na revisao/extracao

Antes, a tela misturava:

- replay mecanico;
- validacao com IA;
- candidatos de extracao;
- contrato visual;
- teste de resultado.

Tambem havia candidatos ruins vindos de DOM tecnico, como CSS:

- `max-width`
- `WebKit`
- `Chrome/Safari`
- texto de `style/script/head`.

Isso fazia parecer que o aprendizado tinha falhado quando, na verdade, a etapa confusa era a configuracao/revisao do resultado.

## Separacao entre replay, extracao e IA

Na UI, a acao salva agora mostra cards separados:

- `Caminho aprendido`
- `Teste da acao`
- `Extracao`
- `Revisao IA`

Revisao com IA foi renomeada para:

```text
Revisar com IA (opcional)
```

Se a IA falhar ou estiver indisponivel, a mensagem deixa claro que a acao continua utilizavel se o teste e a extracao estiverem OK.

## UI revisada

Na area `Resultado da rotina`, a tela agora prioriza:

1. Resultado detectado no ultimo teste.
2. Botao `Confirmar este resultado`.
3. Botao `Testar extracao salva`.
4. Botoes para selecionar outro resultado na tela ou detectar candidatos.

O dropdown tecnico de candidatos foi movido para:

```text
Avancado: candidatos de extracao
```

O botao de teste agora mostra status tecnico claro:

- `Extração OK. Label: ... Valor extraído: ... Tipo: ...`
- ou `Extração precisa configurar. Motivo: ...`

## Filtros de candidatos

Arquivo:

```text
backend/services/result_selection.py
```

Foram adicionados:

- `is_technical_dom_text`
- `is_candidate_text_valid`
- validacao reforcada em `validate_candidate_value`
- filtragem em `detect_extraction_candidates`

Agora sao ignorados:

- CSS;
- `script`;
- `style`;
- `head`;
- `meta`;
- `link`;
- texto tecnico de DOM;
- valor vazio;
- label igual ao valor;
- candidatos como `Ocorrência` para percentual.

## Confirmacao de ultimo resultado

Novo endpoint:

```text
POST /api/actions/{action_id}/extraction/confirm-last-result
```

Ele:

1. busca a ultima run de sucesso da acao;
2. extrai valor de `dados_extraidos` ou `operational_summary`;
3. preserva zero a esquerda, como `032`;
4. cria contrato de extracao confirmado;
5. salva `extraction_review`, `reviewed_overlay` e `final_summary_instruction`.

Novo endpoint de teste:

```text
POST /api/actions/{action_id}/extraction/test
```

Ele testa o contrato salvo contra a ultima run de sucesso e retorna:

- status tecnico;
- label;
- valor;
- tipo;
- motivo quando precisa atencao.

## Como impedir candidato invalido virar contrato

`POST /api/actions/{action_id}/result-selection/confirm` agora retorna `422` quando o contrato fica com `needs_attention`, por exemplo:

- valor vazio;
- texto tecnico;
- label sem valor;
- tipo numerico com texto nao numerico;
- `% Pagar` retornando `Ocorrência`.

## Como mostrar 032 como resultado detectado

A UI usa o ultimo resultado guardado em `demo_last_run` e extrai:

- primeiro de `result_payload.dados_extraidos`;
- depois de `operational_summary`.

Quando encontra valor, exibe:

```text
Valor detectado no último teste: 032
```

e oferece:

```text
Confirmar este resultado
```

## Testes

Novo arquivo:

```text
tests/test_learning_extraction_flow.py
```

Coberturas:

- run de sucesso com `032` gera resultado detectado;
- `032` preserva zero a esquerda;
- confirmar ultimo resultado salva `extraction_review`;
- confirmar ultimo resultado salva `final_summary_instruction`;
- teste de extracao retorna OK para valor valido;
- detector ignora CSS/DOM tecnico;
- candidato vazio nao vira sucesso;
- `Ocorrência` e rejeitado para percentual.

Suites executadas:

```bash
python3 -m compileall backend frontend scripts
docker compose -f docker-compose.test.yml --env-file .env.test up -d --build
docker compose -f docker-compose.test.yml --env-file .env.test ps
sleep 5 && curl -sS http://127.0.0.1:8100/health
docker exec cotasync_test_backend python -m unittest tests.test_learning_extraction_flow tests.test_operator_login_controls tests.test_batch_runner tests.test_clients_repository tests.test_operational_summary tests.test_guided_learning_outputs tests.test_desktop_action_runner tests.test_access_profile_demo_flow
docker exec cotasync_test_backend python scripts/test_desktop_browser_connection.py
```

Resultado:

- compileall OK;
- Docker build/up OK;
- containers OK;
- healthcheck OK;
- 150 testes OK;
- desktop browser/noVNC/CDP/replay OK.

## Validacao manual

Fluxo esperado:

1. Abrir `http://89.116.29.150:3100`.
2. Abrir a acao `Quantidade de parcelas`.
3. Executar teste da acao.
4. Confirmar resposta `032`.
5. Ver cards:
   - Caminho aprendido: OK;
   - Teste da acao: OK;
   - Extracao: OK ou precisa configurar;
   - Revisao IA: opcional.
6. Clicar `Confirmar este resultado`.
7. Confirmar contrato salvo.
8. Abrir `Avancado: candidatos de extracao`.
9. Confirmar que nao aparecem CSS/WebKit/Chrome/Safari.
10. Clicar `Testar extracao salva`.
11. Confirmar `Valor extraído: 032`.
12. Executar novamente e confirmar que o resultado continua correto.

## Limitacoes

- A classificacao de status mais profunda ainda e principalmente UI/backend incremental, nao uma migracao completa do schema da acao.
- O endpoint de confirmar ultimo resultado depende de haver run de sucesso persistida.
- A revisao com IA continua existindo, mas agora isolada como etapa opcional.

## Proximos passos

- Persistir campos explicitos `mechanical_learning_status`, `extraction_status`, `ai_review_status` e `action_ready`.
- Criar painel de historico de testes por acao.
- Melhorar heuristicas por dominio para outros tipos de resultado alem de numero e percentual.
