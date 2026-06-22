# Roteiro CotaSync Demo v0.1

## O que esta demo prova

Em uma única sessão de navegador, o operador faz login manualmente, demonstra uma rotina que não existia, salva os passos capturados e manda o CotaSync repetir a rotina sozinho com outro valor. O replay gera uma run, resultado extraído e screenshot.

O alvo é local, usa somente dados fictícios e não depende de LLM, sistema de cliente ou integração externa.

## Preflight obrigatório

Na raiz do projeto:

```bash
docker compose -f docker-compose.test.yml --env-file .env.test up -d --build
docker compose -f docker-compose.test.yml --env-file .env.test ps
curl -fsS http://127.0.0.1:8100/health
curl -fsS http://127.0.0.1:8100/api/health/browserless
curl -fsS http://127.0.0.1:3100/_stcore/health
docker exec cotasync_test_backend python scripts/test_demo_v01_cycle.py
```

Se a apresentação abrir o CotaSync a partir de outra máquina, configure antes `COTASYNC_BROWSERLESS_PUBLIC_URL` com o endereço público do host e a porta publicada do Browserless. O valor padrão `http://localhost:3010` serve para apresentação local.

O último comando executa três ciclos completos e restaura catálogo, runs e screenshots ao final. Só iniciar a apresentação se terminar com:

```text
Demo v0.1 validada em 3 ciclos consecutivos sem sistema externo.
```

## Roteiro ao vivo — até cinco minutos

1. Abra `http://127.0.0.1:3100` e mantenha o menu **Chat & Ações**.
2. Expanda **Demo v0.1 — Aprender e executar**.
3. Mostre que **Consultar status do pedido** ainda não está no catálogo.
4. Clique em **Abrir sessão de navegador**.
5. Clique em **Abrir navegador da sessão**. Se a página não estiver visível no DevTools, ative **Toggle screencast**.
6. No alvo local, faça o login manual com dados fictícios:
   - usuário: `demo`
   - senha: `demo`
7. Volte ao CotaSync e clique em **Login concluído**. O status deve mudar para **Sessão autenticada**.
8. Clique em **Iniciar gravação**.
9. Na janela do navegador:
   - preencha `PED-1001`;
   - clique em **Pesquisar**;
   - confirme o resultado **Em separação**.
10. Volte ao CotaSync e clique em **Parar gravação**.
11. Mostre o preview com três passos: preencher, clicar e extrair texto. O login e a senha não podem aparecer.
12. Mantenha o nome **Consultar status do pedido** e a variável sugerida para o campo.
13. Clique em **Salvar ação aprendida**. A ação deve aparecer no catálogo sem alteração de Python.
14. No bloco **Replay autônomo**, informe `PED-2002`.
15. Clique em **Executar ação aprendida**.
16. Mostre:
    - status de sucesso e ID da run;
    - se o status interno tiver expirado, a mensagem **Sessão revalidada automaticamente.**;
    - resultado extraído `status_pedido: Enviado`;
    - screenshot final do replay;
    - campo da página alterado para `PED-2002` sem intervenção humana.
17. Clique em **Encerrar sessão da demo**.

## Frase de apresentação

“O login fica com o humano. Depois dele, o CotaSync observa uma rotina nova, transforma a demonstração em passos estruturados e a repete sozinho na mesma sessão, com run e evidência.”

## Critérios de sucesso

- A sessão possui ID e live view.
- A senha não aparece nos passos, arquivos ou logs.
- A ação é criada durante a apresentação.
- `data/ui_map.json` recebe passos estruturados e uma variável.
- O replay usa `PED-2002`, diferente do ensino com `PED-1001`.
- Antes do replay, a sessão é revalidada pela página CDP ativa e, se necessário, pelo `storage_state` salvo durante o login.
- A run termina em `success` e extrai `Enviado`.
- O PNG associado à run é exibido.

## Go/no-go e recuperação

Abortar a execução ao vivo se:

- Browserless não abrir em duas tentativas;
- a live view não aceitar interação;
- **Login concluído** não reconhecer a página autenticada;
- o preview não tiver os três passos esperados;
- o replay não gerar run e screenshot.

Recuperação segura:

1. Clique em **Encerrar sessão da demo**.
2. Recarregue o Streamlit.
3. Execute novamente o preflight de três ciclos.
4. Não substitua o alvo local por um sistema real durante a apresentação.

## Limites intencionais da v0.1

- Uma sessão assistida por vez na apresentação.
- Sessões vivem em memória e terminam com o backend.
- O `storage_state` fica somente em `data/demo_sessions/<session_id>/` durante a sessão e é removido ao encerrá-la.
- O recorder cobre preenchimento, clique, Enter e saída marcada pelo alvo.
- O fluxo antigo de chat/Cartógrafo permanece separado.
- Sem multiusuário, SaaS, Postgres definitivo, fila ou integrações externas.
