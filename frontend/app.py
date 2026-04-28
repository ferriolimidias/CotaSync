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
_UI_MAP_PATH = _ROOT / "ui_map.json"
_WHITELIST_PATH = _ROOT / "usuarios_autorizados.json"

try:
    API_BASE_URL = st.secrets["API_BASE_URL"]
except Exception:
    API_BASE_URL = "http://localhost:8000"


def _defaults_sessao_agendamentos() -> None:
    st.session_state.setdefault("rotina_boletos", True)
    st.session_state.setdefault("aviso_contemplados", False)
    st.session_state.setdefault("cron_log_text", "Nenhuma execucao ainda (simulado).\n")


def _carregar_ui_map() -> dict:
    if not _UI_MAP_PATH.is_file():
        return {"acoes_conhecidas": {}}
    try:
        return json.loads(_UI_MAP_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        st.warning("`ui_map.json` invalido. Usando fallback em memoria.")
        return {"acoes_conhecidas": {}}
    except OSError as exc:
        st.warning(f"Falha ao ler `ui_map.json`: {exc}")
        return {"acoes_conhecidas": {}}


def _obter_acoes_conhecidas(ui_map: dict) -> dict:
    acoes = ui_map.get("acoes_conhecidas", {})
    return acoes if isinstance(acoes, dict) else {}


def _carregar_whitelist() -> dict:
    try:
        if not _WHITELIST_PATH.is_file():
            return {"numeros_permitidos": []}
        return json.loads(_WHITELIST_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        st.error(f"JSON invalido em `usuarios_autorizados.json`: {exc}")
        return {"numeros_permitidos": []}
    except OSError as exc:
        st.error(f"Nao foi possivel ler `usuarios_autorizados.json`: {exc}")
        return {"numeros_permitidos": []}


def _gravar_whitelist(obj: dict) -> bool:
    try:
        _WHITELIST_PATH.write_text(
            json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return True
    except OSError as exc:
        st.error(f"Nao foi possivel gravar `usuarios_autorizados.json`: {exc}")
        return False


if "messages" not in st.session_state:
    if "mensagens" in st.session_state:
        st.session_state.messages = st.session_state.pop("mensagens")
    else:
        st.session_state.messages = [
            {
                "role": "assistant",
                "content": (
                    "Ola! Sou o assistente operacional. Posso ajudar com cadastros, "
                    "boletos, filas e rotinas."
                ),
            }
        ]

_defaults_sessao_agendamentos()
ui_map_data = _carregar_ui_map()
acoes_conhecidas = _obter_acoes_conhecidas(ui_map_data)
nomes_acoes = sorted(acoes_conhecidas.keys())

# Permite injetar comando no chat por botao dinamico.
if comando_rapido := st.session_state.pop("_queued_chat_prompt", None):
    st.session_state.messages.append({"role": "user", "content": comando_rapido})
    st.session_state._pending_agent = True

# Processamento assincrono unico do agente.
if st.session_state.pop("_pending_agent", False):
    ultima = st.session_state.messages[-1]
    historico_anterior = st.session_state.messages[:-1]
    with st.spinner("Analisando ERP..."):
        resposta = asyncio.run(processar_mensagem(ultima["content"], historico_anterior))
    st.session_state.messages.append({"role": "assistant", "content": resposta})
    st.rerun()


st.title("CotaSync")
st.markdown("### Painel de Controle *(Backoffice)* · Assistente Operacional Omnichannel")
st.caption(f"🔗 API REST (FastAPI · proximas integracoes): `{API_BASE_URL}`")

with st.sidebar:
    st.title("CotaSync")
    st.caption("Operacao inteligente em tempo real")
    st.caption("Status do sistema: 🟢 Online")

tab_chat, tab_agendamentos, tab_catalogo, tab_robo, tab_config = st.tabs(
    [
        "💬 Chat & Ações",
        "⏰ Agendamentos e Filas",
        "📚 Catálogo",
        "🖥️ Robô ao Vivo",
        "⚙️ Configurações",
    ]
)

with tab_chat:
    st.subheader("Conversa com o Agente")
    st.caption("Chat operacional com execucao assincrona e evidencias visuais.")

    if nomes_acoes:
        st.markdown("#### Ações Rápidas Dinâmicas")
        colunas = st.columns(min(len(nomes_acoes), 4))
        for idx, nome_acao in enumerate(nomes_acoes):
            coluna = colunas[idx % len(colunas)]
            with coluna:
                if st.button(nome_acao, key=f"acao_dinamica_{idx}", use_container_width=True):
                    st.session_state._queued_chat_prompt = f"Quero executar: {nome_acao}"
                    st.rerun()
    else:
        st.info("Nenhuma acao dinamica disponivel ainda. Ensine novas rotinas pelo chat.")

    caminho_evidencia = _ROOT / _EVIDENCIA
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("role") == "assistant":
                conteudo = str(msg.get("content", ""))
                if _EVIDENCIA in conteudo and os.path.exists(str(caminho_evidencia)):
                    st.image(str(caminho_evidencia), caption="Evidencia do Sistema")

    prompt = st.chat_input("Digite sua mensagem operacional...", key="chat_operacional")
    if prompt:
        historico_antes = list(st.session_state.messages)
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.spinner("Analisando ERP..."):
            resposta_chat = asyncio.run(processar_mensagem(prompt, historico_antes))
        st.session_state.messages.append({"role": "assistant", "content": resposta_chat})
        st.rerun()

    with st.expander("Comando de voz (experimental)", expanded=False):
        st.caption("Gravacao no browser; STT e envio ao agente em iteracao futura.")
        audio_bytes = audio_recorder(
            text="Gravar / parar",
            recording_color="#e74c3c",
            neutral_color="#34495e",
        )
        if audio_bytes:
            st.audio(audio_bytes, format="audio/wav")
            st.info("Audio gravado. Proximo passo: transcrever e enviar ao modelo.")

with tab_agendamentos:
    st.markdown("##### Gestão de rotinas e processamento em lote")
    st.caption(
        "Painel visual de demonstracao. O agendador real (APScheduler) roda no backend."
    )

    st.markdown("**Suba a planilha com a fila de clientes/lotes**")
    upl = st.file_uploader(
        "Planilha para processamento em lote",
        type=["xlsx"],
        accept_multiple_files=False,
        key="lote_xlsx_uploader",
    )
    if upl is not None:
        st.success(f"📎 Recebido: `{upl.name}` ({upl.size:,} bytes)".replace(",", "."))
        st.caption("Pipeline em lote ainda em modo simulado.")

    st.selectbox(
        "Selecione a Ação a ser executada em lote",
        options=nomes_acoes if nomes_acoes else ["Sem acoes disponiveis"],
        index=0,
        key="acao_lote",
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
            f"[{agora}] Execucao manual forcada (simulada).\n"
            f"  · Rotina de boletos: {st.session_state.rotina_boletos}\n"
            f"  · Aviso contemplados: {st.session_state.aviso_contemplados}\n"
        )
        st.session_state.cron_log_text = linha + st.session_state.cron_log_text
        st.rerun()

    st.markdown("**Logs recentes**")
    st.code(st.session_state.cron_log_text.strip() + "\n")

with tab_catalogo:
    st.markdown("##### Catálogo de ações conhecidas")
    busca = st.text_input(
        "Buscar rotina...",
        placeholder="ex.: consulta, boleto, login",
        key="busca_catalogo",
    )

    if not _UI_MAP_PATH.is_file():
        st.warning("Arquivo `ui_map.json` nao encontrado na raiz do projeto.")
    elif not nomes_acoes:
        st.info("Nenhuma acao aprendida ainda. Ensine o robo pelo chat.")
    else:
        consulta = (busca or "").strip().lower()
        filtradas = [nome for nome in nomes_acoes if not consulta or consulta in nome.lower()]
        if not filtradas:
            st.caption("Nenhum resultado para a busca atual.")
        for nome in filtradas:
            with st.expander(f"**{nome}**", expanded=False):
                st.json(acoes_conhecidas.get(nome) if acoes_conhecidas.get(nome) is not None else {})

with tab_robo:
    st.markdown("##### Robô ao Vivo - Intervenção")
    st.info(
        "Use esta tela para intervir no navegador do robo, resolver CAPTCHAs ou fazer "
        "login manual caso a sessao do ERP expire. O robo reaproveitara a sessao."
    )
    host_vnc = st.text_input(
        "Host Browserless (VNC)",
        value=os.getenv("BROWSERLESS_VNC_URL", "http://localhost:3000"),
        help="Exemplo para VPS: http://IP_DA_VPS:3000",
        key="browserless_vnc_url",
    )
    st.components.v1.iframe(src=host_vnc, height=600, scrolling=True)

with tab_config:
    st.markdown("##### Segurança WhatsApp *(whitelist)*")
    st.caption(
        "Numeros autorizados a acionar o webhook Evolution. "
        "Alteracoes gravam em `usuarios_autorizados.json`."
    )

    dados = _carregar_whitelist()
    numeros = dados.get("numeros_permitidos", [])
    if not isinstance(numeros, list):
        numeros = []
        st.warning("Formato inesperado em `numeros_permitidos`; usando lista vazia em memoria.")

    st.markdown("**Numeros com permissao atual**")
    if numeros:
        for numero in numeros:
            st.markdown(f"- `{numero}`")
    else:
        st.info("Nenhum numero na whitelist (ou arquivo vazio).")

    st.divider()
    st.markdown("**Adicionar a whitelist** *(E.164 sem +, ex.: 5511999999999)*")
    novo = st.text_input("Numero de telefone", placeholder="5511999999999", key="novo_num_whitelist")
    if st.button("Adicionar Numero", key="btn_add_whitelist"):
        digitos = re.sub(r"\D", "", novo or "")
        if len(digitos) < 10:
            st.warning("Informe um numero valido (apenas digitos).")
        else:
            lista = [str(item) for item in numeros] if numeros else []
            if digitos in lista:
                st.info("Este numero ja esta na lista.")
            else:
                lista.append(digitos)
                if _gravar_whitelist({"numeros_permitidos": lista}):
                    st.success(f"Numero **{digitos}** adicionado com sucesso.")
                    st.rerun()

    with st.expander("Ver / editar JSON bruto (avancado)", expanded=False):
        try:
            texto_json = (
                _WHITELIST_PATH.read_text(encoding="utf-8")
                if _WHITELIST_PATH.is_file()
                else json.dumps({"numeros_permitidos": []}, ensure_ascii=False, indent=2)
            )
        except OSError as exc:
            texto_json = json.dumps({"numeros_permitidos": numeros}, ensure_ascii=False, indent=2)
            st.caption(f"(Fallback em memoria; leitura falhou: {exc})")

        editado = st.text_area(
            "usuarios_autorizados.json",
            value=texto_json,
            height=200,
            key="raw_whitelist",
        )
        if st.button("Salvar JSON", key="save_raw_whitelist"):
            try:
                parsed = json.loads(editado)
                if not isinstance(parsed.get("numeros_permitidos"), list):
                    st.error("O JSON deve conter a chave `numeros_permitidos` (array).")
                elif _gravar_whitelist(parsed):
                    st.success("Arquivo atualizado.")
                    st.rerun()
            except json.JSONDecodeError as exc:
                st.error(f"JSON invalido: {exc}")

    st.divider()
    st.markdown("##### Conexão WhatsApp (Evolution API)")
    col_connect, col_disconnect = st.columns(2)
    with col_connect:
        if st.button("🔗 Conectar WhatsApp (Gerar QR Code)", use_container_width=True):
            st.info("Simulacao: solicitacao de QR Code enviada para a Evolution API.")
    with col_disconnect:
        if st.button("❌ Desconectar", use_container_width=True):
            st.info("Simulacao: sessao WhatsApp marcada para desconexao.")
