# Arquitetura Após Correções

Fluxo preservado:

React
↓
Nginx same-origin
↓
FastAPI `/api/v1`
↓
PostgreSQL
↓
Worker persistente
↓
desktop_browser_replay
↓
Chromium persistente / noVNC

Mudança relevante:
- Backend v1 agrega status externo de forma conservadora a partir de PostgreSQL.
- Frontend não trata `authenticated` como verdade quando não há validação viva.
- Labels técnicos centralizados em `frontend-react/src/lib/status-labels.ts`.
- `data/external_systems/current.json` não foi reintroduzido como fonte runtime.
