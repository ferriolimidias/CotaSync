# Redis: Auditoria e Remocao

## Decisao

Redis foi removido do ambiente ativo/teste do CotaSync. A auditoria anterior indicava `DBSIZE = 0` e nao havia consumidor operacional no backend.

## Auditoria

Busca feita em codigo ativo para `redis`, `REDIS` e variaveis correlatas nao encontrou dependencia funcional apos a limpeza. Redis nao era usado por fila, cache, lock, sessao ou coordenacao.

## Alteracoes concretas

Arquivo: `docker-compose.yml`, `docker-compose.test.yml`
Funcao/servico: infraestrutura.
Como era: Redis provisionado como container vazio/futuro.
Como ficou: servico removido; backend/frontend nao dependem de Redis.
Por que foi alterado: nao manter container sem consumidor e evitar superficie operacional desnecessaria.
O que foi removido: servico Redis, env vars Redis, `depends_on`, healthcheck e volume.
Dependencias removidas: nenhuma dependencia Python de producao foi adicionada ou mantida para Redis.
Impacto: sistema sobe sem Redis.
Teste realizado: `docker compose ... up -d --build`, suite completa, smoke real.
Resultado: ambiente operacional OK sem Redis.
Risco restante: coordenacao futura deve ser desenhada com PostgreSQL na Rodada 2 ou posterior.

## Provas finais

- Compose final nao lista `cotasync_test_redis`.
- Busca em codigo ativo para `redis` nao retornou ocorrencias.
- `docker compose ... ps` mostra apenas backend, frontend, desktop_browser e postgres.

