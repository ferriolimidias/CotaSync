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
        "url": str(action.get("url_inicial") or "")[:500],
        "steps": safe_steps,
        "learning_events": safe_events,
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
        "Revise a receita sem criar navegação autônoma e sem modificar os passos determinísticos. "
        "Produza estratégias de espera por índice, dicas de replay, rótulos claros de variáveis, "
        "alvo de extração, notas para sistemas lentos e riscos de popup/nova aba. "
        "Não invente credenciais, valores de campos nem seletores. Contexto sanitizado: "
        + json.dumps(safe_context, ensure_ascii=False)
    )
    try:
        llm = ChatOpenAI(
            model=str(config["model"]),
            temperature=0,
            api_key=api_key,
            timeout=_AI_TIMEOUT_SECONDS,
            max_retries=0,
        ).with_structured_output(ObserverReview)
        review = await asyncio.wait_for(llm.ainvoke(prompt), timeout=_AI_TIMEOUT_SECONDS + 1)
        if not isinstance(review, ObserverReview):
            return fallback
        reviewed = review.model_dump()
        return {
            "ai_reviewed": True,
            "ai_observer_summary": review.summary.strip() or "Ação demonstrada revisada pela IA.",
            "replay_hints": reviewed["replay_hints"] or fallback["replay_hints"],
            "waits": reviewed["waits"] or fallback["waits"],
            "variable_schema": reviewed["variable_schema"] or fallback["variable_schema"],
            "extraction_target": review.extraction_target.strip() or fallback["extraction_target"],
            "ai_slow_system_notes": reviewed["slow_system_notes"] or fallback["ai_slow_system_notes"],
            "ai_risk_notes": reviewed["risk_notes"] or fallback["ai_risk_notes"],
        }
    except Exception as exc:
        logger.warning("Revisao da IA indisponivel; usando analise local (%s)", type(exc).__name__)
        failed = dict(fallback)
        failed["ai_observer_summary"] = "Revisão por IA indisponível; ação salva com análise local básica."
        return failed
