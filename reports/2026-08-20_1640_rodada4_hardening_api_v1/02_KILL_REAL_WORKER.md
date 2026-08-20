# Kill Real Worker

Arquivo: `backend/services/action_runner.py`
Função/endpoint: `_run_local_fixture`
Antes: fixture local era imediata.
Depois: fixture local pode dormir quando `COTASYNC_ENABLE_SLOW_FIXTURE=true` e variável `__sleep_seconds` é enviada.
Motivo: criar janela real para matar o worker sem sistema externo.
Impacto: apenas ações `local_fixture`; default desativado.
Teste: container `cotasync_test_worker` morto com `docker kill`.
Resultado: recovery seguro.
Risco restante: não valida efeito de um click externo real em andamento.

Timeline:
- T0: batch `037f075d-04c1-4fcd-8040-39112fd56e41` criado.
- T1: `poll-1`: item 1 `success`, item 2 `running`, item 3 `pending`.
- T2: `docker kill cotasync_test_worker`.
- T3: aguardado stale com heartbeat/stale de teste `1s/3s`.
- T4: worker reiniciado.
- T5: startup recovery marcou item 2 como `interrupted`.
- T6: item 3 executou; batch final `completed_with_errors|3|2|0|1|0`.

Evidência:
- item 2 `error_data.reason=stale_running_item`.
- run para `kill-2`: uma única run, status `running`, sem segunda execução automática.
