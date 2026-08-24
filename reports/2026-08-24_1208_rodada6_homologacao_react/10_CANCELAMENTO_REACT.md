# Cancelamento React

Endpoint: `POST /api/v1/batches/{batch_id}/cancel`.

UI: botão `Cancelar execução` mantém a mensagem de que a execução atual será concluída e os próximos clientes serão cancelados.

Teste: contrato backend de cancel-after-current permanece coberto pela suíte. Teste visual E2E não disparou lote real para evitar efeito operacional externo.

Estado final: integrado, pendente de homologação operacional em lote real seguro.
