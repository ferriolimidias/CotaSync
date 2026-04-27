"""
API principal do CotaSync: FastAPI + agendador + webhook Evolution (simulado).
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request

from backend import whatsapp
from backend.seguranca import validar_numero_autorizado

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cotasync.api")

scheduler = AsyncIOScheduler()


def _job_heartbeat_agendador() -> None:
    """Rotina de teste do APScheduler (visível nos logs do container/host)."""
    logger.info("CotaSync: heartbeat do agendador (a cada 1 minuto)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inicia o scheduler assíncrono junto com o servidor ASGI.
    scheduler.add_job(_job_heartbeat_agendador, "interval", minutes=1, id="heartbeat_cotasync")
    scheduler.start()
    logger.info("APScheduler iniciado.")
    yield
    scheduler.shutdown(wait=False)
    logger.info("APScheduler encerrado.")


app = FastAPI(
    title="CotaSync API",
    description="Backend operacional omnichannel (Evolution, agente, motor web).",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "cotasync"}


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
