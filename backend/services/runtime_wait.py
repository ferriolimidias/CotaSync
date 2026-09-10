"""State-driven waits for slow external systems."""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable
from typing import Any


class RuntimeWaitCancelled(RuntimeError):
    code = "cancelled"


class RuntimeWaitTerminal(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


async def _resolve(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


async def wait_for_runtime_state(
    probe: Callable[[], Any],
    *,
    state_name: str,
    terminal_probe: Callable[[], Any] | None = None,
    cancellation_probe: Callable[[], Any] | None = None,
    on_waiting: Callable[[str], Any] | None = None,
    probe_timeout_seconds: float = 0.75,
    poll_interval_seconds: float = 0.25,
    waiting_interval_seconds: float = 10.0,
) -> Any:
    """Poll a condition until reached; a probe timeout is never a run failure."""
    last_waiting_notification = 0.0
    while True:
        if cancellation_probe is not None and await _resolve(cancellation_probe()):
            raise RuntimeWaitCancelled(f"Execução cancelada enquanto aguardava {state_name}.")
        if terminal_probe is not None:
            terminal = await _resolve(terminal_probe())
            if terminal:
                if isinstance(terminal, RuntimeWaitTerminal):
                    raise terminal
                if isinstance(terminal, tuple):
                    code, message = terminal
                else:
                    code, message = "runtime_terminal_state", str(terminal)
                raise RuntimeWaitTerminal(str(code), str(message))
        try:
            result = await asyncio.wait_for(
                _resolve(probe()),
                timeout=max(0.05, float(probe_timeout_seconds)),
            )
        except (asyncio.TimeoutError, TimeoutError):
            result = None
        if result:
            return result
        now = time.monotonic()
        if on_waiting is not None and (
            not last_waiting_notification
            or now - last_waiting_notification >= max(1.0, float(waiting_interval_seconds))
        ):
            await _resolve(on_waiting(state_name))
            last_waiting_notification = now
        await asyncio.sleep(max(0.05, float(poll_interval_seconds)))
