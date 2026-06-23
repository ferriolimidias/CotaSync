"""Revisao pos-gravacao para aprendizado demonstrado assistido por IA."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field


logger = logging.getLogger("cotasync.ai_observer")
_FALLBACK_SUMMARY = "IA não configurada; ação salva com análise local básica."
_DEFAULT_MODEL = "gpt-4o-mini"
_AI_TIMEOUT_SECONDS = 8


class ObserverReview(BaseModel):
    summary: str
    replay_hints: list[str] = Field(default_factory=list)
    waits: list[dict[str, Any]] = Field(default_factory=list)
    variable_schema: list[dict[str, Any]] = Field(default_factory=list)
    extraction_target: str = ""
    suggested_extraction_targets: list[dict[str, str]] = Field(default_factory=list)
    suggested_objective: str = ""
    suggested_expected_result: str = ""
    slow_system_notes: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)


class LiveStepReview(BaseModel):
    wait_hint: str
    replay_hint: str
    ai_note: str
    selector_robustness: str = ""
    variable_suggestion: str = ""
    expected_wait_target: str = ""
    popup_or_new_tab_risk: bool = False
    modal_risk: bool = False


def _openai_response_text(response: Any) -> str:
    """Extrai texto de AIMessage sem depender de um formato de content especifico."""

    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict) and isinstance(item.get("text"), str):
            parts.append(item["text"])
    return "\n".join(parts).strip()


def _parse_review_json(response: Any) -> ObserverReview | None:
    """Aceita JSON puro, cercado por markdown ou acompanhado de texto curto."""

    text = _openai_response_text(response)
    if not text:
        return None
    candidates = [text]
    if text.startswith("```") and text.endswith("```"):
        fenced = text[3:-3].strip()
        if fenced.lower().startswith("json"):
            fenced = fenced[4:].lstrip()
        candidates.insert(0, fenced)

    decoder = json.JSONDecoder()
    payload: dict[str, Any] | None = None
    for candidate in candidates:
        try:
            decoded = json.loads(candidate)
        except json.JSONDecodeError:
            decoded = None
            for start, character in enumerate(candidate):
                if character != "{":
                    continue
                try:
                    possible, _ = decoder.raw_decode(candidate[start:])
                except json.JSONDecodeError:
                    continue
                if isinstance(possible, dict):
                    decoded = possible
                    break
        if isinstance(decoded, dict):
            payload = decoded
            break
    if payload is None:
        return None

    def string_list(key: str) -> list[str]:
        raw = payload.get(key, [])
        if not isinstance(raw, list):
            return []
        return [str(item).strip() for item in raw if str(item).strip()]

    def object_list(key: str, alternate: str | None = None) -> list[dict[str, Any]]:
        raw = payload.get(key, payload.get(alternate, []) if alternate else [])
        if not isinstance(raw, list):
            return []
        return [item for item in raw if isinstance(item, dict)]

    return ObserverReview(
        summary=str(payload.get("summary") or payload.get("ai_observer_summary") or "").strip()
        or "Ação demonstrada revisada pela IA.",
        replay_hints=string_list("replay_hints"),
        waits=object_list("waits", "wait_strategies"),
        variable_schema=object_list("variable_schema"),
        extraction_target=str(payload.get("extraction_target") or "").strip(),
        suggested_extraction_targets=(
            object_list("suggested_extraction_targets") or object_list("extraction_targets")
        ),
        suggested_objective=str(payload.get("suggested_objective") or "").strip(),
        suggested_expected_result=str(payload.get("suggested_expected_result") or "").strip(),
        slow_system_notes=string_list("slow_system_notes"),
        risk_notes=string_list("risk_notes"),
    )


def openai_configuration_status() -> dict[str, Any]:
    """Status seguro para UI; nunca devolve a chave."""

    return {
        "configured": bool(os.getenv("OPENAI_API_KEY", "").strip()),
        "model": os.getenv("OPENAI_MODEL", _DEFAULT_MODEL).strip() or _DEFAULT_MODEL,
    }


def _safe_action(action: dict[str, Any]) -> dict[str, Any]:
    safe_steps: list[dict[str, Any]] = []
    raw_steps = action.get("passos_playwright", [])
    if isinstance(raw_steps, list):
        for index, raw in enumerate(raw_steps[:100]):
            if not isinstance(raw, dict):
                continue
            safe_steps.append(
                {
                    "index": index,
                    "type": str(raw.get("tipo") or "")[:40],
                    "selector": str(raw.get("seletor") or "")[:500],
                    "variable": str(raw.get("variavel") or "")[:100],
                    "extraction_name": str(raw.get("nome") or "")[:100],
                }
            )
    safe_events: list[dict[str, Any]] = []
    raw_events = action.get("learning_events", [])
    if isinstance(raw_events, list):
        allowed = {
            "step_index",
            "event_type",
            "selector",
            "variable_key",
            "elapsed_ms",
            "url_before",
            "url_after",
            "opened_new_page",
            "active_page_changed",
            "download_detected",
            "wait_hint",
            "replay_hint",
            "ai_note",
        }
        for raw in raw_events[:100]:
            if isinstance(raw, dict):
                safe_events.append({key: raw.get(key) for key in allowed if key in raw})
    return {
        "name": str(action.get("nome_amigavel") or action.get("name") or "")[:200],
        "description": str(action.get("descricao") or action.get("description") or "")[:500],
        "objective": str(action.get("objective") or "")[:1000],
        "input_description": str(action.get("input_description") or "")[:1000],
        "expected_result": str(action.get("expected_result") or "")[:1000],
        "success_criteria": str(action.get("success_criteria") or "")[:1000],
        "output_type": str(action.get("output_type") or "")[:100],
        "url": str(action.get("url_inicial") or "")[:500],
        "steps": safe_steps,
        "learning_events": safe_events,
        "output_candidates": [
            {
                "label": str(item.get("label") or "")[:100],
                "selector": str(item.get("selector") or "")[:500],
                "preview": str(item.get("preview") or "")[:160],
            }
            for item in action.get("output_candidates", [])[:20]
            if isinstance(item, dict)
        ] if isinstance(action.get("output_candidates"), list) else [],
    }


def deterministic_observe_learning_step(step_event: dict[str, Any]) -> dict[str, Any]:
    event_type = str(step_event.get("event_type") or "wait")
    elapsed_ms = max(0, int(step_event.get("elapsed_ms") or 0))
    selector = str(step_event.get("selector") or "")
    wait_hint = "Aguardar DOM pronto antes do próximo passo."
    replay_hint = "Revalidar página ativa e autenticação."
    if selector:
        wait_hint = "Aguardar seletor visível e habilitado."
        replay_hint = "Usar o seletor gravado com diagnóstico seguro em caso de falha."
    if event_type == "click":
        wait_hint = f"Após o clique, aguardar pelo menos {min(max(elapsed_ms, 500), 5000)} ms e a condição seguinte."
        replay_hint = "Rolar para a área visível, clicar e verificar URL, popup/nova aba e próximo seletor."
    elif event_type == "extract":
        wait_hint = "Aguardar o alvo ficar visível e conter texto útil."
        replay_hint = "Extrair somente após estabilização do conteúdo."
    elif event_type == "fill":
        replay_hint = "Preencher com variável, sem persistir o valor demonstrado."
    if step_event.get("opened_new_page"):
        replay_hint += " Trocar para a nova página aberta."
    if step_event.get("download_detected"):
        replay_hint += " Confirmar o download antes de continuar."
    return {
        "wait_hint": wait_hint,
        "replay_hint": replay_hint,
        "ai_note": "Evento observado em tempo real com análise determinística local.",
        "selector_robustness": "Preferir id, name, data-testid, role ou label estáveis.",
        "variable_suggestion": "Tornar variável" if event_type == "fill" else "Manter como ação fixa",
        "expected_wait_target": selector,
        "popup_or_new_tab_risk": bool(step_event.get("opened_new_page")),
        "modal_risk": event_type == "modal",
    }


async def observe_learning_step_with_ai(
    step_event: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Analisa um evento ao vivo; falhas sempre retornam o fallback determinístico."""

    fallback = deterministic_observe_learning_step(step_event)
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return fallback
    safe_event = {
        key: value
        for key, value in step_event.items()
        if key not in {"value", "valor", "cookies", "storage_state"}
    }
    safe_context = context if isinstance(context, dict) else {}
    prompt = (
        "Observe este único passo executado por um humano. Não navegue e não altere a receita. "
        "Classifique espera, robustez do seletor, sugestão de variável, alvo esperado e riscos "
        "de popup, nova aba ou modal. Nunca repita valores digitados. Evento: "
        + json.dumps({"event": safe_event, "context": safe_context}, ensure_ascii=False)
    )
    try:
        config = openai_configuration_status()
        llm = ChatOpenAI(
            model=str(config["model"]),
            temperature=0,
            api_key=api_key,
            timeout=5,
            max_retries=0,
        ).with_structured_output(LiveStepReview)
        review = await asyncio.wait_for(llm.ainvoke(prompt), timeout=6)
        return review.model_dump() if isinstance(review, LiveStepReview) else fallback
    except Exception as exc:
        logger.warning("Observacao IA do passo indisponivel; usando fallback (%s)", type(exc).__name__)
        return fallback


def _variable_label(key: str) -> str:
    return str(key or "campo").replace("_", " ").strip().capitalize() or "Campo"


def _local_analysis(action: dict[str, Any]) -> dict[str, Any]:
    safe = _safe_action(action)
    waits: list[dict[str, Any]] = []
    variables: list[dict[str, Any]] = []
    extraction_targets: list[str] = []
    replay_hints = [
        "Revalidar a página e a autenticação antes de cada passo.",
        "Usar o seletor salvo de forma determinística e registrar evidência em falhas.",
    ]
    for step in safe["steps"]:
        step_type = step["type"]
        strategy = "dom_ready"
        condition = "document.readyState interativo ou completo"
        if step["selector"]:
            strategy = "visible_and_enabled"
            condition = "seletor presente, visível e habilitado"
        if step_type == "extrair_texto":
            strategy = "visible_then_nonempty"
            condition = "alvo visível; aguardar conteúdo quando o sistema for lento"
            extraction_targets.append(step["extraction_name"] or step["selector"])
        waits.append(
            {
                "step_index": step["index"],
                "strategy": strategy,
                "timeout_ms": 10000,
                "condition": condition,
            }
        )
        variable = step["variable"]
        if variable and not any(item["key"] == variable for item in variables):
            variables.append(
                {
                    "key": variable,
                    "label": _variable_label(variable),
                    "required": True,
                }
            )
    if any(step["type"] == "clicar" for step in safe["steps"]):
        replay_hints.append("Antes de clicar, rolar o elemento para a área visível e considerar popup ou nova aba.")
    return {
        "ai_reviewed": False,
        "ai_observer_summary": _FALLBACK_SUMMARY,
        "replay_hints": replay_hints,
        "waits": waits,
        "variable_schema": variables,
        "extraction_target": ", ".join(item for item in extraction_targets if item),
        "suggested_extraction_targets": [],
        "suggested_objective": str(safe.get("objective") or ""),
        "suggested_expected_result": str(safe.get("expected_result") or ""),
        "ai_slow_system_notes": [
            "Seletores podem aparecer antes dos dados; aguardar conteúdo útil em extrações."
        ],
        "ai_risk_notes": [
            "Cliques podem abrir popup ou nova aba; validar a página ativa antes do próximo passo."
        ],
    }


async def analyze_recorded_action_with_ai(
    action: dict[str, Any],
    optional_dom_summary: dict[str, Any] | None = None,
    optional_screenshots: list[str | Path] | None = None,
) -> dict[str, Any]:
    """Enriquece uma receita humana sem alterar seus passos determinísticos."""

    fallback = _local_analysis(action)
    config = openai_configuration_status()
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return fallback

    safe_context = {
        "action": _safe_action(action),
        "dom_summary": optional_dom_summary if isinstance(optional_dom_summary, dict) else {},
        "screenshots_available": len(optional_screenshots or []),
    }
    prompt = (
        "Você é observador de uma automação demonstrada por um humano. "
        "Use objetivo, entradas, resultado esperado, critério de sucesso e tipo de retorno da instrução guiada. "
        "Revise a receita sem criar navegação autônoma e sem modificar os passos determinísticos. "
        "Produza estratégias de espera por índice, dicas de replay, rótulos claros de variáveis digitadas, "
        "alvos de extração entre os candidatos reais, detecção de download, notas para sistemas lentos e riscos. "
        "Não invente credenciais, valores de campos nem seletores. "
        "Responda somente com um objeto JSON válido, sem markdown, com estas chaves: "
        '"summary" (string), "replay_hints" (array de strings), "waits" (array de objetos), '
        '"variable_schema" (array de objetos), "extraction_target" (string), '
        '"suggested_extraction_targets" (array de objetos com label e selector), '
        '"suggested_objective" (string), "suggested_expected_result" (string), '
        '"slow_system_notes" (array de strings) e "risk_notes" (array de strings). '
        "Contexto sanitizado: "
        + json.dumps(safe_context, ensure_ascii=False)
    )
    try:
        llm = ChatOpenAI(
            model=str(config["model"]),
            temperature=0,
            api_key=api_key,
            timeout=_AI_TIMEOUT_SECONDS,
            max_retries=0,
        )
        response = await asyncio.wait_for(llm.ainvoke(prompt), timeout=_AI_TIMEOUT_SECONDS + 1)
        review = _parse_review_json(response)
        if review is None:
            logger.warning("Revisao da IA retornou JSON invalido; usando analise local")
            failed = dict(fallback)
            failed["ai_observer_summary"] = "Revisão por IA indisponível; ação salva com análise local básica."
            return failed
        reviewed = review.model_dump()
        return {
            "ai_reviewed": True,
            "ai_observer_summary": review.summary.strip() or "Ação demonstrada revisada pela IA.",
            "replay_hints": reviewed["replay_hints"] or fallback["replay_hints"],
            "waits": reviewed["waits"] or fallback["waits"],
            "variable_schema": reviewed["variable_schema"] or fallback["variable_schema"],
            "extraction_target": review.extraction_target.strip() or fallback["extraction_target"],
            "suggested_extraction_targets": (
                reviewed["suggested_extraction_targets"] or fallback["suggested_extraction_targets"]
            ),
            "suggested_objective": review.suggested_objective.strip() or fallback["suggested_objective"],
            "suggested_expected_result": (
                review.suggested_expected_result.strip() or fallback["suggested_expected_result"]
            ),
            "ai_slow_system_notes": reviewed["slow_system_notes"] or fallback["ai_slow_system_notes"],
            "ai_risk_notes": reviewed["risk_notes"] or fallback["ai_risk_notes"],
        }
    except Exception as exc:
        logger.warning("Revisao da IA indisponivel; usando analise local (%s)", type(exc).__name__)
        failed = dict(fallback)
        failed["ai_observer_summary"] = "Revisão por IA indisponível; ação salva com análise local básica."
        return failed
