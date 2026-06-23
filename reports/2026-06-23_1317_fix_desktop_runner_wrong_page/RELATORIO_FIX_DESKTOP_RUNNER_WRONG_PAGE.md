# Relatorio: correcao do runner desktop em pagina incorreta

Data: 2026-06-23 13:17 BRT
Commit base: `90865780868892a18edbc6a57e6a7a2e01a8e2ce`

## Causa

O fast-track ignorava os metadados `browser_mode` e `url_inicial` da acao. Ele sempre conectava diretamente ao Browserless, criava uma pagina nova e navegava para o ERP global. Quando nao havia ERP configurado, o fallback era Google. O resultado nao validava o host final e, por isso, uma execucao em `google.com` podia ser persistida como sucesso.

O replay assistido tambem aceitava qualquer pagina HTTP em sessoes externas confirmadas manualmente, sem uma validacao final do host da acao.

## Correcao

- Os metadados `browser_mode` e `url_inicial` passaram a fazer parte do contrato carregado pelo repositorio de acoes.
- Acoes `desktop_browser` usam `DesktopBrowserProvider` via CDP; o fluxo Browserless existente permanece separado.
- Foi adicionada a resolucao de hosts esperados a partir de `url_inicial`, `redirect_uri` do login externo e configuracao corrente do mesmo sistema externo.
- A pagina desktop e escolhida por correspondencia com o host da acao. Se a pagina ativa for Google, vazia ou de outro host, ela navega para `url_inicial` antes do replay.
- O host e validado antes, durante e depois dos passos, inclusive em popup/nova aba.
- Redirecionamentos de autenticacao Microsoft, incluindo `login.microsoftonline.com` e `m365.cloud.microsoft`, produzem erro operacional de reautenticacao.
- O `action_runner` faz uma validacao defensiva da pagina final antes de marcar a run como sucesso.
- Falhas desktop nao acionam o auto-healing Browserless nem alteram a receita gravada.
- Runs com erro de pagina sao persistidas com diagnostico tecnico contendo somente motivo e host; nenhum seletor, token ou credencial e exibido no resumo operacional.
- A UI ja exibia `run.operational_summary` com `st.success`/`st.error`; nao foi necessaria alteracao de framework ou fluxo frontend.

## Comportamento do runner

- Pagina no host esperado: executa `robust_steps` (ou `passos_playwright` como fallback), valida o host final e pode concluir com: `Ação executada com sucesso. A tela solicitada foi aberta, mas nenhum dado foi configurado para extração.`
- Pagina Google/about:blank/outro host: navega para `url_inicial`; se o host esperado nao for atingido, a run termina em `error`.
- Redirecionamento para login Microsoft: termina em `error` com: `Não consegui executar a ação porque a sessão precisa ser autenticada novamente.`
- Browserless: continua usando pagina isolada e o login automatico do ERP configurado.

## Testes

- `python3 -m compileall backend frontend scripts`: passou.
- `docker compose -f docker-compose.test.yml --env-file .env.test up -d --build`: passou.
- `docker compose -f docker-compose.test.yml --env-file .env.test ps`: backend, frontend, Browserless, desktop browser, Redis e servicos preexistentes ativos; desktop browser healthy.
- `curl -s http://127.0.0.1:8100/health`: `status=ok`.
- `docker exec cotasync_test_backend python -m unittest discover -s tests -v`: 26 testes passaram.
- `docker exec cotasync_test_backend python scripts/test_demo_v01_cycle.py`: 3 ciclos Browserless e regressao de revalidacao passaram.
- `docker exec cotasync_test_backend python scripts/test_desktop_browser_connection.py`: CDP, noVNC, operador, aprendizado e replay desktop passaram.

Cobertura nova:

1. Acao desktop nao pode concluir em Google.
2. Pagina Google navega para `url_inicial` antes do replay.
3. Redirecionamentos Microsoft exigem reautenticacao manual.
4. Host final incorreto gera `status=error` e diagnostico seguro.
5. A run criada por `POST /api/actions/{id}/run` aparece em `GET /api/runs`.
6. Provider Browserless e URL de tracking continuam inalterados.

## Validacao manual de Teste2

O endpoint real criou a run `f0f33cf7-304b-494b-852a-5eca5e08d0a3`, anexou ao navegador desktop e tentou abrir a URL inicial. O sistema redirecionou para `m365.cloud.microsoft`; a run foi corretamente persistida como `error`, com um diagnostico e o resumo operacional de reautenticacao. A consulta subsequente a `/api/runs` confirmou a persistencia da run.

Comando:

```bash
curl -sS -X POST http://127.0.0.1:8100/api/actions/teste2/run \
  -H 'Content-Type: application/json' \
  -d '{"variables":{},"mode":"sync","requested_by":"manual-validation"}' | python3 -m json.tool
```

Proximo passo operacional: autenticar manualmente a sessao pelo noVNC e executar `Teste2` novamente. O sucesso so sera aceito se a pagina final continuar em `nwcweb.randonconsorcios.com.br`.
