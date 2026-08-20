# API V1 Clients e Actions

Arquivo: `backend/api/v1.py`
Função/endpoint: `/api/v1/clients`
Antes: clientes existiam em `/api/clients`.
Depois: fachada v1 com `GET`, `POST`, `GET {id}`, `PATCH`, `DELETE` desativando.
Motivo: contrato estável para frontend.
Impacto: preserva `grupo`, `cota`, `versao`, `variables`, `group`, `active`, `notes`.
Teste: contrato v1.
Resultado: 200 em listagem.
Risco restante: import CSV segue no endpoint antigo por compatibilidade.

Arquivo: `backend/api/v1.py`
Função/endpoint: `/api/v1/actions`, `/api/v1/actions/{id}`, `/versions`
Antes: ações existiam em `/api/actions`.
Depois: v1 expõe action, versão publicada, last_run e needs_attention.
Motivo: separar UX normal de diagnóstico técnico.
Impacto: não expõe DOM/raw JSON como caminho principal.
Teste: contrato v1 e OpenAPI.
Resultado: OK.
