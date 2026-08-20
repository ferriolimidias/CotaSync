# Repositories JSON Removidos do Fluxo Operacional

Removidos do caminho normal:
- `clients_repository` para leitura/escrita padrão
- `actions_repository` para catálogo padrão
- `runs_repository` para gravação/leitura padrão
- `result_selection` e `action_validation_review` para persistência padrão
- `external_systems` para persistência padrão

Ainda presentes como legado/apoio de teste:
- `backend/agente.py`
- `backend/demo_session.py`
- `backend/main.py` em agendamentos legados
- scripts de reset e alguns testes que usam fixtures temporárias JSON

Conclusão: o fluxo operacional principal já não depende de JSON, mas ainda sobra legado auxiliar fora do núcleo.
Evidência: busca `rg` e execução da suíte com modo legado apenas para testes.
Estado: parcial.
Impacto: remanescente para saneamento futuro.
