#!/usr/bin/env python3
"""Smoke HTTP do caminho de captura de variável via Modo operador.

Requer backend rodando e uma sessão capaz de abrir o alvo local/demo ou uma
pagina onde COTASYNC_SMOKE_SELECTOR exista.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any

import requests


API_BASE = os.getenv("COTASYNC_API_BASE_URL", "http://127.0.0.1:8100").rstrip("/")
SELECTOR = os.getenv("COTASYNC_SMOKE_SELECTOR", "#pedido-codigo")
VALUE = os.getenv("COTASYNC_SMOKE_VALUE", "PED-SMOKE-1")


def api(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    response = requests.request(method, f"{API_BASE}{path}", json=payload, timeout=30)
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not response.ok:
        raise RuntimeError(f"{method} {path} falhou: {response.status_code} {body}")
    if not isinstance(body, dict):
        raise RuntimeError(f"{method} {path} retornou corpo invalido")
    return body


def main() -> int:
    created = api("POST", "/api/demo/sessions")
    session_id = str(created["session"]["id"])
    try:
        session = created["session"]
        if str(session.get("page_url") or "").endswith("/demo/alvo"):
            # Alvo local pode abrir na tela de login. Usa o proprio Modo
            # operador como helper antes de iniciar a gravacao.
            try:
                api("POST", f"/api/demo/sessions/{session_id}/confirm-login")
            except RuntimeError:
                api(
                    "POST",
                    f"/api/demo/sessions/{session_id}/operator/fill",
                    {"selector": "#demo-user", "value": "demo", "record_action": False},
                )
                api(
                    "POST",
                    f"/api/demo/sessions/{session_id}/operator/fill",
                    {"selector": "#demo-password", "value": "demo", "record_action": False},
                )
                api(
                    "POST",
                    f"/api/demo/sessions/{session_id}/operator/click",
                    {"selector": "#demo-login", "record_action": False},
                )
                api("POST", f"/api/demo/sessions/{session_id}/confirm-login")

        api("POST", f"/api/demo/sessions/{session_id}/recording/start", {"name": "Smoke captura variavel"})
        filled = api(
            "POST",
            f"/api/demo/sessions/{session_id}/operator/fill",
            {
                "selector": SELECTOR,
                "value": VALUE,
                "record_action": True,
                "operator_request_session_id": session_id,
                "active_recording_session_id": session_id,
            },
        )["operator"]
        if filled.get("recorded") is not True:
            raise RuntimeError(f"operator/fill nao gravou evento: {filled}")
        time.sleep(0.5)
        stopped = api("POST", f"/api/demo/sessions/{session_id}/recording/stop")
        review = stopped.get("review_summary") or {}
        variables = review.get("detected_variables") or []
        if int(review.get("fills_captured") or 0) != 1 or not variables:
            raise RuntimeError(f"review nao encontrou Campos=1 e variavel: {review}")
        print(
            "ok: "
            f"session={session_id} campos={review.get('fills_captured')} "
            f"variavel={variables[0].get('suggested_key')}"
        )
        return 0
    finally:
        try:
            api("DELETE", f"/api/demo/sessions/{session_id}")
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
