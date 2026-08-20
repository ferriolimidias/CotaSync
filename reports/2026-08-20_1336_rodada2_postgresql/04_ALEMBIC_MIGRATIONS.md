# Alembic

Arquivos:
- `alembic.ini`
- `alembic/env.py`
- `alembic/script.py.mako`
- `alembic/versions/0001_operational_schema.py`

Conclusão: a árvore do Alembic existe e o banco sobe com `alembic upgrade head`.
Evidência: `alembic current` retornou `0001_operational_schema (head)`.
Estado: saudável.
Impacto: o schema ficou reproduzível a partir de migrações.
