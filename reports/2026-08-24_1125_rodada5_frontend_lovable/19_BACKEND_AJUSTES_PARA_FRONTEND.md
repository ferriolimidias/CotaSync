# Backend Ajustes Para Frontend

Arquivos alterados: `backend/api/v1.py`, `backend/api/demo.py`.

Ajustes: fachada `POST /api/v1/actions/{action_id}/run`; `OperatorInsertActiveRequest` aceita `variable_key` opcional e v1 ecoa o metadado sem armazenar valor sensível.

Sem nova arquitetura paralela.

Contexto: Rodada 5 importou `/home/joseadmin/front.zip` para `frontend-react/`, preservando o Streamlit em `frontend/` durante a transição.

