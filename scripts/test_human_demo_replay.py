"""Regressao do replay apos aprendizado humano em uma pagina CDP substituida."""

from __future__ import annotations

import asyncio

from test_demo_v01_cycle import main as run_demo_cycle


async def main() -> None:
    await run_demo_cycle(
        cycle_count=1,
        include_revalidation=False,
        replace_live_page=True,
        emulate_devtools_live_view=True,
    )
    print("Regressao humana: pagina CDP reanexada, replay, extracao e evidencia validados.")


if __name__ == "__main__":
    asyncio.run(main())
