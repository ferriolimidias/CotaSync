# Fast-track: Auditoria e Remocao

## Decisao

Fast-track foi removido do codigo ativo. Nenhuma dependencia operacional real foi encontrada; runs historicos nao foram tratados como dependencia.

## Auditoria antes da remocao

Referencias encontradas estavam concentradas em:

- `backend/services/action_runner.py`
- `backend/agente.py`
- `backend/motor_browser.py`
- testes de execucao antiga
- payloads/flags diagnosticas novas

Nao foi encontrada acao ativa que exigisse fast-track. O caminho comprovado e preservado e `desktop_browser_replay`.

## Alteracoes concretas

Arquivo: `backend/services/action_runner.py`
Funcao/servico: decisao de runner para acoes.
Como era: podia cair em branch legado fast-track/fallback.
Como ficou: suporta fixture local, replay de demo session quando ha sessao explicita, e replay desktop aprendido.
Por que foi alterado: fast-track era arquitetura abandonada e mascarava a necessidade de replay desktop.
O que foi removido: branch fast-track e flag `whether_fast_track_used` em novos payloads.
Dependencias removidas: import de funcao fast-track.
Impacto: acoes antigas sem passos desktop falham com mensagem explicita.
Teste realizado: `tests/test_desktop_action_runner.py`, suite completa, smoke real.
Resultado: 164 testes OK; replay real `desktop_browser_replay` OK.
Risco restante: migracao de eventual dado historico antigo deve ser feita manualmente na Rodada 2, se aparecer.

Arquivo: `backend/agente.py`
Funcao/servico: chamada direta de acao conhecida.
Como era: nomenclatura e funcao apontavam para fast-track.
Como ficou: funcao renomeada para replay desktop e logs alinhados.
Por que foi alterado: remover conceito legado do fluxo ativo.
O que foi removido: semantica fast-track no caminho de execucao.
Impacto: usuario final continua executando acao conhecida; arquitetura interna nao usa fallback.
Teste realizado: suite completa.
Resultado: OK.
Risco restante: nenhum uso ativo identificado.

Arquivo: `backend/motor_browser.py`
Funcao/servico: motor mecanico Playwright/CDP.
Como era: logs e payloads usavam nome fast-track em parte do caminho.
Como ficou: logs/payloads usam `desktop_browser_replay`; `whether_desktop_browser_used=True`.
Por que foi alterado: alinhar telemetria ao unico mecanismo suportado.
O que foi removido: textos e flags fast-track.
Impacto: novos runs nao carregam indicador inutil de fast-track.
Teste realizado: smoke real.
Resultado: `runner=desktop_browser_replay`, `status=success`.
Risco restante: campos antigos podem existir em runs historicos fora do commit.

## Provas finais

- Busca em codigo ativo: `rg -n -i "fast_track|legacy_fast|whether_fast_track_used"` nao retornou ocorrencias nos caminhos ativos.
- Teste real: `run_id=d6caf738-4c26-403d-ad1f-5a5445b5bd23`, `runner=desktop_browser_replay`, `whether_desktop_browser_used=True`, `status=success`.

