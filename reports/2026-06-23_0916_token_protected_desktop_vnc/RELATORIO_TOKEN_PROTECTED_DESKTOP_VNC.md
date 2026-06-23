# Relatório — noVNC do Desktop Browser protegido por token

Data: 2026-06-23 09:16 -03
Commit base: `c25917dc0fadcfd1510311967951b8eff7269ab2`

## Resultado

O noVNC do Desktop Browser está publicado em HTTPS e protegido por token temporário do CotaSync. A raiz pública redireciona ao CotaSync, e a página, os assets e o handshake WebSocket retornam `403` sem autorização válida. A automação continua conectando diretamente ao CDP interno em `http://cotasync_test_desktop_browser:9222`.

## Arquitetura

1. O Streamlit solicita `POST /api/desktop-browser/view-token` ao FastAPI.
2. O FastAPI cria um token aleatório de 256 bits, grava somente seu SHA-256 e devolve uma URL no domínio público.
3. O nginx recebe a URL, captura o token antes do `auth_request` e consulta o endpoint interno de validação por header para não registrar o segredo na URL do backend.
4. Após a validação inicial, o nginx grava o token em cookie `Secure`, `HttpOnly` e `SameSite=Strict`. O cookie autoriza os assets noVNC e o handshake de `/websockify`.
5. A query é removida antes do proxy para o websockify. O access log do vhost está desativado e o access log do FastAPI mascara validações diretas por query.
6. O CotaSync usa CDP para automação; noVNC é somente a interface visual humana.

## Backend

- `POST /api/desktop-browser/view-token`: retorna `status`, `view_url`, `expires_at` e `ttl_seconds` com `Cache-Control: no-store`.
- `GET /api/desktop-browser/validate-view-token?token=...`: retorna `200` para token válido e `403` para ausente, inválido ou expirado.
- O nginx usa o mesmo endpoint com `X-Desktop-View-Token`, evitando segredo na URL do subrequest interno.
- Serviço: `backend/services/desktop_view_tokens.py`.
- Funções: `create_token()`, `validate_token()`, `cleanup_expired_tokens()` e `mask_token()`.

## TTL e armazenamento

- TTL padrão: 1.800 segundos (30 minutos).
- Configuração: `COTASYNC_DESKTOP_VIEW_TOKEN_TTL_SECONDS=1800`.
- Arquivo runtime: `data/runtime/desktop_view_tokens.json`.
- O arquivo contém digest SHA-256, propósito e timestamps; não contém o token original.
- Permissão de escrita: `0600`.
- O caminho runtime está no `.gitignore` e não foi versionado.

## Frontend

Nas áreas de configuração e sessão do Desktop Browser, `Abrir Navegador Desktop` solicita um token ao backend. A UI então exibe um botão para abrir o acesso temporário e informa tempo e data de expiração, sem renderizar o token como texto. A URL `127.0.0.1:3200` continua somente como fallback de desenvolvimento e não é usada pelo botão em produção.

## nginx

- Template versionado: `deploy/nginx/desktop-cotasync.ferriolimidias.com.br.conf`.
- Configuração ativa: `/etc/nginx/sites-available/desktop-cotasync.ferriolimidias.com.br`.
- Symlink ativo: `/etc/nginx/sites-enabled/desktop-cotasync.ferriolimidias.com.br`.
- Upstream noVNC: `127.0.0.1:3200`.
- Validação: FastAPI em `127.0.0.1:8100`.
- A porta `8100` do backend está vinculada somente a `127.0.0.1`; criação e validação não ficam expostas diretamente pelo IP público.
- Headers de proxy: `Upgrade`, `Connection`, `Host`, `X-Real-IP`, `X-Forwarded-For` e `X-Forwarded-Proto`.
- Proteção aplicada a `/vnc.html`, assets e `/websockify`.
- `/` retorna `302` para `https://cotasync.ferriolimidias.com.br`.
- Os vhosts existentes de CotaSync e Browserless não foram alterados.

## DNS e HTTPS

- DNS em 2026-06-23: `desktop-cotasync.ferriolimidias.com.br` resolveu para `89.116.29.150`, consistente com registro Cloudflare `A desktop-cotasync -> 89.116.29.150` em modo **DNS only**.
- Certbot foi executado somente após a resolução ser confirmada.
- Certificado Let's Encrypt ECDSA emitido para `desktop-cotasync.ferriolimidias.com.br`.
- Validade observada: até 2026-09-21 11:11:29 UTC.
- `nginx -t` passou e nginx foi recarregado.

## URL final

`https://desktop-cotasync.ferriolimidias.com.br/vnc.html?token=<token>&autoconnect=1&resize=scale`

## Testes executados

- `python3 -m compileall backend frontend scripts tests`: passou.
- `docker compose -f docker-compose.test.yml --env-file .env.test up -d --build`: passou.
- `docker compose ... ps`: todos os serviços em execução; Desktop Browser saudável.
- `curl http://127.0.0.1:8100/health`: `status=ok`.
- `curl http://127.0.0.1:8100/api/health/browserless`: `status=ok`.
- `python -m unittest discover -s tests -v` dentro do backend: 10/10 passaram.
- Testes novos: criação, validação antes da expiração, token inválido, token expirado, domínio público, mascaramento e ausência do token em claro no JSON.
- `scripts/test_demo_v01_cycle.py`: 3 ciclos Browserless passaram.
- `scripts/test_desktop_browser_connection.py`: CDP, noVNC local, operador, aprendizado e replay passaram.
- `nginx -t`: passou antes e depois do Certbot.
- HTTPS `/`: `302` para o CotaSync.
- HTTPS `/vnc.html` sem token: `403`.
- Fluxo público com token: `/vnc.html` `200`, asset via cookie `200`, WebSocket `101`.
- Asset sem token/cookie: `403`.
- Access log FastAPI: token de teste apareceu somente como `token=<masked>`.

## Proteções efetivas

- A página noVNC não abre sem token válido.
- Assets estáticos não são entregues sem token/cookie válido.
- O WebSocket de controle não completa o handshake sem token/cookie válido.
- Tokens expirados são rejeitados e removidos na validação.
- Tokens têm propósito único `desktop_browser_view`.
- Tokens não são gravados em claro no runtime, relatório, nginx ou access log do backend.
- Nenhuma credencial, cookie de sistema externo ou `storage_state` foi adicionada ao commit.

## Limitações

- O armazenamento JSON é adequado ao processo único atual; múltiplas réplicas exigiriam armazenamento compartilhado com controle de concorrência.
- O link pode ser reutilizado até expirar; “single-purpose” significa exclusivo para visualização Desktop, não “single-use”.
- Um WebSocket já estabelecido não é encerrado ativamente no instante da expiração; novas requisições e novos handshakes são rejeitados.
- O `Max-Age` do cookie no template nginx é 1.800 segundos. Se o TTL de ambiente mudar, o template deve ser mantido sincronizado; o backend continua sendo a autoridade de expiração.
- Não foi adicionado login ao app principal, conforme o escopo.

## Teste manual

1. Acesse `https://cotasync.ferriolimidias.com.br`.
2. Selecione Desktop Browser em Configurações, se necessário.
3. Clique em `Abrir Navegador Desktop`.
4. Confirme que aparece a validade do link e clique em `Acessar navegador temporariamente`.
5. Confirme que o noVNC conecta e aceita interação.
6. Abra uma janela anônima diretamente em `https://desktop-cotasync.ferriolimidias.com.br/vnc.html`; deve retornar `403`.
7. Acesse a raiz `https://desktop-cotasync.ferriolimidias.com.br`; deve redirecionar ao CotaSync.
8. Após a expiração, um novo carregamento ou handshake com o link antigo deve retornar `403`; gere outro link no CotaSync.
