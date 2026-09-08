from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import tests  # noqa: F401

from backend.services.browser_observation import BrowserObservation, BrowserObservationService


def _snapshot(*, deep: bool = False, source: str = "test") -> BrowserObservation:
    return BrowserObservation(
        observed_at=datetime.now(UTC),
        duration_ms=1.0,
        browser_available=True,
        page_available=True,
        current_url="https://example.test/form",
        current_host="example.test",
        current_path="/form",
        body_text="Pick an account" if deep else "",
        deep=deep,
        source=source,
    )


class BrowserObservationServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_passive_observation_uses_short_cache(self) -> None:
        service = BrowserObservationService(passive_ttl=0.5)
        calls = 0

        async def refresh(*, deep: bool, source: str) -> BrowserObservation:
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.01)
            result = _snapshot(deep=deep, source=source)
            service._snapshot = result
            if deep:
                service._deep_snapshot = result
            return result

        with patch.object(service, "_refresh", new=refresh):
            first = await service.observe(source="first")
            second = await service.observe(source="second")

        self.assertEqual(calls, 1)
        self.assertFalse(first.cache_hit)
        self.assertTrue(second.cache_hit)
        self.assertEqual(second.source, "second")

    async def test_expired_cache_refreshes(self) -> None:
        service = BrowserObservationService(passive_ttl=0.01)
        refresh = AsyncMock(side_effect=lambda *, deep, source: _snapshot(deep=deep, source=source))
        with patch.object(service, "_refresh", refresh):
            await service.observe()
            await asyncio.sleep(0.02)
            await service.observe()
        self.assertEqual(refresh.await_count, 2)

    async def test_expired_single_flight_has_one_refresh(self) -> None:
        service = BrowserObservationService(passive_ttl=0.5)
        calls = 0

        async def refresh(*, deep: bool, source: str) -> BrowserObservation:
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.02)
            result = _snapshot(deep=deep, source=source)
            service._snapshot = result
            if deep:
                service._deep_snapshot = result
            return result

        with patch.object(service, "_refresh", new=refresh):
            results = await asyncio.gather(*(service.observe(source=f"request-{i}") for i in range(5)))

        self.assertEqual(calls, 1)
        self.assertEqual(len(results), 5)
        self.assertTrue(all(result.current_url == results[0].current_url for result in results))

    async def test_force_deep_refresh_bypasses_passive_snapshot(self) -> None:
        service = BrowserObservationService(passive_ttl=10, deep_ttl=10)
        refresh = AsyncMock(side_effect=[_snapshot(deep=False), _snapshot(deep=True)])
        with patch.object(service, "_refresh", refresh):
            await service.observe(source="passive")
            deep = await service.observe_deep(force=True, source="validate")
        self.assertTrue(deep.deep)
        self.assertEqual(refresh.await_count, 2)
