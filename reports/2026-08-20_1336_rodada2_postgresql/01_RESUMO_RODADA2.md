# Resumo Rodada 2

Conclusão: PostgreSQL virou a fonte operacional do CotaSync para `users`, `clients`, `actions`, `action_versions`, `action_steps`, `extraction_contracts`, `runs`, `batches` e `batch_items`.
Evidência: `alembic current` em `0001_operational_schema`; `python -m unittest discover` com `168 OK`; `scripts/migrate_json_to_postgres.py --apply` sem erro e idempotente.
Estado: validado localmente.
Impacto: a persistência principal saiu do JSON e passou para o banco.

Conclusão: a Rodada 2 não ficou totalmente limpa de legado JSON.
Evidência: buscas em `backend/`, `scripts/` e `tests/` ainda encontram rotas auxiliares e legado em `backend/demo_session.py`, `backend/agente.py`, `backend/main.py`, `scripts/reset_demo_catalog.py` e scripts de teste.
Estado: dívida fora do fluxo operacional principal.
Impacto: fica como pendência para a Rodada 3 / limpeza complementar.

Conclusão: o smoke do desktop browser passou.
Evidência: `scripts/test_desktop_browser_connection.py` retornou `status=success` com `runner=desktop_browser_replay`.
Estado: funcional.
Impacto: replay básico continua íntegro após a migração.
