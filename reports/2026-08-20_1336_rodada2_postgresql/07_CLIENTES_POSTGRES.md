# Clients

Contagem no banco: 4.

Campos principais persistidos: `name`, `client_group`, `active`, `grupo`, `cota`, `versao`, `variables`, `notes`.

Conclusão: clientes migraram do JSON para PostgreSQL com aliases preservados na camada de resolução.
Evidência: `backend/services/clients_repository.py` e contagem do banco.
Estado: concluído.
Impacto: leitura e escrita operacionais já passam pelo banco.
