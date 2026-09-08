"""Leitura segura e reutilizavel do estado atual do browser desktop."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from playwright.async_api import async_playwright

from backend.services.browser_providers import BrowserConnection, browser_provider

logger = logging.getLogger("cotasync.browser_observation")

PASSIVE_TTL_SECONDS = 1.5
DEEP_TTL_SECONDS = 30.0


@dataclass(frozen=True)
class BrowserObservation:
    observed_at: datetime
    duration_ms: float
    browser_available: bool
    page_available: bool
    current_url: str = ""
    current_host: str = ""
    current_path: str = ""
    title: str = ""
    body_text: str = ""
    deep: bool = False
    source: str = "refresh"
    cache_hit: bool = False
    reconnect: bool = False
    microsoft_state: str = "unknown"
    profile_matches: tuple[str, ...] = field(default_factory=tuple)


class BrowserObservationService:
    """Mantem uma conexao CDP por event loop e serializa refreshes."""

    def __init__(self, *, passive_ttl: float = PASSIVE_TTL_SECONDS, deep_ttl: float = DEEP_TTL_SECONDS) -> None:
        self.passive_ttl = passive_ttl
        self.deep_ttl = deep_ttl
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._playwright: Any | None = None
        self._connection: BrowserConnection | None = None
        self._snapshot: BrowserObservation | None = None
        self._deep_snapshot: BrowserObservation | None = None

    def _same_loop(self) -> bool:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return False
        return self._loop is loop

    @staticmethod
    def _age(snapshot: BrowserObservation | None) -> float:
        if snapshot is None:
            return float("inf")
        return max(0.0, (datetime.now(UTC) - snapshot.observed_at).total_seconds())

    def _connection_alive(self) -> bool:
        connection = self._connection
        if connection is None:
            return False
        browser = connection.browser
        is_connected = getattr(browser, "is_connected", None)
        return bool(is_connected() if callable(is_connected) else True)

    async def _discard_connection(self) -> None:
        playwright = self._playwright
        self._playwright = None
        self._connection = None
        if playwright is not None:
            try:
                await playwright.stop()
            except Exception:
                logger.debug("Falha ao encerrar conexao CDP invalidada", exc_info=True)

    async def _connect(self) -> BrowserConnection:
        current_loop = asyncio.get_running_loop()
        if self._loop is not None and self._loop is not current_loop:
            # Playwright objects belong to the loop that created them. Do not
            # await teardown on a different loop (notably in test clients).
            self._playwright = None
            self._connection = None
        self._loop = current_loop
        if self._connection_alive():
            return self._connection  # type: ignore[return-value]
        await self._discard_connection()
        self._playwright = await async_playwright().start()
        try:
            self._connection = await browser_provider("desktop_browser").connect(self._playwright, "observation")
        except Exception:
            await self._discard_connection()
            raise
        return self._connection

    @staticmethod
    async def _current_page(connection: BrowserConnection) -> Any | None:
        pages = [page for page in connection.context.pages if not page.is_closed()]
        if not pages:
            return None
        if len(pages) == 1:
            return pages[0]
        for page in reversed(pages):
            try:
                if await page.evaluate("document.visibilityState === 'visible'"):
                    return page
            except Exception:
                continue
        return pages[-1]

    @staticmethod
    def _observation_from_page(
        *,
        started: float,
        page: Any | None,
        body_text: str = "",
        deep: bool = False,
        reconnect: bool = False,
        source: str = "refresh",
        cache_hit: bool = False,
    ) -> BrowserObservation:
        observed_at = datetime.now(UTC)
        if page is None:
            return BrowserObservation(
                observed_at=observed_at,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
                browser_available=True,
                page_available=False,
                body_text=body_text,
                deep=deep,
                source=source,
                cache_hit=cache_hit,
                reconnect=reconnect,
            )
        raw_url = str(page.url or "")
        parsed = urlsplit(raw_url)
        # The configured entry URL may contain OAuth parameters; never retain them.
        safe_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}" if parsed.scheme and parsed.netloc else ""
        return BrowserObservation(
            observed_at=observed_at,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
            browser_available=True,
            page_available=True,
            current_url=safe_url,
            current_host=(parsed.hostname or "").lower(),
            current_path=parsed.path or "/",
            body_text=body_text[:20_000],
            deep=deep,
            source=source,
            cache_hit=cache_hit,
            reconnect=reconnect,
        )

    async def _refresh(self, *, deep: bool, source: str) -> BrowserObservation:
        started = time.perf_counter()
        reconnect = False
        try:
            connection = await self._connect()
            page = await self._current_page(connection)
            body_text = ""
            if deep and page is not None:
                snapshot = await page.evaluate(
                    """() => ({
                        title: document.title || '',
                        ready_state: document.readyState || '',
                        text: document.body ? document.body.innerText.slice(0, 20000) : ''
                    })"""
                )
                body_text = str(snapshot.get("text") or "") if isinstance(snapshot, dict) else ""
            observation = self._observation_from_page(
                started=started,
                page=page,
                body_text=body_text,
                deep=deep,
                reconnect=reconnect,
                source=source,
            )
        except Exception as exc:
            reconnect = True
            await self._discard_connection()
            try:
                connection = await self._connect()
                page = await self._current_page(connection)
                body_text = ""
                if deep and page is not None:
                    body_text = str(await page.locator("body").inner_text(timeout=3000))[:20_000]
                observation = self._observation_from_page(
                    started=started,
                    page=page,
                    body_text=body_text,
                    deep=deep,
                    reconnect=reconnect,
                    source=source,
                )
            except Exception as retry_exc:
                await self._discard_connection()
                logger.warning("Observacao CDP indisponivel: %s", type(retry_exc).__name__)
                observation = BrowserObservation(
                    observed_at=datetime.now(UTC),
                    duration_ms=round((time.perf_counter() - started) * 1000, 1),
                    browser_available=False,
                    page_available=False,
                    deep=deep,
                    source=source,
                    reconnect=reconnect,
                )
        if deep:
            self._deep_snapshot = observation
        self._snapshot = observation
        if observation.duration_ms >= 250:
            logger.info(
                "browser_observation_slow source=%s deep=%s duration_ms=%s cache_hit=%s reconnect=%s",
                source,
                deep,
                observation.duration_ms,
                observation.cache_hit,
                observation.reconnect,
            )
        logger.debug(
            "browser_observation source=%s deep=%s duration_ms=%s cache_hit=%s reconnect=%s",
            source,
            deep,
            observation.duration_ms,
            observation.cache_hit,
            observation.reconnect,
        )
        return observation

    async def observe(self, *, deep: bool = False, force: bool = False, source: str = "passive") -> BrowserObservation:
        if self._loop is None:
            self._loop = asyncio.get_running_loop()

        def cached_result(snapshot: BrowserObservation) -> BrowserObservation:
            deep_snapshot = self._deep_snapshot
            body_text = snapshot.body_text
            has_deep = snapshot.deep
            if (
                not deep
                and deep_snapshot is not None
                and self._age(deep_snapshot) <= self.deep_ttl
                and deep_snapshot.current_url == snapshot.current_url
            ):
                body_text = deep_snapshot.body_text
                has_deep = True
            return BrowserObservation(**{**snapshot.__dict__, "body_text": body_text, "deep": has_deep, "cache_hit": True, "source": source})

        cached = self._snapshot if not deep else self._deep_snapshot
        ttl = self.deep_ttl if deep else self.passive_ttl
        if not force and cached is not None and self._same_loop() and self._age(cached) <= ttl:
            return cached_result(cached)
        async with self._lock:
            cached = self._snapshot if not deep else self._deep_snapshot
            if not force and cached is not None and self._same_loop() and self._age(cached) <= ttl:
                return cached_result(cached)
            return await self._refresh(deep=deep, source=source)

    async def observe_deep(self, *, force: bool = True, source: str = "deep") -> BrowserObservation:
        return await self.observe(deep=True, force=force, source=source)

    async def close(self) -> None:
        async with self._lock:
            await self._discard_connection()
            self._snapshot = None
            self._deep_snapshot = None


browser_observation_service = BrowserObservationService()
