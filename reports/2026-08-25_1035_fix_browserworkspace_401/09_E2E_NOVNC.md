# E2E noVNC

Execucao:
- Base URL: `https://cotasync.ferriolimidias.com.br`.
- Sessao CotaSync temporaria criada em memoria.
- Container efemero Playwright usado para nao instalar dependencias no host.

Resultado:
- `react-e2e-smoke-ok`.

Cobertura relevante:
- Navegacao por Dashboard, Clientes, Acoes, Ensinar acao, Execucao, Relatorios, Configuracoes, Agendamentos e Diagnostico.
- Em Configuracoes, clica `Abrir navegador` ou `Renovar acesso`.
- Verifica iframe `Navegador CotaSync`.
- Falha para `401 Authorization Required`, `403`, `502` e pagina de erro Nginx.
- Falha para chamadas operacionais legacy.

Observacao:
- noVNC solicita `/package.json` e recebe `404 File not found`; essa requisicao auxiliar foi documentada e ignorada explicitamente no E2E porque nao representa falha de autorizacao nem fluxo operacional.

