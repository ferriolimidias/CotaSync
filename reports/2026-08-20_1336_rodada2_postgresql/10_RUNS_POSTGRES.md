# Runs

Fonte migrada: 31 runs.

Estado atual no banco após a suíte e smoke: 38 runs.

Conclusão: o repositório de runs opera em PostgreSQL, mas a validação automática adicionou runs de teste no banco compartilhado.
Evidência: `backend/services/runs_repository.py`, consulta direta no banco, suíte `168 OK`.
Estado: funcional com ruído de validação.
Impacto: o número atual do banco não bate mais com a origem histórica, embora a migração original tenha preservado os 31 registros.
