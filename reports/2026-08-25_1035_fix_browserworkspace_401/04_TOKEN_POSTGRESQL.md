# Token PostgreSQL

Tabela: `desktop_view_tokens`.

Schema observado:
- `digest`: chave primaria.
- `purpose`: escopo logico do token.
- `created_at`: criacao UTC.
- `expires_at`: expiracao UTC indexada.

Implementacao:
- Criacao: `backend/services/desktop_view_tokens.py::create_token`.
- Validacao: `backend/services/desktop_view_tokens.py::validate_token`.
- Limpeza: tokens expirados sao removidos durante criacao e quando encontrados invalidos.

Seguranca:
- O token claro nao e persistido.
- Persistencia usa digest SHA-256.
- Formato aceito: token URL-safe com 43 caracteres.
- TTL atual validado: `1800` segundos.

