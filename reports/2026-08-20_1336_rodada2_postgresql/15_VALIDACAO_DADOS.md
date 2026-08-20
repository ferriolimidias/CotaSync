# Validação de Dados

Contagens atuais no banco:
- users: 2
- clients: 4
- actions: 2
- action_versions: 2
- action_steps: 16
- extraction_contracts: 2
- runs: 38
- batches: 1
- batch_items: 4
- schedules: 0

Conclusão: a carga histórica principal foi preservada, mas os testes de validação acrescentaram runs extras no banco compartilhado.
Evidência: consultas diretas ao PostgreSQL.
Estado: validado com ressalva operacional.
Impacto: a diferença de runs precisa ser considerada ao comparar com a fonte histórica.
