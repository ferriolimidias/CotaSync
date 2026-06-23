# Relatorio - fix final screen summary

Data: 2026-06-23 18:16

## Causa do mau retorno

O texto final estava sendo extraido corretamente em `result_payload.dados_extraidos.texto_tela_final`, mas o resumo deterministico tratava esse conteudo como texto ruidoso. A heuristica de formulario/filtro nao reconhecia termos reais da tela, como `Relatorio`, `Data Base`, `Contemplacao`, `Filial`, `Lista` e `Considera`. Com isso, o fluxo caia no fallback generico:

`A tela final foi aberta, mas nao foi possivel identificar um resultado especifico configurado.`

## IA chamada ou fallback usado

O pipeline ja chama IA quando `ai_result_summary_enabled=true` e existe `OPENAI_API_KEY`. Quando a IA esta desabilitada, sem chave, falha ou retorna texto rejeitado pela validacao de seguranca, o resumo deterministico e usado.

Para este caso, a causa operacional do texto ruim estava no fallback deterministico: mesmo com `texto_tela_final` preenchido, ele nao produzia uma explicacao util da tela.

## Fix aplicado

- Adicionado tratamento dedicado para `dados_extraidos.texto_tela_final`.
- O texto e limpo, compactado e avaliado como conteudo de tela antes do fallback generico.
- Telas de relatorio/formulario com filtros agora geram uma explicacao operacional curta.
- O fallback generico de "nao foi possivel identificar" nao e usado quando `texto_tela_final` tem texto significativo.
- Adicionado `summary_reason` ao resultado interno e ao registro de run.

## Comportamento para `texto_tela_final`

Quando `texto_tela_final` existe e contem texto legivel:

- identifica se a tela parece relatorio, formulario ou tela de filtros;
- reconhece `relatorio de bens a entregar` quando esse assunto aparece;
- lista campos uteis, como data base, grupo, produto, tipo de venda, ponto de venda, filial e unidade de negocio;
- lista opcoes uteis, como entregas parciais, FGTS, contemplacao por sorteio/lance, lances pagos e cotas canceladas;
- informa quando nenhum resultado listado foi exibido e a tela parece aguardar filtros.

## Controle de custo de IA

- Usa `OPENAI_MODEL` existente, sem hardcode de modelo caro.
- Limita o contexto enviado para IA a 8k caracteres.
- Envia apenas dados extraidos sanitizados.
- Nao envia screenshot, imagem, seletor, credencial, token, URL ou caminho local no prompt operacional.
- Se a IA falhar, estiver desabilitada ou retornar conteudo rejeitado, o fallback deterministico continua util.

## Fallback deterministico

O fallback agora reconhece paginas com indicios como `Relatorio`, `Data Base`, `Grupo`, `Produto`, `Tipo de Venda`, `Filial`, `Contemplacao`, `Intervalo`, `Lista` e `Considera`.

Exemplo de saida para o fixture real:

`Consulta concluida. A tela aberta parece ser um relatorio de bens a entregar. Ela contem filtros/campos como data base, grupo, situacao do grupo, produto, tipo de venda, ponto de venda, filial, unidade de negocio. Tambem ha opcoes como entregas parciais, FGTS, contemplacao por sorteio, contemplacao por lance, lances pagos, cotas canceladas. Nenhum resultado listado foi exibido; a tela parece estar aguardando filtros para gerar o relatorio.`

## Testes executados

- `python3 -m compileall backend frontend scripts` - passou.
- `docker compose -f docker-compose.test.yml --env-file .env.test up -d --build` - passou.
- `docker compose -f docker-compose.test.yml --env-file .env.test ps` - containers backend, frontend, desktop browser, browserless, redis e postgres em execucao; desktop browser healthy.
- `curl -sS http://127.0.0.1:8100/health` - retornou `{"status":"ok","service":"cotasync"}`.
- `docker exec cotasync_test_backend python -m unittest tests.test_operational_summary tests.test_guided_learning_outputs tests.test_desktop_action_runner` - passou, 31 testes.
- `docker exec cotasync_test_backend python scripts/test_desktop_browser_connection.py` - passou.

Observacao: o primeiro `curl -s http://127.0.0.1:8100/health` foi executado logo apos subir os containers e falhou por conexao ainda nao pronta. A repeticao com `curl -sS` passou.

## Validacao manual da demo

Passos recomendados:

1. Executar novamente a acao aprendida pela UI.
2. Confirmar que a mensagem principal do chat explica a tela final como relatorio/formulario com filtros.
3. Confirmar que o texto bruto completo aparece somente em `Ver dados extraidos` e `Ver JSON/result_payload`.
4. Confirmar em `/api/runs` que a ultima run contem `operational_summary`, `summary_source`, `ai_summary_used` e `summary_reason`.

## Limites

- A classificacao deterministica usa heuristicas de palavras-chave; pode nao nomear perfeitamente telas muito diferentes.
- A IA depende de `OPENAI_API_KEY` e da configuracao `ai_result_summary_enabled`.
- A correcao nao altera login, noVNC, Browserless, desktop_browser ou arquitetura de navegacao.

## Proximos passos

- Rodar a acao real da demo na UI para validar a mensagem no fluxo completo.
- Se houver novos tipos de relatorio, adicionar fixtures pequenos com textos reais ao `tests.test_operational_summary`.
