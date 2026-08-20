# Mapa de Persistência

| Recurso | Antes | Depois |
| --- | --- | --- |
| users | env/bootstrapping | PostgreSQL |
| clients | JSON | PostgreSQL |
| actions | JSON | PostgreSQL |
| action_versions | inexistente | PostgreSQL |
| action_steps | JSON embutido | PostgreSQL |
| extraction_contracts | JSON embutido | PostgreSQL |
| runs | JSON | PostgreSQL |
| batches | JSON | PostgreSQL |
| batch_items | inexistente | PostgreSQL |
| schedules | JSON legado | PostgreSQL para persistência; scheduler novo ainda não |
| browser profile | volume/arquivo | permanece fora do banco |
| cookies/storage | arquivo do browser | permanece fora do banco |
| screenshots | arquivo | permanece fora do banco |

Conclusão: a persistência operacional primária saiu dos JSONs de catálogo, runs e batches.
Evidência: contagens migradas e consultas diretas no banco.
Estado: concluído para o núcleo operacional.
Impacto: o aplicativo já lê/escreve o caminho principal no PostgreSQL.
