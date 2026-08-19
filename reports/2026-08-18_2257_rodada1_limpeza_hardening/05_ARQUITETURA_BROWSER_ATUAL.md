# Arquitetura Browser Atual

## Estado apos a rodada

Arquitetura operacional unica:

```text
CotaSync
FastAPI
desktop_browser
CDP / Playwright
Chromium persistente
noVNC para interacao humana
Sistema externo
```

Nao existe selecao operacional `browserless | desktop_browser`.

## Alteracoes concretas

Arquivo: `backend/services/browser_providers.py`
Funcao/servico: provider interno.
Como era: abstraia mais de um provider e mantinha compatibilidade conceitual com Browserless.
Como ficou: `BrowserMode` so aceita `desktop_browser`; `browser_provider()` retorna o provider desktop.
Por que foi alterado: a arquitetura suportada e unica.
O que foi removido: escolha de provider e fallback.
Impacto: menor complexidade e menos branches.
Teste realizado: `tests/test_browser_providers.py`.
Resultado: OK.
Risco restante: nenhum para fluxo ativo.

Arquivo: `backend/services/browser_controller.py`
Funcao/servico: interface interna de browser.
Como era: operacoes estavam espalhadas por provider/motor/demo session.
Como ficou: foi criado `BrowserController` com `status`, `ensure_ready`, `current_page`, `current_url`, `current_title`, `click`, `fill`, `insert_active`, `clear_active`, `press`, `screenshot`, `replay`, `recover` e `close`.
Por que foi alterado: preparar consolidacao sem reescrever o motor funcional.
O que foi removido: nada nesse arquivo; e uma consolidacao incremental.
Impacto: proxima rodada pode migrar chamadas diretas com menor risco.
Teste realizado: compileall e suite geral.
Resultado: OK.
Risco restante: nem todas as chamadas existentes foram migradas para o controller nesta rodada para evitar refatoracao arriscada.

Arquivo: `frontend/app.py`, `frontend/api_client.py`
Funcao/servico: Streamlit temporario.
Como era: UI exibia selecao/diagnostico de provider.
Como ficou: mostra modo operacional `desktop_browser` e usa API autenticada.
Por que foi alterado: remover escolha inexistente e proteger operacao.
O que foi removido: textos/controles de provider legado.
Impacto: Streamlit continua temporario e funcional.
Teste realizado: suite com testes de frontend helper; compose frontend UP.
Resultado: OK.
Risco restante: frontend React definitivo fica para rodada posterior.

## Validacao real

`scripts/test_desktop_browser_connection.py` autenticou admin via env, validou CDP, noVNC interno, login local demo, gravacao e replay aprendido.

Resultado final:

- `run_id=d6caf738-4c26-403d-ad1f-5a5445b5bd23`
- `runner=desktop_browser_replay`
- `whether_desktop_browser_used=True`
- `status=success`
- `resultado=status_pedido:Enviado`

