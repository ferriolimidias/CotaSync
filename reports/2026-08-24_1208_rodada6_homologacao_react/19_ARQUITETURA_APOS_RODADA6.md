# Arquitetura Após Rodada 6

React/TanStack Start em `frontend-react/` conversa exclusivamente com `/api/v1`.

FastAPI `/api/v1` agora cobre CSV preview/import/export, runs individuais, relatórios CSV, batches e browser/learning/session.

Worker persistente, PostgreSQL, desktop browser, CDP/Playwright e noVNC permanecem como na Rodada 5.

Streamlit e API legada permanecem porque a homologação real externa ainda não passou.
