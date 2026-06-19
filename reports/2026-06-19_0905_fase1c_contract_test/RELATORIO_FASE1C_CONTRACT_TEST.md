# Relatório Fase 1C - Contract Test Actions/Runs

## Resumo executivo

Foi criada uma validação segura e reproduzível do ciclo completo `actions + runs` usando uma ação aprendida fake/local. O teste injeta uma fixture temporária em `data/ui_map.json`, executa `POST /api/actions/{id}/run`, consulta a run criada e valida 422/404 sem acessar ERP, Browserless, LLM ou qualquer sistema externo.

O catálogo runtime foi restaurado ao final do teste. O arquivo `data/runs/runs.json` ficou sem runs de teste após a limpeza.

## Commit base

- Commit base usado: `becf929 Cria API inicial de execuções do CotaSync`

## Arquivos alterados

- `backend/schemas/actions.py`
- `backend/services/actions_repository.py`
- `backend/services/action_runner.py`
- `tests/fixtures/ui_map_local_action.json`
- `scripts/test_actions_runs_contract.sh`
- `reports/2026-06-19_0905_fase1c_contract_test/RELATORIO_FASE1C_CONTRACT_TEST.md`

## Fixture criada

- Caminho: `tests/fixtures/ui_map_local_action.json`
- Nome/chave da ação: `Teste Local Eco CPF`
- Variável obrigatória: `cpf`
- Marcadores seguros:
  - `modo_teste: true`
  - `tipo_execucao: "local_fixture"`
- URL: `about:blank`
- Passos Playwright: lista vazia

## Como o modo local/fake funciona

O repository de actions passou a normalizar dois metadados opcionais:

- `test_mode`
- `execution_type`

No `backend/services/action_runner.py`, ações com `test_mode=True` ou `execution_type="local_fixture"` usam um caminho local controlado. Esse caminho:

- não chama `executar_acao_fast_track`;
- não chama Browserless;
- não chama LLM;
- não faz login;
- não acessa sistema externo;
- retorna `run.status="success"`;
- retorna `result_summary="Execucao local de teste concluida."`;
- retorna `result_payload` seguro com `fixture=true` e eco mascarado das variáveis.

## Endpoints validados

- `GET /health`
- `GET /api/health/browserless`
- `GET /api/actions`
- `GET /api/runs`
- `POST /api/actions/{action_id}/run`
- `GET /api/runs/{run_id}`
- `HEAD /` no frontend via `curl -I http://127.0.0.1:3100`

## Resultado do POST `/api/actions/{id}/run`

O script localizou o `action_id=teste-local-eco-cpf` a partir de `GET /api/actions` e executou a ação em modo local.

Resultado validado:

```json
{
  "status": "ok",
  "run": {
    "action_id": "teste-local-eco-cpf",
    "action_key": "Teste Local Eco CPF",
    "status": "success",
    "mode": "sync",
    "requested_by": "test",
    "variables": {
      "cpf": "*********00"
    },
    "result_summary": "Execucao local de teste concluida.",
    "result_payload": {
      "echo": {
        "cpf": "*********00"
      },
      "fixture": true,
      "action_id": "teste-local-eco-cpf"
    },
    "error_message": null
  }
}
```

## Validação de máscara de CPF

O teste confirmou que o CPF de entrada não aparece em claro:

- na resposta do `POST /api/actions/{id}/run`;
- na resposta do `GET /api/runs`;
- na resposta do `GET /api/runs/{run_id}`;
- em `data/runs/runs.json`;
- no `result_payload`.

A forma persistida e retornada é `*********00`.

## Validação de erro 422 sem variável obrigatória

O script executou `POST /api/actions/{id}/run` sem `cpf` e validou HTTP 422 com:

```json
{
  "detail": {
    "message": "Variaveis obrigatorias ausentes.",
    "missing_variables": ["cpf"]
  }
}
```

## Validação de erro 404 action inexistente

O script executou `POST /api/actions/acao-inexistente/run` e validou HTTP 404 com:

```json
{
  "detail": "Acao nao encontrada."
}
```

## Resultado do script

Comando executado:

```bash
bash scripts/test_actions_runs_contract.sh
```

Resultado:

```text
Contrato actions/runs validado com run_id=03b561bf-5d37-4ece-ae2d-e890e1d869a1 action_id=teste-local-eco-cpf
```

## Validações executadas

```bash
python3 -m compileall backend scripts
docker compose -f docker-compose.test.yml --env-file .env.test up -d --build
docker compose -f docker-compose.test.yml --env-file .env.test ps
curl -s http://127.0.0.1:8100/health
curl -s http://127.0.0.1:8100/api/health/browserless
curl -s http://127.0.0.1:8100/api/actions | python3 -m json.tool
curl -s http://127.0.0.1:8100/api/runs | python3 -m json.tool
bash scripts/test_actions_runs_contract.sh
curl -I http://127.0.0.1:3100
```

Resultados principais:

- `/health`: `{"status":"ok","service":"cotasync"}`
- `/api/health/browserless`: `status=ok`
- `/api/actions`: catálogo runtime vazio antes e depois do script
- `/api/runs`: lista vazia antes do teste; runs de teste removidas ao final
- frontend: HTTP 200

## Limitações

- O modo local valida contrato HTTP e persistência, não valida automação real de browser.
- A limpeza remove apenas runs da fixture com `requested_by="test"` e `action_key="Teste Local Eco CPF"`.
- A persistência continua em JSON temporário.

## Riscos

- Se `data/runs/runs.json` estiver manualmente corrompido, a limpeza segura do script aborta.
- O schema de actions agora expõe metadados de teste quando uma fixture estiver carregada, o que é esperado para validações locais.
- O modo local deve continuar restrito a fixtures explicitamente marcadas.

## Próximos passos

- Automatizar esse contract test no pipeline de CI.
- Adicionar testes unitários para mascaramento e detecção de fixture local.
- Evoluir runs para Postgres em fase futura.
- Separar política de fixtures por ambiente quando houver pipeline formal.
