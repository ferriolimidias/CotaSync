from __future__ import annotations

import asyncio
import unittest

from backend.services.runtime_wait import RuntimeWaitCancelled, RuntimeWaitTerminal, wait_for_runtime_state


class RuntimeWaitTests(unittest.TestCase):
    def test_slow_element_after_probe_window_passes(self) -> None:
        async def scenario() -> bool:
            attempts = 0

            async def probe() -> bool:
                nonlocal attempts
                attempts += 1
                return attempts > 20

            result = await wait_for_runtime_state(
                probe,
                state_name="slow element",
                probe_timeout_seconds=0.01,
                poll_interval_seconds=0.001,
            )
            self.assertTrue(result)
            self.assertGreater(attempts, 20)
            return result

        asyncio.run(scenario())

    def test_slow_transition_probe_timeouts_do_not_fail_run(self) -> None:
        async def scenario() -> None:
            attempts = 0

            async def probe() -> bool:
                nonlocal attempts
                attempts += 1
                if attempts <= 3:
                    await asyncio.sleep(0.03)
                return attempts >= 5

            self.assertTrue(
                await wait_for_runtime_state(
                    probe,
                    state_name="slow transition",
                    probe_timeout_seconds=0.005,
                    poll_interval_seconds=0.001,
                )
            )

        asyncio.run(scenario())

    def test_cancel_during_wait_is_terminal_cancelled(self) -> None:
        async def scenario() -> None:
            checks = 0

            async def cancelled() -> bool:
                nonlocal checks
                checks += 1
                return checks >= 3

            with self.assertRaises(RuntimeWaitCancelled):
                await wait_for_runtime_state(
                    lambda: False,
                    state_name="cancelled wait",
                    cancellation_probe=cancelled,
                    poll_interval_seconds=0.001,
                )

        asyncio.run(scenario())

    def test_browser_dead_is_terminal(self) -> None:
        async def scenario() -> None:
            with self.assertRaises(RuntimeWaitTerminal) as raised:
                await wait_for_runtime_state(
                    lambda: False,
                    state_name="browser state",
                    terminal_probe=lambda: ("browser_unavailable", "browser dead"),
                )
            self.assertEqual(raised.exception.code, "browser_unavailable")

        asyncio.run(scenario())

    def test_reauth_is_terminal(self) -> None:
        async def scenario() -> None:
            with self.assertRaises(RuntimeWaitTerminal) as raised:
                await wait_for_runtime_state(
                    lambda: False,
                    state_name="account bootstrap",
                    terminal_probe=lambda: RuntimeWaitTerminal("reauth_required", "MFA"),
                )
            self.assertEqual(raised.exception.code, "reauth_required")

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
