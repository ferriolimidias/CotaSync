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

DEFAULT_ACCESS_PROFILE = {
    "access_profile_name": "Priscila",
    "microsoft_saved_account_text": "Priscila Susin",
    "microsoft_saved_account_identifier": "D0004267@rdmz.com.br",
    "expected_system_host": "nwcweb.randonconsorcios.com.br",
    "microsoft_hosts": ["login.microsoftonline.com", "m365.cloud.microsoft"],
}
MICROSOFT_HOST_SUFFIXES = (
    "login.microsoftonline.com",
    "login.live.com",
    "login.microsoft.com",
    "login.windows.net",
    "m365.cloud.microsoft",
)


class ExternalSystemConfigError(RuntimeError):
    """Erro seguro de validacao ou persistencia da configuracao externa."""


def empty_external_system() -> dict[str, Any]:
    return {
        "external_system_name": "",
        "external_login_url": "",
        "validation": "",
        "auth_success_text": "",
        "auth_success_selector": "",
        "access_profile_name": DEFAULT_ACCESS_PROFILE["access_profile_name"],
        "access_profile_email_or_identifier": DEFAULT_ACCESS_PROFILE["microsoft_saved_account_identifier"],
        "microsoft_saved_account_identifier": DEFAULT_ACCESS_PROFILE["microsoft_saved_account_identifier"],
        "microsoft_saved_account_selector": "",
        "microsoft_saved_account_text": DEFAULT_ACCESS_PROFILE["microsoft_saved_account_text"],
        "expected_system_host": DEFAULT_ACCESS_PROFILE["expected_system_host"],
        "microsoft_hosts": list(DEFAULT_ACCESS_PROFILE["microsoft_hosts"]),
        "updated_at": None,
    }


def _string_keys() -> tuple[str, ...]:
    return (
        "external_system_name",
        "external_login_url",
        "validation",
        "auth_success_text",
        "auth_success_selector",
        "access_profile_name",
        "access_profile_email_or_identifier",
        "microsoft_saved_account_identifier",
        "microsoft_saved_account_selector",
        "microsoft_saved_account_text",
        "expected_system_host",
    )


def _normalize_microsoft_hosts(raw: Any) -> list[str]:
    if isinstance(raw, list):
        hosts = []
        for item in raw:
            host = str(item or "").strip().lower().rstrip(".")
            if _looks_like_url(host):
                host = (urlsplit(host).hostname or "").lower().rstrip(".")
            if host:
                hosts.append(host)
    else:
        hosts = []
    result: list[str] = []
    seen: set[str] = set()
    for host in [*(hosts or []), *DEFAULT_ACCESS_PROFILE["microsoft_hosts"]]:
        if host and host not in seen:
            seen.add(host)
            result.append(host)
    return result


def _looks_like_url(value: str) -> bool:
    parsed = urlsplit(str(value or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _normalize_access_profile_fields(result: dict[str, Any]) -> None:
    for key in ("access_profile_email_or_identifier", "microsoft_saved_account_identifier"):
        if _looks_like_url(str(result.get(key) or "")):
            result[key] = ""

    host = str(result.get("expected_system_host") or "").strip().lower().rstrip(".")
    if _looks_like_url(host):
        host = urlsplit(host).netloc.lower().rstrip(".")
    microsoft_hosts = set(_normalize_microsoft_hosts(result.get("microsoft_hosts")))
    is_microsoft_host = any(host == suffix or host.endswith(f".{suffix}") for suffix in MICROSOFT_HOST_SUFFIXES)
    if not host or "/" in host or "?" in host or host in microsoft_hosts or is_microsoft_host:
        result["expected_system_host"] = ""
    else:
        result["expected_system_host"] = host


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
    for key in _string_keys():
        result[key] = str(payload.get(key) or "").strip()
    result["microsoft_hosts"] = _normalize_microsoft_hosts(payload.get("microsoft_hosts"))
    _normalize_access_profile_fields(result)
    if not result["microsoft_saved_account_identifier"]:
        result["microsoft_saved_account_identifier"] = result["access_profile_email_or_identifier"]
    if not result["access_profile_email_or_identifier"]:
        result["access_profile_email_or_identifier"] = result["microsoft_saved_account_identifier"]
    for key, value in DEFAULT_ACCESS_PROFILE.items():
        if key == "microsoft_hosts":
            continue
        if not result.get(key):
            result[key] = str(value)
    if result["external_login_url"]:
        result["validation"] = _validation_mode(result)
    result["updated_at"] = payload.get("updated_at")
    return result


def save_current_external_system(payload: dict[str, Any]) -> dict[str, Any]:
    result = empty_external_system()
    for key in _string_keys():
        result[key] = str(payload.get(key) or "").strip()
    result["microsoft_hosts"] = _normalize_microsoft_hosts(payload.get("microsoft_hosts"))
    _normalize_access_profile_fields(result)
    if not result["microsoft_saved_account_identifier"]:
        result["microsoft_saved_account_identifier"] = result["access_profile_email_or_identifier"]
    if not result["access_profile_email_or_identifier"]:
        result["access_profile_email_or_identifier"] = result["microsoft_saved_account_identifier"]
    for key, value in DEFAULT_ACCESS_PROFILE.items():
        if key == "microsoft_hosts":
            continue
        if not result.get(key):
            result[key] = str(value)

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
