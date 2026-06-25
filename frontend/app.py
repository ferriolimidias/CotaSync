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
from urllib.parse import quote

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

from backend.agente import processar_mensagem  # noqa: E402
from backend.services.ai_observer import openai_configuration_status  # noqa: E402
from frontend.api_client import DemoApiError, demo_api_request, get_actions_for_ui  # noqa: E402

_EVIDENCIA = "data/print_teste.png"
_UI_MAP_PATH = _DATA_DIR / "ui_map.json"
_WHITELIST_PATH = _DATA_DIR / "usuarios_autorizados.json"
_LOG_PATH = _ROOT / "logs" / "operation.log"
_CHAT_HISTORY_PATH = _DATA_DIR / "chat_history.json"

API_BASE_URL = os.getenv("COTASYNC_API_BASE_URL", "").strip()
if not API_BASE_URL:
    try:
        API_BASE_URL = str(st.secrets["API_BASE_URL"]).strip()
    except Exception:
        API_BASE_URL = "http://cotasync_test_backend:8000"


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


def _acoes_ui_por_chave(actions: list[dict]) -> dict[str, dict]:
    return {
        str(action["key"]): action
        for action in actions
        if isinstance(action, dict) and str(action.get("key", "")).strip()
    }


def _excluir_acao_local(chave_acao: str) -> None:
    memoria = _carregar_ui_map()
    acoes = memoria.get("acoes_conhecidas", {})
    if not isinstance(acoes, dict) or chave_acao not in acoes:
        raise KeyError(chave_acao)
    del acoes[chave_acao]
    _UI_MAP_PATH.write_text(
        json.dumps(memoria, ensure_ascii=False, indent=4) + "\n",
        encoding="utf-8",
    )


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


def _render_desktop_view_access(state_suffix: str) -> None:
    """Gera acesso noVNC sob demanda sem renderizar o token como texto."""

    state_key = f"desktop_view_access_{state_suffix}"
    if st.button(
        "Abrir Navegador Desktop",
        key=f"desktop_view_generate_{state_suffix}",
        use_container_width=True,
    ):
        try:
            access = demo_api_request(
                "POST",
                "/api/desktop-browser/view-token",
                api_base_url=API_BASE_URL,
            )
            st.session_state[state_key] = access
        except DemoApiError as exc:
            st.session_state.pop(state_key, None)
            st.error(str(exc))

    access = st.session_state.get(state_key)
    if not isinstance(access, dict):
        return
    view_url = str(access.get("view_url") or "")
    expires_at = str(access.get("expires_at") or "")
    ttl_seconds = int(access.get("ttl_seconds") or 0)
    if view_url:
        st.link_button("Acessar navegador temporariamente", view_url, use_container_width=True)
        ttl_minutes = max(1, ttl_seconds // 60)
        expiry_label = expires_at.replace("T", " ").replace("+00:00", " UTC")
        st.caption(f"Link temporário: {ttl_minutes} min · expira em {expiry_label}.")


def _nome_variavel_sugerida(selector: str, index: int) -> str:
    lowered = str(selector or "").casefold()
    if "edtgrupo" in lowered or "grupo" in lowered:
        return "grupo"
    if "edtcota" in lowered or "cota" in lowered:
        return "cota"
    if "cpf" in lowered:
        return "cpf"
    if "cliente" in lowered:
        return "cliente"
    if "data base" in lowered or "database" in lowered or "data_base" in lowered:
        return "data_base"
    if "select" in lowered:
        return "tipo_consulta"
    tokens = [
        token.lower()
        for token in re.findall(r"[A-Za-zÀ-ÿ0-9]+", str(selector or ""))
        if token.lower() not in {"input", "textarea", "select", "name", "nth", "of", "type", "ctl00", "conteudo"}
    ]
    return "_".join(tokens[-2:]) or f"campo_{index + 1}"


def _rotulo_variavel(variable: object) -> tuple[str, str, bool]:
    if isinstance(variable, dict):
        key = str(variable.get("key") or "").strip()
        label = str(variable.get("label") or key).strip() or key
        return key, label, bool(variable.get("required", True))
    key = str(variable or "").strip()
    return key, key, True


def _render_demo_v01() -> None:
    with st.expander("🎬 Demo v0.1 — Aprender e executar", expanded=True):
        st.caption("Humano demonstra a rotina; a IA revisa esperas, variáveis e riscos antes do replay determinístico.")
        session_id = str(st.session_state.get("demo_session_id", "") or "")

        try:
            browser_status = demo_api_request(
                "GET", "/api/browser/status", api_base_url=API_BASE_URL
            ).get("browser", {})
        except DemoApiError:
            browser_status = {}
        selected_browser_mode = str(browser_status.get("browser_mode") or "browserless")
        st.caption(f"Modo de navegador: `{selected_browser_mode}`")

        if not session_id:
            if st.button("Abrir sessão de navegador", type="primary", key="demo_open_session"):
                try:
                    with st.spinner("Abrindo navegador seguro..."):
                        response = demo_api_request("POST", "/api/demo/sessions", api_base_url=API_BASE_URL)
                    session = response.get("session", {})
                    st.session_state.demo_session_id = str(session.get("id", ""))
                    st.session_state.pop("demo_recorded_steps", None)
                    st.session_state.pop("demo_recording_result", None)
                    st.session_state.pop("demo_saved_action", None)
                    st.session_state.pop("demo_last_run", None)
                    st.rerun()
                except DemoApiError as exc:
                    st.error(str(exc))
            return

        encoded_session = quote(session_id, safe="")
        try:
            response = demo_api_request(
                "GET",
                f"/api/demo/sessions/{encoded_session}",
                api_base_url=API_BASE_URL,
            )
            session = response.get("session", {})
        except DemoApiError as exc:
            st.error(str(exc))
            if st.button("Descartar sessão local", key="demo_forget_session"):
                st.session_state.pop("demo_session_id", None)
                st.rerun()
            return

        status = str(session.get("status", "desconhecida"))
        status_labels = {
            "aguardando_login": "Aguardando login manual",
            "autenticada": "Sessão autenticada",
            "gravando": "Gravando rotina",
            "expirada": "Sessão expirada",
        }
        st.write(f"**Status:** {status_labels.get(status, status)}")
        st.caption(f"Sessão: `{session_id}` · Página: {session.get('page_title', '')}")
        if session.get("using_external_system"):
            st.caption(
                f"Sistema externo: {session.get('external_system_name', '')} · "
                f"Validação: {session.get('auth_validation_mode', '')}"
            )
        else:
            st.caption("Alvo local de demonstração (fallback).")

        live_url = str(session.get("live_url", "") or "")
        if session.get("browser_mode") == "desktop_browser":
            _render_desktop_view_access(f"session_{session_id}")
            st.caption("Se a janela remota não aceitar teclado, use Modo operador.")
        elif live_url:
            link_label = (
                "Abrir Navegador Desktop"
                if session.get("browser_mode") == "desktop_browser"
                else "Abrir navegador da sessão"
            )
            st.link_button(link_label, live_url, use_container_width=True)
            public_devtools_host = str(session.get("public_devtools_host", "") or "")
            if public_devtools_host:
                st.caption(f"DevTools público: `{public_devtools_host}`")
            st.caption("Se a janela remota não aceitar teclado, use Modo operador.")

        if status == "aguardando_login":
            if session.get("using_external_system"):
                if session.get("auth_validation_mode") == "manual_confirmation":
                    st.info(
                        "Validação manual: ao clicar em Login concluído, esta página será aceita "
                        "como sessão autenticada."
                    )
                else:
                    st.info("Faça o login manual no sistema externo e clique em Login concluído.")
            else:
                st.info("Faça o login na janela do navegador. No alvo local, use as credenciais fictícias `demo` / `demo`.")
            if st.button("Login concluído", key="demo_confirm_login", use_container_width=True):
                try:
                    demo_api_request(
                        "POST",
                        f"/api/demo/sessions/{encoded_session}/confirm-login",
                        api_base_url=API_BASE_URL,
                    )
                    st.rerun()
                except DemoApiError as exc:
                    st.warning(str(exc))

        if status in {"aguardando_login", "autenticada", "gravando"}:
            with st.expander("Modo operador", expanded=status == "aguardando_login"):
                records_business_action = status == "gravando"
                st.caption(
                    "Insira texto sem depender da área de transferência do navegador remoto. "
                    + (
                        "Ações por seletor serão capturadas pela gravação."
                        if records_business_action
                        else "Durante o login, estas ações não entram no aprendizado."
                    )
                )
                text_key = f"demo_operator_text_{session_id}"
                selector_key = f"demo_operator_selector_{session_id}"
                flash_key = f"demo_operator_flash_{session_id}"

                def run_operator_request(operation: str) -> None:
                    text_value = str(st.session_state.get(text_key, "") or "")
                    selector_value = str(st.session_state.get(selector_key, "") or "").strip()
                    try:
                        if operation == "insert_active":
                            demo_api_request(
                                "POST",
                                f"/api/demo/sessions/{encoded_session}/operator/insert-active",
                                {"value": text_value},
                                api_base_url=API_BASE_URL,
                            )
                            message = "Texto inserido no campo ativo sem entrar no aprendizado."
                        elif operation == "fill":
                            demo_api_request(
                                "POST",
                                f"/api/demo/sessions/{encoded_session}/operator/fill",
                                {
                                    "selector": selector_value,
                                    "value": text_value,
                                    "record_action": records_business_action,
                                },
                                api_base_url=API_BASE_URL,
                            )
                            message = (
                                "Campo preenchido e capturado pela gravação."
                                if records_business_action
                                else "Campo preenchido sem entrar no aprendizado."
                            )
                        else:
                            demo_api_request(
                                "POST",
                                f"/api/demo/sessions/{encoded_session}/operator/click",
                                {
                                    "selector": selector_value,
                                    "record_action": records_business_action,
                                },
                                api_base_url=API_BASE_URL,
                            )
                            message = (
                                "Clique enviado e capturado pela gravação."
                                if records_business_action
                                else "Clique enviado sem entrar no aprendizado."
                            )
                        st.session_state[flash_key] = ("success", message)
                    except DemoApiError as exc:
                        st.session_state[flash_key] = ("error", str(exc))
                    finally:
                        if operation in {"insert_active", "fill"}:
                            st.session_state[text_key] = ""

                st.text_input(
                    "Texto para inserir no campo ativo",
                    value="",
                    type="password",
                    key=text_key,
                    help="O texto é mascarado, enviado somente à sessão atual e limpo após o envio.",
                )
                st.button(
                    "Inserir no campo ativo",
                    key=f"demo_operator_insert_active_{session_id}",
                    on_click=run_operator_request,
                    args=("insert_active",),
                    use_container_width=True,
                )
                st.text_input(
                    "Seletor do campo",
                    value="",
                    placeholder="#pedido-codigo ou input[type='email']",
                    key=selector_key,
                )
                left, right = st.columns(2)
                left.button(
                    "Preencher seletor",
                    key=f"demo_operator_fill_{session_id}",
                    on_click=run_operator_request,
                    args=("fill",),
                    use_container_width=True,
                )
                right.button(
                    "Clicar elemento por seletor",
                    key=f"demo_operator_click_{session_id}",
                    on_click=run_operator_request,
                    args=("click",),
                    use_container_width=True,
                )
                flash = st.session_state.pop(flash_key, None)
                if isinstance(flash, tuple) and len(flash) == 2:
                    if flash[0] == "success":
                        st.success(flash[1])
                    else:
                        st.error(flash[1])

        recorded_steps = st.session_state.get("demo_recorded_steps")
        saved_action = st.session_state.get("demo_saved_action")
        if status == "autenticada" and not recorded_steps and not saved_action:
            st.markdown("**Aprendizado guiado**")
            st.caption("Descreva o resultado de negócio antes de iniciar a demonstração.")
            action_name_key = f"demo_guided_name_{session_id}"
            objective_key = f"demo_guided_objective_{session_id}"
            input_key = f"demo_guided_input_{session_id}"
            expected_key = f"demo_guided_expected_{session_id}"
            success_key = f"demo_guided_success_{session_id}"
            output_key = f"demo_guided_output_{session_id}"
            ai_mode_key = f"demo_guided_ai_mode_{session_id}"
            st.text_input("Nome da ação", key=action_name_key, placeholder="Ex.: Consultar resultado da assembleia")
            st.text_area("Objetivo da ação", key=objective_key)
            st.text_area(
                "O que o usuário vai informar para executar essa ação",
                key=input_key,
                placeholder="Ex.: grupo e cota",
            )
            st.text_area("O que o CotaSync deve retornar no final", key=expected_key)
            st.text_area("Como saber que deu certo", key=success_key)
            st.selectbox(
                "Tipo de retorno esperado",
                ["texto/dados da tela", "arquivo/PDF", "ambos", "apenas abrir tela"],
                index=0,
                key=output_key,
            )
            st.selectbox(
                "Uso de IA na execução",
                [
                    "não usar IA na execução",
                    "usar IA só para resumir resultado",
                    "usar IA para tentar recuperar falha",
                ],
                index=0,
                key=ai_mode_key,
            )
            if st.button("Iniciar gravação", key="demo_start_recording", type="primary", use_container_width=True):
                try:
                    ai_mode = str(st.session_state.get(ai_mode_key) or "")
                    demo_api_request(
                        "POST",
                        f"/api/demo/sessions/{encoded_session}/recording/start",
                        {
                            "name": st.session_state.get(action_name_key, ""),
                            "objective": st.session_state.get(objective_key, ""),
                            "input_description": st.session_state.get(input_key, ""),
                            "expected_result": st.session_state.get(expected_key, ""),
                            "success_criteria": st.session_state.get(success_key, ""),
                            "output_type": st.session_state.get(output_key, "texto/dados da tela"),
                            "ai_result_summary_enabled": ai_mode == "usar IA só para resumir resultado",
                            "ai_recovery_enabled": ai_mode == "usar IA para tentar recuperar falha",
                        },
                        api_base_url=API_BASE_URL,
                    )
                    st.rerun()
                except DemoApiError as exc:
                    st.error(str(exc))

        if status == "gravando":
            st.warning("Gravação ativa. Execute agora a rotina na janela do navegador.")
            if st.button("Parar gravação", key="demo_stop_recording", type="primary", use_container_width=True):
                try:
                    result = demo_api_request(
                        "POST",
                        f"/api/demo/sessions/{encoded_session}/recording/stop",
                        api_base_url=API_BASE_URL,
                    )
                    st.session_state.demo_recorded_steps = result.get("steps", [])
                    st.session_state.demo_recording_result = result
                    st.rerun()
                except DemoApiError as exc:
                    st.error(str(exc))

        if isinstance(recorded_steps, list) and recorded_steps:
            recording_result = st.session_state.get("demo_recording_result", {})
            if not isinstance(recording_result, dict):
                recording_result = {}
            guided = recording_result.get("guided_learning", {})
            if not isinstance(guided, dict):
                guided = {}
            synthesis = recording_result.get("ai_synthesis", {})
            if isinstance(synthesis, dict) and synthesis:
                st.markdown("**Síntese do aprendizado**")
                st.info(str(synthesis.get("ai_observer_summary") or "Análise local concluída."))
            st.markdown("**Passos capturados**")
            variable_names: dict[str, str] = {}
            captured_variable_rows: list[tuple[int, str, str]] = []
            for step in recorded_steps:
                if not isinstance(step, dict):
                    continue
                index = int(step.get("index", 0))
                step_type = str(step.get("tipo", "ação"))
                selector = str(step.get("seletor", ""))
                st.code(f"{index + 1}. {step_type} → {selector}", language=None)
                if step_type == "preencher":
                    captured_variable_rows.append((index, selector, _nome_variavel_sugerida(selector, index)))

            if captured_variable_rows:
                st.markdown("**Revisar variáveis**")
                for index, selector, suggested in captured_variable_rows:
                    variable_names[str(index)] = st.text_input(
                        f"Rótulo/chave da variável do passo {index + 1}",
                        value=suggested,
                        key=f"demo_variable_{session_id}_{index}",
                    )

            suggested_targets = [
                str(step.get("nome") or "").replace("_", " ").strip()
                for step in recorded_steps
                if isinstance(step, dict) and str(step.get("tipo") or "").lower() == "extrair_texto"
            ]
            st.markdown("**Configuração final da ação**")
            action_name = st.text_input(
                "Nome da ação",
                value=str(guided.get("name") or ""),
                placeholder="Ex.: Consultar resultado da assembleia",
                key=f"demo_action_name_{session_id}",
            )
            action_objective = st.text_input(
                "Objetivo da ação",
                value=str(guided.get("objective") or synthesis.get("suggested_objective") or ""),
                key=f"demo_action_objective_{session_id}",
            )
            input_description = st.text_input(
                "Entradas informadas pelo usuário",
                value=str(guided.get("input_description") or ""),
                key=f"demo_action_input_{session_id}",
            )
            expected_result = st.text_input(
                "Resultado esperado para retornar ao usuário",
                value=str(guided.get("expected_result") or synthesis.get("suggested_expected_result") or ""),
                key=f"demo_action_expected_result_{session_id}",
            )
            success_criteria = st.text_input(
                "Como saber que deu certo",
                value=str(guided.get("success_criteria") or ""),
                key=f"demo_action_success_{session_id}",
            )
            output_options = ["texto/dados da tela", "arquivo/PDF", "ambos", "apenas abrir tela"]
            guided_output = str(guided.get("output_type") or "texto/dados da tela")
            output_type = st.selectbox(
                "Tipo de retorno esperado",
                output_options,
                index=output_options.index(guided_output) if guided_output in output_options else 0,
                key=f"demo_action_output_{session_id}",
            )

            st.markdown("**Resultado que a ação deve retornar**")
            candidates = recording_result.get("output_candidates", [])
            candidates = candidates if isinstance(candidates, list) else []
            ai_candidates = synthesis.get("suggested_extraction_targets", []) if isinstance(synthesis, dict) else []
            if isinstance(ai_candidates, list):
                candidates = candidates + [item for item in ai_candidates if isinstance(item, dict)]
            objective_terms = ("valor", "parcela", "valor da parcela", "parcela atual", "vencimento", "número de parcelas", "numero de parcelas", "status")
            objective_text = f"{action_objective} {expected_result}".casefold()
            if any(term in objective_text for term in ("valor", "parcela")):
                focused = [
                    item for item in candidates
                    if isinstance(item, dict)
                    and any(term in f"{item.get('label', '')} {item.get('preview', '')}".casefold() for term in objective_terms)
                ]
                candidates = focused + [item for item in candidates if item not in focused]
            candidate_options = {
                f"{item.get('label', 'resultado')}: {item.get('preview', '')}": item
                for item in candidates
                if isinstance(item, dict) and item.get("selector")
            }
            selected_candidates = st.multiselect(
                "Textos detectados na tela final",
                list(candidate_options),
                key=f"demo_output_candidates_{session_id}",
            )
            manual_label = st.text_input(
                "Nome do resultado manual",
                key=f"demo_manual_output_label_{session_id}",
                placeholder="Ex.: valor_contemplacao",
            )
            manual_selector = st.text_input(
                "Seletor CSS do resultado manual",
                key=f"demo_manual_output_selector_{session_id}",
                placeholder="#resultado ou .valor-final",
            )
            extract_visible_text = st.checkbox(
                "Extrair texto visível da tela final (menos preciso)",
                key=f"demo_extract_visible_{session_id}",
            )
            download_detected = bool(recording_result.get("download_detected"))
            if download_detected:
                st.success("Download detectado durante a demonstração.")
            return_downloaded_file = st.checkbox(
                "Retornar arquivo baixado",
                value=download_detected and output_type in {"arquivo/PDF", "ambos"},
                disabled=not download_detected,
                key=f"demo_return_download_{session_id}",
            )
            if st.button("Salvar ação aprendida", key="demo_save_action", type="primary", use_container_width=True):
                try:
                    configured_targets = [
                        {
                            "label": str(candidate_options[item].get("label") or "resultado"),
                            "selector": str(candidate_options[item].get("selector") or ""),
                        }
                        for item in selected_candidates
                    ]
                    if manual_label.strip() and manual_selector.strip():
                        configured_targets.append({"label": manual_label, "selector": manual_selector})
                    ai_result_enabled = bool(guided.get("ai_result_summary_enabled", False))
                    ai_recovery_enabled = bool(guided.get("ai_recovery_enabled", False))
                    with st.spinner("Revisando a demonstração e salvando a ação..."):
                        result = demo_api_request(
                            "POST",
                            f"/api/demo/sessions/{encoded_session}/actions",
                            {
                                "name": action_name,
                                "description": "Rotina demonstrada manualmente e revisada pelo observador de IA.",
                                "objective": action_objective,
                                "input_description": input_description,
                                "expected_result": expected_result,
                                "success_criteria": success_criteria,
                                "output_type": output_type,
                                "variable_names": variable_names,
                                "extraction_targets": configured_targets,
                                "extract_visible_text": extract_visible_text,
                                "return_downloaded_file": return_downloaded_file,
                                "ai_result_summary_enabled": ai_result_enabled,
                                "ai_recovery_enabled": ai_recovery_enabled,
                            },
                            api_base_url=API_BASE_URL,
                            timeout=30,
                        )
                    st.session_state.demo_saved_action = result.get("action", {})
                    st.session_state.pop("demo_recorded_steps", None)
                    st.session_state.pop("demo_recording_result", None)
                    st.success("Ação aprendida e salva no catálogo.")
                    st.rerun()
                except DemoApiError as exc:
                    st.error(str(exc))

        saved_action = st.session_state.get("demo_saved_action")
        if isinstance(saved_action, dict) and saved_action:
            st.markdown(f"**Replay determinístico:** {saved_action.get('name', '')}")
            observer_summary = str(saved_action.get("ai_observer_summary") or "").strip()
            if saved_action.get("ai_reviewed") is True:
                st.success("Observador IA ativo")
                st.write(f"Síntese IA: {observer_summary or 'Ação demonstrada revisada pela IA.'}")
                st.caption(f"Modo: {saved_action.get('learning_mode') or 'aprendizado demonstrado observado por IA'}")
            elif observer_summary:
                st.info(observer_summary)
            run_variables: dict[str, str] = {}
            for variable in saved_action.get("variables", []):
                variable_name, variable_label, _required = _rotulo_variavel(variable)
                if not variable_name:
                    continue
                run_variables[variable_name] = st.text_input(
                    variable_label,
                    placeholder="Ex.: PED-2002",
                    key=f"demo_run_variable_{session_id}_{variable_name}",
                )
            if st.button("Executar ação aprendida", key="demo_run_action", type="primary", use_container_width=True):
                try:
                    action_id = quote(str(saved_action.get("id", "")), safe="")
                    result = demo_api_request(
                        "POST",
                        f"/api/actions/{action_id}/run",
                        {
                            "variables": run_variables,
                            "mode": "sync",
                            "requested_by": "streamlit-demo",
                            "session_id": session_id,
                        },
                        api_base_url=API_BASE_URL,
                        timeout=30,
                    )
                    st.session_state.demo_last_run = result.get("run", {})
                    st.rerun()
                except DemoApiError as exc:
                    st.error(str(exc))

        last_run = st.session_state.get("demo_last_run")
        if isinstance(last_run, dict) and last_run:
            if last_run.get("status") == "success":
                st.success(str(last_run.get("operational_summary") or "Ação executada."))
            else:
                st.error(str(last_run.get("operational_summary") or "Execução não concluída."))
            payload = last_run.get("result_payload", {})
            if isinstance(payload, dict):
                if payload.get("session_revalidated") is True:
                    st.info("Sessão revalidada automaticamente.")
                extracted = payload.get("dados_extraidos")
                steps_executed = payload.get("passos_executados")
                if steps_executed:
                    st.caption(f"Passos executados: {steps_executed}")
                if extracted:
                    with st.expander("Ver dados extraídos", expanded=False):
                        st.json(extracted)
                diagnostics = payload.get("step_diagnostics") or payload.get("selector_diagnostics")
                if diagnostics:
                    with st.expander("Ver diagnóstico técnico", expanded=False):
                        st.json(diagnostics)
                with st.expander("Ver JSON/result_payload", expanded=False):
                    st.json(payload)
                _render_runtime_downloads(
                    payload.get("downloaded_files", []),
                    key_prefix=f"demo_run_download_{last_run.get('id', '')}",
                )
                evidence = str(payload.get("evidencia") or "")
                evidence_path = _ROOT / evidence
                if evidence and evidence_path.is_file():
                    st.image(str(evidence_path), caption="Evidência do replay", use_container_width=True)

        st.divider()
        if st.button("Encerrar sessão da demo", key="demo_close_session", use_container_width=True):
            try:
                demo_api_request(
                    "DELETE",
                    f"/api/demo/sessions/{encoded_session}",
                    api_base_url=API_BASE_URL,
                )
            except DemoApiError:
                pass
            for key in (
                "demo_session_id",
                "demo_recorded_steps",
                "demo_recording_result",
                "demo_saved_action",
                "demo_last_run",
            ):
                st.session_state.pop(key, None)
            st.rerun()


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
        downloaded_files = resposta.get("downloaded_files")
        if isinstance(downloaded_files, list) and downloaded_files:
            payload["downloaded_files"] = downloaded_files
        main_file = resposta.get("main_file")
        if isinstance(main_file, dict) and main_file:
            payload["main_file"] = main_file
        result_payload = resposta.get("result_payload")
        if isinstance(result_payload, dict) and result_payload:
            payload["result_payload"] = result_payload
        return payload
    return {"role": "assistant", "content": str(resposta)}


def _render_runtime_downloads(files: object, *, key_prefix: str) -> None:
    if not isinstance(files, list):
        return
    allowed_root = (_ROOT / "data" / "runs" / "downloads").resolve()
    for file_index, metadata in enumerate(files):
        if not isinstance(metadata, dict):
            continue
        relative_path = str(metadata.get("path") or "")
        file_path = (_ROOT / relative_path).resolve()
        if not file_path.is_file() or not file_path.is_relative_to(allowed_root):
            continue
        st.download_button(
            "Baixar arquivo gerado",
            data=file_path.read_bytes(),
            file_name=str(metadata.get("name") or file_path.name),
            mime=str(metadata.get("mime_type") or "application/octet-stream"),
            key=f"{key_prefix}_{file_index}",
        )


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
                if "downloaded_files" in item and isinstance(item.get("downloaded_files"), list):
                    msg_restaurada["downloaded_files"] = item["downloaded_files"]
                if "main_file" in item and isinstance(item.get("main_file"), dict):
                    msg_restaurada["main_file"] = item["main_file"]
                if "result_payload" in item and isinstance(item.get("result_payload"), dict):
                    msg_restaurada["result_payload"] = item["result_payload"]
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
acoes_ui_result = get_actions_for_ui(API_BASE_URL, _UI_MAP_PATH)
acoes_ui = _acoes_ui_por_chave(acoes_ui_result.actions)

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
st.caption(f"🔗 API REST (FastAPI): `{API_BASE_URL}`")
if acoes_ui_result.fallback_error:
    st.error("Não foi possível carregar as ações aprendidas no momento.")
elif acoes_ui_result.source == "fallback_local":
    st.caption("⚠️ API indisponível, usando leitura local temporária.")

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
    acoes_sidebar = acoes_ui
    if acoes_sidebar:
        opcoes_sidebar = {
            dados.get("name", chave): chave
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
            [
                variable
                for variable in acao_sidebar_dados.get("variables", [])
                if isinstance(variable, dict) and variable.get("required", True) and variable.get("key")
            ]
            if isinstance(acao_sidebar_dados, dict)
            else []
        )
        dados_digitados: dict[str, str] = {}
        if isinstance(variaveis_necessarias, list) and variaveis_necessarias:
            for variable in variaveis_necessarias:
                chave_var, rotulo_var, _required = _rotulo_variavel(variable)
                if not chave_var:
                    continue
                dados_digitados[chave_var] = st.text_input(
                    rotulo_var,
                    key=f"acao_var_{chave_acao}_{chave_var}",
                )
        if st.button("🚀 Disparar Ação", use_container_width=True, key="acao_sidebar_btn"):
            if isinstance(variaveis_necessarias, list) and variaveis_necessarias:
                faltantes = [
                    _rotulo_variavel(v)[1]
                    for v in variaveis_necessarias
                    if not str(dados_digitados.get(_rotulo_variavel(v)[0], "")).strip()
                ]
                if faltantes:
                    st.warning(f"Preencha as variáveis obrigatórias: {', '.join(faltantes)}")
                else:
                    st.session_state.messages.append({"role": "user", "content": chave_acao})
                    salvar_historico_disco(st.session_state.messages)
                    with st.spinner("Executando ação parametrizada..."):
                        action_id = quote(str(acao_sidebar_dados.get("id") or chave_acao), safe="")
                        run_response = demo_api_request(
                            "POST",
                            f"/api/actions/{action_id}/run",
                            {"variables": dados_digitados, "mode": "sync", "requested_by": "streamlit-quick"},
                            api_base_url=API_BASE_URL,
                            timeout=60,
                        )
                        run = run_response.get("run", {})
                        payload = run.get("result_payload") if isinstance(run, dict) else {}
                        payload = payload if isinstance(payload, dict) else {}
                        resultado_direto = {
                            "texto": str(run.get("operational_summary") or "Execução concluída."),
                            "result_payload": payload,
                            "downloaded_files": payload.get("downloaded_files", []),
                            "main_file": payload.get("main_file"),
                            "status": run.get("status"),
                            "estado": "NORMAL",
                        }
                    if isinstance(resultado_direto, dict):
                        st.session_state.estado_agente = str(resultado_direto.get("estado", "NORMAL"))
                    st.session_state.messages.append(_normalizar_resposta_assistente(resultado_direto))
                    salvar_historico_disco(st.session_state.messages)
                    st.rerun()
            else:
                st.session_state.messages.append({"role": "user", "content": chave_acao})
                salvar_historico_disco(st.session_state.messages)
                with st.spinner("Executando ação rápida..."):
                    action_id = quote(str(acao_sidebar_dados.get("id") or chave_acao), safe="")
                    run_response = demo_api_request(
                        "POST",
                        f"/api/actions/{action_id}/run",
                        {"variables": {}, "mode": "sync", "requested_by": "streamlit-quick"},
                        api_base_url=API_BASE_URL,
                        timeout=60,
                    )
                    run = run_response.get("run", {})
                    payload = run.get("result_payload") if isinstance(run, dict) else {}
                    payload = payload if isinstance(payload, dict) else {}
                    resultado_direto = {
                        "texto": str(run.get("operational_summary") or "Execução concluída."),
                        "result_payload": payload,
                        "downloaded_files": payload.get("downloaded_files", []),
                        "main_file": payload.get("main_file"),
                        "status": run.get("status"),
                        "estado": "NORMAL",
                    }
                if isinstance(resultado_direto, dict):
                    st.session_state.estado_agente = str(resultado_direto.get("estado", "NORMAL"))
                st.session_state.messages.append(_normalizar_resposta_assistente(resultado_direto))
                salvar_historico_disco(st.session_state.messages)
                st.rerun()
    else:
        st.caption("Nenhuma ação aprendida ainda.")

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
    _render_demo_v01()
    st.subheader("Conversa com o Agente")
    st.caption("Chat operacional com execucao assincrona e evidencias visuais.")

    caminho_evidencia_padrao = _ROOT / _EVIDENCIA
    for i, msg in enumerate(st.session_state.messages):
        with st.chat_message(msg["role"]):
            st.markdown(msg.get("content", ""))

            dados_ex = msg.get("dados_extraidos")
            if isinstance(dados_ex, dict) and dados_ex:
                with st.expander("Ver dados extraídos", expanded=False):
                    st.json(dados_ex)

            result_payload_msg = msg.get("result_payload")
            if isinstance(result_payload_msg, dict) and result_payload_msg:
                with st.expander("Ver JSON/result_payload", expanded=False):
                    st.json(result_payload_msg)

            runtime_files = msg.get("downloaded_files")
            if isinstance(runtime_files, list) and runtime_files:
                _render_runtime_downloads(runtime_files, key_prefix=f"chat_runtime_download_{i}")

            if "arquivos" in msg and msg["arquivos"]:
                from backend.motor_browser import _converter_pdf_para_excel
                for idx_arq, caminho in enumerate(msg["arquivos"]):
                    nome_arq = os.path.basename(str(caminho))
                    caminho_abs = Path(str(caminho)) if os.path.isabs(str(caminho)) else _ROOT / str(caminho)
                    caminho_resolvido = str(caminho_abs)
                    if os.path.exists(caminho_resolvido):
                        col1, col2 = st.columns([1, 1])

                        with col1:
                            with open(caminho_resolvido, "rb") as f:
                                arquivo_bytes = f.read()
                                st.download_button(
                                    label="📄 Baixar PDF",
                                    data=arquivo_bytes,
                                    file_name=nome_arq,
                                    mime="application/pdf",
                                    key=f"dl_pdf_{i}_{idx_arq}_{nome_arq}",
                                )

                        with col2:
                            if caminho_resolvido.endswith(".pdf"):
                                caminho_excel = caminho_resolvido.replace(".pdf", ".xlsx")
                                if os.path.exists(caminho_excel):
                                    with open(caminho_excel, "rb") as f_xls:
                                        excel_bytes = f_xls.read()
                                        st.download_button(
                                            label="📊 Baixar Excel",
                                            data=excel_bytes,
                                            file_name=os.path.basename(caminho_excel),
                                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                            key=f"dl_xls_{i}_{idx_arq}_{nome_arq}",
                                        )
                                else:
                                    if st.button("🪄 Converter para Excel", key=f"btn_conv_{i}_{idx_arq}_{nome_arq}"):
                                        with st.spinner("Extraindo tabelas do PDF..."):
                                            _converter_pdf_para_excel(caminho_resolvido)
                                        st.rerun()

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
                "downloaded_files": resultado_ia.get("downloaded_files", []),
                "main_file": resultado_ia.get("main_file", {}),
                "result_payload": resultado_ia.get("result_payload", {}),
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
                                    max_concorrencia=5
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
                                csv_bytes = file_csv.read()
                                st.download_button(
                                    label="📥 Descarregar Resultado (CSV)",
                                    data=csv_bytes,
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
    if not acoes_ui:
        st.info("Nenhuma ação aprendida ainda.")
    else:
        for chave_acao, dados_acao in list(acoes_ui.items()):
            if not isinstance(dados_acao, dict):
                continue
            nome_amigavel = str(dados_acao.get("name", chave_acao))
            descricao = str(dados_acao.get("description") or "Sem descrição")
            variables = dados_acao.get("variables", [])
            if not isinstance(variables, list):
                variables = []
            steps_count = int(dados_acao.get("steps_count", 0) or 0)

            with st.expander(f"🧠 {nome_amigavel}", expanded=False):
                col_info, col_btn = st.columns([4, 1])
                with col_info:
                    st.caption(descricao)
                with col_btn:
                    if st.button("🗑️ Excluir", key=f"del_{chave_acao}"):
                        try:
                            _excluir_acao_local(chave_acao)
                            if hasattr(st, "toast"):
                                st.toast(f"Ação '{nome_amigavel}' removida com sucesso.")
                            else:
                                st.success(f"Ação '{nome_amigavel}' removida com sucesso.")
                            st.rerun()
                        except (KeyError, OSError, TypeError) as exc:
                            st.error(f"Não foi possível excluir a ação: {exc}")
                if variables:
                    variable_labels = [
                        str(variable.get("label") or variable.get("key"))
                        for variable in variables
                        if isinstance(variable, dict) and variable.get("key")
                    ]
                    if variable_labels:
                        st.caption(f"Variáveis: {', '.join(variable_labels)}")
                if steps_count:
                    st.caption(f"Passos técnicos registrados: {steps_count}")
                else:
                    st.info("Esta rotina ainda não possui passos técnicos registrados.")
                observer_summary = str(dados_acao.get("ai_observer_summary") or "").strip()
                if dados_acao.get("learning_mode") in {
                    "human_demo_live_ai_observed",
                    "desktop_browser_live_ai_observed",
                }:
                    if dados_acao.get("ai_reviewed"):
                        st.success("Observador IA ativo")
                        st.write(f"Síntese IA: {observer_summary or 'Ação demonstrada revisada pela IA.'}")
                        st.caption("Modo: aprendizado demonstrado observado por IA")
                    else:
                        st.caption("Aprendizado demonstrado · Análise local (IA não configurada ou indisponível)")
                        if observer_summary:
                            st.write(observer_summary)

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
    openai_status = openai_configuration_status()
    st.markdown("##### Observador OpenAI")
    st.write(f"**OpenAI configurada:** {'sim' if openai_status['configured'] else 'não'}")
    st.write(f"**Modelo atual:** `{openai_status['model']}`")
    st.caption("Configure `OPENAI_API_KEY` e, opcionalmente, `OPENAI_MODEL` no ambiente. A chave não é exibida nem persistida.")
    st.divider()

    st.markdown("##### Navegador")
    try:
        browser_payload = demo_api_request(
            "GET", "/api/browser/status", api_base_url=API_BASE_URL
        ).get("browser", {})
    except DemoApiError as exc:
        browser_payload = {}
        st.error(str(exc))
    current_browser_mode = str(browser_payload.get("browser_mode") or "browserless")
    available_browser_modes = browser_payload.get("available_modes") or ["browserless", "desktop_browser"]
    if current_browser_mode not in available_browser_modes:
        current_browser_mode = "browserless"
    with st.form("browser_mode_config_form"):
        selected_browser_mode = st.selectbox(
            "browser_mode",
            options=available_browser_modes,
            index=available_browser_modes.index(current_browser_mode),
            format_func=lambda value: "Browserless" if value == "browserless" else "Desktop Browser",
        )
        if st.form_submit_button("Salvar modo de navegador", type="primary", use_container_width=True):
            try:
                demo_api_request(
                    "PUT",
                    "/api/browser/config",
                    {"browser_mode": selected_browser_mode},
                    api_base_url=API_BASE_URL,
                )
                st.success("Modo salvo. Novas sessões usarão este provider.")
                st.rerun()
            except DemoApiError as exc:
                st.error(str(exc))

    desktop_status = browser_payload.get("desktop_browser", {})
    if isinstance(desktop_status, dict):
        status_left, status_right = st.columns(2)
        status_left.metric("Desktop Browser", "rodando" if desktop_status.get("running") else "parado")
        status_right.metric("CDP", "acessível" if desktop_status.get("cdp_reachable") else "indisponível")
        st.caption(f"CDP interno: `{desktop_status.get('cdp_url') or 'não configurado'}`")
        _render_desktop_view_access("settings")
        st.caption(f"Perfil persistente no worker: `{desktop_status.get('profile_dir') or '/data/profile'}`")
    st.divider()

    st.markdown("##### Sistema externo")
    st.caption("A próxima sessão de navegador usará esta URL. Campos de autenticação são opcionais e não armazenam credenciais.")
    try:
        external_config = demo_api_request(
            "GET", "/api/external-systems/current", api_base_url=API_BASE_URL
        ).get("external_system", {})
    except DemoApiError as exc:
        external_config = {}
        st.error(str(exc))
    with st.form("external_system_config_form"):
        external_system_name = st.text_input(
            "external_system_name",
            value=str(external_config.get("external_system_name") or ""),
            placeholder="Ex.: ERP do cliente",
        )
        external_login_url = st.text_input(
            "external_login_url",
            value=str(external_config.get("external_login_url") or ""),
            placeholder="https://erp.cliente.com/login",
        )
        auth_success_text = st.text_input(
            "auth_success_text (opcional)",
            value=str(external_config.get("auth_success_text") or ""),
            help="Texto que só aparece após autenticação.",
        )
        auth_success_selector = st.text_input(
            "auth_success_selector (opcional)",
            value=str(external_config.get("auth_success_selector") or ""),
            help="Tem prioridade sobre auth_success_text e deve estar visível após o login.",
        )
        validation_options = ["automática", "manual_confirmation"]
        configured_validation = str(external_config.get("validation") or "")
        validation = st.selectbox(
            "validation",
            validation_options,
            index=1 if configured_validation == "manual_confirmation" else 0,
            help="No modo manual, o clique do usuário confirma uma página web válida.",
        )
        if st.form_submit_button("Salvar sistema externo", type="primary", use_container_width=True):
            try:
                demo_api_request(
                    "PUT",
                    "/api/external-systems/current",
                    {
                        "external_system_name": external_system_name,
                        "external_login_url": external_login_url,
                        "validation": "manual_confirmation" if validation == "manual_confirmation" else "",
                        "auth_success_text": auth_success_text,
                        "auth_success_selector": auth_success_selector,
                    },
                    api_base_url=API_BASE_URL,
                )
                st.success("Sistema externo salvo. A próxima sessão usará esta configuração.")
                st.rerun()
            except DemoApiError as exc:
                st.error(str(exc))
    public_base_url = os.getenv("COTASYNC_PUBLIC_BASE_URL", "").strip()
    browserless_public_url = os.getenv("COTASYNC_BROWSERLESS_PUBLIC_URL", "").strip()
    desktop_public_url = os.getenv("COTASYNC_DESKTOP_VIEW_PUBLIC_BASE_URL", "").strip()
    desktop_browser_view_url = os.getenv("DESKTOP_BROWSER_VIEW_URL", "").strip()
    st.caption(f"URL pública do app: `{public_base_url or 'não configurada'}`")
    st.caption(f"URL pública do navegador: `{browserless_public_url or 'não configurada'}`")
    st.caption(f"URL pública protegida do Desktop Browser: `{desktop_public_url or 'não configurada'}`")
    st.caption(f"Visualização local do Desktop Browser: `{desktop_browser_view_url or 'não configurada'}`")
    st.divider()

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
