# Relatorio - Perfil visivel antes do login

## Contexto

O demo CotaSync precisava mostrar o perfil de acesso do sistema externo antes do login manual, para que o operador confirme a conta Microsoft, identificador e host esperado antes de autenticar e ensinar uma rotina.

## Causa

Em `frontend/app.py`, o bloco "Perfil de acesso da gravação" estava dentro da condicao `status == "autenticada" and not recorded_steps and not saved_action`. Com isso, no estado `aguardando_login`, a UI exibia o sistema externo e a validacao, mas escondia o perfil operacional.

## Correcao

- Extraido `render_access_profile_summary(session, session_id)` para renderizar o perfil externo em modo somente leitura.
- O helper e chamado logo apos a legenda de sistema externo, antes do bloco de login.
- O resumo agora aparece tambem em `aguardando_login`.
- A validacao de completude do perfil continua bloqueando o aprendizado quando os dados obrigatorios nao estao preenchidos.
- Quando o perfil esta incompleto, a UI mostra: "Perfil de acesso incompleto. Configure antes de ensinar uma rotina."

## Comportamento esperado

Para sessoes com sistema externo ativo, a area da demo exibe antes do login:

- Perfil de acesso / operador
- Sistema externo
- Perfil
- Conta Microsoft
- Identificador
- Host esperado

Os campos permanecem desabilitados. A edicao continua concentrada em Configuracoes.

## Validacao

Comandos executados:

```bash
python3 -m compileall backend frontend scripts
docker compose -f docker-compose.test.yml --env-file .env.test up -d --build
docker compose -f docker-compose.test.yml --env-file .env.test ps
curl -sS http://127.0.0.1:8100/health
docker exec cotasync_test_backend python -m unittest tests.test_operational_summary tests.test_guided_learning_outputs tests.test_desktop_action_runner tests.test_access_profile_demo_flow
docker exec cotasync_test_backend python scripts/test_desktop_browser_connection.py
```

Resultados:

- `compileall`: OK
- `docker compose ps`: servicos principais em execucao
- `/health`: `{"status":"ok","service":"cotasync"}`
- Unit tests: 55 testes OK
- Desktop Browser: CDP, noVNC, alvo local, operador fill/click, aprendizado e replay validados

## Limites

- Nao houve redesign da UI.
- Nao houve alteracao em arquitetura de login/navegador.
- Nao houve alteracao em Session Guardian.
- `data/external_systems/current.json` nao foi incluido no commit.
