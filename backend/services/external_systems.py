"""Persistencia JSON da configuracao do sistema externo atual."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from urllib.parse import urlsplit


_ROOT = Path(__file__).resolve().parents[2]
CURRENT_EXTERNAL_SYSTEM_PATH = _ROOT / "data" / "external_systems" / "current.json"


class ExternalSystemConfigError(RuntimeError):
    """Erro seguro de validacao ou persistencia da configuracao externa."""


def empty_external_system() -> dict[str, Any]:
    return {
        "external_system_name": "",
        "external_login_url": "",
        "validation": "",
        "auth_success_text": "",
        "auth_success_selector": "",
        "updated_at": None,
    }


def load_current_external_system() -> dict[str, Any]:
    if not CURRENT_EXTERNAL_SYSTEM_PATH.is_file():
        return empty_external_system()
    try:
        payload = json.loads(CURRENT_EXTERNAL_SYSTEM_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExternalSystemConfigError("Nao foi possivel ler a configuracao do sistema externo.") from exc
    if not isinstance(payload, dict):
        raise ExternalSystemConfigError("Configuracao do sistema externo em formato invalido.")
    result = empty_external_system()
    for key in (
        "external_system_name",
        "external_login_url",
        "validation",
        "auth_success_text",
        "auth_success_selector",
    ):
        result[key] = str(payload.get(key) or "").strip()
    if result["external_login_url"]:
        result["validation"] = _validation_mode(result)
    result["updated_at"] = payload.get("updated_at")
    return result


def save_current_external_system(payload: dict[str, Any]) -> dict[str, Any]:
    result = empty_external_system()
    for key in (
        "external_system_name",
        "external_login_url",
        "validation",
        "auth_success_text",
        "auth_success_selector",
    ):
        result[key] = str(payload.get(key) or "").strip()

    login_url = result["external_login_url"]
    system_name = result["external_system_name"]
    if login_url:
        parsed = urlsplit(login_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ExternalSystemConfigError("A URL de login deve ser uma URL HTTP ou HTTPS valida.")
        if not system_name:
            raise ExternalSystemConfigError("Informe o nome do sistema externo.")
    elif any(result[key] for key in ("auth_success_text", "auth_success_selector")):
        raise ExternalSystemConfigError("Informe a URL de login para usar a validacao de autenticacao.")

    if login_url:
        result["validation"] = _validation_mode(result)
    elif result["validation"]:
        raise ExternalSystemConfigError("Informe a URL de login para usar a validacao de autenticacao.")

    result["updated_at"] = datetime.now(UTC).isoformat()
    CURRENT_EXTERNAL_SYSTEM_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with NamedTemporaryFile(
            "w", encoding="utf-8", dir=CURRENT_EXTERNAL_SYSTEM_PATH.parent, delete=False
        ) as tmp:
            json.dump(result, tmp, ensure_ascii=False, indent=2)
            tmp.write("\n")
            tmp_path = Path(tmp.name)
        os.replace(tmp_path, CURRENT_EXTERNAL_SYSTEM_PATH)
        tmp_path = None
    except OSError as exc:
        raise ExternalSystemConfigError("Nao foi possivel salvar a configuracao do sistema externo.") from exc
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
    return result


def _validation_mode(config: dict[str, Any]) -> str:
    requested = str(config.get("validation") or "").strip().lower()
    if requested == "manual_confirmation":
        return requested
    if requested and requested not in {"selector", "text"}:
        raise ExternalSystemConfigError(
            "Validacao invalida. Use manual_confirmation, selector ou text."
        )
    if config.get("auth_success_selector"):
        return "selector"
    if config.get("auth_success_text"):
        return "text"
    if requested in {"selector", "text"}:
        raise ExternalSystemConfigError("Configure o sinal correspondente ao modo de validacao.")
    return "manual_confirmation"
