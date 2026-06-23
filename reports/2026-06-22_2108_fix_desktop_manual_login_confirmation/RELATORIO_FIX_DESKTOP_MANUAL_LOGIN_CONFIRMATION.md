# Relatório — correção da confirmação manual de login no Desktop Browser

Data: 2026-06-22 21:08 -03
Commit base: `c7e1d1e1e8104d4131c2889b423bb5f081218d7e`

## Causa

O endpoint `POST /api/demo/sessions/{session_id}/confirm-login` delegava a validação ao `DemoSessionManager`, mas o fluxo externo sem texto/seletor ainda limitava a página confirmada à mesma origem da URL inicial de login. Logins federados que terminavam em outra origem eram rejeitados mesmo após a confirmação humana.

Além disso, o modo de validação era apenas inferido pela presença de `auth_success_text` ou `auth_success_selector`; não existia suporte persistido para selecionar explicitamente `manual_confirmation`.

## Correção

- Adicionado o campo opcional `validation` à configuração do sistema externo.
- `manual_confirmation` agora tem precedência explícita sobre texto/seletor configurados.
- Na ausência de texto e seletor, o modo continua sendo manual por compatibilidade.
- A confirmação manual aceita uma página HTTP(S) viva, com URL não vazia, título não vazio ou URL diferente da inicial, sem textos conhecidos de bloqueio.
- A validação manual não restringe a página à origem inicial, permitindo redirecionamentos de autenticação federada.
- Modos automáticos continuam exigindo seletor visível ou texto configurado.
- Após sucesso, a sessão salva `storage_state`, URL e título confirmados e expõe a referência do perfil persistente no modo desktop.
- A UI informa exatamente: “Validação manual: ao clicar em Login concluído, esta página será aceita como sessão autenticada.”

## Regressão adicionada

O teste de conexão desktop agora configura um sistema externo com `validation=manual_confirmation`, mantém texto/seletor inválidos para comprovar a precedência manual, navega para uma fixture local intitulada “Intranet Newcon”, confirma o login, verifica status `autenticada`, storage state, URL/título salvos e inicia a gravação imediatamente.

O ciclo local passou a selecionar Browserless de forma determinística e restaurar a configuração anterior, evitando dependência de `.env.test` ou da ordem dos testes.

## Arquivos alterados

- `backend/api/demo.py`
- `backend/api/external_systems.py`
- `backend/services/demo_session.py`
- `backend/services/external_systems.py`
- `frontend/app.py`
- `scripts/test_demo_v01_cycle.py`
- `scripts/test_desktop_browser_connection.py`

`data/external_systems/current.json` já continha alteração local do usuário e não faz parte da correção nem do commit.

## Validação executada

- `python3 -m compileall backend frontend scripts` — passou.
- `docker compose -f docker-compose.test.yml --env-file .env.test up -d --build` — passou.
- `docker compose -f docker-compose.test.yml --env-file .env.test ps` — serviços ativos; Desktop Browser saudável.
- `curl -s http://127.0.0.1:8100/health` — `{"status":"ok","service":"cotasync"}`.
- `docker exec cotasync_test_backend python scripts/test_demo_v01_cycle.py` — passou em três ciclos, incluindo replay, revalidação CDP e restauração de storage state.
- `docker exec cotasync_test_backend python scripts/test_desktop_browser_connection.py` — passou, incluindo a nova regressão manual e o ciclo local desktop completo.

O host não possui o módulo `pytest`; essa verificação adicional não foi executada. Os testes obrigatórios acima rodaram no container do backend com as dependências do projeto.

## Passos manuais

1. Em Configurações, selecione `manual_confirmation` para o sistema externo e salve.
2. Crie uma sessão em Desktop Browser e conclua o login no sistema externo.
3. Confirme que a UI mostra URL/título da página final e a mensagem de validação manual.
4. Clique em **Login concluído**.
5. Confirme o status **Sessão autenticada** e inicie a gravação imediatamente.

## Limites preservados

Não foram adicionados stealth, bypass, spoofing, segredos, cookies ou storage state versionados. Não houve alteração em OmniBid, Evolution ou Hermes, nem introdução de framework de UI ou dependência de Postgres para esta correção.
