# Auth, CSRF e HTTPS

Auditoria:

- Auth usa cookie de sessao `HttpOnly`.
- Cookie CSRF separado fica legivel pelo frontend para envio em `X-CSRF-Token`.
- `credentials: "include"` esta configurado no cliente HTTP do frontend.
- Middleware do backend exige CSRF para metodos mutaveis sob `/api/`, exceto endpoints publicos definidos.
- CSRF nao foi desabilitado.

Acao:

- `.env.test` passou a definir `COTASYNC_COOKIE_SECURE=true` para homologacao HTTPS.

Cookies esperados em HTTPS:

- Sessao: `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`.
- CSRF: `Secure`, `SameSite=Lax`, `Path=/`, nao `HttpOnly` para permitir o header CSRF.
- `Domain` nao e definido explicitamente, ficando host-only.

