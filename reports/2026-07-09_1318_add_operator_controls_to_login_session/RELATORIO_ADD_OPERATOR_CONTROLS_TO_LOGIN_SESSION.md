# Relatorio - Modo operador no login manual

## Problema identificado

No fluxo de `Configuracoes / Sistema externo / Sessao do navegador`, o usuario conseguia abrir o navegador/noVNC para login manual e salvar a sessao, mas alguns campos do navegador remoto nao aceitavam bem digitacao direta ou colagem, especialmente senhas e numeros.

Era necessario expor o mesmo tipo de apoio do modo operador nessa tela, sem transformar login em automacao e sem salvar credenciais.

## Onde foi adicionado

Arquivo:

```text
frontend/app.py
```

Na tela `Configuracoes`, dentro de `Sessao do navegador`, quando ha uma sessao aberta, foi adicionada a secao:

```text
Modo operador para login
```

Controles:

- `Texto/login`
- `Digitar texto no campo ativo`
- `Senha ou texto sensivel`
- `Digitar senha no campo ativo`
- `Tab`
- `Enter`
- `Limpar campo ativo`

Instrucao exibida:

```text
Clique primeiro no campo desejado dentro do navegador/noVNC. Depois digite ou cole o texto aqui e envie para o navegador.
```

## Endpoints/funcoes

Endpoints existentes reaproveitados:

- `POST /api/demo/sessions/{session_id}/operator/insert-active`

Endpoints criados:

- `POST /api/demo/sessions/{session_id}/operator/press`
- `POST /api/demo/sessions/{session_id}/operator/clear-active`

Funcoes de servico:

- `operator_insert_active(..., sensitive=False)`
- `operator_press(session_id, key)`
- `operator_clear_active(session_id)`

Helpers do frontend:

- `operator_type_active`
- `operator_press_key`
- `operator_clear_active`

## Como envia texto ao campo ativo

O usuario clica no campo desejado dentro do noVNC. O backend usa `document.activeElement` na pagina da sessao.

Fluxo:

1. valida se a sessao existe e o navegador esta disponivel;
2. valida se o elemento ativo e editavel;
3. tenta `keyboard.insert_text`;
4. em fallback, define o valor via DOM para `input`, `textarea` ou `contenteditable`;
5. dispara eventos `input` e `change`;
6. retorna apenas metadados seguros.

## Tratamento de senha/texto sensivel

Para texto sensivel:

- o input no Streamlit usa `type="password"`;
- o envio usa `sensitive=true`;
- resposta retorna apenas `typed_chars` e `sensitive`;
- a resposta nunca inclui o texto;
- o formulario de senha usa `clear_on_submit=True`;
- nao ha funcao de lembrar senha;
- nao ha automacao de login/MFA;
- nao ha persistencia de credenciais.

Exemplo seguro de resposta:

```json
{
  "status": "ok",
  "operator": {
    "operation": "insert_active_text",
    "typed_chars": 12,
    "sensitive": true
  }
}
```

## Garantias de nao persistencia

O valor digitado nao e salvo em:

- `data/*.json`;
- `data/runs`;
- logs de runs;
- `ui_map.json`;
- `current.json`;
- reports;
- historico de acoes.

O logger registra somente:

- id da sessao;
- quantidade de caracteres;
- flag `sensitive`.

Nao registra o valor.

`session.last_operator_result` guarda apenas metadados seguros como `typed_chars`, `operation` e `sensitive`.

## Testes

Novo arquivo:

```text
tests/test_operator_login_controls.py
```

Coberturas:

- endpoint digita texto normal no activeElement;
- aceita numeros e caracteres especiais;
- endpoint sensivel nao retorna o texto;
- `Enter` chama endpoint de press;
- `Tab` chama endpoint de press;
- limpar campo ativo chama endpoint correto;
- UI contem os controles de login;
- API client expoe helpers do modo operador.

Comandos executados:

```bash
python3 -m compileall backend frontend scripts
docker compose -f docker-compose.test.yml --env-file .env.test up -d --build
docker compose -f docker-compose.test.yml --env-file .env.test ps
sleep 5 && curl -sS http://127.0.0.1:8100/health
docker exec cotasync_test_backend python -m unittest tests.test_operator_login_controls tests.test_batch_runner tests.test_clients_repository tests.test_operational_summary tests.test_guided_learning_outputs tests.test_desktop_action_runner tests.test_access_profile_demo_flow
docker exec cotasync_test_backend python scripts/test_desktop_browser_connection.py
```

Resultado:

- compileall OK;
- Docker build/up OK;
- containers OK;
- healthcheck OK;
- 146 testes OK;
- desktop browser/noVNC/CDP/replay OK.

## Validacao manual

Fluxo esperado:

1. Abrir `http://89.116.29.150:3100`.
2. Ir em `Configuracoes`.
3. Abrir navegador para login.
4. Clicar no campo de login/e-mail dentro do noVNC.
5. Usar `Texto/login` e `Digitar texto no campo ativo`.
6. Clicar no campo de senha dentro do noVNC.
7. Usar `Senha ou texto sensivel`.
8. Clicar `Digitar senha no campo ativo`.
9. Usar `Enter` ou seguir manualmente no noVNC.
10. Concluir MFA/consentimento manualmente.
11. Salvar sessao do navegador.

Verificar que a senha nao aparece em resposta da API, logs, arquivos `data`, report ou historico.

## Limitacoes

- O recurso depende de o usuario focar manualmente o campo correto no noVNC.
- Nao tenta localizar automaticamente campos de senha.
- Nao automatiza login, MFA ou consentimento.
- `insert_text` pode depender do comportamento do navegador/sistema externo; ha fallback DOM para inputs editaveis.

## Proximos passos

- Adicionar opcao avancada de preencher por seletor na tela de Configuracoes.
- Adicionar diagnostico visual do elemento ativo sem revelar valor.
- Criar teste e2e especifico para `insert-active` no alvo local do desktop browser.
