# Relatorio - Clientes com campos amigaveis e aliases

## Problema visual identificado

A aba `Clientes` expunha nomes tecnicos de variaveis:

- `grupo`
- `grupo_2`
- `grupo_3`
- `cota`
- `vers_o`
- JSON de variaveis extras aberto por padrao.

Isso confundia o usuario final. Para o sistema de consorcio, o cadastro precisa falar em:

- Grupo
- Cota
- Versao

## Campos tecnicos escondidos

A UI foi ajustada para mostrar no cadastro e edicao:

- Nome do cliente
- Lista/grupo
- Ativo
- Notas
- Grupo
- Cota
- Versao

O JSON tecnico agora fica fechado no expander:

```text
Avancado / outras variaveis
```

Com a orientacao:

```text
Use apenas se uma acao precisar de campos adicionais.
```

## Novo modelo visual Grupo/Cota/Versao

Ao salvar pela UI, as variaveis principais sao gravadas preferencialmente como:

```json
{
  "grupo": "935",
  "cota": "110",
  "versao": "00"
}
```

A tabela de clientes agora exibe:

- Nome
- Lista/grupo
- Ativo
- Grupo
- Cota
- Versao
- Notas
- Atualizado em

Nao exibe por padrao:

- `grupo_2`
- `grupo_3`
- `vers_o`
- `variables_json`

## Aliases implementados

Arquivo central:

```text
backend/services/clients_repository.py
```

Funcoes adicionadas/ajustadas:

- `normalize_client_variables`
- `get_client_display_fields`
- `resolve_variables_for_action`
- `validate_clients_for_action`

Mapeamento:

- `grupo` -> `grupo`
- `cota` -> `cota`, depois `grupo_2`
- `grupo_2` -> `grupo_2`, depois `cota`
- `versao` -> `versao`, depois `vers_o`, depois `grupo_3`
- `vers_o` -> `vers_o`, depois `versao`, depois `grupo_3`
- `grupo_3` -> `grupo_3`, depois `versao`, depois `vers_o`

## Compatibilidade com clientes antigos

Clientes antigos com:

```json
{
  "grupo_2": "110",
  "grupo_3": "00",
  "vers_o": "00"
}
```

continuam validos.

A exibicao amigavel preenche:

- Cota a partir de `cota` ou `grupo_2`;
- Versao a partir de `versao`, `vers_o` ou `grupo_3`.

## Ajuste do CSV modelo

O modelo CSV agora usa campos amigaveis:

```csv
id,name,group,active,grupo,cota,versao,notes
,Cliente 1,Lista Principal,true,935,110,00,
```

O CSV antigo continua aceito:

```csv
name,group,active,grupo,grupo_2,grupo_3,cota,vers_o
Cliente 1,Lista Principal,true,935,110,00,110,00
```

## Ajuste da importacao

Ao importar:

- `cota` salva em `variables.cota`;
- `versao` salva em `variables.versao`;
- `grupo_2` vira fallback para `cota`;
- `grupo_3` vira fallback para `versao`;
- `vers_o` vira fallback para `versao`;
- zeros a esquerda sao preservados;
- BOM UTF-8 e linhas vazias continuam tratados.

## Ajuste da validacao da execucao em massa

A validacao da execucao em massa usa os aliases.

Exemplo para `numero de parcelas pagas`:

Cliente:

```json
{
  "grupo": "935",
  "cota": "110",
  "versao": "00"
}
```

Acao exige:

```json
["grupo", "grupo_2", "grupo_3"]
```

Batch recebe:

```json
{
  "grupo": "935",
  "grupo_2": "110",
  "grupo_3": "00"
}
```

Exemplo para `porcentagem a pagar`:

Acao exige:

```json
["grupo", "cota", "vers_o"]
```

Batch recebe:

```json
{
  "grupo": "935",
  "cota": "110",
  "vers_o": "00"
}
```

## Testes

Testes ajustados/adicionados em:

```text
tests/test_clients_repository.py
```

Cobertura:

- cliente novo salvo com `grupo`, `cota`, `versao`;
- cliente antigo com `grupo_2`/`grupo_3` exibido como Cota/Versao;
- cliente antigo com `vers_o` exibido como Versao;
- CSV novo preserva zeros a esquerda;
- CSV antigo continua funcionando;
- aliases para `numero de parcelas pagas`;
- aliases para `porcentagem a pagar`;
- validacao de cliente pronto por aliases;
- cliente sem cota fica incompleto;
- template CSV usa cabecalhos amigaveis.

Comandos executados:

```bash
python3 -m compileall backend frontend scripts
docker compose -f docker-compose.test.yml --env-file .env.test up -d --build
docker compose -f docker-compose.test.yml --env-file .env.test ps
sleep 5 && curl -sS http://127.0.0.1:8100/health
docker exec cotasync_test_backend python -m unittest tests.test_batch_runner tests.test_clients_repository tests.test_operational_summary tests.test_guided_learning_outputs tests.test_desktop_action_runner tests.test_access_profile_demo_flow
docker exec cotasync_test_backend python scripts/test_desktop_browser_connection.py
curl -sS http://127.0.0.1:8100/api/clients/template.csv
```

Resultado:

- compileall OK;
- build Docker OK;
- containers OK;
- healthcheck OK;
- 140 testes OK;
- desktop browser/noVNC/CDP/replay OK;
- template CSV amigavel OK.

## Validacao manual

Fluxo esperado:

1. Abrir `http://89.116.29.150:3100`.
2. Ir em `Clientes`.
3. Confirmar campos visiveis:
   - Nome do cliente;
   - Lista/grupo;
   - Ativo;
   - Notas;
   - Grupo;
   - Cota;
   - Versao.
4. Confirmar que JSON fica fechado em `Avancado / outras variaveis`.
5. Cadastrar Cliente 1 com Grupo `935`, Cota `110`, Versao `00`.
6. Cadastrar Cliente 2 com Grupo `935`, Cota `111`, Versao `00`.
7. Ir em `Execucao em massa`.
8. Escolher `numero de parcelas pagas`.
9. Escolher `Lista Principal`.
10. Confirmar que os dois clientes aparecem prontos.
11. Executar lote.
12. Confirmar que o batch envia `grupo`, `grupo_2`, `grupo_3`.
13. Baixar CSV final com cliente + resultado.

## Limitacoes

- O expander avancado ainda permite JSON livre para campos extras, mas permanece oculto por padrao.
- Clientes antigos nao sao migrados fisicamente no arquivo ate serem salvos/importados novamente; a compatibilidade e resolvida em leitura/validacao.
- O armazenamento continua em JSON local.

## Proximos passos

- Adicionar migracao opcional para preencher `cota`/`versao` em clientes antigos.
- Adicionar validacao visual por acao na tela de edicao do cliente.
- Criar historico por cliente/acao usando os campos amigaveis.
