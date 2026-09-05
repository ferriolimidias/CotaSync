"""Shared Fernet key derivation for backend-only encrypted settings."""
from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet


def get_settings_fernet() -> Fernet:
    master = os.getenv("COTASYNC_AI_SETTINGS_SECRET", "").strip() or os.getenv("COTASYNC_SESSION_SECRET", "").strip()
    if not master:
        raise RuntimeError("COTASYNC_AI_SETTINGS_SECRET is required to use stored secrets.")
    key = base64.urlsafe_b64encode(hashlib.sha256(master.encode("utf-8")).digest())
    return Fernet(key)
