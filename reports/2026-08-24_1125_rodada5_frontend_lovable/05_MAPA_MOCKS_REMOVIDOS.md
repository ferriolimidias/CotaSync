# Mocks Removidos

Removidos: `src/lib/mock-data.ts`, componente antigo `ActionCard` com JSON mock, uso de `mockClients`, `mockActions`, `mockExecutions`, `mockSchedules`, números fixos do dashboard, batches fake, relatórios fake e scheduler fake.

Busca final: não há `mock`, `dummy`, `fake`, Supabase, Firebase, localStorage ou sessionStorage no código funcional. O único `setTimeout` remanescente é timeout real centralizado da API.

Contexto: Rodada 5 importou `/home/joseadmin/front.zip` para `frontend-react/`, preservando o Streamlit em `frontend/` durante a transição.

