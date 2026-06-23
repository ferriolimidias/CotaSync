"""Metadados seguros para arquivos gerados em runtime."""

from __future__ import annotations

import mimetypes
import re
from pathlib import Path
from uuid import uuid4


_ROOT = Path(__file__).resolve().parents[2]
_DOWNLOAD_ROOT = _ROOT / "data" / "runs" / "downloads"


def runtime_download_path(action_name: str, run_reference: str = "", extension: str = ".pdf") -> Path:
    safe_action = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(action_name or "arquivo")).strip("_") or "arquivo"
    safe_reference = re.sub(r"[^a-zA-Z0-9_-]+", "", str(run_reference or "")) or uuid4().hex
    safe_extension = extension if extension.startswith(".") and len(extension) <= 10 else ".bin"
    _DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    return _DOWNLOAD_ROOT / f"{safe_reference}_{safe_action}{safe_extension.lower()}"


def runtime_file_metadata(path: Path | str) -> dict[str, object]:
    candidate = Path(path).resolve()
    download_root = _DOWNLOAD_ROOT.resolve()
    if not candidate.is_file() or not candidate.is_relative_to(download_root):
        raise ValueError("Arquivo de runtime invalido.")
    relative = candidate.relative_to(_ROOT).as_posix()
    mime_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
    return {
        "name": candidate.name,
        "path": relative,
        "mime_type": mime_type,
        "size_bytes": candidate.stat().st_size,
    }
