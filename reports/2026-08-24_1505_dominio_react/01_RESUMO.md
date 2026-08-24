# Resumo

Objetivo: publicar o frontend React/TanStack Start em `https://cotasync.ferriolimidias.com.br` durante a homologacao, mantendo o Streamlit apenas local em `127.0.0.1:3100`.

Resultado esperado da mudanca:

- `/` no dominio principal proxy para `127.0.0.1:3300`.
- `/api/` no dominio principal proxy para `127.0.0.1:8100`, preservando o prefixo `/api`.
- `desktop-cotasync.ferriolimidias.com.br` mantido para noVNC em `127.0.0.1:3200`.
- CDP em `127.0.0.1:9222` sem exposicao publica direta.

