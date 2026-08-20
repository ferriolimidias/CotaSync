# Validação de Dados

Contagens atuais no banco:
- users: 2
- clients: 4
- actions: 2
- action_versions: 2
- action_steps: 16
- extraction_contracts: 2
- runs: 40
- batches: 1
- batch_items: 4
- schedules: 0

Conclusão: a carga histórica principal foi preservada e o banco operacional manteve a contagem estável durante a suíte isolada.
Evidência: consultas diretas ao PostgreSQL antes/depois da suíte e do smoke.
Estado: validado.
Impacto: a comparação histórica continua baseada nos 31 runs migrados.
