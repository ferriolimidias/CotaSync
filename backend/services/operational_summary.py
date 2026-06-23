"""Resumo curto e seguro do resultado de uma acao para exibicao ao usuario."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from langchain_openai import ChatOpenAI


_SENSITIVE_PARTS = (
    "authorization", "bearer", "cookie", "credential", "password", "secret",
    "senha", "storage_state", "token",
)
_TECHNICAL_TERMS = (
    "desktop_browser", "browserless", "run id", "seletor", "selector",
    "playwright", "storage_state",
)
_MAX_SUMMARY_LENGTH = 500


def _metadata(action: Any, key: str, default: Any = None) -> Any:
    if isinstance(action, dict):
        aliases = {"name": ("name", "nome_amigavel"), "description": ("description", "descricao")}
        for candidate in aliases.get(key, (key,)):
            if candidate in action:
                return action.get(candidate)
        return default
    return getattr(action, key, default)


def _is_sensitive_key(key: str) -> bool:
    lowered = str(key or "").casefold()
    return any(part in lowered for part in _SENSITIVE_PARTS)


def _is_selector_like(value: str) -> bool:
    text = str(value or "").strip()
    return bool(
        text.startswith(("#", ".", "//", "["))
        or " > " in text
        or ":nth-" in text
        or re.search(r"\[[\w-]+=[^\]]+\]", text)
    )


def _clean_scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "sim" if value else "não"
    if not isinstance(value, (str, int, float)):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()[:300]


def _raw_steps(action: Any) -> list[dict[str, Any]]:
    if not isinstance(action, dict):
        return []
    steps = action.get("robust_steps") or action.get("passos_playwright") or []
    return [step for step in steps if isinstance(step, dict)] if isinstance(steps, list) else []


def extraction_targets(action: Any) -> list[str]:
    configured = _metadata(action, "extraction_targets", [])
    targets = [str(item).strip() for item in configured if str(item).strip()] if isinstance(configured, list) else []
    if targets:
        return targets
    for step in _raw_steps(action):
        if str(step.get("tipo") or step.get("type") or "").strip().lower() != "extrair_texto":
            continue
        label = str(step.get("nome") or step.get("extraction_name") or "").strip()
        if label and label not in targets:
            targets.append(label)
    return targets


def _safe_extracted_values(action: Any, result_payload: dict[str, Any] | None) -> dict[str, str]:
    payload = result_payload if isinstance(result_payload, dict) else {}
    raw = payload.get("dados_extraidos", {})
    if not isinstance(raw, dict):
        return {}
    targets = extraction_targets(action)
    selector_labels: dict[str, str] = {}
    for step in _raw_steps(action):
        if str(step.get("tipo") or "").strip().lower() == "extrair_texto":
            selector = str(step.get("seletor") or "").strip()
            label = str(step.get("nome") or "").strip()
            if selector and label:
                selector_labels[selector] = label

    safe: dict[str, str] = {}
    for index, (raw_key, raw_value) in enumerate(raw.items()):
        key = str(raw_key or "").strip()
        if _is_sensitive_key(key):
            continue
        label = selector_labels.get(key) or key
        if _is_selector_like(label):
            label = targets[index] if index < len(targets) else f"resultado {index + 1}"
        value = _clean_scalar(raw_value)
        if value:
            safe[label.replace("_", " ").strip()] = value
    return safe


def _safe_final_title(result_payload: dict[str, Any] | None) -> str:
    payload = result_payload if isinstance(result_payload, dict) else {}
    final_page = payload.get("final_page", {})
    if not isinstance(final_page, dict):
        return ""
    title = _clean_scalar(final_page.get("title"))
    if not title or _is_selector_like(title) or any(term in title.casefold() for term in _TECHNICAL_TERMS):
        return ""
    return title[:160]


def _has_files(result_payload: dict[str, Any] | None) -> bool:
    payload = result_payload if isinstance(result_payload, dict) else {}
    files = payload.get("arquivos", [])
    return isinstance(files, list) and any(str(item).strip() for item in files)


def deterministic_operational_summary(
    action: Any,
    *,
    status: str,
    result_payload: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> str:
    if str(status).lower() != "success":
        error = str(error_message or "").casefold()
        if "autentic" in error or "login" in error:
            return "Não foi possível concluir a ação porque a sessão do sistema não está autenticada."
        if "não encontr" in error or "nao encontr" in error:
            return "Não foi possível concluir a ação porque a informação solicitada não foi encontrada."
        if "indispon" in error or "timeout" in error:
            return "Não foi possível concluir a ação porque o sistema não respondeu a tempo."
        if "não possui passos" in error or "nao possui passos" in error:
            return "Não foi possível executar a ação porque ela ainda não possui uma rotina configurada."
        return "Não foi possível concluir a ação no sistema. Tente novamente ou verifique se o serviço está disponível."

    extracted = _safe_extracted_values(action, result_payload)
    if extracted:
        template = _clean_scalar(_metadata(action, "user_result_summary_template", ""))
        if template:
            values = {key.replace(" ", "_"): value for key, value in extracted.items()}
            values.update(extracted)
            try:
                rendered = template.format_map(values)
            except (KeyError, ValueError):
                rendered = ""
            if rendered and _summary_is_safe(rendered, extracted):
                return rendered
        values = ". ".join(f"{key.capitalize()}: {value}" for key, value in extracted.items())
        return f"Ação concluída com sucesso. {values}."
    if extraction_targets(action):
        return "Ação executada com sucesso, mas o resultado configurado não foi encontrado ou está vazio."
    if _has_files(result_payload):
        return "Ação concluída com sucesso. O arquivo gerado está disponível para envio."
    title = _safe_final_title(result_payload)
    if title:
        return f"Ação executada com sucesso. A tela '{title}' foi aberta, mas nenhum dado foi configurado para extração."
    return "Ação executada com sucesso. Nenhum resultado final foi configurado para retorno nesta ação."


def _summary_is_safe(summary: str, extracted: dict[str, str]) -> bool:
    text = re.sub(r"\s+", " ", str(summary or "")).strip()
    lowered = text.casefold()
    if not text or len(text) > _MAX_SUMMARY_LENGTH:
        return False
    if any(term in lowered for term in _TECHNICAL_TERMS + _SENSITIVE_PARTS):
        return False
    if _is_selector_like(text):
        return False
    return all(value.casefold() in lowered for value in extracted.values())


async def build_operational_summary(
    action: Any,
    *,
    status: str,
    result_payload: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> str:
    fallback = deterministic_operational_summary(
        action, status=status, result_payload=result_payload, error_message=error_message
    )
    enabled = bool(_metadata(action, "ai_result_summary_enabled", True))
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not enabled or not api_key:
        return fallback

    extracted = _safe_extracted_values(action, result_payload)
    context = {
        "objective": _clean_scalar(_metadata(action, "objective", "")),
        "expected_result": _clean_scalar(_metadata(action, "expected_result", "")),
        "status": "success" if str(status).lower() == "success" else "error",
        "extracted_values": extracted,
        "has_configured_extraction": bool(extraction_targets(action)),
        "final_page_title": _safe_final_title(result_payload),
        "has_files": _has_files(result_payload),
        "fallback": fallback,
    }
    prompt = (
        "Escreva uma única resposta operacional curta em português do Brasil para o usuário. "
        "Diga se o objetivo foi atingido e apresente somente os resultados fornecidos. Não invente dados. "
        "Não mencione navegador, modo, passos, cliques, seletores, IDs, logs, credenciais ou detalhes técnicos. "
        "Se não houver extração configurada, diga isso claramente. Contexto seguro: "
        + json.dumps(context, ensure_ascii=False)
    )
    try:
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
        response = await ChatOpenAI(
            model=model, temperature=0, api_key=api_key, timeout=6, max_retries=0
        ).ainvoke(prompt)
        candidate = _clean_scalar(getattr(response, "content", response))
        return candidate if _summary_is_safe(candidate, extracted) else fallback
    except Exception:
        return fallback


def build_technical_summary(
    *, status: str, executed_steps: int = 0, result_payload: dict[str, Any] | None = None
) -> str:
    payload = result_payload if isinstance(result_payload, dict) else {}
    diagnostics = payload.get("selector_diagnostics", [])
    diagnostic_count = len(diagnostics) if isinstance(diagnostics, list) else 0
    outcome = "concluída" if str(status).lower() == "success" else "falhou"
    return f"Execução {outcome}; passos={max(0, int(executed_steps))}; diagnósticos={diagnostic_count}."
