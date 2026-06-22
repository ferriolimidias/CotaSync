# Relatório — Desktop Browser Worker MVP

Data: 2026-06-22 18:54 America/Sao_Paulo

## Arquitetura escolhida

Foi adicionado o provider `desktop_browser` ao lado do provider `browserless`. O `DemoSessionManager` seleciona o provider ao criar a sessão e mantém o mesmo pipeline existente de login confirmado, recorder, observador de IA, Modo operador, persistência de sessão e replay.

O worker `cotasync_test_desktop_browser` é um contêiner Debian com Chromium, Xvfb, Openbox, x11vnc e noVNC/websockify. Chromium roda com interface gráfica e perfil persistente. Um proxy TCP interno publica o CDP loopback do Chromium para a rede Docker. Não foram implementados stealth, spoofing, troca de user-agent, proxy, evasão ou bypass de WAF.

## Docker, portas e persistência

- serviço: `cotasync_test_desktop_browser`
- noVNC: contêiner `6080`, host `127.0.0.1:3200`
- CDP: Chromium `127.0.0.1:9223`, proxy interno `0.0.0.0:9222`, host `127.0.0.1:9222`
- CDP usado pelo backend: `http://cotasync_test_desktop_browser:9222`
- perfil: `/data/profile`
- volume: `cotasync_test_desktop_browser_profile`
- memória compartilhada: 2 GiB
- política Chromium: password manager desabilitado

O compose mantém Browserless ativo e inalterado. noVNC e CDP são publicados somente em loopback.

## Variáveis de ambiente

- `COTASYNC_BROWSER_MODE=browserless|desktop_browser`
- `DESKTOP_BROWSER_CDP_URL=http://cotasync_test_desktop_browser:9222`
- `DESKTOP_BROWSER_VIEW_URL=http://127.0.0.1:3200/vnc.html?autoconnect=1&resize=scale`
- `DESKTOP_BROWSER_PROFILE_DIR=/data/profile`
- `DESKTOP_BROWSER_VIEW_PORT=3200`
- `DESKTOP_BROWSER_CDP_PORT=9222`

Somente `.env.test.example` foi alterado; nenhum segredo de `.env.test` foi commitado.

## Operação

Para acesso local no VPS, abrir `http://127.0.0.1:3200/vnc.html?autoconnect=1&resize=scale`. De outra máquina, criar túnel SSH para as portas 3100 e 3200. Em Configurações, selecionar Desktop Browser e verificar `running` e `CDP reachable`. A ação **Abrir sessão de navegador** anexa ao Chromium persistente e navega para `external_login_url`; **Abrir Navegador Desktop** abre o noVNC.

Após login manual, **Login concluído** valida o seletor/texto configurado ou a confirmação manual. Gravação, observador, operador e replay usam a página/contexto CDP desse mesmo perfil. Ações desktop recebem `learning_mode=desktop_browser_live_ai_observed`; Browserless continua usando `human_demo_live_ai_observed`.

## Testes executados

- `python3 -m compileall backend frontend scripts tests`: aprovado.
- `python3 -m unittest discover -s tests -v`: 5 testes aprovados.
- `docker compose -f docker-compose.test.yml --env-file .env.test up -d --build`: aprovado após validação da imagem.
- `docker compose ... ps`: todos os seis serviços ativos; desktop browser e Postgres saudáveis.
- `curl http://127.0.0.1:8100/health`: `status=ok`.
- `curl http://127.0.0.1:8100/api/health/browserless`: `status=ok`.
- `curl http://127.0.0.1:8100/api/health/desktop-browser`: worker rodando e CDP acessível, Chrome 149.
- noVNC `http://127.0.0.1:3200/vnc.html`: HTTP 200.
- CDP `http://127.0.0.1:9222/json/version`: protocolo 1.3 disponível.
- `docker exec cotasync_test_backend python scripts/test_demo_v01_cycle.py`: 3 ciclos Browserless aprovados, incluindo storage state e replay.
- `docker exec cotasync_test_backend python scripts/test_desktop_browser_connection.py`: aprovado duas vezes consecutivas; validou CDP, noVNC, alvo local, fill/click, gravação, observer, salvamento e replay.
- `curl -I https://cotasync.ferriolimidias.com.br`: HTTP 200.

Nenhuma credencial externa real foi usada.

## Teste manual do login externo

1. Criar túnel: `ssh -L 3100:127.0.0.1:3100 -L 3200:127.0.0.1:3200 usuario@vps`.
2. Abrir `http://127.0.0.1:3100`, entrar em Configurações e selecionar Desktop Browser.
3. Configurar o nome e a URL de login externos, preferencialmente com seletor/texto pós-login.
4. Em Chat & Ações, abrir uma sessão.
5. Abrir o Desktop Browser e concluir o login manual, inclusive Microsoft/MFA quando solicitado.
6. Não salvar senha no navegador.
7. Clicar em Login concluído e confirmar status autenticado.
8. Iniciar gravação, demonstrar uma rotina sem dados sensíveis, parar e salvar.
9. Executar replay na mesma sessão e confirmar resultado/evidência.
10. Reiniciar apenas o backend, se desejado, e confirmar que o worker/perfil permanecem ativos.

## Riscos e limites

- noVNC não tem autenticação e tráfego local é HTTP; deve permanecer em loopback/túnel SSH.
- CDP permite controle total e também deve permanecer em loopback/rede Docker.
- o perfil contém cookies/tokens de sessão; volume e backups exigem acesso restrito e nunca devem ser commitados.
- o worker usa `--no-sandbox` porque namespaces não privilegiados são bloqueados neste VPS; o isolamento fica a cargo do contêiner e do host.
- um worker representa uma única estação interativa; concorrência multiusuário não faz parte do MVP.
- uma atualização do Chromium ou mudança no login externo pode exigir nova validação.
- confirmação manual sem seletor/texto é menos forte que um marcador pós-login explícito.
- nenhuma garantia pode ser dada para políticas do sistema externo.

## Probabilidade de resolver o bloqueio

É provável que ajude quando o bloqueio é específico da infraestrutura Browserless/sessões remotas efêmeras: agora o login ocorre em Chromium desktop normal, visual, persistente e operado por uma pessoa. Não é garantia. O sistema externo ainda pode aplicar regras de rede, geolocalização, dispositivo, tenant ou política corporativa. Esta implementação não tenta contornar essas regras.

## Próximos passos

1. Fazer o teste manual real com login Microsoft e MFA, sem compartilhar credenciais.
2. Definir marcador pós-login robusto para o sistema externo.
3. Restringir acesso ao volume e estabelecer backup criptografado, se necessário.
4. Para subdomínio público, revisar o template `cotasync-browser.ferriolimidias.com.br`, adicionar autenticação, TLS e política de acesso antes de habilitar Nginx; Certbot não foi executado.
5. Se houver concorrência, criar um worker/perfil por operador em vez de compartilhar a mesma estação.
