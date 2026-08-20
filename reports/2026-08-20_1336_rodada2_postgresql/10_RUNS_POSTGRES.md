# Runs

Fonte migrada: 31 runs.

Estado atual no banco após a suíte e smoke: 40 runs.

Conclusão: o repositório de runs opera em PostgreSQL, e a suíte isolada já não polui o banco operacional.
Evidência: `backend/services/runs_repository.py`, consulta direta no banco, suíte `168 OK` no banco isolado e contagem operacional estável em 40.
Estado: funcional.
Impacto: os 31 runs históricos permanecem preservados e os artefatos de validação ficaram separados.
