# Compose React

Serviço adicionado: `cotasync_test_frontend_react`.

Porta: `127.0.0.1:3300 -> 3000`.

Build: `frontend-react/Dockerfile`. Staging usa Bun/TanStack runtime com `serve.mjs` para SSR/assets e proxy `/api` para `cotasync_test_backend:8000`. Streamlit permanece em `3100`.

Contexto: Rodada 5 importou `/home/joseadmin/front.zip` para `frontend-react/`, preservando o Streamlit em `frontend/` durante a transição.

