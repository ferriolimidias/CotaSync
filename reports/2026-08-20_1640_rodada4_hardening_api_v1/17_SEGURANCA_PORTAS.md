# Segurança Portas

Teste:
`sudo -n ss -ltnp`

Resultado relevante:
- `3010`: inexistente.
- `5900`: não público.
- `9222`: `127.0.0.1:9222`.
- `3200`: `127.0.0.1:3200`.
- `3100`: `127.0.0.1:3100`.
- `8100`: `127.0.0.1:8100`.
- PostgreSQL não exposto no host como `5432`.
- Worker sem bind de porta pública.

Risco restante:
Há portas `0.0.0.0:8000` e `0.0.0.0:3000` de outros containers/processos existentes no host; não foram introduzidas pela Rodada 4.
