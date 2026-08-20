# API V1 Auth e Dashboard

Arquivo: `backend/api/auth.py`
Função/endpoint: `/api/v1/auth/login`, `/logout`, `/me`
Antes: já existiam.
Depois: preservados para cookie HttpOnly e CSRF.
Motivo: frontend futuro usa cookie, não localStorage.
Impacto: contrato documentado.
Teste: `test_auth_v1_uses_cookie_session`.
Resultado: login 200, cookie HttpOnly, me 200.
Risco restante: CSRF token ainda é retornado no body de login.

Arquivo: `backend/api/v1.py`
Função/endpoint: `GET /api/v1/dashboard`
Antes: inexistente.
Depois: retorna sessão, clientes ativos, ações prontas, runs do dia, last_run, worker, fila e alerts.
Motivo: reduzir chamadas iniciais do dashboard.
Impacto: não expõe segredos.
Teste: `test_dashboard_clients_actions_reports_and_worker_contracts`.
Resultado: 200.
