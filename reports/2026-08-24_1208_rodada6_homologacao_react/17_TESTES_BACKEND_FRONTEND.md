# Testes Backend Frontend

Frontend:
- `bun run typecheck`: OK.
- `bun run lint`: OK, 0 erros, 7 warnings Fast Refresh herdados.
- `bun run build`: OK.

Backend:
- suíte completa: `187 passed`, 1 warning Starlette/httpx.
- testes novos: CSV preview/import/export, conflitos de aliases, alias de resultados batch, detalhe de run e reports CSV.

Banco: antes da suíte completa/E2E `operational=10`; depois `operational=10`. Testes automatizados não poluíram runs operacionais.
