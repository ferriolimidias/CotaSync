# Relatório — resposta operacional da execução rápida

Data: 2026-06-23 10:33 BRT
Commit base: `55d88284e108f7b6148354ffedd5e6396f794d4f`

## Causa

A execução rápida devolvia ao chat uma confirmação fixa sobre a execução da memória. O fluxo não interpretava o objetivo da ação, não distinguia ações com e sem extração e misturava resultado para o usuário com evidências e diagnósticos técnicos.

## Correção

- Criado um gerador central de `operational_summary`, com fallback determinístico e uso opcional da configuração OpenAI existente.
- O resumo usa objetivo, resultado esperado, valores extraídos, arquivos e título final seguro; não inventa dados.
- Saídas de IA com termos técnicos, seletores ou referências sensíveis são rejeitadas em favor do fallback.
- Runs agora expõem `operational_summary`, `technical_summary` e `result_payload`; `result_summary` permanece como alias compatível do resumo operacional.
- Título e URL final sem query/credenciais são registrados no payload quando disponíveis.
- Diagnósticos, seletores, evidências e contagem de passos permanecem no payload/API de runs, fora da mensagem do chat.
- A tela de salvamento de ação aprendida agora permite editar nome, objetivo e resultado esperado e não preenche mais o nome com a ação de demonstração.

## Metadados

- `objective`
- `expected_result`
- `output_schema`
- `extraction_targets`
- `user_result_summary_template`
- `ai_result_summary_enabled`

## Comportamento para o usuário

- Com extração: confirma a conclusão e apresenta os valores efetivamente extraídos.
- Extração configurada, mas vazia: informa que o resultado não foi encontrado ou está vazio.
- Sem extração: informa claramente que nenhum resultado final foi configurado; se útil, informa qual tela foi aberta.
- Com arquivo: informa que o arquivo está disponível.
- Em erro: apresenta uma causa operacional simples, sem detalhes do navegador ou da automação.

## Validação

- `python3 -m compileall backend frontend scripts`: passou.
- `docker compose -f docker-compose.test.yml --env-file .env.test up -d --build`: passou.
- `docker compose -f docker-compose.test.yml --env-file .env.test ps`: todos os serviços ativos; desktop browser saudável.
- `curl -s http://127.0.0.1:8100/health`: `status=ok`.
- `docker exec cotasync_test_backend python -m unittest discover -s tests -v`: 16 testes passaram, incluindo 6 novos testes do resumo operacional.
- `BASE_URL=http://127.0.0.1:8100 bash scripts/test_actions_runs_contract.sh`: passou.
- `docker exec cotasync_test_backend python scripts/test_demo_v01_cycle.py`: passou com 3 ciclos e revalidação de sessão.
- `docker exec cotasync_test_backend python scripts/test_desktop_browser_connection.py`: passou.

Houve intermitência inicial do recorder da demo em tentativas intermediárias; a execução final completa passou sem alteração corretiva adicional.

## Limites

- A qualidade semântica pode ser refinada pela IA quando configurada, mas o fallback determinístico é sempre usado sem chave ou diante de saída insegura.
- A ação só retorna dados de negócio quando possui etapa/alvo de extração e o executor realmente devolve valores.
- Não foram adicionados fluxos de documentos, Telegram, Postgres ou alterações em OmniBid/Evolution/Hermes.

## Próximo passo sugerido

Adicionar templates operacionais específicos às ações de maior valor (boleto, cliente e pedido) e definir seus `output_schema`/`extraction_targets` durante o aprendizado real.
