from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any


def safe_file_name(value: Any, *, default: str = "acao", max_length: int = 120) -> str:
    """Return a filesystem-safe filename stem or full name.

    Accents are removed, whitespace becomes underscores, unsafe characters are
    stripped, and a suffix like ".png" is preserved when present.
    """

    text = str(value or "").strip()
    fallback = str(default or "arquivo").strip() or "arquivo"
    suffix = Path(text).suffix if text and not text.endswith(("/", "\\")) else ""
    stem = text[: -len(suffix)] if suffix else text

    normalized = unicodedata.normalize("NFKD", stem or fallback)
    ascii_stem = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_stem = re.sub(r"\s+", "_", ascii_stem.strip())
    ascii_stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", ascii_stem)
    ascii_stem = re.sub(r"_+", "_", ascii_stem).strip("._-")
    if not ascii_stem:
        ascii_stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", fallback).strip("._-") or "arquivo"

    safe_suffix = ""
    if suffix:
        normalized_suffix = unicodedata.normalize("NFKD", suffix)
        safe_suffix = normalized_suffix.encode("ascii", "ignore").decode("ascii")
        safe_suffix = re.sub(r"[^A-Za-z0-9.]+", "", safe_suffix)
        if safe_suffix.count(".") != 1 or not safe_suffix.startswith("."):
            safe_suffix = ""

    max_length = max(1, int(max_length or 120))
    available = max_length - len(safe_suffix)
    if available < 1:
        safe_suffix = ""
        available = max_length
    ascii_stem = ascii_stem[:available].rstrip("._-") or "arquivo"
    return f"{ascii_stem}{safe_suffix}"
