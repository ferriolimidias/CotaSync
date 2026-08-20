# OpenAPI e Frontend Contract

Arquivo: `docs/frontend_api_contract.md`
Função/endpoint: documentação do contrato frontend.
Antes: inexistente.
Depois: documenta endpoints, auth, CSRF, erros, polling, noVNC e learning.
Motivo: próxima rodada importará frontend real.
Impacto: frontend React tem contrato inicial.
Teste: arquivo criado e OpenAPI validado.
Resultado: `/openapi.json` parseado como JSON; contém v1.
Risco restante: contrato pode evoluir na integração real.

OpenAPI:
- comando: `curl http://127.0.0.1:8100/openapi.json`.
- resultado: `openapi-ok 81 True True`.
