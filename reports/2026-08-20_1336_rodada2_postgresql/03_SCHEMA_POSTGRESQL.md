# Schema PostgreSQL

Tabelas criadas: `users`, `clients`, `actions`, `action_versions`, `action_steps`, `extraction_contracts`, `runs`, `batches`, `batch_items`, `schedules`, `external_systems`, `desktop_view_tokens`.

Relações principais:
- `actions` -> `action_versions` via `published_version_id`.
- `action_versions` -> `actions` via `action_id`.
- `action_steps` -> `action_versions` via `action_version_id`.
- `extraction_contracts` -> `action_versions` via `action_version_id`.
- `runs` -> `actions`, `action_versions`, `clients`, `batches`.
- `batches` -> `actions`, `action_versions`.
- `batch_items` -> `batches`, `clients`, `runs`.
- `schedules` -> `actions`.

Conclusão: o modelo já separa versão publicada, passos e contratos de extração.
Evidência: migration `alembic/versions/0001_operational_schema.py` e `alembic current`.
Estado: pronto para evolução sem sobrescrever a ação publicada.
Impacto: permite versionamento e rastreio por passo.
