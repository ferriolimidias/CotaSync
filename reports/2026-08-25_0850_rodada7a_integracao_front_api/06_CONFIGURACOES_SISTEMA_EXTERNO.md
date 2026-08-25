# Configurações Sistema Externo

Endpoint principal: `GET /api/v1/external-session/status`.

Semântica corrigida:
- Sistema externo configurado: nome + URL de login presentes.
- Login configurado: URL de login presente.
- Sessão externa: estado de sessão; agora `unknown` quando há configuração sem validação viva.
- Login: modo manual.

Fonte de verdade: PostgreSQL tabela `external_systems` via `backend/services/external_systems.py`.

Evidência:
- Tela: Configurações.
- Elemento: Sistema externo.
- Sintoma: nome vazio/login não configurado enquanto Dashboard dizia autenticado.
- Request: `GET /api/v1/external-session/status`.
- Response antiga: não tinha `session_status` nem `external_system_configured`.
- Causa: conceitos diferentes apresentados sem distinção.
- Correção: campos separados e UI somente leitura clara.
- Teste: compilação Python OK; endpoint real autenticado não testado sem credenciais.
- Resultado: corrigido em código.
