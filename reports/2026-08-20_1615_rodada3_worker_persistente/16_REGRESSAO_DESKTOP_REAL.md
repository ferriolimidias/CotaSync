# Regressão Desktop Real

Comando:
`sudo -n docker exec cotasync_test_backend python scripts/test_desktop_browser_connection.py`

Resultado:
- `runner=desktop_browser_replay`
- `whether_desktop_browser_used=True`
- `status=success`
- `resultado=status_pedido:Enviado`

Arquivo: `scripts/test_desktop_browser_connection.py`
Antes: smoke real já validava CDP/noVNC/alvo local/replay.
Depois: continua passando com worker persistente no compose.
Motivo: garantir que o worker não quebrou desktop browser.
Banco/estado afetado: smoke pode criar run própria; não altera dados externos reais.
Transação: runs normais do action runner.
Recovery: não aplicável ao smoke individual.
Risco restante: ação real `quantidade-de-parcelas` foi bloqueada por segurança porque a versão publicada não tem `initial_url` e não tem `robust_steps`.

Batch real seguro:
- batch: `f55bb4b9-8bff-4be0-88a9-c563243dc4b0`
- clientes/linhas: 2
- resultado: `completed`, 2 success
- dados: `status_pedido=Pedido não encontrado` para ambos.
