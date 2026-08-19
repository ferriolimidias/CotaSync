# Browserless Removido

## Decisao

Browserless foi removido completamente do codigo ativo. O historico Git permanece como unica fonte de recuperacao futura.

## Auditoria antes da remocao

Pergunta: `desktop_browser` importava algo exclusivo de Browserless?
Resposta: nao. O uso ativo de CDP esta em `DesktopBrowserProvider` e no container `desktop_browser`.

Pergunta: havia classe compartilhada indispensavel?
Resposta: nao. A interface comum de provider foi mantida sem a implementacao Browserless.

Pergunta: existia endpoint que escolhia Browserless?
Resposta: havia endpoint/configuracao de browser com opcoes. Foi simplificado para modo unico.

Pergunta: alguma acao persistida exigia Browserless?
Resposta: nao foi encontrada dependencia operacional ativa. Configuracoes antigas sao tratadas por normalizacao de leitura para `desktop_browser` quando necessario.

Pergunta: algum teste/script ativo exigia Browserless?
Resposta: sim, testes e scripts legados. Foram removidos.

Pergunta: variaveis de ambiente ainda controlavam Browserless?
Resposta: sim, em compose/env exemplo. Foram removidas.

Pergunta: alguma configuracao salva possuia `browser_mode=browserless`?
Resposta: nao foi encontrada dependencia ativa; dados operacionais nao foram alterados nem commitados.

## Arquivos removidos

- `backend/services/browserless_urls.py`
- `tests/test_browserless_urls.py`
- `scripts/test_browserless_connection.py`
- `scripts/test_demo_v01_cycle.py`
- `scripts/test_external_system_cycle.py`
- `deploy/nginx/browserless-cotasync.ferriolimidias.com.br.conf`
- `docs/ROTEIRO_DEMO_V01.md`

## Alteracoes concretas

Arquivo: `backend/services/browser_providers.py`
Funcao/servico: provider de browser.
Como era: continha provider Browserless, URL publica, normalizacao com opcoes e fallback.
Como ficou: somente `DesktopBrowserProvider`; `VALID_BROWSER_MODES = ("desktop_browser",)`.
Por que foi alterado: Browserless nao e arquitetura desejada nem fallback.
O que foi removido: provider, selecao, env URL e dependencia conceitual Browserless.
Dependencias removidas: `BROWSERLESS_URL`, URL publica Browserless e helper `browserless_urls`.
Impacto: API e runners sempre operam contra desktop browser.
Teste realizado: suite automatizada e smoke real.
Resultado: 164 testes OK; replay real desktop OK.
Risco restante: nenhum uso ativo identificado.

Arquivo: `docker-compose.yml`, `docker-compose.test.yml`
Funcao/servico: orquestracao.
Como era: Browserless era servico com porta 3010.
Como ficou: servico removido; sem publicacao 3010.
Por que foi alterado: reduzir superficie e remover arquitetura abandonada.
O que foi removido: imagem, service, healthcheck, env vars, depends_on e porta 3010.
Impacto: `docker compose ps` nao lista Browserless.
Teste realizado: `docker compose ... ps`, `ss -ltnp`, `docker ps`.
Resultado: nenhum container `cotasync_test_browserless`; nenhum listener 3010.
Risco restante: nenhum.

Arquivo: `backend/main.py`
Funcao/servico: health/API.
Como era: havia health especifico Browserless.
Como ficou: health Browserless removido; permanece health desktop browser.
Por que foi alterado: nao divulgar nem preservar provider removido.
O que foi removido: endpoint/import Browserless.
Impacto: API ativa reflete arquitetura real.
Teste realizado: health geral e suite.
Resultado: OK.
Risco restante: documentacao historica antiga permanece apenas em `reports/2026-08-18_2048_auditoria_geral_pre_producao`.

## Provas finais

- Busca em codigo ativo: `rg -n -i "browserless" backend frontend scripts tests docs deploy Dockerfile docker-compose.yml docker-compose.test.yml .env.test.example` nao retornou ocorrencias.
- Porta 3010: sem listener.
- Compose: sem servico Browserless.
- Desktop browser: `run_id=d6caf738-4c26-403d-ad1f-5a5445b5bd23`, `runner=desktop_browser_replay`, `status=success`.

