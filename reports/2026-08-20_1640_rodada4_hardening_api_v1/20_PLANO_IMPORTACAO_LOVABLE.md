# Plano Importação Lovable

Estrutura recomendada:
- manter `frontend/` para Streamlit temporário nesta transição.
- importar o React em `frontend-react/` na próxima rodada.
- criar `frontend-react/src/services/api.ts` apontando para `/api/v1`.
- criar tipos TypeScript a partir de `docs/frontend_api_contract.md` e OpenAPI.
- configurar build estático em serviço/container próprio depois da validação local.

Passos:
1. Receber pacote real Lovable do usuário.
2. Colocar em `frontend-react/`, sem sobrescrever Streamlit.
3. Mapear auth cookie/CSRF.
4. Implementar services para dashboard, clients, actions, learning, browser, batches, worker, reports e diagnostics.
5. Adaptar BrowserWorkspace para `POST /api/v1/browser/view-token`.
6. Adaptar OperatorAssistant para `/api/v1/learning/sessions/{id}/operator/*`.
7. Migrar batches para polling em `/api/v1/batches/{id}`.
8. Validar visual, fluxos e regressão desktop.
9. Só então decidir retirada do Streamlit.

Preservar:
- identidade visual aprovada.
- padrão gráfico.
- qualidade visual.

Não preservar cegamente:
- mocks.
- services falsos.
- nomes de rota que conflitem com produto correto.
