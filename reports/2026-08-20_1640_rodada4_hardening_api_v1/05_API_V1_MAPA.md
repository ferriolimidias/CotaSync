# API V1 Mapa

Arquivo: `backend/api/v1.py`
Função/endpoint: router `/api/v1`
Antes: APIs oficiais estavam espalhadas entre `/api/*` e `/api/demo/*`.
Depois: fachada REST oficial sob `/api/v1`.
Motivo: o frontend React não deve depender de nomes históricos.
Impacto: OpenAPI contém os contratos v1.
Teste: `/openapi.json`.
Resultado: `openapi-ok 81 True True`.
Risco restante: endpoints antigos permanecem para Streamlit.

Mapa:
- `/api/v1/auth`: preservado em `backend/api/auth.py`.
- `/api/v1/dashboard`
- `/api/v1/clients`
- `/api/v1/actions`
- `/api/v1/learning`
- `/api/v1/browser`
- `/api/v1/external-session`
- `/api/v1/batches`
- `/api/v1/worker`
- `/api/v1/reports`
- `/api/v1/diagnostics`
