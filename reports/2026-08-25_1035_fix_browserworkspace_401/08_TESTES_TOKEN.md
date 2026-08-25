# Testes Token

Testes automatizados adicionados:
- `tests/test_desktop_view_tokens.py::test_v1_validation_accepts_header_without_cotasync_session`.
- `tests/test_api_v1_contract.py::test_browser_external_session_and_learning_contracts` valida tambem o endpoint v1 por header.

Resultados manuais tecnicos sem expor token:
- `POST /api/v1/browser/view-token`: `200`, TTL `1800`.
- `GET /api/v1/browser/validate-view-token` com header valido: `204`, body vazio.
- `GET /api/v1/browser/validate-view-token` com token aleatorio: `401`.
- Validacao de expirado: coberta por `tests/test_desktop_view_tokens.py::test_expired_token_fails`.

Resultado da suite:
- Backend completo: `188 passed, 1 warning`.

