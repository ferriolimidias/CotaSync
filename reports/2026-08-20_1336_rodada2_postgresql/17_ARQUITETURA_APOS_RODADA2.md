# Arquitetura Após Rodada 2

Fluxo operacional principal:
`FastAPI -> PostgreSQL -> serviços CotaSync -> BrowserController -> desktop_browser_replay -> CDP / Playwright / Chromium`

Conclusão: o BrowserController existe e é fino; o replay segue funcional.
Evidência: `backend/services/browser_controller.py`, `backend/services/action_runner.py`, smoke do desktop browser.
Estado: alinhado com a direção pretendida.
Impacto: a rodada prepara a próxima camada de worker sem reescrever o motor de browser.
