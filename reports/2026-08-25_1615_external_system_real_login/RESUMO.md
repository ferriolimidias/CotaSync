# Fluxo definitivo do sistema externo real

Data: 2026-08-25

## Fluxo anterior

- A rota dedicada do navegador criava automaticamente uma sessão de aprendizado/controle.
- Quando não havia `external_login_url` configurada no PostgreSQL, essa sessão caía no alvo demo `cotasync_test_backend:8000/demo/alvo`.
- A página Configurações não tinha formulário persistente v1 para cadastrar o sistema externo real.
- Havia duplicidade conceitual entre abrir navegador e abrir sessão para login.
- O OperatorAssistant aparecia no workspace normal de Configurações/Navegador.

## Fluxo novo

- `/configuracoes` possui formulário persistente para:
  - Nome do sistema;
  - URL de login;
  - Usuário / identificador;
  - Host esperado após login em seção avançada.
- O formulário salva em PostgreSQL via `/api/v1/external-system/config`.
- `Abrir sessão para login` chama `/api/v1/external-session/open-login`.
- O backend valida a configuração, conecta ao Chromium persistente via CDP e navega para a URL de login salva, preservando a URL integral.
- Após abrir login, o React navega para `/configuracoes/navegador`.
- `/configuracoes/navegador` abre o noVNC automaticamente e mostra `Renovar acesso` apenas para renovar o token de visualização.
- O workspace normal não renderiza OperatorAssistant; a digitação de login/senha/MFA deve ocorrer diretamente no noVNC.
- O OperatorAssistant permanece disponível em `/ensinar-acao` para variáveis e aprendizado.

## Persistência

- Fonte de verdade da configuração: PostgreSQL, tabela `external_systems`, campo JSONB `config`.
- Perfil persistente do Chromium: volume Docker `cotasync_test_desktop_browser_profile`, montado em `/data/profile`.
- Cookies/storage do sistema externo permanecem no perfil do Chromium enquanto o sistema externo os considerar válidos.

## O que não é persistido

- Senha do sistema externo.
- Segredo MFA, OTP ou aprovação de celular.
- Tokens/cookies do sistema externo em PostgreSQL.
- Token temporário noVNC no relatório.

## Validações mínimas

- `python -m py_compile backend/api/v1.py backend/services/external_systems.py`: OK.
- `bun run typecheck`: OK.
- `bun run build`: OK.
- React local `/configuracoes`: 200.
- React público `/configuracoes`: 200.
- API local `/api/v1/auth/me` sem cookie: 401 esperado.
- Consulta autenticada de `/api/v1/external-session/status`: configuração vazia e `not_configured`.
- Consulta autenticada de `/api/v1/external-system/config`: campos vazios, sem fallback demo/histórico.

## Deploy

- Backend recriado para carregar os endpoints v1 e a navegação CDP.
- React reconstruído e recriado porque o source não é montado no container React.
- Não foram executados E2E demo, pytest completo, batches, actions ou learning real.
