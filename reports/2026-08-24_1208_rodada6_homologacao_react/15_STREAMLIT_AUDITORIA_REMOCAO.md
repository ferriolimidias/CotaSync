# Streamlit Auditoria Remoção

Antes: `frontend/`, serviço `cotasync_test_frontend`, porta `127.0.0.1:3100`, dependências `streamlit`, `audio-recorder-streamlit`, `streamlit-option-menu` e contrato HTTP legado consumido pelo Streamlit.

Critério: remover somente quando React cobrir e tiver homologação real de aprendizado, browser, execução individual, batch, cancelamento, resultados, sessão externa e ação segura.

Decisão: não remover nesta rodada porque a homologação real externa e a ação histórica `quantidade-de-parcelas` seguem bloqueadas.

Estado final: Streamlit preservado temporariamente e documentado como dependência de fallback até a homologação real.
