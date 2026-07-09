"""Endpoints minimos do ciclo demonstravel CotaSync v0.1."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from backend.services.demo_session import DemoSessionError, demo_session_manager


router = APIRouter(tags=["demo-v0.1"])


class SaveDemoActionRequest(BaseModel):
    name: str
    description: str = "Rotina aprendida por demonstracao manual."
    objective: str = ""
    input_description: str = ""
    expected_result: str = ""
    success_criteria: str = ""
    output_type: str = "apenas abrir tela"
    user_result_summary_template: str | None = None
    ai_result_summary_enabled: bool = True
    ai_recovery_enabled: bool = False
    variable_names: dict[str, str] = Field(default_factory=dict)
    extraction_targets: list[dict[str, str]] = Field(default_factory=list)
    extract_visible_text: bool = False
    return_downloaded_file: bool = False
    requires_authenticated_session: bool | None = None
    action_timeout_seconds: int | None = None


class GuidedLearningRequest(BaseModel):
    name: str = ""
    objective: str = ""
    input_description: str = ""
    expected_result: str = ""
    success_criteria: str = ""
    output_type: str = "apenas abrir tela"
    ai_result_summary_enabled: bool = True
    ai_recovery_enabled: bool = False


class OperatorFillRequest(BaseModel):
    selector: str
    value: str = ""
    record_action: bool = True
    active_recording_session_id: str = ""
    operator_request_session_id: str = ""


class OperatorInsertActiveRequest(BaseModel):
    value: str = ""
    sensitive: bool = False


class OperatorPressRequest(BaseModel):
    key: str


class OperatorClickRequest(BaseModel):
    selector: str
    record_action: bool = True
    active_recording_session_id: str = ""
    operator_request_session_id: str = ""


def _raise_safe(exc: DemoSessionError, status_code: int = 409) -> None:
    raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.post("/api/demo/sessions")
async def create_demo_session() -> dict[str, Any]:
    try:
        session = await demo_session_manager.create()
    except DemoSessionError as exc:
        _raise_safe(exc, 503)
    return {"status": "ok", "session": session}


@router.get("/api/demo/sessions/{session_id}")
async def get_demo_session(session_id: str) -> dict[str, Any]:
    try:
        session = await demo_session_manager.status(session_id)
    except DemoSessionError as exc:
        _raise_safe(exc, 404)
    return {"status": "ok", "session": session}


@router.get("/api/demo/sessions/{session_id}/operator-diagnostics")
async def get_operator_diagnostics(session_id: str) -> dict[str, Any]:
    try:
        diagnostics = await demo_session_manager.operator_diagnostics(session_id)
    except DemoSessionError as exc:
        _raise_safe(exc, 404)
    return {"status": "ok", "operator": diagnostics}


@router.get("/api/demo/sessions/{session_id}/recording/diagnostics")
async def get_recording_diagnostics(session_id: str) -> dict[str, Any]:
    try:
        diagnostics = await demo_session_manager.recording_diagnostics(session_id)
    except DemoSessionError as exc:
        _raise_safe(exc, 404)
    return {"status": "ok", "diagnostics": diagnostics}


@router.post("/api/demo/sessions/{session_id}/operator/fill")
async def operator_fill(session_id: str, payload: OperatorFillRequest) -> dict[str, Any]:
    expected_session = payload.active_recording_session_id or payload.operator_request_session_id
    try:
        result = await demo_session_manager.operator_fill(
            session_id,
            payload.selector,
            payload.value,
            record_action=payload.record_action,
            active_recording_session_id=expected_session,
        )
    except DemoSessionError as exc:
        _raise_safe(exc)
    return {"status": "ok", "operator": result}


@router.post("/api/demo/sessions/{session_id}/operator/insert-active")
async def operator_insert_active(
    session_id: str,
    payload: OperatorInsertActiveRequest,
) -> dict[str, Any]:
    try:
        result = await demo_session_manager.operator_insert_active(
            session_id,
            payload.value,
            sensitive=payload.sensitive,
        )
    except DemoSessionError as exc:
        _raise_safe(exc)
    return {"status": "ok", "operator": result}


@router.post("/api/demo/sessions/{session_id}/operator/press")
async def operator_press(session_id: str, payload: OperatorPressRequest) -> dict[str, Any]:
    try:
        result = await demo_session_manager.operator_press(session_id, payload.key)
    except DemoSessionError as exc:
        _raise_safe(exc)
    return {"status": "ok", "operator": result}


@router.post("/api/demo/sessions/{session_id}/operator/clear-active")
async def operator_clear_active(session_id: str) -> dict[str, Any]:
    try:
        result = await demo_session_manager.operator_clear_active(session_id)
    except DemoSessionError as exc:
        _raise_safe(exc)
    return {"status": "ok", "operator": result}


@router.post("/api/demo/sessions/{session_id}/operator/click")
async def operator_click(session_id: str, payload: OperatorClickRequest) -> dict[str, Any]:
    expected_session = payload.active_recording_session_id or payload.operator_request_session_id
    try:
        result = await demo_session_manager.operator_click(
            session_id,
            payload.selector,
            record_action=payload.record_action,
            active_recording_session_id=expected_session,
        )
    except DemoSessionError as exc:
        _raise_safe(exc)
    return {"status": "ok", "operator": result}


@router.post("/api/demo/sessions/{session_id}/confirm-login")
async def confirm_demo_login(session_id: str) -> dict[str, Any]:
    try:
        session = await demo_session_manager.confirm_login(session_id)
    except DemoSessionError as exc:
        _raise_safe(exc)
    return {"status": "ok", "session": session}


@router.delete("/api/demo/sessions/{session_id}/saved-session")
async def clear_demo_saved_session(session_id: str) -> dict[str, Any]:
    try:
        result = await demo_session_manager.clear_saved_session(session_id)
    except DemoSessionError as exc:
        _raise_safe(exc, 404)
    return {"status": "ok", **result}


@router.post("/api/demo/sessions/{session_id}/saved-session/reopen")
async def reopen_demo_saved_session(session_id: str) -> dict[str, Any]:
    try:
        result = await demo_session_manager.reopen_with_saved_session(session_id)
    except DemoSessionError as exc:
        _raise_safe(exc)
    session = result.pop("session")
    return {"status": "ok", "session": session, "saved_session": result}


@router.post("/api/demo/sessions/{session_id}/recording/start")
async def start_demo_recording(
    session_id: str,
    payload: GuidedLearningRequest | None = None,
) -> dict[str, Any]:
    try:
        session = await demo_session_manager.start_recording(
            session_id,
            payload.model_dump() if payload is not None else {},
        )
    except DemoSessionError as exc:
        _raise_safe(exc)
    return {"status": "ok", "session": session}


@router.post("/api/demo/sessions/{session_id}/recording/stop")
async def stop_demo_recording(session_id: str) -> dict[str, Any]:
    try:
        result = await demo_session_manager.stop_recording(session_id)
    except DemoSessionError as exc:
        _raise_safe(exc)
    return {"status": "ok", **result}


@router.post("/api/demo/sessions/{session_id}/actions")
async def save_demo_action(session_id: str, payload: SaveDemoActionRequest) -> dict[str, Any]:
    try:
        action = await demo_session_manager.save_action(
            session_id,
            payload.name,
            payload.description,
            payload.variable_names,
            objective=payload.objective,
            input_description=payload.input_description,
            expected_result=payload.expected_result,
            success_criteria=payload.success_criteria,
            output_type=payload.output_type,
            user_result_summary_template=payload.user_result_summary_template,
            ai_result_summary_enabled=payload.ai_result_summary_enabled,
            ai_recovery_enabled=payload.ai_recovery_enabled,
            extraction_targets=payload.extraction_targets,
            extract_visible_text=payload.extract_visible_text,
            return_downloaded_file=payload.return_downloaded_file,
            requires_authenticated_session=payload.requires_authenticated_session,
            action_timeout_seconds=payload.action_timeout_seconds,
        )
    except DemoSessionError as exc:
        _raise_safe(exc)
    return {"status": "ok", "action": action}


@router.delete("/api/demo/sessions/{session_id}")
async def close_demo_session(session_id: str) -> dict[str, str]:
    await demo_session_manager.close(session_id)
    return {"status": "ok"}


@router.get("/demo/alvo", response_class=HTMLResponse, include_in_schema=False)
async def demo_target(request: Request) -> HTMLResponse:
    if request.cookies.get("cotasync_demo_session") != "authenticated":
        return HTMLResponse(_LOGIN_HTML)
    return HTMLResponse(_ORDERS_HTML)


@router.post("/demo/alvo/login", include_in_schema=False, response_model=None)
async def demo_target_login(request: Request) -> RedirectResponse | HTMLResponse:
    body = (await request.body()).decode("utf-8", errors="ignore")
    from urllib.parse import parse_qs

    form = parse_qs(body)
    if form.get("usuario", [""])[0] != "demo" or form.get("senha", [""])[0] != "demo":
        return HTMLResponse(_LOGIN_HTML.replace("<!--ERROR-->", "<p class='error'>Login inválido.</p>"), status_code=401)
    response = RedirectResponse("/demo/alvo", status_code=303)
    response.set_cookie(
        "cotasync_demo_session",
        "authenticated",
        httponly=True,
        samesite="strict",
    )
    return response


@router.get("/demo/manual-confirmation-test", response_class=HTMLResponse, include_in_schema=False)
async def manual_confirmation_test_target() -> HTMLResponse:
    """Pagina local sem login usada pela regressao de confirmacao manual desktop."""

    return HTMLResponse(_MANUAL_CONFIRMATION_TEST_HTML)


_LOGIN_HTML = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><title>Alvo Local — Login</title>
<style>body{font-family:sans-serif;max-width:420px;margin:80px auto;padding:24px}label,input,button{display:block;width:100%;margin:10px 0}input,button{padding:10px;box-sizing:border-box}.error{color:#b91c1c}</style>
</head><body><h1>Pedidos Demo</h1><p>Faça o login manual para continuar.</p><!--ERROR-->
<form method="post" action="/demo/alvo/login">
<label for="demo-user">Usuário</label><input id="demo-user" name="usuario" autocomplete="username" required>
<label for="demo-password">Senha</label><input id="demo-password" name="senha" type="password" autocomplete="current-password" required>
<button id="demo-login" type="submit">Entrar</button></form></body></html>"""


_MANUAL_CONFIRMATION_TEST_HTML = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><title>Intranet Newcon</title></head>
<body><main><h1>Intranet Newcon</h1><p>Página autenticada simulada para teste local.</p></main></body></html>"""


_ORDERS_HTML = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><title>Pedidos Demo — Consulta</title>
<style>body{font-family:sans-serif;max-width:620px;margin:60px auto;padding:24px}label,input,button{display:block;margin:10px 0}input{padding:10px;width:100%;box-sizing:border-box}button{padding:10px 18px}.result{margin-top:24px;padding:18px;background:#eef2ff;min-height:24px}</style>
</head><body data-cotasync-authenticated="true"><h1>Consulta de Pedidos</h1>
<p>Ambiente local com dados fictícios.</p>
<label for="pedido-codigo">Código do pedido</label>
<input id="pedido-codigo" name="codigo_pedido" placeholder="PED-1001">
<button id="buscar-pedido" type="button">Pesquisar</button>
<div id="pedido-status" class="result" data-cotasync-output="status_pedido" aria-live="polite"></div>
<script>
const pedidos={'PED-1001':'Em separação','PED-2002':'Enviado','PED-3003':'Entregue'};
document.getElementById('buscar-pedido').addEventListener('click',()=>{
 const codigo=document.getElementById('pedido-codigo').value.trim().toUpperCase();
 document.getElementById('pedido-status').textContent=pedidos[codigo]||'Pedido não encontrado';
});
</script></body></html>"""
