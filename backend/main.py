"""
API principal do CotaSync: FastAPI + agendador + webhook Evolution (simulado).
"""

from __future__ import annotations

import asyncio
import glob
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import pandas as pd
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

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
from backend.motor_browser import processar_lote_com_semaforo
from backend.services.auth import SESSION_COOKIE, parse_session_token, validate_csrf
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
    await demo_session_manager.close_all()
    scheduler.shutdown(wait=False)
    logger.info("APScheduler encerrado.")


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


_PUBLIC_API_PATHS = {
    "/api/health/desktop-browser",
    "/api/v1/auth/login",
    "/api/v1/auth/logout",
    "/webhook/evolution",
}


@app.middleware("http")
async def cotasync_auth_middleware(request: Request, call_next):
    path = request.url.path.rstrip("/") or "/"
    if path.startswith("/api/") and path not in _PUBLIC_API_PATHS:
        user = parse_session_token(request.cookies.get(SESSION_COOKIE, ""))
        if user is None:
            return JSONResponse({"detail": "Authentication required."}, status_code=401)
        request.state.auth_user = user
        if request.method.upper() not in {"GET", "HEAD", "OPTIONS"} and not validate_csrf(request):
            return JSONResponse({"detail": "CSRF token required."}, status_code=403)
    return await call_next(request)


async def verificar_fila_agendamentos():
    """Verifica a cada minuto se há lotes agendados para a hora atual."""
    pasta = "data/agendamentos"
    os.makedirs(pasta, exist_ok=True)

    while True:
        try:
            agora_data = datetime.now().strftime("%Y-%m-%d")
            agora_hora = datetime.now().strftime("%H:%M")
            arquivos_job = glob.glob("data/agendamentos/job_*.json")

            for caminho_json in arquivos_job:
                with open(caminho_json, "r", encoding="utf-8") as f:
                    job = json.load(f)

                data_job = job.get("data_execucao", agora_data)
                hora_job = job.get("hora_execucao")

                if job.get("status") == "pendente" and data_job == agora_data and hora_job == agora_hora:
                    logging.info(f"[CRON] Iniciando processamento do lote agendado: {job['id']}")

                    job["status"] = "processando"
                    with open(caminho_json, "w", encoding="utf-8") as f:
                        json.dump(job, f, ensure_ascii=False, indent=4)

                    try:
                        df_lote = pd.read_csv(job["caminho_csv"])
                        lista_dados = df_lote.to_dict("records")

                        resultados = await processar_lote_com_semaforo(
                            chave_acao=job["chave_acao"],
                            lista_linhas=lista_dados,
                            mapeamento=job["mapeamento"],
                            max_concorrencia=5,
                        )

                        df_resultado = df_lote.copy()
                        df_resultado["Status_Robo"] = [res.get("Status_Robo", "") for res in resultados]
                        df_resultado["Detalhes_Erro"] = [res.get("Detalhes_Erro", "") for res in resultados]
                        df_resultado["Dados_Extraidos"] = [res.get("Dados_Extraidos", "") for res in resultados]

                        caminho_resultado = str(job["caminho_csv"]).replace(".csv", "_concluido.csv")
                        df_resultado.to_csv(caminho_resultado, index=False)

                        job["status"] = "concluido"
                        job["resultado_csv"] = caminho_resultado
                    except Exception as err_job:
                        logging.error(f"[CRON] Erro crítico no job {job['id']}: {err_job}")
                        job["status"] = "erro"
                        job["detalhes_erro"] = str(err_job)

                    with open(caminho_json, "w", encoding="utf-8") as f:
                        json.dump(job, f, ensure_ascii=False, indent=4)

        except Exception as e:
            logging.error(f"[CRON] Falha no loop de verificação: {e}")

        await asyncio.sleep(60)


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(verificar_fila_agendamentos())
    logging.info("Agendador de tarefas em lote iniciado em background.")


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
