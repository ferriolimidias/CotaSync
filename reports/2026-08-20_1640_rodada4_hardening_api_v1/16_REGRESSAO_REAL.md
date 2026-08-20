# Regressão Real

Desktop browser:
- comando: `sudo -n docker exec cotasync_test_backend python scripts/test_desktop_browser_connection.py`.
- resultado: `runner=desktop_browser_replay`, `whether_desktop_browser_used=True`, `status=success`.
- resultado extraído: `status_pedido:Enviado`.

Arquivo: `backend/services/action_runner.py`
Função/endpoint: replay desktop intacto.
Antes: Rodada 3 validada.
Depois: segue funcionando após API v1 e hardening.
Motivo: garantir que não houve regressão no motor.
Impacto: browser CDP/noVNC/replay OK.
Teste: smoke real.
Resultado: success.
Risco restante: ação `quantidade-de-parcelas` não executada por segurança; ver relatório 13.
