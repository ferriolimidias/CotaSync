"""
Interface híbrida Streamlit do CotaSync — chat operacional + ações rápidas.

Próxima iteração: consumir `http://localhost:8000` (FastAPI) para eco do agente e webhooks.
"""

from __future__ import annotations

import streamlit as st
from audio_recorder_streamlit import audio_recorder

st.set_page_config(
    page_title="CotaSync - Assistente Operacional",
    layout="wide",
    initial_sidebar_state="expanded",
)

try:
    API_BASE_URL = st.secrets["API_BASE_URL"]
except Exception:
    API_BASE_URL = "http://localhost:8000"

st.title("CotaSync - Assistente Operacional")

# --- Estado da sessão (chat) ---
if "mensagens" not in st.session_state:
    st.session_state.mensagens = [
        {"role": "assistant", "content": "Olá! Sou o assistente operacional. Como posso ajudar hoje?"}
    ]


def _agendamentos_simulados() -> list[dict[str, str]]:
    return [
        {"id": "1", "titulo": "Follow-up Cliente X — 10:00", "status": "pendente"},
        {"id": "2", "titulo": "Cotação fornecedor Y — 14:30", "status": "confirmado"},
        {"id": "3", "titulo": "Revisão cadastro ERP — amanhã 09:00", "status": "pendente"},
    ]


# --- Sidebar ---
with st.sidebar:
    st.header("Ações rápidas")
    cnpj = st.text_input("CNPJ", placeholder="00.000.000/0001-00", key="cnpj_input")
    if st.button("Consultar cadastro", type="primary"):
        doc = (cnpj or "").strip() or "(não informado)"
        st.session_state.mensagens.append(
            {"role": "user", "content": f"Consultar cadastro para o documento: {doc}"}
        )
        st.session_state.mensagens.append(
            {
                "role": "assistant",
                "content": (
                    "Ação registrada na interface. Na próxima iteração isso chamará o "
                    "endpoint do agente (`consultar_cadastro_erp`) no backend."
                ),
            }
        )
        st.rerun()

    st.divider()
    st.subheader("Agendamentos")
    agendamentos = _agendamentos_simulados()
    labels = [f"{a['titulo']} — [{a['status']}]" for a in agendamentos]
    st.selectbox("Selecione um agendamento", options=labels, index=0)
    st.caption("Dados simulados para o layout; depois virão da API/agendador.")

# --- Chat principal ---
st.subheader("Conversa")
for msg in st.session_state.mensagens:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

prompt = st.chat_input("Digite sua mensagem operacional…")
if prompt:
    st.session_state.mensagens.append({"role": "user", "content": prompt})
    st.session_state.mensagens.append(
        {
            "role": "assistant",
            "content": (
                f"Recebi: «{prompt}». "
                f"Integração com o backend em `{API_BASE_URL}` será ligada nas próximas iterações."
            ),
        }
    )
    st.rerun()

# --- Comando de voz (placeholder com biblioteca real) ---
with st.expander("Comando de voz (experimental)", expanded=False):
    st.caption("Gravação local no navegador; transcrição e envio ao agente ainda não conectados.")
    audio_bytes = audio_recorder(text="Gravar / parar", recording_color="#e74c3c", neutral_color="#34495e")
    if audio_bytes:
        st.audio(audio_bytes, format="audio/wav")
        st.info("Áudio capturado. Próximo passo: enviar para serviço de STT e encaminhar o texto ao chat.")
