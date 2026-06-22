# Relatório — correção da entrada do operador no navegador da sessão

Data: 2026-06-22 14:41 (America/Sao_Paulo)

## Resultado

O fluxo demonstrado passou a ter um caminho de entrada confiável sem console. A janela Browserless/DevTools continua disponível como caminho preferencial. Quando o encaminhamento de teclado do screencast remoto falhar, o operador usa o novo **Modo operador** na UI do CotaSync para preencher e clicar na página ativa; essas operações geram eventos Playwright/DOM normais e são capturadas pelo mesmo recorder e observador de IA.

## Causa raiz

A sessão e o target CDP estavam corretos: o `target_id` retornado pela criação da sessão existia no Browserless, a página ativa era `/demo/alvo` e a URL pública apontava ao target atual. Também não havia mistura entre o WebSocket interno do backend e o host público do usuário.

O link, porém, abre o frontend genérico `devtools/inspector.html`. A interação ocorre no screencast do DevTools e o encaminhamento de teclado depende do estado de foco/implementação da versão Chromium/DevTools servida pelo Browserless. Cliques e foco chegavam ao target, mas o teclado não era encaminhado de forma confiável. Essa camada fica fora do controle do recorder da página e não oferece garantia operacional para a demo.

## Correção escolhida

Foi aplicada a opção B prevista no escopo:

- mantida a URL direta do DevTools como primeira opção;
- adicionado aviso: “Se a janela remota não aceitar teclado, use Modo operador.”;
- adicionado Modo operador durante a gravação, com:
  - seletor e valor para preenchimento;
  - botão `Preencher campo no navegador`;
  - seletor para clique;
  - botão `Clicar elemento`;
- as ações atuam na `session.page` ligada ao target CDP atual;
- somente seletores únicos, visíveis e habilitados são aceitos;
- seletores sensíveis são bloqueados;
- o valor preenchido não é retornado nem escrito em logs;
- o recorder continua removendo o valor demonstrado da receita e preservando apenas variável/template;
- o observador OpenAI por evento e a síntese final permanecem ativos.

## URL pública e URL interna

- O backend continua conectando ao Browserless por `BROWSERLESS_URL`, usando a rede interna Docker.
- O link aberto pelo usuário continua sendo construído por `COTASYNC_BROWSERLESS_PUBLIC_URL` quando configurada, com host/porta acessíveis pelo navegador do operador.
- O target é atualizado por `_set_active_page` quando a página ativa muda.
- O diagnóstico seguro informa `session_id`, `target_id/page_id`, URL atual sanitizada, quantidade de páginas, tipo da live URL e se a URL pública está configurada. Nenhuma chave OpenAI, credencial ou URL WebSocket interna é exposta.

Endpoint: `GET /api/demo/sessions/{session_id}/operator-diagnostics`.

## Arquivos alterados

- `backend/api/demo.py`
- `backend/services/demo_session.py`
- `frontend/app.py`
- `scripts/test_demo_v01_cycle.py`

## Testes

- `python3 -m compileall backend frontend scripts` — passou.
- `docker compose -f docker-compose.test.yml --env-file .env.test up -d --build` — passou.
- `docker compose -f docker-compose.test.yml --env-file .env.test ps` — serviços ativos; Postgres saudável.
- `curl -s http://127.0.0.1:8100/health` — `status=ok`.
- `curl -s http://127.0.0.1:8100/api/health/browserless` — `status=ok`.
- `curl -I http://127.0.0.1:3100` — HTTP 200.
- `docker exec cotasync_test_backend python scripts/test_demo_v01_cycle.py` — passou:
  - diagnóstico do target e da live URL validado;
  - primeiro ciclo executou preenchimento e clique pelos mesmos endpoints do Modo operador usados pela UI;
  - recorder capturou `preencher`, `clicar` e `extrair_texto`;
  - ação salva manteve `learning_mode=human_demo_live_ai_observed`;
  - síntese OpenAI, três ciclos de replay e revalidação CDP/storage state passaram.

## Passos humanos para a demo

1. Em **Chat & Ações**, clicar em **Abrir sessão de navegador**.
2. Abrir **Abrir navegador da sessão**, fazer login com as credenciais fictícias da demo e confirmar **Login concluído**.
3. Clicar em **Iniciar gravação**.
4. Tentar a interação direta na janela remota: clicar em `#pedido-codigo`, digitar `PED-1001` e clicar em `#buscar-pedido`.
5. Se o teclado remoto não responder, abrir **Modo operador** no CotaSync:
   - manter `#pedido-codigo`, informar `PED-1001` e clicar em **Preencher campo no navegador**;
   - manter `#buscar-pedido` e clicar em **Clicar elemento**.
6. Verificar o resultado na janela remota e clicar em **Parar gravação**.
7. Salvar a ação, confirmar a síntese da IA e executar o replay.

Não é necessário abrir console ou executar JavaScript manualmente.
