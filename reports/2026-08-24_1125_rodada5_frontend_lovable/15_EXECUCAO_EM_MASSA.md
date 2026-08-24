# Execução Em Massa

API: `/api/v1/batches`, `/api/v1/batches/{id}`, `/api/v1/batches/{id}/cancel`.

Fluxo implementado: escolher ação, grupo/lista, revisar quantidade, criar batch, polling de progresso e cancelamento após cliente atual.

Polling: 2,5s e encerra em status final. Concorrência não é exibida; interface afirma 1 cliente por vez.

Contexto: Rodada 5 importou `/home/joseadmin/front.zip` para `frontend-react/`, preservando o Streamlit em `frontend/` durante a transição.

