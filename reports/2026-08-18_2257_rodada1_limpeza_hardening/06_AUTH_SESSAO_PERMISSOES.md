# Auth, Sessao e Permissoes

## Modelo implementado

Autenticacao por sessao/cookie, preparada para frontend no mesmo dominio.

- Cookie de sessao: HttpOnly.
- `Secure`: configuravel por `COTASYNC_COOKIE_SECURE`; em teste usa `false`.
- CSRF: cookie nao HttpOnly + header `X-CSRF-Token` em mutacoes autenticadas.
- Perfis: `admin`, `operator`.
- Senhas: hash PBKDF2-SHA256 via stdlib; credenciais iniciais por env.
- Sem token persistido em `localStorage` ou `sessionStorage`.

## Endpoints

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`

## Alteracoes concretas

Arquivo: `backend/services/auth.py`
Funcao/servico: usuarios, hash, sessao, cookie e CSRF.
Como era: nao havia autenticacao do produto.
Como ficou: usuarios admin/operator por env, hash forte, token de sessao assinado por HMAC, validacao CSRF.
Por que foi alterado: impedir acesso anonimo a API operacional.
O que foi removido: acesso aberto por ausencia de sessao.
Dependencias removidas: nenhuma; implementado com stdlib.
Impacto: consumidores precisam login e cookie.
Teste realizado: `tests/test_auth_security.py`.
Resultado: login admin/operator, senha incorreta, logout e `/auth/me` OK.
Risco restante: persistencia de usuarios em PostgreSQL fica para Rodada 2.

Arquivo: `backend/api/auth.py`
Funcao/servico: contrato HTTP de auth.
Como era: inexistente.
Como ficou: endpoints versionados sob `/api/v1/auth`.
Por que foi alterado: contrato limpo para frontend futuro.
O que foi removido: n/a.
Impacto: Streamlit e futuro React podem autenticar no mesmo dominio.
Teste realizado: suite completa.
Resultado: OK.
Risco restante: fluxo de redefinicao de senha nao implementado nesta rodada.

Arquivo: `backend/main.py`
Funcao/servico: middleware de protecao.
Como era: routers eram majoritariamente publicos.
Como ficou: `/api/*` exige sessao, exceto health desktop, login/logout e webhook Evolution; mutacoes autenticadas exigem CSRF.
Por que foi alterado: protecao backend, nao apenas UI.
O que foi removido: acesso anonimo a endpoints sensiveis.
Impacto: chamadas diretas sem login retornam 401; sem CSRF retornam 403.
Teste realizado: curl anonimo em `/api/desktop-browser/view-token`.
Resultado: `401 {"detail":"Authentication required."}`.
Risco restante: revisar excecoes publicas quando Evolution/webhooks forem endurecidos.

Arquivo: `backend/api/browser.py`, `backend/api/external_systems.py`
Funcao/servico: configuracoes sensiveis.
Como era: configuracao podia ser alterada sem papel administrativo.
Como ficou: `PUT /api/browser/config` e `PUT /api/external-systems/current` exigem admin.
Por que foi alterado: operador nao deve alterar configuracao sensivel.
O que foi removido: permissao ampla.
Impacto: operator recebe 403; admin recebe 200.
Teste realizado: `tests/test_auth_security.py`.
Resultado: OK.
Risco restante: granularidade fina de permissoes pode ser refinada depois sem RBAC pesado.

## Papeis

Admin:
- acesso completo.
- configuracoes administrativas.
- usuarios futuros.
- browser, acoes, aprendizado, clientes, batches e diagnostico.

Operator:
- dashboard, clientes, acoes, ensinar/executar acoes, batches, navegador/noVNC, renovar sessao externa e resultados.
- bloqueado em configuracoes sensiveis administrativas.

