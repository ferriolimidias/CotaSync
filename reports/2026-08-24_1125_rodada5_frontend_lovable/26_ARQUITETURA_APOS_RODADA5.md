# Arquitetura Após Rodada 5

React/Lovable integrado -> `/api/v1` -> FastAPI -> PostgreSQL -> Worker persistente -> BrowserController/execution services -> desktop_browser_replay -> CDP/Playwright -> Chromium persistente.

Staging React: `127.0.0.1:3300` com proxy same-origin `/api`. Streamlit fallback: `127.0.0.1:3100`. noVNC segue via token curto da API.

Contexto: Rodada 5 importou `/home/joseadmin/front.zip` para `frontend-react/`, preservando o Streamlit em `frontend/` durante a transição.

