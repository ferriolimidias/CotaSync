# Pendências Frontend

O frontend React/Lovable não foi importado nesta rodada.

Arquivo: `docs/frontend_api_contract.md`
Função/endpoint: contrato para próxima rodada.
Antes: sem contrato consolidado.
Depois: contrato v1 documentado.
Motivo: preparar importação sem copiar frontend inexistente na VPS.
Impacto: próxima rodada pode mapear hooks/services contra `/api/v1`.
Teste: documentação e OpenAPI.
Resultado: OK.
Risco restante: ajustes reais surgirão quando o código Lovable for entregue.

Regra da próxima rodada:
O frontend visual é base visual, não contrato técnico imutável. Pode alterar páginas, hooks, services, rotas, estados, tabelas, BrowserWorkspace e OperatorAssistant, preservando identidade visual.
