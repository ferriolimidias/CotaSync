# Desktop Browser Worker

O modo `desktop_browser` usa Chromium normal com interface gráfica, perfil persistente e login manual. Não inclui stealth, alteração de fingerprint, proxy ou bypass de segurança.

## Serviços e endereços

- noVNC no host: `http://127.0.0.1:3200/vnc.html?autoconnect=1&resize=scale`
- CDP no host: `http://127.0.0.1:9222`
- CDP para o backend: `http://cotasync_test_desktop_browser:9222`
- perfil no worker: `/data/profile`
- volume: `cotasync_test_desktop_browser_profile`

As portas 3200 e 9222 são publicadas somente em loopback. Para operar de outra máquina, use um túnel SSH:

```bash
ssh -L 3100:127.0.0.1:3100 -L 3200:127.0.0.1:3200 usuario@vps
```

Depois abra o CotaSync em `http://127.0.0.1:3100` e o noVNC em `http://127.0.0.1:3200/vnc.html?autoconnect=1&resize=scale`.

## Configuração

```dotenv
COTASYNC_BROWSER_MODE=desktop_browser
DESKTOP_BROWSER_CDP_URL=http://cotasync_test_desktop_browser:9222
DESKTOP_BROWSER_VIEW_URL=http://127.0.0.1:3200/vnc.html?autoconnect=1&resize=scale
DESKTOP_BROWSER_PROFILE_DIR=/data/profile
```

O modo também pode ser escolhido em **Configurações > Navegador**. A escolha da UI vale para novas sessões e é gravada em `data/browser_config.json`; sem esse arquivo, vale `COTASYNC_BROWSER_MODE`.

## Fluxo manual

1. Configure `external_system_name`, `external_login_url` e, se disponível, um seletor/texto de sucesso.
2. Selecione `desktop_browser` e confirme que worker e CDP aparecem disponíveis.
3. Em Chat & Ações, clique em **Abrir sessão de navegador**.
4. Clique em **Abrir Navegador Desktop** e faça o login manual no noVNC.
5. Não aceite salvar senha no navegador. O password manager também é desabilitado por política.
6. Volte ao CotaSync e clique em **Login concluído**.
7. Grave a rotina, use o Modo operador quando necessário e execute o replay na mesma sessão/perfil.

## Validação sem credenciais reais

```bash
docker exec cotasync_test_backend python scripts/test_desktop_browser_connection.py
```

O script usa apenas `/demo/alvo` e valida CDP, noVNC, operador, gravação, ação aprendida e replay.

## Segurança e limites

noVNC não possui autenticação no MVP e CDP concede controle total do navegador; mantenha ambos em loopback e use túnel SSH. O volume contém cookies e sessões e deve ter acesso e backups restritos. O Chromium usa `--no-sandbox` dentro do contêiner porque o VPS bloqueia namespaces não privilegiados; o isolamento depende do contêiner/host. O MVP pressupõe um operador e uma sessão interativa por worker.

O template `deploy/nginx/cotasync-browser.ferriolimidias.com.br.conf` é somente para uma fase futura. Antes de habilitá-lo, adicionar TLS e controle de acesso.
