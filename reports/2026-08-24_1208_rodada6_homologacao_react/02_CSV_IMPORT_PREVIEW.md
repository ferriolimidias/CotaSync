# CSV Import Preview

Endpoint: `POST /api/v1/clients/import/preview`.

Contrato: payload JSON com `filename` e `csv_text`, mantendo o fluxo visual de arquivo no React. O React lê o arquivo localmente e a validação oficial ocorre no backend.

Limites: UTF-8, arquivo `.csv`, máximo 1 MB e 1000 linhas.

Headers suportados: `id`, `name`, `group`, `active`, `grupo`, `cota`, `grupo_2`, `versao`, `vers_o`, `grupo_3`, `notes`.

Conflitos: `cota` versus `grupo_2` e `versao` versus `vers_o`/`grupo_3` são reportados no preview quando divergentes; a importação é bloqueada.

Teste: `tests/test_api_v1_contract.py::test_clients_csv_preview_import_and_export_contract` e `test_clients_csv_preview_reports_alias_conflicts` passaram. Smoke HTTP via React/proxy retornou `can_import=True`, `valid=1`, `new=1`.
