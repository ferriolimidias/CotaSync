# Loading Error Cache

Loading:
- BrowserWorkspace passou a distinguir loading, erro, offline, indisponível e pronto.
- Queries de sessão/browser usam retry limitado.

Error handling:
- `apiFetch` central trata timeout, 401, 403, 409, browser unavailable e login URL ausente.

Cache:
- Configurações invalida `external-session`, `browser` e `dashboard` após abrir login.
- Validar sessão invalida `external-session` e `dashboard`.
- Clientes já invalidava `clients` e `dashboard`.
- Execução já invalidava `reports`, `batches` e `dashboard`.

Status: corrigido nos fluxos auditados.
