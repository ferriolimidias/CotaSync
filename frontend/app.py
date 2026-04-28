"""
CotaSync — Painel de Controle (Backoffice) + chat com o agente LangChain.

Execução: a partir da raiz do projeto, ex.:
  streamlit run frontend/app.py
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st
from audio_recorder_streamlit import audio_recorder
from dotenv import load_dotenv

st.set_page_config(
    page_title="CotaSync — Painel Operacional",
    layout="wide",
    initial_sidebar_state="expanded",
)

load_dotenv()

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.agente import processar_mensagem  # noqa: E402

_EVIDENCIA = "print_teste.png"
_Ui_MAP_PATH = _ROOT / "ui_map.json"
_WHITELIST_PATH = _ROOT / "usuarios_autorizados.json"

try:
    API_BASE_URL = st.secrets["API_BASE_URL"]
except Exception:
    API_BASE_URL = "http://localhost:8000"


def _defaults_sessao_agendamentos() -> None:
    """Estado simulado do módulo de CRON (Tab 2)."""
    st.session_state.setdefault("rotina_boletos", True)
    st.session_state.setdefault("aviso_contemplados", False)
    st.session_state.setdefault("cron_log_text", "Nenhuma execução ainda (simulado).\n")


# --- Chat: histórico de mensagens ---
if "messages" not in st.session_state:
    if "mensagens" in st.session_state:
        st.session_state.messages = st.session_state.pop("mensagens")
    else:
        st.session_state.messages = [
            {
                "role": "assistant",
                "content": "Olá! Sou o assistente operacional. Posso ajudar com cadastros, boletos e rotinas.",
            }
        ]

_defaults_sessao_agendamentos()

# Ação rápida: após injetar pedido, reprocessa com o agente (fora das abas; evita duplicar lógica).
if st.session_state.pop("_pending_agent", False):
    ultima = st.session_state.messages[-1]
    historico_anterior = st.session_state.messages[:-1]
    with st.spinner("Analisando ERP..."):
        resposta = asyncio.run(
            processar_mensagem(ultima["content"], historico_anterior)
        )
    st.session_state.messages.append({"role": "assistant", "content": resposta})
    st.rerun()


# --- Cabeçalho ---
st.title("CotaSync")
st.markdown("### Painel de Controle *(Backoffice)* · Assistente Operacional Omnichannel")
st.caption(f"🔗 API REST (FastAPI · próximas integrações): `{API_BASE_URL}`")


# ============================================================================
# Sidebar — Ações rápidas + Operação em lote
# ============================================================================
with st.sidebar:
    st.header("Ações rápidas")
    st.caption("Atalhos para o fluxo mais usado pelo operador.")

    cnpj = st.text_input("CNPJ", placeholder="00.000.000/0001-00", key="cnpj_input")

    bc1, bc2 = st.columns(2)
    with bc1:
        consultar = st.button("Consultar cadastro", type="primary", use_container_width=True)
    with bc2:
        gerar_boleto = st.button("Gerar Boleto", use_container_width=True)

    if consultar:
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

    if gerar_boleto:
        st.toast("Geração de boleto (simulada) acionada — ligação ao motor de boletos em breve.")

    st.divider()

    st.subheader("Operação em Lote")
    upl = st.file_uploader(
        "Subir planilha para lances/boletos",
        type=["xlsx"],
        accept_multiple_files=False,
        key="lote_xlsx_uploader",
        help=".xlsx apenas; processamento em batch será ligado ao backend.",
    )
    if upl is not None:
        st.success(f"📎 **Recebido:** `{upl.name}` ({upl.size:,} bytes)".replace(",", "."))
        st.caption("_Pipeline em lote ainda simulado._")

# ============================================================================
# Abas principais
# ============================================================================
tab1, tab2, tab3, tab4 = st.tabs(
    [
        "💬 Chat & Operação",
        "⏰ Agendamentos",
        "📚 Catálogo de Ações",
        "⚙️ Configurações",
    ]
)

# --- Tab 1: Chat & Operação ---------------------------------------------------
with tab1:
    st.subheader("Conversa")
    st.caption("Interaja com o cérebro (LangChain). As **ferramentas** executam o motor web quando aplicável.")

    _caminho_evidencia = _ROOT / _EVIDENCIA

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("role") == "assistant":
                conteudo = str(msg.get("content", ""))
                if _EVIDENCIA in conteudo and os.path.exists(str(_caminho_evidencia)):
                    st.image(str(_caminho_evidencia), caption="Evidência do Sistema")

    prompt = st.chat_input("Digite sua mensagem operacional…", key="chat_operacional")
    if prompt:
        historico_antes = list(st.session_state.messages)
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.spinner("Analisando ERP..."):
            resposta_chat = asyncio.run(processar_mensagem(prompt, historico_antes))
        st.session_state.messages.append({"role": "assistant", "content": resposta_chat})
        st.rerun()

    with st.expander("Comando de voz (experimental)", expanded=False):
        st.caption("Gravação no browser; STT e encaminhamento ao agente em iteração futura.")
        audio_bytes = audio_recorder(
            text="Gravar / parar",
            recording_color="#e74c3c",
            neutral_color="#34495e",
        )
        if audio_bytes:
            st.audio(audio_bytes, format="audio/wav")
            st.info("Áudio gravado — próximo passo: transcrever e enviar ao modelo.")

# --- Tab 2: Agendamentos (simulado CRON) ------------------------------------
with tab2:
    st.markdown("##### Gestão de rotinas *(simulação CRON)*")
    st.caption(
        "Estas opções são um **painel visual de demonstração**. "
        "O APScheduler real corre no FastAPI quando o backend estiver ligado."
    )

    col_a, col_b = st.columns(2)
    with col_a:
        st.toggle("Rotina de Boletos (Dia 10)", key="rotina_boletos")
    with col_b:
        st.toggle("Aviso de Contemplados (Sexta-feira)", key="aviso_contemplados")

    st.divider()
    if st.button("⚙️ Forçar Execução Manual Agora", type="secondary", key="force_cron_run"):
        agora = datetime.now().isoformat(timespec="seconds")
        linha = (
            f"[{agora}] Execução manual forçada (simulada).\n"
            f"  · Rotina de boletos: {st.session_state.rotina_boletos}\n"
            f"  · Aviso contemplados: {st.session_state.aviso_contemplados}\n"
        )
        st.session_state.cron_log_text = linha + st.session_state.cron_log_text
        st.rerun()

    st.markdown("**Logs recentes**")
    st.code(st.session_state.cron_log_text.strip() + "\n")

# --- Tab 3: Catálogo de ações (ui_map.json) -----------------------------------
with tab3:
    st.markdown("##### Catálogo de ações conhecidas")
    busca = st.text_input("Buscar rotina…", placeholder="ex.: consulta, boleto, login", key="busca_catalogo")

    try:
        if not _Ui_MAP_PATH.is_file():
            st.warning("Ficheiro `ui_map.json` não encontrado na raiz do projeto.")
        else:
            raw = _Ui_MAP_PATH.read_text(encoding="utf-8")
            data = json.loads(raw)
            acoes = data.get("acoes_conhecidas")
            if not isinstance(acoes, dict):
                st.error("O campo `acoes_conhecidas` não é um objeto JSON válido.")
            else:
                chaves = list(acoes.keys())
                if not chaves:
                    st.info("Nenhuma ação aprendida ainda. Ensine o robô pelo chat!")
                else:
                    q = (busca or "").strip().lower()
                    filtradas = [k for k in chaves if not q or q in k.lower()]
                    if not filtradas:
                        st.caption("Nenhum resultado para a busca atual.")
                    for nome in sorted(filtradas):
                        with st.expander(f"**{nome}**", expanded=False):
                            st.json(acoes.get(nome) if acoes.get(nome) is not None else {})
    except json.JSONDecodeError as e:
        st.error(f"JSON inválido em `ui_map.json`: {e}")
    except Exception as e:
        st.error(f"Erro ao ler catálogo: {e}")

# --- Tab 4: Configurações & whitelist ----------------------------------------
with tab4:
    st.markdown("##### Segurança WhatsApp *(whitelist)*")
    st.caption(
        "Números autorizados a acionar o webhook Evolution. "
        "Alterações gravam em `usuarios_autorizados.json` na raiz do projeto."
    )

    def _carregar_whitelist() -> dict:
        try:
            if not _WHITELIST_PATH.is_file():
                return {"numeros_permitidos": []}
            return json.loads(_WHITELIST_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            st.error(f"JSON inválido: {e}")
            return {"numeros_permitidos": []}
        except OSError as e:
            st.error(f"Não foi possível ler o ficheiro: {e}")
            return {"numeros_permitidos": []}

    def _gravar_whitelist(obj: dict) -> bool:
        try:
            _WHITELIST_PATH.write_text(
                json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            return True
        except OSError as e:
            st.error(f"Não foi possível gravar: {e}")
            return False

    dados = _carregar_whitelist()
    numeros = dados.get("numeros_permitidos", [])
    if not isinstance(numeros, list):
        numeros = []
        st.warning("Formato inesperado: `numeros_permitidos` resetado para lista vazia na memória.")

    st.markdown("**Números com permissão atual**")
    if numeros:
        for n in numeros:
            st.markdown(f"- `{n}`")
    else:
        st.info("Nenhum número na whitelist (ou ficheiro vazio).")

    st.divider()
    st.markdown("**Adicionar à whitelist** *(E.164 sem +, ex.: 5511999999999)*")
    novo = st.text_input("Número de telefone", placeholder="5511999999999", key="novo_num_whitelist")
    if st.button("Adicionar Número", key="btn_add_whitelist"):
        digitos = re.sub(r"\D", "", novo or "")
        if len(digitos) < 10:
            st.warning("Introduza um número válido (apenas dígitos).")
        else:
            lista = [str(x) for x in numeros] if numeros else []
            if digitos in lista:
                st.info("Este número já está na lista.")
            else:
                lista.append(digitos)
                if _gravar_whitelist({"numeros_permitidos": lista}):
                    st.success(f"Número **{digitos}** adicionado (simulação persistida em disco).")
                    st.rerun()

    with st.expander("Ver / editar JSON bruto (avançado)", expanded=False):
        try:
            texto_json = (
                _WHITELIST_PATH.read_text(encoding="utf-8")
                if _WHITELIST_PATH.is_file()
                else json.dumps({"numeros_permitidos": []}, ensure_ascii=False, indent=2)
            )
        except OSError as e:
            texto_json = json.dumps({"numeros_permitidos": numeros}, ensure_ascii=False, indent=2)
            st.caption(f"(Fallback em memória — leitura falhou: {e})")

        editado = st.text_area("usuarios_autorizados.json", value=texto_json, height=200, key="raw_whitelist")
        if st.button("Guardar JSON", key="save_raw_whitelist"):
            try:
                parsed = json.loads(editado)
                if not isinstance(parsed.get("numeros_permitidos"), list):
                    st.error("O JSON deve conter a chave `numeros_permitidos` (array).")
                else:
                    if _gravar_whitelist(parsed):
                        st.success("Ficheiro atualizado.")
                        st.rerun()
            except json.JSONDecodeError as e:
                st.error(f"JSON inválido: {e}")
