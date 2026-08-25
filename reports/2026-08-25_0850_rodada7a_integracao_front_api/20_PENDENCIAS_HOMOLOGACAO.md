# Pendências Homologação

P0:
- Validar manualmente no domínio real com sessão admin segura: Dashboard, Configurações, Navegador, Clientes e Ações.

P1:
- Implementar validação viva de sessão externa no backend, usando browser persistente para classificar autenticada/expirada/offline quando o operador solicitar.
- Formalizar se `external_session/status` deve continuar conservador (`unknown`) ou chamar classificação ativa do browser sob demanda.

P2:
- Criar endpoint administrativo persistente para editar configurações operacionais se a UI deixar de ser somente leitura.
- Formalizar enum de status de ação no OpenAPI.

OPERATOR_ACTION_REQUIRED:
- URL: https://cotasync.ferriolimidias.com.br
- Validar manualmente: Dashboard, Configurações, Navegador, Clientes, Ações.
- Não iniciar learning real até essa validação.
