# Portas e Servicos

## Compose final de teste

`docker compose -f docker-compose.test.yml --env-file .env.test ps` mostrou:

- `cotasync_test_backend`: `127.0.0.1:8100->8000`
- `cotasync_test_frontend`: `127.0.0.1:3100->8501`
- `cotasync_test_desktop_browser`: `127.0.0.1:9222->9222`, `127.0.0.1:3200->6080`
- `cotasync_test_postgres`: interno `5432/tcp`

## Portas

Browserless:
- antes: porta 3010 exposta pelo compose legado.
- depois: sem listener 3010 e sem container Browserless.

CDP:
- porta 9222 bindada em `127.0.0.1` no ambiente de teste.
- nao esta publica em `0.0.0.0`.

VNC:
- porta 5900 nao esta publicada.

noVNC:
- porta 3200 bindada em `127.0.0.1` no ambiente de teste.
- emissao de token/view protegida pela API.

## Alteracoes concretas

Arquivo: `docker-compose.test.yml`
Funcao/servico: ambiente de regressao.
Como era: Browserless e Redis; frontend/test services com envs legadas.
Como ficou: desktop browser, postgres, backend e frontend.
Por que foi alterado: refletir arquitetura ativa.
O que foi removido: Browserless, Redis, porta 3010, envs obsoletas.
Impacto: ambiente sobe sem servicos mortos.
Teste realizado: build, ps, health, smoke.
Resultado: OK.
Risco restante: o reverse proxy de producao ainda deve restringir noVNC/CDP conforme desenho final.

Arquivo: `docker-compose.yml`
Funcao/servico: ambiente principal.
Como era: continha servicos legados.
Como ficou: mesmo desenho simplificado.
Por que foi alterado: evitar divergencia entre teste e principal.
O que foi removido: Browserless/Redis ativos.
Impacto: menor superficie e menos custo operacional.
Teste realizado: validado principalmente com compose de teste.
Resultado: OK.
Risco restante: validar variaveis reais de producao antes de deploy.

## Evidencia de listeners

`ss -ltnp` relevante:

```text
127.0.0.1:9222
127.0.0.1:3200
```

Nao apareceu:

```text
:3010
:5900
```

