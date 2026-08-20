# Padrão de Erros e Paginação

Arquivo: `backend/main.py`
Função/endpoint: `cotasync_http_exception_handler`, `cotasync_auth_middleware`
Antes: v1 recebia `detail` como endpoints antigos.
Depois: `/api/v1/*` retorna `{ "error": { "code": "...", "message": "..." } }`.
Motivo: frontend não interpreta traceback nem strings soltas.
Impacto: endpoints antigos preservados.
Teste: `test_v1_unauthenticated_error_shape`.
Resultado: 401 com `AUTH_REQUIRED`.
Risco restante: exceções não HTTP inesperadas ainda usam handler padrão do FastAPI.

Arquivo: `backend/api/v1.py`
Função/endpoint: `_paginate`
Antes: listas sem contrato comum.
Depois: `page`, `page_size`, `total`, `items`.
Motivo: preparar listas grandes.
Impacto: clients, actions, runs e batches v1.
Teste: contrato v1.
Resultado: OK.
