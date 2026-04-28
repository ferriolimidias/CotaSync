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
from time import sleep

import streamlit as st
from audio_recorder_streamlit import audio_recorder
from dotenv import load_dotenv
from streamlit_option_menu import option_menu

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
_ERP_CONFIG_PATH = _ROOT / "erp_config.json"
_LOG_PATH = _ROOT / "logs" / "operation.log"
_CHAT_HISTORY_PATH = _ROOT / "data" / "chat_history.json"

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


def _ler_ultimas_linhas_log(limite: int = 50) -> str:
    try:
        if not _LOG_PATH.is_file():
            return "Arquivo de log ainda nao encontrado."
        linhas = _LOG_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
        if not linhas:
            return "Log vazio."
        return "\n".join(linhas[-limite:])
    except OSError as exc:
        return f"Falha ao ler logs: {exc}"


def _listar_mapeamentos() -> list[Path]:
    try:
        return sorted(_ROOT.glob("mapeamento_*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return []


def _normalizar_nome_arquivo(texto: str) -> str:
    return re.sub(r"[^\w\-]+", "_", str(texto or "").strip(), flags=re.UNICODE).strip("_")


def _screenshot_por_acao(chave_acao: str) -> Path:
    return _ROOT / f"mapeamento_{_normalizar_nome_arquivo(chave_acao)}.png"


def carregar_historico_disco() -> list[dict]:
    try:
        if not _CHAT_HISTORY_PATH.is_file():
            return []
        conteudo = json.loads(_CHAT_HISTORY_PATH.read_text(encoding="utf-8"))
        if not isinstance(conteudo, list):
            return []
        mensagens_validas: list[dict] = []
        for item in conteudo:
            if isinstance(item, dict) and item.get("role") and item.get("content") is not None:
                mensagens_validas.append(
                    {"role": str(item.get("role")), "content": str(item.get("content", ""))}
                )
        return mensagens_validas
    except (json.JSONDecodeError, OSError):
        return []


def salvar_historico_disco(mensagens: list[dict]) -> None:
    try:
        _CHAT_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CHAT_HISTORY_PATH.write_text(
            json.dumps(mensagens, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


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
    historico_disco = carregar_historico_disco()
    if historico_disco:
        st.session_state.messages = historico_disco
    elif "mensagens" in st.session_state:
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
    salvar_historico_disco(st.session_state.messages)
    st.session_state._pending_agent = True

# Processamento assincrono unico do agente.
if st.session_state.pop("_pending_agent", False):
    ultima = st.session_state.messages[-1]
    historico_anterior = st.session_state.messages[:-1]
    with st.spinner("Analisando ERP..."):
        resposta = asyncio.run(processar_mensagem(ultima["content"], historico_anterior))
    st.session_state.messages.append({"role": "assistant", "content": resposta})
    salvar_historico_disco(st.session_state.messages)
    st.rerun()


st.title("CotaSync")
st.markdown("### Painel de Controle *(Backoffice)* · Assistente Operacional Omnichannel")
st.caption(f"🔗 API REST (FastAPI · proximas integracoes): `{API_BASE_URL}`")

with st.sidebar:
    st.title("CotaSync")
    st.caption("Operacao inteligente em tempo real")
    st.caption("Status do sistema: 🟢 Online")
    menu_selecionado = option_menu(
        menu_title="Menu Principal",
        options=["Chat & Ações", "Agendamentos e Filas", "Catálogo de Ações", "Logs do Sistema", "Configurações"],
        icons=["chat-dots", "calendar2-check", "book", "terminal", "gear"],
        default_index=0,
        styles={
            "container": {"padding": "0!important", "background-color": "#0f172a"},
            "icon": {"color": "#93c5fd", "font-size": "16px"},
            "nav-link": {
                "font-size": "14px",
                "text-align": "left",
                "margin": "4px 0",
                "--hover-color": "#1e293b",
                "border-radius": "8px",
                "color": "#e2e8f0",
            },
            "nav-link-selected": {
                "background-color": "#2563eb",
                "color": "#ffffff",
                "font-weight": "600",
            },
        },
    )
    st.divider()
    st.markdown("#### ⚡ Execução Rápida")
    acoes_sidebar = _obter_acoes_conhecidas(_carregar_ui_map())
    if acoes_sidebar:
        opcoes_sidebar = {
            dados.get("nome_amigavel", chave): chave
            for chave, dados in acoes_sidebar.items()
            if isinstance(dados, dict)
        }
        if not opcoes_sidebar:
            opcoes_sidebar = {chave: chave for chave in acoes_sidebar.keys()}
        acao_sidebar_nome = st.selectbox(
            "Selecione uma ação para disparar:",
            options=list(opcoes_sidebar.keys()),
            key="acao_sidebar_select",
            label_visibility="collapsed",
        )
        if st.button("🚀 Disparar Ação", use_container_width=True, key="acao_sidebar_btn"):
            chave_acao = opcoes_sidebar[acao_sidebar_nome]
            st.session_state.messages.append({"role": "user", "content": chave_acao})
            salvar_historico_disco(st.session_state.messages)
            st.session_state._pending_agent = True
            st.rerun()
    else:
        st.caption("Sem ações aprendidas no momento.")

    with st.expander("🎤 Comando de voz", expanded=False):
        st.caption("Gravacao no browser; STT e envio ao agente em iteracao futura.")
        audio_bytes_sidebar = audio_recorder(
            text="Gravar / parar",
            recording_color="#e74c3c",
            neutral_color="#34495e",
            key="audio_recorder_sidebar",
        )
        if audio_bytes_sidebar:
            st.audio(audio_bytes_sidebar, format="audio/wav")
            st.info("Audio gravado. Proximo passo: transcrever e enviar ao modelo.")

if menu_selecionado == "Chat & Ações":
    st.subheader("Conversa com o Agente")
    st.caption("Chat operacional com execucao assincrona e evidencias visuais.")

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
        salvar_historico_disco(st.session_state.messages)
        with st.spinner("Analisando ERP..."):
            resposta_chat = asyncio.run(processar_mensagem(prompt, historico_antes))
        st.session_state.messages.append({"role": "assistant", "content": resposta_chat})
        salvar_historico_disco(st.session_state.messages)
        st.rerun()

elif menu_selecionado == "Agendamentos e Filas":
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

elif menu_selecionado == "Catálogo de Ações":
    st.markdown("##### 📚 Catálogo de Ações")
    memoria_replay = _obter_acoes_conhecidas(_carregar_ui_map())
    if not memoria_replay:
        st.info("Ainda não há rotinas aprendidas para exibir.")
    else:
        for chave_acao, dados_acao in memoria_replay.items():
            if not isinstance(dados_acao, dict):
                continue
            nome_amigavel = str(dados_acao.get("nome_amigavel", chave_acao))
            descricao = str(dados_acao.get("descricao", "Sem descrição"))
            passos = dados_acao.get("passos_playwright", [])
            if not isinstance(passos, list):
                passos = []

            with st.expander(f"🧠 {nome_amigavel}", expanded=False):
                st.caption(descricao)
                if passos:
                    timeline_linhas: list[str] = []
                    for passo in passos:
                        if not isinstance(passo, dict):
                            continue
                        tipo = str(passo.get("tipo", "ação")).lower()
                        seletor = str(passo.get("seletor", "sem seletor"))
                        valor = str(passo.get("valor", passo.get("variavel", ""))).strip()
                        if tipo == "clicar":
                            timeline_linhas.append(f"🖱️ Clique em: `{valor or seletor}`")
                        elif tipo == "preencher":
                            timeline_linhas.append(f"⌨️ Preencher: `{seletor}` com `{valor or 'valor dinâmico'}`")
                        else:
                            timeline_linhas.append(f"➡️ {tipo.title()}: `{valor or seletor}`")
                    st.markdown(" ➔ ".join(timeline_linhas) if timeline_linhas else "Sem passos válidos no replay.")
                else:
                    st.info("Esta rotina ainda não possui passos técnicos registrados.")

                caminho_print = _screenshot_por_acao(chave_acao)
                if caminho_print.is_file():
                    st.image(str(caminho_print), caption=f"Evidência: {nome_amigavel}", use_container_width=True)

elif menu_selecionado == "Logs do Sistema":
    st.markdown("##### Logs do Sistema")
    st.info("🔒 Área Restrita: Operação invisível em background.")
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _LOG_PATH.touch(exist_ok=True)

    c1, c2 = st.columns([3, 1])
    with c1:
        auto_atualizar = st.toggle("Atualizacao automatica", value=True, key="logs_auto_toggle")
    with c2:
        if st.button("🗑️ Limpar Logs", use_container_width=True, key="clear_logs_btn"):
            try:
                _LOG_PATH.write_text("", encoding="utf-8")
                st.success("Logs limpos.")
            except OSError as exc:
                st.error(f"Falha ao limpar logs: {exc}")

    placeholder_logs = st.empty()

    def _render_logs() -> None:
        placeholder_logs.code(_ler_ultimas_linhas_log(50))

    if auto_atualizar and hasattr(st, "fragment"):
        @st.fragment(run_every="2s")
        def _stream_logs_fragment() -> None:
            _render_logs()

        _stream_logs_fragment()
    elif auto_atualizar:
        for _ in range(2):
            _render_logs()
            sleep(0.3)
    else:
        _render_logs()

    st.divider()
    st.markdown("#### 🖼️ Galeria de Aprendizados")
    if st.button("Atualizar Galeria", key="refresh_gallery_btn"):
        st.rerun()

    imagens = _listar_mapeamentos()
    if not imagens:
        st.info("Nenhum mapeamento encontrado ainda.")
    else:
        cols = st.columns(3)
        for idx, imagem in enumerate(imagens):
            nome_acao = imagem.stem.replace("mapeamento_", "").replace("_", " ").strip()
            with cols[idx % 3]:
                st.image(str(imagem), caption=nome_acao, use_container_width=True)
                st.caption(f"Ação: {nome_acao}")

elif menu_selecionado == "Configurações":
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

    st.divider()
    st.subheader("Credenciais do Sistema Externo (ERP)")

    def _carregar_erp_config() -> dict:
        try:
            if not _ERP_CONFIG_PATH.is_file():
                return {"url_sistema": "", "usuario": "", "senha": ""}
            data = json.loads(_ERP_CONFIG_PATH.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return {"url_sistema": "", "usuario": "", "senha": ""}
            return {
                "url_sistema": str(data.get("url_sistema", "")),
                "usuario": str(data.get("usuario", "")),
                "senha": str(data.get("senha", "")),
            }
        except (json.JSONDecodeError, OSError):
            return {"url_sistema": "", "usuario": "", "senha": ""}

    dados_erp = _carregar_erp_config()
    with st.form("erp_config_form"):
        url_sistema = st.text_input("URL do Sistema", value=dados_erp["url_sistema"])
        usuario_erp = st.text_input("Usuário", value=dados_erp["usuario"])
        senha_erp = st.text_input("Senha", value=dados_erp["senha"], type="password")
        salvar_erp = st.form_submit_button("Salvar Credenciais ERP", use_container_width=True)
        if salvar_erp:
            try:
                payload = {
                    "url_sistema": url_sistema.strip(),
                    "usuario": usuario_erp.strip(),
                    "senha": senha_erp,
                }
                _ERP_CONFIG_PATH.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                st.success("Credenciais do ERP salvas com sucesso.")
            except OSError as exc:
                st.error(f"Nao foi possivel salvar `erp_config.json`: {exc}")
