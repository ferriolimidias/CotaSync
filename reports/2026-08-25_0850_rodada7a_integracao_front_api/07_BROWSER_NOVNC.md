# Browser noVNC

Endpoints:
- `GET /api/v1/browser/status`.
- `POST /api/v1/browser/ensure-ready`.
- `POST /api/v1/browser/view-token`.

Correções:
- `BrowserWorkspace` agora distingue Verificando, Pronto, Abrindo, Offline, Indisponível e Erro.
- Mutations emitem toast real somente após sucesso/erro.
- `ensure-ready` invalida `browser` antes de emitir token.
- Token não é impresso no relatório.

Evidência:
- Tela: Configurações/Ensinar ação.
- Elemento: Navegador do sistema externo.
- Sintoma: `Verificando navegador...` podia ficar como estado visual principal após falha.
- Request: `GET /api/v1/browser/status`.
- Response local: browser offline por CDP indisponível.
- Causa: UI só verificava `status.data`.
- Correção: estados derivados de `isLoading`, erros e health.
- Teste: `py_compile` OK; E2E bloqueado por `node` ausente.
- Resultado: corrigido em código.
