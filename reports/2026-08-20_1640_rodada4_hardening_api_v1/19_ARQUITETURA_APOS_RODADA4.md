# Arquitetura Após Rodada 4

Fluxo:
React futuro ou Streamlit temporário -> `/api/v1` ou endpoints legados temporários -> services -> PostgreSQL -> CotaSync Worker -> desktop_browser_replay -> CDP/Playwright -> Chromium persistente.

Garantias:
- Worker separado.
- Fila PostgreSQL.
- Advisory lock do browser.
- Recovery real validado com kill de container.
- Idempotência scoped por usuário/operação/key.
- API v1 documentada.
- Endpoints antigos preservados apenas para Streamlit/transição.

Não feito:
- Importar React/Lovable.
- Reescrever BrowserController.
- Implementar scheduler.
- Automatizar senha/MFA.
