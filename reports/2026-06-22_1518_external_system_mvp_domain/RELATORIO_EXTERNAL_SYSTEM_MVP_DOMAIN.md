# Relatório — External System MVP + domínio público

Data: 2026-06-22 15:18 -03
Commit de origem: `3d6ca3eb7010f5832dcc7cef078b020d457df958`

## Resultado

O CotaSync agora permite configurar um sistema externo, abrir sua URL de login no Browserless, confirmar o login manual com validação configurável, gravar a demonstração com observação de IA e executar o replay na mesma sessão desse sistema. O alvo `/demo/alvo` permanece como fallback quando não há URL externa.

## Campos adicionados

- `external_system_name`: nome operacional do sistema.
- `external_login_url`: URL HTTP/HTTPS aberta pela próxima sessão.
- `auth_success_text`: texto opcional esperado após o login.
- `auth_success_selector`: seletor CSS opcional esperado e visível após o login; tem prioridade sobre o texto.

A tela Configurações salva os campos pela API `GET/PUT /api/external-systems/current`. Nenhuma credencial é solicitada ou persistida.

## Schema JSON

Arquivo: `data/external_systems/current.json`.

```json
{
  "external_system_name": "Sistema do cliente",
  "external_login_url": "https://sistema.cliente.com/login",
  "auth_success_text": "",
  "auth_success_selector": "#menu-principal",
  "updated_at": "2026-06-22T18:00:00+00:00"
}
```

Todos os campos de texto são strings. `updated_at` é ISO 8601 UTC ou `null` no seed vazio. A URL, quando preenchida, exige nome e esquema HTTP/HTTPS.

## Fluxo externo

1. O operador salva a configuração em Configurações.
2. Em Chat & Ações, `Abrir sessão de navegador` lê o JSON atual e faz snapshot da configuração na sessão.
3. Se `external_login_url` estiver vazia, abre `COTASYNC_DEMO_TARGET_URL` (`/demo/alvo`).
4. O usuário autentica manualmente na janela Browserless e clica `Login concluído`.
5. O backend valida e persiste `storage_state.json` em `data/external_systems/sessions/<sistema>/<session_id>/` com modo `0600`.
6. Gravação, Modo operador, observação IA ao vivo, salvamento e replay usam a página CDP ativa.
7. O replay compara a URL externa da ação com a sessão selecionada e rejeita sessão de outro sistema.

Cada ação externa salva `external_system_name`, `external_login_url`, `learning_mode=human_demo_live_ai_observed`, `ai_reviewed`, `ai_observer_summary`, `replay_hints`, `waits` e `wait_strategies`, além dos eventos e passos robustos já existentes.

## Validação do login manual

A ordem é determinística:

1. Se há `auth_success_selector`, o seletor deve existir e estar visível.
2. Senão, se há `auth_success_text`, o texto deve estar presente no `body`.
3. Senão, a confirmação humana define `manual_confirmed=true` para uma página HTTP/HTTPS carregada.

O fallback local não usa confirmação genérica: continua exigindo os marcadores da página demo. Cookies, local storage, screenshots e valores digitados não entram no Git.

## Domínio e reverse proxy

O VPS usa nginx 1.24 e IP público `89.116.29.150`. Foram instalados e habilitados, sem alterar os virtual hosts existentes:

- `/etc/nginx/sites-available/cotasync.ferriolimidias.com.br` → `127.0.0.1:3100`.
- `/etc/nginx/sites-available/browserless-cotasync.ferriolimidias.com.br` → `127.0.0.1:3010`, incluindo upgrade WebSocket.

`nginx -t` passou e o serviço foi recarregado. Requisições locais com os respectivos headers `Host` retornaram Streamlit e Browserless `/json/version`. As cópias versionadas estão em `deploy/nginx/`.

O DNS ainda não possui os dois registros. Criar no Cloudflare, inicialmente em modo DNS only:

```text
A  cotasync              89.116.29.150  TTL Auto
A  browserless-cotasync  89.116.29.150  TTL Auto
```

Após `dig +short` devolver o IP para ambos:

```bash
sudo certbot --nginx -d cotasync.ferriolimidias.com.br -d browserless-cotasync.ferriolimidias.com.br
sudo nginx -t
sudo systemctl reload nginx
```

Atualizar o `.env.test` local, sem commit:

```dotenv
COTASYNC_PUBLIC_BASE_URL=https://cotasync.ferriolimidias.com.br
COTASYNC_BROWSERLESS_PUBLIC_URL=https://browserless-cotasync.ferriolimidias.com.br
```

E aplicar somente aos containers CotaSync:

```bash
docker compose -f docker-compose.test.yml --env-file .env.test up -d --force-recreate cotasync_test_backend cotasync_test_frontend
```

## Browserless público

Um segundo hostname é necessário no MVP porque o app e o DevTools Browserless usam raízes HTTP e WebSocket próprias. Recomendação:

- App: `https://cotasync.ferriolimidias.com.br`.
- Browserless/DevTools: `https://browserless-cotasync.ferriolimidias.com.br`.

Com HTTPS, `_live_url` gera `wss://` automaticamente. O backend FastAPI permanece interno ao frontend/compose, exceto a porta de teste já existente `8100`; não foi criado proxy público para ele.

## Testes executados

- `python3 -m compileall backend frontend scripts`: passou.
- `docker compose -f docker-compose.test.yml --env-file .env.test up -d --build`: passou.
- `docker compose ... ps`: cinco serviços CotaSync ativos; Postgres saudável, embora o MVP novo use somente JSON.
- `GET http://127.0.0.1:8100/health`: `status=ok`.
- `GET /api/health/browserless`: `status=ok`.
- `HEAD http://127.0.0.1:3100`: HTTP 200.
- `scripts/test_external_system_cycle.py`: passou configuração externa fake, rejeição de login prematuro, seletor de sucesso, `storage_state`, três passos, metadados, síntese IA e replay com extração `Enviado`.
- `scripts/test_demo_v01_cycle.py`: passou três ciclos locais, Modo operador, observação IA, replay e regressão de revalidação/restauração.
- `scripts/test_actions_runs_contract.sh`: passou.
- `scripts/test_streamlit_actions_api_integration.sh`: passou.
- `nginx -t` e proxies locais por `Host`: passaram.

## Limitações

- Os hostnames ainda não são acessíveis pelo cliente até criar os registros DNS e emitir o certificado.
- Browserless fica publicamente acessível sem autenticação, conforme escopo atual; isso é aceitável apenas para teste controlado e deve receber proteção na próxima fase.
- O `storage_state` externo fica no disco local ignorado pelo Git; não há criptografia em repouso, expiração, catálogo multiusuário ou retomada após restart do backend.
- Existe um único sistema externo configurado em `current.json`; sessões abertas preservam seu snapshot, mas não há seletor de múltiplos sistemas na UI.
- O modo sem seletor/texto confia explicitamente na confirmação humana.
- O recorder cobre interações DOM usuais; iframes cross-origin, CAPTCHA, MFA, downloads complexos e aplicações com seletores altamente dinâmicos podem exigir adaptação.

## Próximos passos

1. Criar os dois registros A, emitir HTTPS e atualizar as duas variáveis públicas para `https://`.
2. Executar um teste remoto real da janela DevTools, teclado, login e replay no navegador do cliente.
3. Restringir Browserless por token, allowlist/VPN ou camada de acesso antes de uso além do teste controlado.
4. Adicionar catálogo de múltiplos sistemas e retomada segura/expiração de sessões.
5. Remover Postgres/Redis do compose de teste numa tarefa separada se não forem usados por outros fluxos; não foram alterados neste trabalho.
