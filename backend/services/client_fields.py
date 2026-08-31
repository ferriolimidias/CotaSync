from __future__ import annotations

import unicodedata
from typing import Any


CANONICAL_CLIENT_FIELDS = {"grupo", "cota", "versao"}
_CLIENT_FIELD_ALIASES = {
    "grupo": "grupo",
    "cota": "cota",
    "grupo_2": "cota",
    "versao": "versao",
    "vers_o": "versao",
    "grupo_3": "versao",
}
_CLIENT_FIELD_LABELS = {"grupo": "Grupo", "cota": "Cota", "versao": "Versão"}


def canonical_client_field_key(value: Any) -> str | None:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return _CLIENT_FIELD_ALIASES.get(text.strip().casefold())


def client_field_label(key: str) -> str:
    return _CLIENT_FIELD_LABELS.get(key, key)
