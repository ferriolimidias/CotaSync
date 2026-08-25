# Seguranca

Estado de rede CotaSync:
- Backend FastAPI: `127.0.0.1:8100`.
- React: `127.0.0.1:3300`.
- Streamlit: `127.0.0.1:3100`.
- noVNC: `127.0.0.1:3200`.
- CDP: `127.0.0.1:9222`.
- PostgreSQL CotaSync: sem porta publicada no host.
- Portas publicas esperadas: Nginx `80/443`.

Validacoes:
- Acesso protegido ao desktop sem token/cookie: `401`.
- Primeiro acesso com token: `200`.
- Acesso seguinte com cookie temporario: `200`.
- Caminho websocket com cookie nao foi negado por autenticacao; resposta observada `404` do app upstream para path testado, nao `401/403`.

Cookie:
- Nome: `cotasync_desktop_view`.
- `Secure`.
- `HttpOnly`.
- `Path=/`.
- `SameSite=Strict`.
- `Max-Age=1800`.

Nao realizado:
- Nao foi removido `auth_request`.
- Nao foi tornado publico o noVNC.
- Nao houve token fixo, hardcoded ou cookie permanente.

