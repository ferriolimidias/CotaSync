# Endpoints e Superficie de Ataque

## Regra aplicada

Health minimo pode permanecer publico. Endpoints operacionais sob `/api/*` agora exigem autenticacao por middleware, com protecao CSRF para mutacoes.

## Publicos preservados

- `GET /health`
- `GET /api/health/desktop-browser`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `POST /webhook/evolution`

## Protegidos por autenticacao

Exemplos cobertos:

- execucao de acoes.
- runs.
- batches.
- clientes.
- demo sessions.
- operador browser/noVNC.
- configuracao browser.
- external systems.
- ensino/aprendizado.
- token de visualizacao noVNC.

## Alteracoes concretas

Arquivo: `backend/main.py`
Funcao/servico: middleware HTTP.
Como era: protecao inexistente ou dispersa.
Como ficou: politica padrao de autenticacao para `/api/*`.
Por que foi alterado: nao depender de controles visuais no frontend.
O que foi removido: acesso anonimo por default.
Impacto: APIs criticas retornam 401 sem sessao.
Teste realizado: curl anonimo em `/api/desktop-browser/view-token`; suite auth.
Resultado: 401 anonimo, 200 autenticado.
Risco restante: catalogo formal endpoint-permissao deve ser revisado quando React entrar.

Arquivo: `tests/test_auth_security.py`
Funcao/servico: regressao de auth.
Como era: nao havia testes dedicados.
Como ficou: cobre login admin/operator, senha incorreta, logout, me, 401 anonimo, 403 operator em config e 200 admin.
Por que foi alterado: garantir que hardening nao seja acidentalmente removido.
O que foi removido: n/a.
Impacto: regressao automatizada de seguranca inicial.
Teste realizado: `docker exec cotasync_test_backend python -m unittest discover`.
Resultado: 164 testes OK.
Risco restante: testes de expiracao de cookie podem ser adicionados quando houver store de usuarios.

## noVNC e tokens

`POST /api/desktop-browser/view-token` agora exige login. O endpoint de validacao de token continua necessario para o fluxo de visualizacao, mas a emissao do token e protegida.

Teste anonimo:

```text
POST /api/desktop-browser/view-token -> 401
{"detail":"Authentication required."}
```

Teste autenticado:

```text
operator -> 200
```

O token completo nao foi impresso pelo smoke test nem pelos relatios de teste.

