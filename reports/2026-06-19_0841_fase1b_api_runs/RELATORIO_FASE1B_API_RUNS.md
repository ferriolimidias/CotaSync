# Relatório Fase 1B - API de Runs

## Resumo executivo

Foi implementado o contrato HTTP inicial para execução individual de ações aprendidas no CotaSync. A API agora permite solicitar a execução síncrona de uma ação, registrar a tentativa como run em persistência JSON temporária e consultar runs salvas.

Como `data/ui_map.json` estava vazio durante a validação, não foi executada ação real nem fixture temporária. O contrato seguro de catálogo vazio foi validado com 404 em `POST /api/actions/nao-existe/run`.

## Commit base

- Commit base esperado pelo objetivo: `93f588f Cria API inicial de ações aprendidas do CotaSync`
- HEAD local usado como base efetiva: `94dc466 Finaliza API inicial de ações aprendidas do CotaSync`

## Arquivos alterados

- `.gitignore`
- `backend/main.py`
- `backend/api/runs.py`
- `backend/schemas/runs.py`
- `backend/services/action_runner.py`
- `backend/services/runs_repository.py`
- `data/runs/.gitkeep`
- `scripts/test_runs_api.sh`
- `reports/2026-06-19_0841_fase1b_api_runs/RELATORIO_FASE1B_API_RUNS.md`

## Endpoints criados

- `POST /api/actions/{action_id}/run`
- `GET /api/runs`
- `GET /api/runs/{run_id}`

## Schemas criados

- `ActionRunRequest`
- `RunRecord`
- `ActionRunResponse`
- `RunsListResponse`
- `RunDetailResponse`
- `RunStatus`
- `RunMode`

## Formato de `data/runs/runs.json`

```json
{
  "runs": [
    {
      "id": "uuid",
      "action_id": "slug-da-acao",
      "action_key": "chave_original",
      "status": "success",
      "mode": "sync",
      "requested_by": "api",
      "created_at": "2026-06-19T11:00:00+00:00",
      "started_at": "2026-06-19T11:00:01+00:00",
      "finished_at": "2026-06-19T11:00:10+00:00",
      "variables": {
        "cpf": "*******8900"
      },
      "result_summary": "Execucao concluida.",
      "result_payload": null,
      "error_message": null
    }
  ]
}
```

O arquivo é criado sob demanda em `data/runs/runs.json`, com diretório criado automaticamente e escrita atômica simples via arquivo temporário e `os.replace`.

## Como `POST /api/actions/{id}/run` funciona

O endpoint aceita `action_id` por slug, chave original ou forma URL-encoded compatível com a busca da Fase 1A. A ação é carregada pelo repository atual de actions. Se não existir, retorna 404 seguro. Se variáveis obrigatórias estiverem ausentes, retorna 422 com `missing_variables`.

Para `mode="sync"`, a API cria uma run `pending`, persiste, muda para `running`, executa a ação por um wrapper fino em `backend/services/action_runner.py` usando `executar_acao_fast_track`, captura falhas e finaliza a run como `success` ou `error`.

Variáveis sensíveis como `cpf`, `cnpj`, `senha`, `token`, `secret`, `email`, `telefone` e similares são mascaradas antes de persistir.

## Como `GET /api/runs` funciona

O endpoint lê `data/runs/runs.json` e retorna:

```json
{
  "status": "ok",
  "count": 0,
  "runs": []
}
```

Se o arquivo não existir, retorna lista vazia. Os filtros opcionais implementados são `action_id`, `status` e `limit`. A ordenação usa `started_at` ou `created_at` em ordem decrescente.

## Como `GET /api/runs/{id}` funciona

O endpoint consulta uma run por `run_id`. Se existir, retorna `{"status":"ok","run":{...}}`. Se não existir, retorna 404 seguro:

```json
{"detail":"Run nao encontrada."}
```

## Validações executadas

Comandos executados:

```bash
python3 -m compileall backend scripts/test_runs_api.sh
docker compose -f docker-compose.test.yml --env-file .env.test up -d --build
docker compose -f docker-compose.test.yml --env-file .env.test ps
curl -s http://127.0.0.1:8100/health
curl -s http://127.0.0.1:8100/api/health/browserless
curl -s http://127.0.0.1:8100/api/actions | python3 -m json.tool
curl -s http://127.0.0.1:8100/api/runs | python3 -m json.tool
curl -s http://127.0.0.1:8100/api/runs/nao-existe -i
curl -s -i -H 'Content-Type: application/json' -d '{"variables":{"cpf":"12345678900"},"mode":"sync","requested_by":"api"}' http://127.0.0.1:8100/api/actions/nao-existe/run
scripts/test_runs_api.sh
```

## Resultados dos curls

`GET /health`:

```json
{"status":"ok","service":"cotasync"}
```

`GET /api/health/browserless`:

```json
{"status":"ok","browserless_url":"ws://cotasync_test_browserless:3000","elapsed_ms":12734,"screenshot":""}
```

`GET /api/actions`:

```json
{
  "status": "ok",
  "count": 0,
  "actions": [],
  "warning": null
}
```

`GET /api/runs`:

```json
{
  "status": "ok",
  "count": 0,
  "runs": []
}
```

`GET /api/runs/nao-existe -i`:

```http
HTTP/1.1 404 Not Found
content-type: application/json

{"detail":"Run nao encontrada."}
```

`POST /api/actions/nao-existe/run -i`:

```http
HTTP/1.1 404 Not Found
content-type: application/json

{"detail":"Acao nao encontrada."}
```

## Fixture temporária

Não foi usada fixture temporária. O catálogo `data/ui_map.json` estava vazio:

```json
{"acoes_conhecidas": {}}
```

## Limitações

- Persistência em JSON é temporária e não resolve concorrência forte entre múltiplos workers.
- `mode` aceito nesta fase é somente `sync`.
- Não há fila/worker assíncrono real.
- Execuções reais continuam dependendo da lógica existente de Fast-Track, Browserless e configuração segura do ambiente.
- Com catálogo vazio, só foi validado o contrato seguro de erro para execução inexistente.

## Riscos

- Corrupção manual de `data/runs/runs.json` retorna erro seguro 500 até correção do arquivo.
- Runs reais podem conter dados extraídos pelo motor existente; o wrapper só preserva payloads de resultado selecionados.
- A persistência local não é adequada para escala ou auditoria definitiva.

## Próximos passos

- Criar testes automatizados com fixture isolada e segura para contrato 200 com `run.status`.
- Migrar runs para Postgres em fase futura.
- Adicionar worker/fila real para execução assíncrona.
- Definir política formal de retenção e mascaramento de payloads de execução.
