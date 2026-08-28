"""
API principal do CotaSync: FastAPI + agendador + webhook Evolution (simulado).
"""

from __future__ import annotations

import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.api.actions import router as actions_router
from backend.api.auth import router as auth_router
from backend.api.batches import router as batches_router
from backend.api.browser import router as browser_router
from backend.api.clients import groups_router as client_groups_router
from backend.api.clients import router as clients_router
from backend.api.demo import router as demo_router
from backend.api.desktop_browser import router as desktop_browser_router
from backend.api.external_systems import router as external_systems_router
from backend.api.runs import actions_run_router, runs_router
from backend.api.v1 import router as api_v1_router
from backend.services.auth import SESSION_COOKIE, parse_session_token, validate_csrf, validate_session_user
from backend.services.demo_session import demo_session_manager
from backend import whatsapp
from backend.seguranca import validar_numero_autorizado

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cotasync.api")


class _MaskViewTokenFilter(logging.Filter):
    """Impede que validacoes diretas por query exponham o segredo no access log."""

    _pattern = re.compile(r"(?i)(token=)[^&\s\"]+")

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._pattern.sub(r"\1<masked>", record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(
                self._pattern.sub(r"\1<masked>", value) if isinstance(value, str) else value
                for value in record.args
            )
        return True


logging.getLogger("uvicorn.access").addFilter(_MaskViewTokenFilter())

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await demo_session_manager.close_all()


app = FastAPI(
    title="CotaSync API",
    description="Backend operacional omnichannel (Evolution, agente, motor web).",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(actions_router)
app.include_router(auth_router)
app.include_router(batches_router)
app.include_router(browser_router)
app.include_router(clients_router)
app.include_router(client_groups_router)
app.include_router(actions_run_router)
app.include_router(runs_router)
app.include_router(demo_router)
app.include_router(desktop_browser_router)
app.include_router(external_systems_router)
app.include_router(api_v1_router)


@app.exception_handler(StarletteHTTPException)
async def cotasync_http_exception_handler(request: Request, exc: StarletteHTTPException):
    path = request.url.path.rstrip("/") or "/"
    if path.startswith("/api/v1/"):
        detail = exc.detail
        if isinstance(detail, dict):
            code = str(detail.get("code") or "HTTP_ERROR")
            message = str(detail.get("message") or detail.get("detail") or "Operacao indisponivel.")
            extra = {key: value for key, value in detail.items() if key not in {"code", "message", "detail"}}
        else:
            code = "HTTP_ERROR"
            message = str(detail or "Operacao indisponivel.")
            extra = {}
        return JSONResponse({"error": {"code": code, "message": message, **extra}}, status_code=exc.status_code)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


_PUBLIC_API_PATHS = {
    "/api/health/desktop-browser",
    "/api/v1/auth/login",
    "/api/v1/auth/logout",
    "/api/v1/browser/validate-view-token",
    "/webhook/evolution",
}


@app.middleware("http")
async def cotasync_auth_middleware(request: Request, call_next):
    path = request.url.path.rstrip("/") or "/"
    if path.startswith("/api/") and path not in _PUBLIC_API_PATHS:
        user = parse_session_token(request.cookies.get(SESSION_COOKIE, ""))
        if user is not None:
            user = validate_session_user(user)
        if user is None:
            if path.startswith("/api/v1/"):
                return JSONResponse({"error": {"code": "AUTH_REQUIRED", "message": "Authentication required."}}, status_code=401)
            return JSONResponse({"detail": "Authentication required."}, status_code=401)
        request.state.auth_user = user
        if request.method.upper() not in {"GET", "HEAD", "OPTIONS"} and not validate_csrf(request):
            if path.startswith("/api/v1/"):
                return JSONResponse({"error": {"code": "CSRF_REQUIRED", "message": "CSRF token required."}}, status_code=403)
            return JSONResponse({"detail": "CSRF token required."}, status_code=403)
    return await call_next(request)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "cotasync"}


@app.get("/api/health/desktop-browser")
async def health_desktop_browser() -> dict[str, Any]:
    from backend.services.browser_providers import configured_browser_mode, desktop_browser_health

    result = await desktop_browser_health()
    return {"status": "ok" if result["cdp_reachable"] else "error", "browser_mode": configured_browser_mode(), **result}


def _extrair_remetente_e_texto_simulado(body: dict[str, Any]) -> tuple[str, str]:
    """
    Extrai (jid_ou_numero, texto) de payloads típicos messages.* da Evolution.
    Mantém fallback para testes manuais com JSON mínimo.
    """
    # Forma explícita para testes: { "from": "5511...", "text": "..." }
    if "from" in body and "text" in body:
        return str(body["from"]), str(body["text"])

    data = body.get("data") or {}
    key = data.get("key") or {}
    remote = key.get("remoteJid") or data.get("remoteJid") or body.get("remoteJid")
    if not remote:
        raise HTTPException(status_code=400, detail="Não foi possível identificar o remetente.")

    msg = data.get("message") or body.get("message") or {}
    texto = (
        msg.get("conversation")
        or (msg.get("extendedTextMessage") or {}).get("text")
        or body.get("text")
        or ""
    )
    return str(remote), str(texto)


@app.post("/webhook/evolution")
async def webhook_evolution(
    request: Request,
    payload: dict[str, Any] | None = None,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """
    Webhook para eventos da Evolution API (mensagens simuladas ou reais).

    Valida whitelist antes de processar. Próxima iteração: despachar para o agente.
    """
    expected = os.getenv("EVOLUTION_API_KEY")
    if expected and expected != "..." and x_api_key != expected:
        raise HTTPException(status_code=401, detail="API Key inválida.")

    body = payload if payload is not None else await request.json()
    jid_ou_numero, texto = _extrair_remetente_e_texto_simulado(body)
    validar_numero_autorizado(jid_ou_numero)

    logger.info("Webhook Evolution aceito. Texto recebido (len=%s)", len(texto))
    # eco mock opcional
    _ = whatsapp.enviar_mensagem_whatsapp(jid_ou_numero, f"[CotaSync] Recebido: {texto[:200]}")

    return {"received": True, "preview": texto[:120]}
