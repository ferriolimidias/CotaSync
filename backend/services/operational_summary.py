"""Resumo curto e seguro do resultado de uma acao para exibicao ao usuario."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
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
_MAX_AI_CONTEXT_CHARS = 8000
_NOISY_TEXT_THRESHOLD = 700
_FORM_HINTS = (
    "consultar",
    "considera",
    "contemplação",
    "contemplacao",
    "data base",
    "filial",
    "filtro",
    "filtrar",
    "gerar",
    "grupo",
    "intervalo",
    "lista",
    "período",
    "periodo",
    "produto",
    "relatório",
    "relatorio",
    "situação",
    "situacao",
    "tipo de venda",
    "unidade negócio",
    "unidade negocio",
    "vencimento",
)
_NAVIGATION_HINTS = (
    "página inicial",
    "pagina inicial",
    "menu",
    "sair",
    "venda",
    "cobrança",
    "cobranca",
    "relatórios",
    "relatorios",
)


@dataclass(frozen=True)
class OperationalSummaryResult:
    summary: str
    ai_summary_used: bool
    summary_source: str
    summary_reason: str = ""


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
    text = str(value)
    text = re.sub(r"([?&](?:token|key|secret|password|senha|credential)=)[^&\s]+", r"\1[REDACTED]", text, flags=re.I)
    text = re.sub(r"((?:token|secret|password|senha|authorization|cookie)\s*[:=]\s*)\S+", r"\1[REDACTED]", text, flags=re.I)
    text = re.sub(r"(?i)\b(bearer)\s+[a-z0-9._~+/=-]+", r"\1 [REDACTED]", text)
    text = re.sub(r"(?i)\b(?:/[a-z0-9._ -]+){2,}/[a-z0-9._ -]+", "[caminho omitido]", text)
    text = re.sub(r"https?://[^\s]+", "[url omitida]", text)
    return re.sub(r"\s+", " ", text).strip()[:300]


def _normalize_label_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _friendly_extraction_label(value: str) -> str:
    normalized = _normalize_label_key(value)
    if (
        "qtd pcls pagas" in normalized
        or "qtd parcelas pagas" in normalized
        or "quantidade parcelas pagas" in normalized
        or "quantidade de parcelas pagas" in normalized
    ):
        return "Quantidade de parcelas pagas"
    return str(value or "").replace("_", " ").strip()


def _clean_text(value: Any, *, limit: int = 1200) -> str:
    if value is None or not isinstance(value, (str, int, float, bool)):
        return ""
    text = str(value)
    text = re.sub(r"([?&](?:token|key|secret|password|senha|credential)=)[^&\s]+", r"\1[REDACTED]", text, flags=re.I)
    text = re.sub(r"((?:token|secret|password|senha|authorization|cookie)\s*[:=]\s*)\S+", r"\1[REDACTED]", text, flags=re.I)
    text = re.sub(r"(?i)\b(bearer)\s+[a-z0-9._~+/=-]+", r"\1 [REDACTED]", text)
    text = re.sub(r"(?i)\b(?:/[a-z0-9._ -]+){2,}/[a-z0-9._ -]+", "[caminho omitido]", text)
    text = re.sub(r"https?://[^\s]+", "[url omitida]", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _is_meaningful_text(text: str) -> bool:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    alpha_count = len(re.findall(r"[A-Za-zÀ-ÿ]", cleaned))
    return len(cleaned) >= 30 and alpha_count >= 20


def _dedupe_lines(text: str, *, limit: int = _MAX_AI_CONTEXT_CHARS) -> str:
    seen: set[str] = set()
    kept: list[str] = []
    for raw_line in re.split(r"[\r\n]+| {2,}", str(text or "")):
        line = _clean_text(raw_line, limit=500)
        if not line:
            continue
        key = line.casefold()
        if key in seen:
            continue
        seen.add(key)
        kept.append(line)
        if sum(len(item) + 1 for item in kept) >= limit:
            break
    return "\n".join(kept)[:limit]


def _looks_like_noisy_text(text: str) -> bool:
    cleaned = str(text or "").strip()
    lowered = cleaned.casefold()
    if len(cleaned) >= _NOISY_TEXT_THRESHOLD:
        return True
    hints = sum(1 for hint in _NAVIGATION_HINTS if hint in lowered)
    return hints >= 3 and len(cleaned) >= 250


def _looks_like_form_or_filter(text: str) -> bool:
    lowered = str(text or "").casefold()
    form_hits = sum(1 for hint in _FORM_HINTS if hint in lowered)
    result_hints = (
        "resultado",
        "resultados encontrados",
        "total encontrado",
        "status ativo",
        "boleto localizado",
        "valor:",
    )
    has_result_hint = any(hint in lowered for hint in result_hints)
    return form_hits >= 4 and not has_result_hint


def _labels_found(text: str, labels: list[tuple[str, str]]) -> list[str]:
    lowered = str(text or "").casefold()
    found: list[str] = []
    for needle, label in labels:
        if needle in lowered and label not in found:
            found.append(label)
    return found


def _extract_form_fields(text: str) -> list[str]:
    return _labels_found(
        text,
        [
            ("data base", "data base"),
            ("grupo", "grupo"),
            ("sit. do grupo", "situação do grupo"),
            ("situação do grupo", "situação do grupo"),
            ("situacao do grupo", "situação do grupo"),
            ("produto", "produto"),
            ("tipo de venda", "tipo de venda"),
            ("ponto de venda", "ponto de venda"),
            ("filial", "filial"),
            ("unidade negócio", "unidade de negócio"),
            ("unidade negocio", "unidade de negócio"),
            ("comissionado", "comissionado"),
            ("ponto entrega", "ponto de entrega"),
            ("ponto de entrega", "ponto de entrega"),
            ("contemplação", "contemplação"),
            ("contemplacao", "contemplação"),
            ("intervalo", "intervalo"),
            ("percentual pago bem", "percentual pago do bem"),
            ("ordem", "ordem"),
            ("período", "período"),
            ("periodo", "período"),
            ("vencimento", "vencimento"),
        ],
    )[:10]


def _extract_form_options(text: str) -> list[str]:
    return _labels_found(
        text,
        [
            ("entregas parciais", "entregas parciais"),
            ("entrega de bem parcial", "entregas parciais"),
            ("fgts", "FGTS"),
            ("sorteio", "contemplação por sorteio"),
            ("lance", "contemplação por lance"),
            ("lances pagos", "lances pagos"),
            ("cotas canceladas", "cotas canceladas"),
            ("lance parcelado pendente", "lance parcelado pendente"),
            ("salta de página por grupo", "salto de página por grupo"),
            ("salta de pagina por grupo", "salto de página por grupo"),
            ("situação grupo na data base", "situação do grupo na data base"),
            ("situacao grupo na data base", "situação do grupo na data base"),
        ],
    )[:8]


def _legacy_form_options(text: str) -> list[str]:
    lowered = str(text or "").casefold()
    labels = [
        ("grupo", "grupo"),
        ("período", "período"),
        ("periodo", "período"),
        ("produto", "produto"),
        ("tipo de venda", "tipo de venda"),
        ("situação", "situação"),
        ("situacao", "situação"),
        ("vencimento", "vencimento"),
        ("relatório", "relatório"),
        ("relatorio", "relatório"),
    ]
    options: list[str] = []
    for needle, label in labels:
        if needle in lowered and label not in options:
            options.append(label)
    return options[:6]


def _screen_subject(text: str) -> str:
    lowered = str(text or "").casefold()
    if "bens a entregar" in lowered:
        return "um relatório de bens a entregar"
    if _looks_like_form_or_filter(text):
        return "um formulário/relatório com filtros"
    if "relatório" in lowered or "relatorio" in lowered:
        return "um relatório"
    return "uma tela do sistema"


def _summarize_full_page_text(text: str, *, has_files: bool = False) -> str:
    cleaned = _clean_text(text, limit=3000)
    if not _is_meaningful_text(cleaned):
        return ""

    subject = _screen_subject(cleaned)
    suffix = " Arquivo disponível." if has_files else ""
    if _looks_like_form_or_filter(cleaned):
        fields = _extract_form_fields(cleaned)
        options = _extract_form_options(cleaned)
        parts = [f"Consulta concluída. A tela aberta parece ser {subject}."]
        if fields:
            parts.append(f"Ela contém filtros/campos como {', '.join(fields[:8])}.")
        if options:
            parts.append(f"Também há opções como {', '.join(options[:6])}.")
        parts.append("Nenhum resultado listado foi exibido; a tela parece estar aguardando filtros para gerar o relatório.")
        return " ".join(parts) + suffix

    compact = cleaned
    for noise in ("Página Inicial", "Pagina Inicial", "Voltar"):
        compact = re.sub(rf"\b{re.escape(noise)}\b", "", compact, flags=re.I)
    compact = re.sub(r"\s+", " ", compact).strip()
    if not compact:
        return ""
    return f"Consulta concluída. A tela aberta parece ser {subject}. Conteúdo principal encontrado: {compact[:220]}.{suffix}"


def _full_page_text(result_payload: dict[str, Any] | None) -> str:
    payload = result_payload if isinstance(result_payload, dict) else {}
    raw = payload.get("dados_extraidos", {})
    if not isinstance(raw, dict):
        return ""
    for key, value in raw.items():
        normalized = str(key or "").strip().casefold()
        if normalized in {"texto_tela_final", "texto tela final", "final_screen_text", "full_page_text"}:
            return _clean_text(value, limit=_MAX_AI_CONTEXT_CHARS)
    return ""


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
        if str(step.get("tipo") or step.get("type") or "").strip().lower() == "extrair_texto":
            selector = str(step.get("seletor") or "").strip()
            label = str(step.get("nome") or step.get("extraction_name") or "").strip()
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
            safe[_friendly_extraction_label(label)] = value
    return safe


def _safe_extracted_context(action: Any, result_payload: dict[str, Any] | None) -> dict[str, str]:
    payload = result_payload if isinstance(result_payload, dict) else {}
    raw = payload.get("dados_extraidos", {})
    if not isinstance(raw, dict):
        return {}
    targets = extraction_targets(action)
    selector_labels: dict[str, str] = {}
    for step in _raw_steps(action):
        if str(step.get("tipo") or step.get("type") or "").strip().lower() == "extrair_texto":
            selector = str(step.get("seletor") or "").strip()
            label = str(step.get("nome") or step.get("extraction_name") or "").strip()
            if selector and label:
                selector_labels[selector] = label

    safe: dict[str, str] = {}
    remaining = _MAX_AI_CONTEXT_CHARS
    for index, (raw_key, raw_value) in enumerate(raw.items()):
        if remaining <= 0:
            break
        key = str(raw_key or "").strip()
        if _is_sensitive_key(key):
            continue
        label = selector_labels.get(key) or key
        if _is_selector_like(label):
            label = targets[index] if index < len(targets) else f"resultado {index + 1}"
        label = _clean_scalar(label.replace("_", " ").strip()) or f"resultado {index + 1}"
        value_limit = min(_MAX_AI_CONTEXT_CHARS, remaining)
        value = _dedupe_lines(_clean_text(raw_value, limit=value_limit), limit=value_limit)
        if not value:
            continue
        safe[label] = value
        remaining -= len(label) + len(value) + 4
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
    files = payload.get("downloaded_files") or payload.get("arquivos", [])
    return (isinstance(files, list) and bool(files)) or isinstance(payload.get("main_file"), dict)


def _safe_file_metadata(result_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    payload = result_payload if isinstance(result_payload, dict) else {}
    raw_files: list[Any] = []
    if isinstance(payload.get("downloaded_files"), list):
        raw_files.extend(payload["downloaded_files"])
    if isinstance(payload.get("main_file"), dict):
        raw_files.append(payload["main_file"])

    files: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_files:
        if not isinstance(raw, dict):
            continue
        name = _clean_scalar(raw.get("name") or "arquivo") or "arquivo"
        if name in seen:
            continue
        seen.add(name)
        metadata: dict[str, Any] = {"name": name}
        mime_type = _clean_scalar(raw.get("mime_type"))
        if mime_type:
            metadata["mime_type"] = mime_type
        try:
            size_bytes = int(raw.get("size_bytes") or 0)
        except (TypeError, ValueError):
            size_bytes = 0
        if size_bytes > 0:
            metadata["size_bytes"] = size_bytes
        files.append(metadata)
    return files


def _combined_extracted_text(action: Any, result_payload: dict[str, Any] | None) -> str:
    values = _safe_extracted_context(action, result_payload)
    return "\n".join(values.values())


def deterministic_operational_summary(
    action: Any,
    *,
    status: str,
    result_payload: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> str:
    if str(status).lower() != "success":
        error = str(error_message or "").casefold()
        payload = result_payload if isinstance(result_payload, dict) else {}
        session_state = str(payload.get("session_state") or "").casefold()
        operator_required = bool(payload.get("operator_action_required", False))
        step_diagnostics = payload.get("step_diagnostics", [])
        has_step_timeout = isinstance(step_diagnostics, list) and any(
            str(item.get("result") or "").casefold() == "timeout"
            for item in step_diagnostics
            if isinstance(item, dict)
        )
        if "precisa ser autenticada novamente" in error or "reauthentication_required" in error:
            return "Não consegui executar a ação porque a sessão precisa ser autenticada novamente."
        if session_state == "microsoft_consent_required":
            return "A Microsoft solicitou aceite/consentimento. Abra o navegador desktop, clique em Accept e depois continue."
        if session_state in {"microsoft_password_required", "microsoft_mfa_required"}:
            return "Não consegui continuar porque a Microsoft solicitou senha ou MFA."
        if session_state == "microsoft_pick_account":
            return "Não consegui continuar porque a conta salva configurada não apareceu na tela da Microsoft."
        if session_state in {"system_unresponsive", "system_loading"}:
            return "Não consegui concluir porque o sistema ficou sem resposta mesmo após atualizar a página."
        if operator_required and session_state in {"microsoft_signed_out", "unknown"}:
            return "Não consegui executar a ação porque o sistema pediu login manual novamente."
        if "pagina do sistema esperado" in error or "unexpected_page_host" in error:
            return "Não consegui executar a ação porque a página do sistema esperado não está disponível."
        if "autentic" in error or "login" in error:
            return "Não foi possível concluir a ação porque a sessão do sistema não está autenticada."
        if "não encontr" in error or "nao encontr" in error:
            return "Não foi possível concluir a ação porque a informação solicitada não foi encontrada."
        if has_step_timeout or "indispon" in error or "timeout" in error or "demorou" in error:
            return (
                "Não consegui concluir a ação porque o sistema demorou para abrir a próxima tela. "
                "Tente novamente ou reautentique a sessão se necessário."
            )
        if "não possui passos" in error or "nao possui passos" in error:
            return "Não foi possível executar a ação porque ela ainda não possui uma rotina configurada."
        return "Não foi possível concluir a ação no sistema. Tente novamente ou verifique se o serviço está disponível."

    extracted = _safe_extracted_values(action, result_payload)
    has_files = _has_files(result_payload)
    full_page_text = _full_page_text(result_payload)
    if full_page_text:
        full_page_summary = _summarize_full_page_text(full_page_text, has_files=has_files)
        if full_page_summary:
            return full_page_summary
    if extracted:
        combined_text = _combined_extracted_text(action, result_payload)
        if _looks_like_noisy_text(combined_text):
            if _looks_like_form_or_filter(combined_text):
                options = _legacy_form_options(combined_text)
                details = f", com opções de {', '.join(options)}" if options else ""
                suffix = " Arquivo disponível." if has_files else ""
                return (
                    "Consulta concluída. A tela aberta parece ser um formulário de relatório/filtro"
                    f"{details}. Nenhum resultado específico foi listado ainda.{suffix}"
                )
            suffix = " Arquivo disponível." if has_files else ""
            return (
                "Ação executada com sucesso. A tela final foi aberta, mas não foi possível "
                f"identificar um resultado específico configurado.{suffix}"
            )
        template = _clean_scalar(_metadata(action, "user_result_summary_template", ""))
        if template:
            values = {key.replace(" ", "_"): value for key, value in extracted.items()}
            values.update(extracted)
            try:
                rendered = template.format_map(values)
            except (KeyError, ValueError):
                rendered = ""
            if rendered and _summary_is_safe(rendered, extracted):
                return f"{rendered} Arquivo disponível." if has_files else rendered
        values = ". ".join(f"{key.capitalize()}: {value}" for key, value in extracted.items())
        suffix = " Arquivo disponível." if has_files else ""
        return f"Consulta concluída. Encontrei: {values}.{suffix}"
    if extraction_targets(action):
        targets = extraction_targets(action)
        target_text = " ".join(targets).replace("_", " ").casefold()
        objective_text = str(_metadata(action, "objective", "") or "").replace("_", " ").casefold()
        normalized_target = _normalize_label_key(target_text)
        if (
            "qtd pcls pagas" in normalized_target
            or "qtd parcelas pagas" in normalized_target
            or "quantidade parcelas pagas" in normalized_target
            or "quantidade de parcelas pagas" in normalized_target
        ):
            return "A ação foi executada, mas não encontrei o campo Qtd. Pcls. Pagas na tela final."
        if "parcela" in target_text or "parcela" in objective_text:
            return "A ação foi executada, mas não encontrei o valor da parcela atual na tela final."
        readable = targets[0].replace("_", " ") if targets else "resultado configurado"
        return f"A ação foi executada, mas não encontrei {readable} na tela final."
    if has_files:
        return "Arquivo gerado com sucesso. Arquivo disponível."
    output_type = str(_metadata(action, "output_type", "") or "").strip().casefold()
    if output_type in {"texto/dados da tela", "arquivo/pdf", "ambos"}:
        return "Ação executada com sucesso, mas nenhum resultado final foi configurado para retorno."
    title = _safe_final_title(result_payload)
    if title:
        return "Ação executada com sucesso. A tela solicitada foi aberta, mas nenhum dado foi configurado para extração."
    return "Ação executada com sucesso, mas nenhum resultado final foi configurado para retorno."


def _summary_is_safe(summary: str, extracted: dict[str, str]) -> bool:
    text = re.sub(r"\s+", " ", str(summary or "")).strip()
    lowered = text.casefold()
    if not text or len(text) > _MAX_SUMMARY_LENGTH:
        return False
    if any(term in lowered for term in _TECHNICAL_TERMS + _SENSITIVE_PARTS):
        return False
    if _is_selector_like(text):
        return False
    if re.search(r"(?i)(sk-[a-z0-9]|bearer\s+[a-z0-9._~+/=-]+)", text):
        return False
    if re.search(r"(?i)(?:/[a-z0-9._ -]+){2,}/[a-z0-9._ -]+", text):
        return False
    return True


async def build_operational_summary(
    action: Any,
    *,
    status: str,
    result_payload: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> str:
    result = await build_operational_summary_result(
        action,
        status=status,
        result_payload=result_payload,
        error_message=error_message,
    )
    return result.summary


async def build_operational_summary_result(
    action: Any,
    *,
    status: str,
    result_payload: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> OperationalSummaryResult:
    fallback = deterministic_operational_summary(
        action, status=status, result_payload=result_payload, error_message=error_message
    )
    if str(status).lower() != "success" and fallback.startswith("Não consegui executar a ação"):
        return OperationalSummaryResult(
            fallback,
            ai_summary_used=False,
            summary_source="deterministic",
            summary_reason="stable_error_without_ai",
        )
    if (
        str(status).lower() == "success"
        and not extraction_targets(action)
        and bool(_safe_final_title(result_payload))
    ):
        return OperationalSummaryResult(
            fallback,
            ai_summary_used=False,
            summary_source="deterministic",
            summary_reason="page_opened_without_extracted_data",
        )
    enabled = bool(_metadata(action, "ai_result_summary_enabled", True))
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    has_files = _has_files(result_payload)
    extracted_context = _safe_extracted_context(action, result_payload)
    if not enabled or not api_key:
        return OperationalSummaryResult(
            fallback,
            ai_summary_used=False,
            summary_source="deterministic",
            summary_reason="ai_disabled" if not enabled else "openai_api_key_missing",
        )
    if str(status).lower() == "success" and not extracted_context and not has_files:
        return OperationalSummaryResult(
            fallback,
            ai_summary_used=False,
            summary_source="deterministic",
            summary_reason="no_extracted_context_or_files",
        )

    extracted = _safe_extracted_values(action, result_payload)
    context = {
        "objective": _clean_scalar(_metadata(action, "objective", "")),
        "expected_result": _clean_scalar(_metadata(action, "expected_result", "")),
        "output_type": _clean_scalar(_metadata(action, "output_type", "")),
        "status": "success" if str(status).lower() == "success" else "error",
        "extracted_data": extracted_context,
        "has_configured_extraction": bool(extraction_targets(action)),
        "final_page_title": _safe_final_title(result_payload),
        "downloaded_files": _safe_file_metadata(result_payload),
        "fallback": fallback,
    }
    prompt = (
        "Você é o assistente operacional do CotaSync. Resuma o resultado da execução para o usuário final. "
        "Use apenas os dados extraídos. Não invente. Ignore menus de navegação quando não forem o conteúdo "
        "principal. Se a tela parecer ser apenas um formulário/filtro sem resultado listado, diga isso "
        "claramente. Seja direto, em português, com no máximo 5 linhas, exceto se houver muitos dados úteis. "
        "Não mencione seletores, navegador, modo, host, domínio, run id, passos, cliques, logs, tokens, "
        "credenciais, caminhos locais ou URLs. Contexto seguro: "
        + json.dumps(context, ensure_ascii=False)
    )
    try:
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
        response = await ChatOpenAI(
            model=model, temperature=0, api_key=api_key, timeout=6, max_retries=0
        ).ainvoke(prompt)
        candidate = _clean_text(getattr(response, "content", response), limit=_MAX_SUMMARY_LENGTH)
        if _summary_is_safe(candidate, extracted):
            return OperationalSummaryResult(
                candidate,
                ai_summary_used=True,
                summary_source="ai",
                summary_reason="openai_summary_accepted",
            )
        return OperationalSummaryResult(
            fallback,
            ai_summary_used=False,
            summary_source="deterministic",
            summary_reason="openai_summary_rejected",
        )
    except Exception:
        return OperationalSummaryResult(
            fallback,
            ai_summary_used=False,
            summary_source="deterministic",
            summary_reason="openai_summary_failed",
        )


def build_technical_summary(
    *, status: str, executed_steps: int = 0, result_payload: dict[str, Any] | None = None
) -> str:
    payload = result_payload if isinstance(result_payload, dict) else {}
    diagnostics = payload.get("selector_diagnostics", [])
    diagnostic_count = len(diagnostics) if isinstance(diagnostics, list) else 0
    step_diagnostics = payload.get("step_diagnostics", [])
    step_diagnostic_count = len(step_diagnostics) if isinstance(step_diagnostics, list) else 0
    checkpoint_diagnostics = payload.get("checkpoint_diagnostics", [])
    checkpoint_diagnostic_count = len(checkpoint_diagnostics) if isinstance(checkpoint_diagnostics, list) else 0
    outcome = "concluída" if str(status).lower() == "success" else "falhou"
    return (
        f"Execução {outcome}; passos={max(0, int(executed_steps))}; "
        f"diagnósticos={diagnostic_count}; step_diagnostics={step_diagnostic_count}; "
        f"checkpoint_diagnostics={checkpoint_diagnostic_count}."
    )
