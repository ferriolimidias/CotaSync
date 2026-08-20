# Migração JSON -> PostgreSQL

Dry-run:
- clients: 4
- actions: 2
- runs: 31
- batches: 1
- action_steps: 16
- batch_items: 4
- schedules: 0
- extraction_contracts planejados: 2

Apply:
- idempotente em duas execuções seguidas.
- sem erros de FK após os ajustes.

Conclusão: o importador migra os dados operacionais atuais sem duplicar registros.
Evidência: `scripts/migrate_json_to_postgres.py --dry-run` e `--apply`.
Estado: validado.
Impacto: a carga inicial do banco pode ser repetida com segurança.
