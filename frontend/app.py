"""
CotaSync — Painel de Controle (Backoffice) + chat com o agente LangChain.

Execução: a partir da raiz do projeto, ex.:
  streamlit run frontend/app.py
"""

from __future__ import annotations

import asyncio
import glob
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from time import sleep

import pandas as pd
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
os.makedirs("data", exist_ok=True)
_DATA_DIR = _ROOT / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.agente import executar_acao_fast_track, processar_mensagem  # noqa: E402

_EVIDENCIA = "data/print_teste.png"
_UI_MAP_PATH = _DATA_DIR / "ui_map.json"
_WHITELIST_PATH = _DATA_DIR / "usuarios_autorizados.json"
_ERP_CONFIG_PATH = _DATA_DIR / "erp_config.json"
_LOG_PATH = _ROOT / "logs" / "operation.log"
_CHAT_HISTORY_PATH = _DATA_DIR / "chat_history.json"

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
        return sorted(_DATA_DIR.glob("mapeamento_*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return []


def _normalizar_nome_arquivo(texto: str) -> str:
    return re.sub(r"[^\w\-]+", "_", str(texto or "").strip(), flags=re.UNICODE).strip("_")


def _screenshot_por_acao(chave_acao: str) -> Path:
    return _DATA_DIR / f"mapeamento_{_normalizar_nome_arquivo(chave_acao)}.png"


def _normalizar_resposta_assistente(resposta: object) -> dict:
    if isinstance(resposta, dict):
        content = str(resposta.get("texto", resposta.get("content", "")))
        arquivos = resposta.get("arquivos", [])
        evidencia = str(resposta.get("evidencia", "") or "")
        if not isinstance(arquivos, list):
            arquivos = []
        payload = {"role": "assistant", "content": content, "arquivos": arquivos}
        if evidencia:
            payload["evidencia"] = evidencia
        dados_extra = resposta.get("dados_extraidos")
        if isinstance(dados_extra, dict) and dados_extra:
            payload["dados_extraidos"] = dados_extra
        return payload
    return {"role": "assistant", "content": str(resposta)}


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
                msg_restaurada: dict = {
                    "role": str(item.get("role")),
                    "content": str(item.get("content", "")),
                }
                if "arquivos" in item and isinstance(item.get("arquivos"), list):
                    msg_restaurada["arquivos"] = item["arquivos"]
                if "evidencia" in item and item.get("evidencia"):
                    msg_restaurada["evidencia"] = str(item["evidencia"])
                if "dados_extraidos" in item and isinstance(item.get("dados_extraidos"), dict):
                    msg_restaurada["dados_extraidos"] = item["dados_extraidos"]
                mensagens_validas.append(msg_restaurada)
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
st.session_state.setdefault("estado_agente", "NORMAL")

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
    if isinstance(resposta, dict):
        st.session_state.estado_agente = str(resposta.get("estado", "NORMAL"))
    else:
        st.session_state.estado_agente = "NORMAL"
    st.session_state.messages.append(_normalizar_resposta_assistente(resposta))
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
        chave_acao = opcoes_sidebar[acao_sidebar_nome]
        acao_sidebar_dados = acoes_sidebar.get(chave_acao, {}) if isinstance(acoes_sidebar, dict) else {}
        variaveis_necessarias = (
            acao_sidebar_dados.get("variaveis_necessarias", [])
            if isinstance(acao_sidebar_dados, dict)
            else []
        )
        dados_digitados: dict[str, str] = {}
        if isinstance(variaveis_necessarias, list) and variaveis_necessarias:
            for var_nome in variaveis_necessarias:
                chave_var = str(var_nome)
                if not chave_var:
                    continue
                dados_digitados[chave_var] = st.text_input(
                    f"Preencha {chave_var}",
                    key=f"acao_var_{chave_acao}_{chave_var}",
                )
        st.divider()
        converter_pdf_sidebar = st.checkbox(
            "🔄 Converter PDF p/ Excel",
            key="chk_pdf_sidebar",
            help="Extrai tabelas de PDFs baixados para planilhas .xlsx",
        )
        if st.button("🚀 Disparar Ação", use_container_width=True, key="acao_sidebar_btn"):
            if isinstance(variaveis_necessarias, list) and variaveis_necessarias:
                faltantes = [str(v) for v in variaveis_necessarias if not str(dados_digitados.get(str(v), "")).strip()]
                if faltantes:
                    st.warning(f"Preencha as variáveis obrigatórias: {', '.join(faltantes)}")
                else:
                    st.session_state.messages.append({"role": "user", "content": chave_acao})
                    salvar_historico_disco(st.session_state.messages)
                    with st.spinner("Executando ação parametrizada..."):
                        resultado_direto = asyncio.run(
                            executar_acao_fast_track(
                                chave_acao,
                                dados_digitados,
                                converter_pdf_excel=converter_pdf_sidebar,
                            )
                        )
                    if isinstance(resultado_direto, dict):
                        st.session_state.estado_agente = str(resultado_direto.get("estado", "NORMAL"))
                    st.session_state.messages.append(_normalizar_resposta_assistente(resultado_direto))
                    salvar_historico_disco(st.session_state.messages)
                    st.rerun()
            else:
                st.session_state.messages.append({"role": "user", "content": chave_acao})
                salvar_historico_disco(st.session_state.messages)
                with st.spinner("Executando ação rápida..."):
                    resultado_direto = asyncio.run(
                        executar_acao_fast_track(
                            chave_acao,
                            None,
                            converter_pdf_excel=converter_pdf_sidebar,
                        )
                    )
                if isinstance(resultado_direto, dict):
                    st.session_state.estado_agente = str(resultado_direto.get("estado", "NORMAL"))
                st.session_state.messages.append(_normalizar_resposta_assistente(resultado_direto))
                salvar_historico_disco(st.session_state.messages)
                st.rerun()
    else:
        st.caption("Sem ações aprendidas no momento.")

    st.divider()
    st.markdown("### 🎓 Mapeamento")
    if st.button("Ensinar Nova Rotina", use_container_width=True, type="primary", key="ensinar_nova_rotina_btn"):
        st.session_state.messages.append({"role": "user", "content": "Quero ensinar uma nova rotina"})
        salvar_historico_disco(st.session_state.messages)
        st.session_state._pending_agent = True
        st.rerun()

    st.divider()
    st.subheader("🧹 Manutenção")
    if st.button("🗑️ Limpar Histórico de Chat", use_container_width=True, key="limpar_historico_chat_btn"):
        st.session_state.messages = [
            {"role": "assistant", "content": "Olá! O histórico foi limpo. Como posso ajudar?"}
        ]
        try:
            salvar_historico_disco(st.session_state.messages)
        except Exception:
            pass
        st.rerun()

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

    caminho_evidencia_padrao = _ROOT / _EVIDENCIA
    for i, msg in enumerate(st.session_state.messages):
        with st.chat_message(msg["role"]):
            st.markdown(msg.get("content", ""))

            dados_ex = msg.get("dados_extraidos")
            if isinstance(dados_ex, dict) and dados_ex:
                st.write("Textos / dados extraídos nesta execução:")
                st.json(dados_ex)

            arquivos_msg = msg.get("arquivos")
            if isinstance(arquivos_msg, list) and arquivos_msg:
                for caminho_arq in arquivos_msg:
                    caminho_str = str(caminho_arq)
                    caminho_abs = Path(caminho_str) if os.path.isabs(caminho_str) else _ROOT / caminho_str
                    if caminho_abs.is_file():
                        nome_arquivo = caminho_abs.name
                        conteudo_arquivo = caminho_abs.read_bytes()
                        st.download_button(
                            label=f"📥 Baixar {nome_arquivo}",
                            data=conteudo_arquivo,
                            file_name=nome_arquivo,
                            mime="application/octet-stream",
                            key=f"dl_btn_msg_{i}_{nome_arquivo}",
                        )

            evidencia_msg = str(msg.get("evidencia", "") or "").strip()
            if evidencia_msg:
                caminho_img = Path(evidencia_msg) if os.path.isabs(evidencia_msg) else _ROOT / evidencia_msg
                if caminho_img.is_file() and caminho_img.suffix.lower() in {
                    ".png",
                    ".jpg",
                    ".jpeg",
                    ".webp",
                    ".gif",
                }:
                    st.image(str(caminho_img), caption="Evidência Visual", width=500)
            elif msg.get("role") == "assistant":
                conteudo_txt = str(msg.get("content", ""))
                if _EVIDENCIA in conteudo_txt and caminho_evidencia_padrao.is_file():
                    st.image(str(caminho_evidencia_padrao), caption="Evidência Visual", width=500)

    estado_agente = st.session_state.get("estado_agente", "NORMAL")
    if estado_agente == "ESPERANDO_APROVACAO_PLANO":
        st.warning(
            "⏳ **Ação Pausada:** O robô criou um plano de ação acima. Responda com 'ok' para autorizar a execução ou peça correções.",
            icon="🚨",
        )
    elif estado_agente == "APRENDENDO":
        st.info(
            "🧠 **Modo de Aprendizado:** O robô está a navegar no sistema neste momento para mapear a rotina...",
            icon="🤖",
        )

    prompt = st.chat_input("Digite sua mensagem operacional...", key="chat_operacional")
    if prompt:
        historico_antes = list(st.session_state.messages)
        st.session_state.messages.append({"role": "user", "content": prompt})
        salvar_historico_disco(st.session_state.messages)
        with st.spinner("Analisando ERP..."):
            resultado_ia = asyncio.run(processar_mensagem(prompt, historico_antes))
        if isinstance(resultado_ia, dict):
            resposta_texto = str(resultado_ia.get("texto", ""))
            estado_atual = str(resultado_ia.get("estado", "NORMAL"))
            st.session_state.estado_agente = estado_atual
            arquivos_anexos = resultado_ia.get("arquivos", [])
            if not isinstance(arquivos_anexos, list):
                arquivos_anexos = []
            resposta_chat = {
                "texto": resposta_texto,
                "arquivos": arquivos_anexos,
                "evidencia": resultado_ia.get("evidencia", ""),
                "dados_extraidos": resultado_ia.get("dados_extraidos", {}),
            }
        else:
            resposta_chat = str(resultado_ia)
            st.session_state.estado_agente = "NORMAL"
        st.session_state.messages.append(_normalizar_resposta_assistente(resposta_chat))
        salvar_historico_disco(st.session_state.messages)
        st.rerun()

elif menu_selecionado == "Agendamentos e Filas":
    st.header("⏰ Agendamentos e Operação em Lote")
    
    st.subheader("📁 Operação em Lote (Excel)")
    
    # 1. Escolha da Ação
    memoria = _carregar_ui_map()
    acoes_disponiveis = memoria.get("acoes_conhecidas", {})
    
    if not acoes_disponiveis:
        st.info("Nenhuma ação aprendida ainda. Volte ao Chat e ensine o robô primeiro!")
    else:
        opcoes_lote = {dados.get("nome_amigavel", chave): chave for chave, dados in acoes_disponiveis.items()}
        nome_acao_lote = st.selectbox("1. Qual rotina deseja aplicar à planilha?", list(opcoes_lote.keys()), key="lote_acao")
        chave_acao_selecionada = opcoes_lote[nome_acao_lote]
        variaveis_exigidas = acoes_disponiveis[chave_acao_selecionada].get("variaveis_necessarias", [])
        
        # 2. Upload do Arquivo
        arquivo_excel = st.file_uploader("2. Suba a planilha (.xlsx, .csv)", type=["xlsx", "csv"])
        
        if arquivo_excel is not None:
            try:
                import pandas as pd
                if arquivo_excel.name.endswith('.csv'):
                    df_lote = pd.read_csv(arquivo_excel)
                else:
                    df_lote = pd.read_excel(arquivo_excel)
                    
                colunas_excel = df_lote.columns.tolist()
                
                st.write("Visualização rápida dos dados:")
                st.dataframe(df_lote.head(3), use_container_width=True)
                
                # 3. Mapeamento
                if variaveis_exigidas:
                    st.markdown("### 🔗 Mapeamento de Variáveis")
                    st.info(f"A rotina '{nome_acao_lote}' precisa de dados. Indique em que coluna da sua planilha eles estão:")
                    
                    mapeamento_colunas = {}
                    for var in variaveis_exigidas:
                        col_selecionada = st.selectbox(
                            f"A variável '{var}' corresponde à coluna:",
                            options=["-- Selecione a coluna --"] + colunas_excel,
                            key=f"map_{var}"
                        )
                        mapeamento_colunas[var] = col_selecionada
                    
                    todas_mapeadas = all(v != "-- Selecione a coluna --" for v in mapeamento_colunas.values())
                else:
                    st.success(f"A rotina '{nome_acao_lote}' não exige variáveis. Pronta para disparar o lote!")
                    mapeamento_colunas = {}
                    todas_mapeadas = True
                
                # 4. Botões de Disparo
                if todas_mapeadas:
                    st.divider()
                    st.markdown("### 🛠️ Opções de Processamento")
                    converter_pdfs = st.checkbox(
                        "🔄 Tentar converter PDFs de relatórios para Excel (.xlsx)?",
                        help=(
                            "Marque se a rotina baixa um relatório em PDF que você deseja transformar em planilha. "
                            "Deixe desmarcado para boletos/faturas normais."
                        ),
                    )
                    st.divider()
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        if st.button("🚀 Iniciar Processamento Agora", use_container_width=True, type="primary"):
                            lista_dados = df_lote.to_dict('records')
                            st.info(f"A processar {len(lista_dados)} itens... Por favor, não feche a página.")
                            barra_progresso = st.progress(0)
                            
                            import asyncio
                            from backend.motor_browser import processar_lote_com_semaforo
                            
                            with st.spinner("O robô está a operar em lote..."):
                                resultados_lote = asyncio.run(processar_lote_com_semaforo(
                                    chave_acao=chave_acao_selecionada, 
                                    lista_linhas=lista_dados, 
                                    mapeamento=mapeamento_colunas, 
                                    max_concorrencia=5,
                                    converter_pdf_excel=converter_pdfs
                                ))
                                
                            df_resultado = df_lote.copy()
                            df_resultado["Status_Robo"] = [res.get("Status_Robo", "") for res in resultados_lote]
                            df_resultado["Detalhes_Erro"] = [res.get("Detalhes_Erro", "") for res in resultados_lote]
                            df_resultado["Dados_Extraidos"] = [res.get("Dados_Extraidos", "") for res in resultados_lote]
                            
                            st.success("✅ Processamento concluído!")
                            st.markdown("### 📊 Relatório Final")
                            st.dataframe(df_resultado, use_container_width=True)
                            
                            csv_final = df_resultado.to_csv(index=False).encode('utf-8')
                            st.download_button(
                                label="📥 Descarregar Relatório Processado (CSV)",
                                data=csv_final,
                                file_name="relatorio_cotasync_processado.csv",
                                mime="text/csv",
                                type="primary",
                                use_container_width=True
                            )
                    
                    with col2:
                        if st.button("⏰ Agendar para o futuro", use_container_width=True):
                            st.session_state.mostrando_agendador = True
                            
                    if st.session_state.get("mostrando_agendador", False):
                        st.divider()
                        st.markdown("### 📅 Configurar Agendamento")
                        
                        col_data, col_hora = st.columns(2)
                        with col_data:
                            data_agendamento = st.date_input("Data de Início")
                        with col_hora:
                            hora_agendamento = st.time_input("Hora de Início")
                        
                        if st.button("Confirmar Agendamento", type="primary"):
                            import uuid
                            import json
                            import datetime
                            import os
                            
                            os.makedirs("data/agendamentos", exist_ok=True)
                            job_id = str(uuid.uuid4())[:8]
                            caminho_csv = f"data/agendamentos/lote_{job_id}.csv"
                            caminho_json = f"data/agendamentos/job_{job_id}.json"
                            
                            df_lote.to_csv(caminho_csv, index=False)
                            
                            config_job = {
                                "id": job_id,
                                "chave_acao": chave_acao_selecionada,
                                "mapeamento": mapeamento_colunas,
                                "caminho_csv": caminho_csv,
                                "data_execucao": data_agendamento.strftime("%Y-%m-%d"),
                                "hora_execucao": hora_agendamento.strftime("%H:%M"),
                                "converter_pdf_excel": converter_pdfs,
                                "status": "pendente",
                                "criado_em": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            }
                            
                            with open(caminho_json, "w", encoding="utf-8") as f:
                                json.dump(config_job, f, ensure_ascii=False, indent=4)
                                
                            st.success(f"✅ Lote agendado com sucesso para {data_agendamento.strftime('%d/%m/%Y')} às {hora_agendamento.strftime('%H:%M')}! Pode fechar o sistema.")
                            st.session_state.mostrando_agendador = False
                            st.rerun()
            except Exception as e:
                st.error(f"Erro ao ler a planilha: {str(e)}")
        else:
            # SE O UTILIZADOR AINDA NÃO SUBIU O EXCEL, MOSTRA UM PLACEHOLDER CLARO
            st.divider()
            col1, col2 = st.columns(2)

            with col1:
                st.markdown("### 🚀 Execução Imediata")
                st.button("Iniciar Processamento Agora", disabled=True, key="btn_fake_run", use_container_width=True)

            with col2:
                st.markdown("### 📅 Agendamento Futuro")
                st.button("⏰ Agendar para o futuro", disabled=True, key="btn_fake_cron", use_container_width=True)

            st.warning(
                "⚠️ **Ação Necessária:** Para libertar o Calendário de Agendamentos e a Execução em Lote, "
                "por favor faça o upload da sua planilha (.xlsx ou .csv) no campo acima."
            )

    # STATUS DOS AGENDAMENTOS (Sempre visível no fundo da página)
    st.divider()
    st.subheader("📋 Status dos Agendamentos")
    
    import glob
    import os
    import json
    pasta_agendamentos = "data/agendamentos"
    os.makedirs(pasta_agendamentos, exist_ok=True)
    arquivos_job = glob.glob(f"{pasta_agendamentos}/job_*.json")
    
    if arquivos_job:
        for job_file in arquivos_job:
            try:
                with open(job_file, "r", encoding="utf-8") as f:
                    job_data = json.load(f)
                
                status = job_data.get("status", "pendente")
                cor_status = "🟠" if status == "pendente" else "🔵" if status == "processando" else "🟢" if status == "concluido" else "🔴"
                
                with st.expander(f"{cor_status} Lote: {job_data.get('chave_acao', 'N/A')} | Data: {job_data.get('data_execucao', 'N/A')} às {job_data.get('hora_execucao', 'N/A')} | Status: {status.upper()}"):
                    st.write(f"**ID da Tarefa:** {job_data.get('id')}")
                    st.write(f"**Data de Criação:** {job_data.get('criado_em', 'N/A')}")
                    
                    if status == "concluido" and "resultado_csv" in job_data:
                        caminho_res = job_data["resultado_csv"]
                        if os.path.exists(caminho_res):
                            with open(caminho_res, "rb") as file_csv:
                                st.download_button(
                                    label="📥 Descarregar Resultado (CSV)",
                                    data=file_csv,
                                    file_name=f"resultado_lote_{job_data['id']}.csv",
                                    mime="text/csv",
                                    key=f"dl_job_{job_data['id']}"
                                )
                    elif status == "erro":
                        st.error(f"Erro: {job_data.get('detalhes_erro', 'Falha desconhecida')}")
            except Exception as e:
                pass
    else:
        st.info("Nenhum agendamento pendente ou concluído encontrado.")

elif menu_selecionado == "Catálogo de Ações":
    st.markdown("##### 📚 Catálogo de Ações")
    try:
        if not _UI_MAP_PATH.is_file():
            memoria = {"acoes_conhecidas": {}}
        else:
            bruto = _UI_MAP_PATH.read_text(encoding="utf-8").strip()
            memoria = json.loads(bruto) if bruto else {"acoes_conhecidas": {}}
            if not isinstance(memoria, dict):
                memoria = {"acoes_conhecidas": {}}
    except (json.JSONDecodeError, OSError) as exc:
        st.warning(f"Falha ao ler `ui_map.json`: {exc}")
        memoria = {"acoes_conhecidas": {}}

    acoes_memoria = memoria.get("acoes_conhecidas", {})
    if not isinstance(acoes_memoria, dict) or not acoes_memoria:
        st.info("Ainda não há rotinas aprendidas para exibir.")
    else:
        for chave_acao, dados_acao in list(acoes_memoria.items()):
            if not isinstance(dados_acao, dict):
                continue
            nome_amigavel = str(dados_acao.get("nome_amigavel", chave_acao))
            descricao = str(dados_acao.get("descricao", "Sem descrição"))
            passos = dados_acao.get("passos_playwright", [])
            if not isinstance(passos, list):
                passos = []

            with st.expander(f"🧠 {nome_amigavel}", expanded=False):
                col_info, col_btn = st.columns([4, 1])
                with col_info:
                    st.caption(descricao)
                with col_btn:
                    if st.button("🗑️ Excluir", key=f"del_{chave_acao}"):
                        try:
                            if isinstance(memoria.get("acoes_conhecidas"), dict):
                                del memoria["acoes_conhecidas"][chave_acao]
                            _UI_MAP_PATH.write_text(
                                json.dumps(memoria, ensure_ascii=False, indent=4) + "\n",
                                encoding="utf-8",
                            )
                            if hasattr(st, "toast"):
                                st.toast(f"Ação '{nome_amigavel}' removida com sucesso.")
                            else:
                                st.success(f"Ação '{nome_amigavel}' removida com sucesso.")
                            st.rerun()
                        except (KeyError, OSError, TypeError) as exc:
                            st.error(f"Não foi possível excluir a ação: {exc}")
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
