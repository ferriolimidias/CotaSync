# Validacao Real Controlada

## Objetivo

Confirmar que o replay real `desktop_browser_replay` continua funcionando depois da remocao de Browserless, fast-track e Redis, e depois do hardening de autenticacao/API.

## Script usado

`scripts/test_desktop_browser_connection.py`

Alteracao feita:

Arquivo: `scripts/test_desktop_browser_connection.py`
Funcao/servico: smoke/integracao desktop browser.
Como era: chamava endpoints administrativos anonimamente e fazia replay vinculado a `session_id`.
Como ficou: autentica como admin via env, envia cookie/CSRF e executa o replay final sem `session_id`, acionando `desktop_browser_replay`.
Por que foi alterado: endpoints estao protegidos e o criterio de aceite exige runner desktop real.
O que foi removido: dependencia de acesso anonimo e replay de demo session no teste final.
Impacto: smoke valida o caminho real endurecido.
Teste realizado: execucao no container backend.
Resultado: sucesso.
Risco restante: o smoke usa alvo local de demo, nao um sistema externo real com credenciais de cliente.

## Resultado final

```text
run_id=d6caf738-4c26-403d-ad1f-5a5445b5bd23
runner=desktop_browser_replay
whether_desktop_browser_used=True
status=success
resultado=status_pedido:Enviado
```

## Fluxo validado

- Login autenticado do CotaSync.
- CSRF em mutacoes.
- CDP acessivel internamente ao backend.
- noVNC interno respondendo.
- Criacao de sessao demo.
- Confirmacao de login local.
- Gravacao mecanica de fill/click/extracao.
- Salvamento de acao aprendida.
- Replay direto via `desktop_browser_replay`.
- Health desktop browser OK.

## Dados operacionais

O script preserva/restaura arquivos operacionais rastreados durante a execucao:

- `data/browser_config.json`
- `data/external_systems/current.json`
- `data/ui_map.json`
- `data/runs/runs.json`

Arquivos operacionais locais nao foram commitados.

