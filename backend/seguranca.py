"""
Validação de whitelist para webhooks e canais externos (Evolution / WhatsApp).
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException


def _raiz_projeto() -> Path:
    return Path(__file__).resolve().parent.parent


_DATA_DIR = _raiz_projeto() / "data"
os.makedirs(str(_DATA_DIR), exist_ok=True)


@lru_cache(maxsize=1)
def _carregar_numeros_permitidos() -> set[str]:
    path = _DATA_DIR / "usuarios_autorizados.json"
    if not path.is_file():
        raise FileNotFoundError(f"Arquivo de whitelist não encontrado: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    numeros = data.get("numeros_permitidos", [])
    # Normaliza para apenas dígitos para comparação estável.
    return {re.sub(r"\D", "", str(n)) for n in numeros}


def normalizar_numero_whatsapp(jid_ou_numero: str) -> str:
    """
    Extrai dígitos do JID Evolution (ex.: 5511999999999@s.whatsapp.net) ou número cru.
    """
    s = jid_ou_numero.strip()
    if "@" in s:
        s = s.split("@", 1)[0]
    return re.sub(r"\D", "", s)


def validar_numero_autorizado(jid_ou_numero: str) -> str:
    """
    Garante que o remetente está na whitelist.

    Returns:
        Número normalizado (somente dígitos).

    Raises:
        HTTPException 403 se não autorizado.
    """
    numero = normalizar_numero_whatsapp(jid_ou_numero)
    permitidos = _carregar_numeros_permitidos()
    if numero not in permitidos:
        raise HTTPException(
            status_code=403,
            detail="Número não autorizado para este webhook.",
        )
    return numero
