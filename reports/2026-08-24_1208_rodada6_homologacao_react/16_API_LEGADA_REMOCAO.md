# API Legada Remoção

Endpoints legados auditados: `/api/clients`, `/api/actions`, `/api/batches`, `/api/browser`, `/api/desktop-browser`, `/api/demo`, `/api/runs`.

Consumidores encontrados: `frontend/` Streamlit, scripts de smoke/contrato e `scripts/test_desktop_browser_connection.py` ainda usam endpoints legados, especialmente `/api/demo` e `/api/actions/{id}/run`.

Decisão: não remover API HTTP legada nesta rodada porque o Streamlit não foi removido e scripts operacionais ainda dependem dela.

Estado final: React usa `/api/v1`; legado permanece por consumidor real identificado.
