# Relatório Final - AI Operational Response

Data: 2026-06-23 17:31

## O que foi auditado e reutilizado

- Reutilizado `backend/services/operational_summary.py` como ponto único de geração do resumo final.
- Reutilizados `result_payload`, `dados_extraidos`, `downloaded_files`, `main_file`, `OPENAI_MODEL`, `OPENAI_API_KEY` e fallback determinístico existente.
- Reutilizado o fluxo atual de `backend/services/action_runner.py` para persistir runs.
- Reutilizada a renderização do chat em `frontend/app.py`, agora com dados brutos em áreas expansíveis.
- Não foram alterados login, sessão, noVNC token, Browserless, `manual_confirmation`, validação de página errada nem fluxo guiado, exceto pela apresentação final do resultado.

## Causa da resposta confusa

Quando a extração capturava o texto visível inteiro da tela final, menus e rótulos de formulário eram salvos como um campo único em `dados_extraidos`, por exemplo `texto_tela_final`.

O fallback determinístico tratava esse bloco como um resultado real e montava:

`Consulta concluída. Encontrei: Texto tela final: ...`

Isso fazia o chat exibir DOM/texto bruto com menus, filtros e navegação, apesar da execução estar correta.

## Comportamento final

- Campos pequenos e úteis continuam aparecendo diretamente: cliente, grupo, cota, status, valor e vencimento.
- Texto grande/ruidoso é compactado e classificado antes de virar resposta.
- Tela que parece formulário/filtro passa a ser descrita como formulário/filtro sem resultado listado.
- Arquivos em `downloaded_files` ou `main_file` geram mensagem operacional de arquivo disponível.
- Quando nada foi configurado para retorno, a resposta permanece objetiva e não despeja payload bruto.

## Uso de IA e controle de custo

- A IA é chamada somente quando há dados extraídos ou arquivo e `ai_result_summary_enabled` está ativo.
- Usa `OPENAI_MODEL` do ambiente, sem hardcode de modelo caro.
- O contexto enviado é limitado a 8k caracteres.
- O texto é sanitizado e deduplicado antes do prompt.
- Não envia screenshots nem imagens.
- O prompt instrui a IA a usar apenas dados extraídos, não inventar, ignorar menus e não expor detalhes técnicos.
- A resposta da IA é rejeitada se contiver termos técnicos, tokens, credenciais, seletores, URLs ou caminhos locais.

## Fallback determinístico

- Sem OpenAI, com OpenAI desativado, erro ou timeout, usa fallback determinístico.
- O fallback remove repetição/ruído e não mostra texto bruto longo.
- Para tela final sem resultado claro, retorna:

`Ação executada com sucesso. A tela final foi aberta, mas não foi possível identificar um resultado específico configurado.`

## Arquivos alterados

- `backend/services/operational_summary.py`
- `backend/services/action_runner.py`
- `backend/schemas/runs.py`
- `backend/agente.py`
- `frontend/app.py`
- `tests/test_operational_summary.py`

## Testes executados

- `python3 -m compileall backend frontend scripts` - passou.
- `docker compose -f docker-compose.test.yml --env-file .env.test up -d --build` - passou.
- `docker compose -f docker-compose.test.yml --env-file .env.test ps` - containers ativos; desktop browser saudável.
- `curl -sS http://127.0.0.1:8100/health` - `{"status":"ok","service":"cotasync"}`.
- `docker exec cotasync_test_backend python -m unittest tests.test_operational_summary tests.test_guided_learning_outputs tests.test_desktop_action_runner` - 30 testes passaram.
- `docker exec cotasync_test_backend python scripts/test_desktop_browser_connection.py` - passou.
- `docker exec cotasync_test_backend python scripts/test_demo_v01_cycle.py` - falhou fora do caminho alterado: timeout aguardando `#pedido-status` mudar após `/operator/click` retornar 200 no alvo local Browserless.
- `bash scripts/test_actions_runs_contract.sh` - falhou por assert legado sensível a caixa procurando `"Nenhum"` com N maiúsculo, enquanto a frase operacional contém `"nenhum"` no meio da sentença.

## Passos manuais de demo

1. Abrir o painel em `http://localhost:3100`.
2. Configurar uma ação com retorno por texto visível da tela final e `usar IA só para resumir resultado`.
3. Executar a ação aprendida.
4. Conferir que o chat principal mostra somente a resposta operacional limpa.
5. Abrir `Ver dados extraídos` para ver o conteúdo bruto capturado.
6. Abrir `Ver JSON/result_payload` para inspecionar payload técnico quando necessário.
7. Se houver arquivo baixado, usar o botão `Baixar arquivo gerado`.

## Limitações

- A classificação determinística de formulário/filtro é heurística; telas muito específicas podem precisar de labels de extração melhores.
- O resumo por IA depende de `OPENAI_API_KEY` e do modelo configurado em `OPENAI_MODEL`.
- Dados úteis escondidos dentro de grandes blocos de texto podem exigir ajuste de alvo de extração para máxima precisão.
- O script `test_demo_v01_cycle.py` apresentou instabilidade no operador Browserless durante esta execução.

## Recomendações para produção

- Configurar targets de extração específicos para campos de negócio, evitando depender de texto visível completo.
- Medir taxa de `summary_source=ai` versus `deterministic` em runs reais.
- Adicionar métrica de tamanho de `dados_extraidos` para detectar telas ruidosas recorrentes.
- Ajustar `scripts/test_actions_runs_contract.sh` para comparar mensagem sem sensibilidade a caixa ou por código/estado.
- Investigar o timeout do operador Browserless no ciclo demo, isolando sessão, target e evento de click.
