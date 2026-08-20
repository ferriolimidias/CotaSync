# API V1 Learning e Browser

Arquivo: `backend/api/v1.py`
Função/endpoint: `/api/v1/learning/*`
Antes: frontend teria que conhecer `/api/demo/*`.
Depois: fachada v1 cria sessão, consulta estado, grava, para, publica ação e opera campo ativo.
Motivo: remover dependência técnica do nome demo.
Impacto: `DemoSessionManager` permanece implementação interna.
Teste: `GET /api/v1/learning/capabilities`.
Resultado: 200.
Risco restante: nem todo fluxo visual foi exercitado ponta a ponta nesta rodada.

Arquivo: `backend/api/v1.py`
Função/endpoint: `/api/v1/browser/status`, `/view-token`, `/ensure-ready`
Antes: browser dividido entre `/api/browser` e `/api/desktop-browser`.
Depois: fachada v1.
Motivo: contrato limpo para BrowserWorkspace.
Impacto: CDP continua interno; token noVNC tem TTL curto.
Teste: `test_browser_external_session_and_learning_contracts`.
Resultado: 200.
