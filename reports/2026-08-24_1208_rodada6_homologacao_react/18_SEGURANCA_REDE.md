# Segurança Rede

Compose ativo:
- Backend: `127.0.0.1:8100 -> 8000`.
- React: `127.0.0.1:3300 -> 3000`.
- Streamlit: `127.0.0.1:3100 -> 8501`.
- noVNC: `127.0.0.1:3200 -> 6080`.
- CDP: `127.0.0.1:9222 -> 9222`.
- PostgreSQL: sem porta publicada no compose.

Observação: `ss` no host mostrou listeners `0.0.0.0:3000` e `0.0.0.0:8000` externos ao mapeamento dos containers de teste; precisam ser auditados fora do escopo do compose antes de hardening de produção.

Porta 5900: não apareceu publicada pelo compose.
