"""
Integração WhatsApp (Evolution API) — camada de envio.

Por enquanto apenas mocks; na próxima iteração substituir por chamadas HTTP à Evolution.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def enviar_mensagem_whatsapp(numero: str, texto: str) -> dict[str, str | bool]:
    """
    Envia uma mensagem de texto para um número (formato E.164 sem '+' ou com).

    Mock: não realiza HTTP; apenas registra e devolve confirmação simulada.
    """
    destino = numero.strip()
    logger.info("[MOCK WhatsApp] Para=%s len(texto)=%s", destino, len(texto))
    return {"ok": True, "destino": destino, "modo": "mock"}
