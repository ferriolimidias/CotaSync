"""Regressao do replay apos aprendizado humano em uma pagina CDP substituida."""

from __future__ import annotations

import asyncio

try:
    from test_demo_v01_cycle import main as run_demo_cycle
except ModuleNotFoundError:
    # The optional human-demo harness is not part of the repository checkout.
    # Keep collection usable; invoking this script still reports the missing
    # external harness explicitly.
    run_demo_cycle = None


async def main() -> None:
    if run_demo_cycle is None:
        raise RuntimeError("test_demo_v01_cycle.py não está disponível neste checkout.")
    await run_demo_cycle(
        cycle_count=1,
        include_revalidation=False,
        replace_live_page=True,
        emulate_devtools_live_view=True,
    )
    print("Regressao humana: pagina CDP reanexada, replay, extracao e evidencia validados.")


if __name__ == "__main__":
    asyncio.run(main())
