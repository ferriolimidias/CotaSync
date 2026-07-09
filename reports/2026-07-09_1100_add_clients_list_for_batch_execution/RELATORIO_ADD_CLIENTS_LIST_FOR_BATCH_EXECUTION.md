# Relatorio - Lista de clientes para execucao em massa

## Auditoria da execucao em massa atual

O modulo anterior de batch estava correto na arquitetura de fila sequencial:

- `POST /api/batches`
- `GET /api/batches`
- `GET /api/batches/{batch_id}`
- `GET /api/batches/{batch_id}/results.csv`
- `POST /api/batches/{batch_id}/cancel`
- worker unico com lock global;
- execucao via `run_action_sync`;
- delay padrao de 3 segundos;
- persistencia em `data/batches`.

O ponto problemático estava na experiencia: a tela principal começava por CSV, o que comunicava uma execucao avulsa, nao uma base recorrente de clientes.

## Problema de UX identificado

O produto precisa demonstrar:

1. clientes cadastrados uma vez;
2. acoes ensinadas uma vez;
3. execucao de uma acao para uma lista de clientes;
4. possibilidade de agendamento recorrente para a mesma lista.

CSV deve alimentar a base de clientes, nao ser o centro da execucao em massa.

## Nova estrutura de clientes

Criado `backend/services/clients_repository.py`.

Persistencia:

```text
data/clients/clients.json
```

Modelo:

```json
{
  "id": "uuid",
  "name": "Cliente 1",
  "active": true,
  "group": "Lista Principal",
  "notes": "",
  "created_at": "...",
  "updated_at": "...",
  "variables": {
    "grupo": "935",
    "grupo_2": "110",
    "grupo_3": "00",
    "cota": "110",
    "vers_o": "00"
  }
}
```

O campo `variables` e generico para suportar acoes diferentes sem hardcode por acao.

## Endpoints de clientes

Criado `backend/api/clients.py`.

Endpoints:

- `GET /api/clients`
- `POST /api/clients`
- `PUT /api/clients/{client_id}`
- `POST /api/clients/{client_id}/deactivate`
- `DELETE /api/clients/{client_id}`
- `POST /api/clients/import-csv`
- `GET /api/clients/template.csv`
- `GET /api/clients/validate-for-action/{action_id}`
- `GET /api/client-groups`

## UI de clientes

Atualizado `frontend/app.py`.

Nova aba:

- `Clientes`

Componentes:

- cadastro manual;
- nome;
- grupo/lista;
- ativo;
- notas;
- campos comuns para demo: `grupo`, `grupo_2`, `grupo_3`, `cota`, `vers_o`;
- campo JSON para variaveis extras;
- importacao CSV;
- download de modelo CSV;
- tabela de clientes;
- filtro por grupo/lista;
- mostrar/ocultar inativos;
- editar cliente;
- ativar/desativar via edicao.

## UI revisada da execucao em massa

A aba `Execucao em massa` agora começa por:

1. escolher uma acao;
2. escolher uma lista/grupo de clientes;
3. ver variaveis obrigatorias;
4. ver clientes prontos;
5. ver clientes incompletos;
6. ver clientes inativos;
7. executar agora;
8. acompanhar fila/resultados por cliente;
9. baixar CSV final.

O fluxo antigo por CSV foi preservado em:

```text
Avancado: executar com CSV avulso
```

## CSV virou importacao de clientes

Modelo:

```csv
name,group,active,grupo,grupo_2,grupo_3,cota,vers_o
Cliente 1,Lista Principal,true,935,110,00,110,00
Cliente 2,Lista Principal,true,935,111,00,111,00
```

Regras implementadas:

- aceita BOM UTF-8;
- ignora linhas vazias;
- preserva zeros a esquerda;
- cria id quando nao houver;
- atualiza por `id` quando houver;
- para MVP, atualiza por `name + group` quando nao houver `id`.

## Batch com client_group/client_ids

`POST /api/batches` continua aceitando `rows`.

Foi adicionado suporte a:

```json
{
  "action_id": "numero-de-parcelas-pagas",
  "client_group": "Lista Principal",
  "client_ids": ["..."],
  "requested_by": "streamlit-client-list",
  "delay_between_rows_seconds": 3
}
```

O backend valida os clientes contra a acao, usa somente clientes ativos e completos, e cria linhas com:

- `client_id`
- `client_name`
- `client_group`
- `variables`
- `run_id`
- `status`
- `operational_summary`
- `error_message`

## CSV final do batch

O CSV final agora inclui:

```text
batch_id
row_index
client_id
client_name
client_group
action_id
status
run_id
variables_json
operational_summary
dados_extraidos_json
error_message
started_at
finished_at
```

## Agendamento revisado/sincronizado

A tela `Agendamentos e Filas` recebeu uma seção de alinhamento para rascunho de agendamento por:

- acao;
- lista/grupo de clientes;
- frequencia mensal/semanal;
- delay entre clientes;
- status ativo.

Nao foi criado cron real novo nesta rodada para evitar risco. A estrutura visual e o formato do rascunho agora apontam para `action_id + client_group`, que e o mesmo modelo usado pela execucao em massa.

## Testes

Novos/ajustados:

- `tests/test_clients_repository.py`
- `tests/test_batch_runner.py`

Coberturas adicionadas:

- criar cliente;
- atualizar cliente;
- desativar cliente;
- importar CSV preservando zeros a esquerda;
- atualizar por `name + group`;
- listar grupos;
- validar clientes por acao;
- identificar pronto/incompleto/inativo;
- criar batch por `client_group`;
- salvar `client_id/client_name/client_group` por linha;
- CSV final com dados de cliente;
- CSV avulso preservado;
- fila sequencial e bloqueio de paralelismo mantidos.

Comandos executados:

```bash
python3 -m compileall backend frontend scripts
docker compose -f docker-compose.test.yml --env-file .env.test up -d --build
docker compose -f docker-compose.test.yml --env-file .env.test ps
sleep 5 && curl -sS http://127.0.0.1:8100/health
docker exec cotasync_test_backend python -m unittest tests.test_batch_runner tests.test_clients_repository tests.test_operational_summary tests.test_guided_learning_outputs tests.test_desktop_action_runner tests.test_access_profile_demo_flow
docker exec cotasync_test_backend python scripts/test_desktop_browser_connection.py
curl -sS http://127.0.0.1:8100/api/client-groups
curl -sS http://127.0.0.1:8100/api/clients/template.csv
```

Resultado:

- compileall OK;
- build Docker OK;
- containers OK;
- healthcheck OK;
- 133 testes OK;
- desktop browser/noVNC/CDP/replay OK;
- endpoints de clientes OK.

## Validacao manual

Fluxo esperado:

1. Abrir CotaSync em `http://89.116.29.150:3100`.
2. Ir em `Clientes`.
3. Cadastrar:
   - Cliente 1 / Lista Principal / grupo 935 / grupo_2 110 / grupo_3 00;
   - Cliente 2 / Lista Principal / grupo 935 / grupo_2 111 / grupo_3 00.
4. Confirmar tabela.
5. Ir em `Execucao em massa`.
6. Escolher `numero de parcelas pagas`.
7. Escolher `Lista Principal`.
8. Confirmar 2 clientes prontos.
9. Executar.
10. Confirmar fila sequencial.
11. Confirmar resultados por cliente.
12. Baixar CSV final com cliente + resultado.

Validacao extra:

- importar CSV de clientes;
- confirmar que ele alimenta a aba `Clientes`;
- confirmar que nao inicia execucao automaticamente.

## Limitacoes

- O rascunho de agendamento ainda nao cria cron recorrente real.
- O armazenamento e JSON local, adequado para demo/MVP.
- Exclusao fisica existe no endpoint, mas a UI prioriza desativacao.
- Retomada automatica de batch interrompido ainda nao foi implementada.
- Lock de batch continua em memoria com guarda por batch persistido `pending/running`.

## Proximos passos

- Persistir agendamentos recorrentes em `data/client_schedules`.
- Criar executor de agenda mensal/semanal usando `client_group`.
- Adicionar reprocessamento de clientes com erro.
- Adicionar historico por cliente/acao.
- Adicionar busca e paginacao se a base crescer.
