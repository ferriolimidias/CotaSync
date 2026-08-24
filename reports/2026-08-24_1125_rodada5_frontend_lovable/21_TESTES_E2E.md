# Testes E2E

Playwright smoke em container: login real via React staging, dashboard e rotas `/clientes`, `/acoes`, `/execucao`, `/ensinar-acao`, `/relatorios`, `/configuracoes`, `/diagnostico`, `/agendamentos`.

Resultado: `playwright-smoke-ok`. Screenshots em `screenshots/`. Único erro de console: `401` esperado do `auth/me` antes do login.

Contexto: Rodada 5 importou `/home/joseadmin/front.zip` para `frontend-react/`, preservando o Streamlit em `frontend/` durante a transição.

