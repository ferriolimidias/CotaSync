# Auth CSRF

Auth real: `POST /api/v1/auth/login`, `GET /api/v1/auth/me`, `POST /api/v1/auth/logout`.

Sessão: cookie HttpOnly. Token de sessão não é armazenado em `localStorage` nem `sessionStorage`.

CSRF: token retornado no login fica em memória; em reload é restaurado do cookie `cotasync_csrf`. Teste HTTP: `me=admin`, logout com `X-CSRF-Token` retornou `200`.

Contexto: Rodada 5 importou `/home/joseadmin/front.zip` para `frontend-react/`, preservando o Streamlit em `frontend/` durante a transição.

