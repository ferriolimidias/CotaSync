#!/usr/bin/env python3
"""Smoke test local para Browserless/CDP sem acessar sistemas externos."""

from __future__ import annotations

import asyncio
import json
import sys

from backend.motor_browser import verificar_browserless


async def main() -> int:
    resultado = await verificar_browserless("data/health/browserless_test.png")
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return 0 if resultado.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
