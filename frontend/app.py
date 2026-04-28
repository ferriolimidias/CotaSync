"""
Interface híbrida Streamlit do CotaSync — chat ligado ao agente LangChain (`processar_mensagem`).

Execução local: rode a partir da raiz do projeto, ex.:
  streamlit run frontend/app.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import streamlit as st
from audio_recorder_streamlit import audio_recorder
from dotenv import load_dotenv

st.set_page_config(
    page_title="CotaSync - Assistente Operacional",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Carrega OPENAI_API_KEY e demais variáveis antes de importar o backend.
load_dotenv()

# Permite `from backend.agente import ...` ao rodar Streamlit sem Docker (raiz no PYTHONPATH).
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.agente import processar_mensagem  # noqa: E402

try:
    API_BASE_URL = st.secrets["API_BASE_URL"]
except Exception:
    API_BASE_URL = "http://localhost:8000"

st.title("CotaSync - Assistente Operacional")
st.caption(f"API FastAPI (próximas iterações): `{API_BASE_URL}`")

# --- Estado da sessão (chat): `messages` alinhado ao pedido da Fase 2 ---
if "messages" not in st.session_state:
    if "mensagens" in st.session_state:
        st.session_state.messages = st.session_state.pop("mensagens")
    else:
        st.session_state.messages = [
            {"role": "assistant", "content": "Olá! Sou o assistente operacional. Como posso ajudar hoje?"}
        ]

# Após ação rápida com rerun: processa a última mensagem do usuário na rodada seguinte.
if st.session_state.pop("_pending_agent", False):
    ultima = st.session_state.messages[-1]
    historico_anterior = st.session_state.messages[:-1]
    with st.spinner("Analisando ERP..."):
        resposta = asyncio.run(
            processar_mensagem(ultima["content"], historico_anterior)
        )
    st.session_state.messages.append({"role": "assistant", "content": resposta})
    st.rerun()


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
        doc = (cnpj or "").strip()
        if doc:
            st.session_state.messages.append(
                {
                    "role": "user",
                    "content": f"Consulte o cadastro do documento: {doc}",
                }
            )
            st.session_state._pending_agent = True
            st.rerun()
        else:
            st.warning("Preencha o CNPJ para consultar o cadastro.")

    st.divider()
    st.subheader("Agendamentos")
    agendamentos = _agendamentos_simulados()
    labels = [f"{a['titulo']} — [{a['status']}]" for a in agendamentos]
    st.selectbox("Selecione um agendamento", options=labels, index=0)
    st.caption("Dados simulados para o layout; depois virão da API/agendador.")

# --- Chat principal ---
st.subheader("Conversa")
_EVIDENCIA = "print_teste.png"
_caminho_evidencia = _ROOT / _EVIDENCIA

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("role") == "assistant":
            conteudo = str(msg.get("content", ""))
            if _EVIDENCIA in conteudo and os.path.exists(str(_caminho_evidencia)):
                st.image(str(_caminho_evidencia), caption="Evidência do Sistema")

prompt = st.chat_input("Digite sua mensagem operacional…")
if prompt:
    historico_antes = list(st.session_state.messages)
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.spinner("Analisando ERP..."):
        resposta_chat = asyncio.run(processar_mensagem(prompt, historico_antes))
    st.session_state.messages.append({"role": "assistant", "content": resposta_chat})
    st.rerun()

# --- Comando de voz (placeholder com biblioteca real) ---
with st.expander("Comando de voz (experimental)", expanded=False):
    st.caption("Gravação local no navegador; transcrição e envio ao agente ainda não conectados.")
    audio_bytes = audio_recorder(text="Gravar / parar", recording_color="#e74c3c", neutral_color="#34495e")
    if audio_bytes:
        st.audio(audio_bytes, format="audio/wav")
        st.info("Áudio capturado. Próximo passo: enviar para serviço de STT e encaminhar o texto ao chat.")
