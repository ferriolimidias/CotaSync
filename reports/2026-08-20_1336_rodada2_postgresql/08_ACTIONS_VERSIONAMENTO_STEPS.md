# Actions, Versions e Steps

Contagem no banco:
- actions: 2
- action_versions: 2
- action_steps: 16

Cada ação atual virou `v1` publicada:
- `quantidade-de-parcelas` -> `quantidade-de-parcelas-v1`
- `quantidade-de-parcelas-2` -> `quantidade-de-parcelas-2-v1`

Conclusão: o produto ganhou versionamento explícito sem sobrescrever a ação publicada.
Evidência: `backend/db.py`, migration e consulta direta no banco.
Estado: funcional.
Impacto: correções futuras podem nascer em nova versão.
