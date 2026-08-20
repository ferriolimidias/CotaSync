# Streamlit Compatibilidade

Arquivo: endpoints antigos `/api/clients`, `/api/actions`, `/api/batches`, `/api/browser/status`
Função/endpoint: compatibilidade Streamlit.
Antes: Streamlit usa endpoints antigos.
Depois: endpoints antigos permanecem; v1 é contrato oficial novo.
Motivo: não importar React nesta rodada e não quebrar operação temporária.
Impacto: transição gradual.
Teste: login e chamadas HTTP reais.
Resultado:
- frontend `http://127.0.0.1:3100/`: 200.
- `/api/clients`: 200.
- `/api/actions`: 200.
- `/api/batches`: 200.
- `/api/browser/status`: 200.
- `/api/v1/worker/status`: 200.
Risco restante: Streamlit ainda não foi migrado para usar v1 internamente.
