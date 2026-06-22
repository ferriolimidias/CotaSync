"""Sessao assistida e recorder minimo para a demonstracao CotaSync v0.1."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from playwright.async_api import (
    Browser,
    BrowserContext,
    Locator,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

from backend.services.browserless_urls import public_devtools_host
from backend.services.browser_providers import (
    BrowserMode,
    BrowserProviderError,
    browser_provider,
    configured_browser_mode,
)


logger = logging.getLogger("cotasync.demo")
_ROOT = Path(__file__).resolve().parents[2]
_DATA_DIR = _ROOT / "data"
_UI_MAP_PATH = _DATA_DIR / "ui_map.json"
_DEMO_SESSIONS_DIR = _DATA_DIR / "demo_sessions"
_MAX_RECORDED_STEPS = 200
_REPLAY_STEP_TIMEOUT_MS = 5000


class DemoSessionError(RuntimeError):
    """Erro operacional seguro no fluxo da demonstracao."""


class DemoReplayStepError(DemoSessionError):
    """Falha de replay com diagnostico seguro para persistencia na run."""

    def __init__(self, message: str, diagnostics: dict[str, Any]) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


_RECORDER_SCRIPT = r"""
(() => {
  if (window.__cotasyncRecorderInstalled) return;
  window.__cotasyncRecorderInstalled = true;

  const attrValue = (value) => String(value || '').replace(/\\/g, '\\\\').replace(/"/g, '\\"');
  const sensitive = (el) => {
    if (!el) return true;
    const signature = [el.type, el.name, el.id, el.autocomplete, el.getAttribute('aria-label')]
      .join(' ').toLowerCase();
    return /password|senha|secret|token|otp|one-time|captcha/.test(signature);
  };
  const selectorFor = (el) => {
    if (!el || !el.tagName) return '';
    const tag = el.tagName.toLowerCase();
    const explicit = el.getAttribute('data-cotasync-selector');
    if (explicit) return explicit;
    if (el.id) return `#${CSS.escape(el.id)}`;
    const testId = el.getAttribute('data-testid');
    if (testId) return `[data-testid="${attrValue(testId)}"]`;
    if (el.name) return `${tag}[name="${attrValue(el.name)}"]`;
    const aria = el.getAttribute('aria-label');
    if (aria) return `${tag}[aria-label="${attrValue(aria)}"]`;
    const parent = el.parentElement;
    if (!parent) return tag;
    const siblings = Array.from(parent.children).filter((item) => item.tagName === el.tagName);
    const position = siblings.indexOf(el) + 1;
    return `${selectorFor(parent)} > ${tag}:nth-of-type(${Math.max(position, 1)})`;
  };
  window.__cotasyncSelectorFor = selectorFor;
  const domSummary = () => ({
    ready_state: document.readyState,
    element_count: document.body ? document.body.querySelectorAll('*').length : 0,
    interactive_count: document.querySelectorAll('button,input,select,textarea,a,[role="button"]').length,
    modal_count: document.querySelectorAll('[role="dialog"],dialog[open],.modal.show,[aria-modal="true"]').length,
    authenticated_marker: document.body?.dataset?.cotasyncAuthenticated === 'true'
  });
  const snapshot = () => ({
    timestamp: new Date().toISOString(),
    timestamp_ms: Date.now(),
    url: String(location.href || '').split(/[?#]/, 1)[0],
    title: String(document.title || '').slice(0, 200),
    dom_summary: domSummary()
  });
  const send = (payload, before, delay = 0) => {
    if (!payload.seletor || typeof window.__cotasyncRecord !== 'function') return;
    setTimeout(() => {
      const after = snapshot();
      Promise.resolve(window.__cotasyncRecord({
        ...payload,
        timestamp_before: before.timestamp,
        timestamp_after: after.timestamp,
        elapsed_ms: Math.max(0, after.timestamp_ms - before.timestamp_ms),
        url_before: before.url,
        url_after: after.url,
        title_before: before.title,
        title_after: after.title,
        dom_summary_before: before.dom_summary,
        dom_summary_after: after.dom_summary
      })).catch(() => {});
    }, delay);
  };

  const inputBefore = new WeakMap();
  const inputTimers = new WeakMap();
  document.addEventListener('beforeinput', (event) => {
    if (event.target && !sensitive(event.target)) inputBefore.set(event.target, snapshot());
  }, true);
  document.addEventListener('input', (event) => {
    const el = event.target;
    if (!el || !['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName) || sensitive(el)) return;
    const previousTimer = inputTimers.get(el);
    if (previousTimer) clearTimeout(previousTimer);
    const before = inputBefore.get(el) || snapshot();
    inputTimers.set(el, setTimeout(() => {
      send({tipo: 'preencher', event_type: 'fill', seletor: selectorFor(el), valor: '', value_template: '{{input_value}}'}, before);
      inputBefore.delete(el);
    }, 250));
  }, true);

  document.addEventListener('click', (event) => {
    const el = event.target && event.target.closest
      ? event.target.closest('button, a, input, [role="button"]')
      : null;
    if (!el || sensitive(el)) return;
    const type = String(el.type || '').toLowerCase();
    if (['text', 'email', 'password', 'search', 'number'].includes(type)) return;
    const before = snapshot();
    send({tipo: 'clicar', event_type: 'click', seletor: selectorFor(el), valor: ''}, before, 500);
    setTimeout(captureOutputs, 650);
    setTimeout(captureOutputs, 900);
  }, true);

  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' || sensitive(event.target)) return;
    const before = snapshot();
    Promise.resolve(window.__cotasyncRecord({
      tipo: 'teclar', event_type: 'wait', seletor: '', valor: 'Enter',
      timestamp_before: before.timestamp, timestamp_after: before.timestamp,
      elapsed_ms: 0, url_before: before.url, url_after: before.url,
      title_before: before.title, title_after: before.title,
      dom_summary_before: before.dom_summary, dom_summary_after: before.dom_summary
    })).catch(() => {});
  }, true);

  const outputValues = new Map();
  const captureOutputs = () => {
    document.querySelectorAll('[data-cotasync-output]').forEach((el) => {
      const value = String(el.innerText || el.value || '').trim();
      const selector = selectorFor(el);
      if (!value || outputValues.get(selector) === value) return;
      outputValues.set(selector, value);
      const before = snapshot();
      send({
        tipo: 'extrair_texto',
        event_type: 'extract',
        seletor: selector,
        valor: '',
        nome: el.getAttribute('data-cotasync-output') || 'resultado'
      }, before);
    });
  };
  new MutationObserver(captureOutputs).observe(document.documentElement, {
    childList: true,
    subtree: true,
    characterData: true,
    attributes: true
  });
  captureOutputs();
})();
"""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _tracking_id(session_id: str) -> str:
    return f"cotasync-{str(session_id).replace('-', '')[:16]}"


def _demo_target_url() -> str:
    return os.getenv(
        "COTASYNC_DEMO_TARGET_URL",
        "http://cotasync_test_backend:8000/demo/alvo",
    ).strip()


def _live_url_kind(live_url: str) -> str:
    path = urlsplit(str(live_url or "")).path.rstrip("/")
    if path.endswith("/devtools/inspector.html"):
        return "devtools_inspector"
    if path.endswith("/vnc.html") or path.endswith("/index.html"):
        return "novnc"
    return "unknown"


def _safe_page_url(url: str) -> str:
    parsed = urlsplit(str(url or ""))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _expected_replay_url(saved_url: Any) -> str:
    candidate = str(saved_url or "").strip()
    if urlsplit(candidate).scheme in {"http", "https"}:
        return _safe_page_url(candidate)
    return _safe_page_url(_demo_target_url())


def _page_matches_url(page: Page, expected_url: str) -> bool:
    return _safe_page_url(page.url) == _safe_page_url(expected_url)


def _safe_file_name(value: str) -> str:
    return re.sub(r"[^\w\-]+", "_", str(value or "acao"), flags=re.UNICODE).strip("_") or "acao"


def _is_sensitive_selector(selector: str) -> bool:
    return bool(re.search(r"password|senha|secret|token|otp|captcha", selector, flags=re.IGNORECASE))


def _storage_state_path(session_id: str) -> Path:
    return _DEMO_SESSIONS_DIR / str(session_id) / "storage_state.json"


def _external_storage_state_path(system_name: str, session_id: str) -> Path:
    return (
        _DATA_DIR
        / "external_systems"
        / "sessions"
        / _safe_file_name(system_name).lower()
        / str(session_id)
        / "storage_state.json"
    )


def _load_ui_map() -> dict[str, Any]:
    if not _UI_MAP_PATH.is_file():
        return {"acoes_conhecidas": {}}
    try:
        payload = json.loads(_UI_MAP_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise DemoSessionError("Nao foi possivel ler o catalogo de acoes.") from exc
    if not isinstance(payload, dict):
        raise DemoSessionError("Catalogo de acoes em formato invalido.")
    if not isinstance(payload.get("acoes_conhecidas"), dict):
        payload["acoes_conhecidas"] = {}
    return payload


def _save_ui_map(payload: dict[str, Any]) -> None:
    _UI_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with NamedTemporaryFile("w", encoding="utf-8", dir=_UI_MAP_PATH.parent, delete=False) as tmp:
            json.dump(payload, tmp, ensure_ascii=False, indent=2)
            tmp.write("\n")
            tmp_path = Path(tmp.name)
        os.replace(tmp_path, _UI_MAP_PATH)
    except OSError as exc:
        raise DemoSessionError("Nao foi possivel salvar a acao aprendida.") from exc


@dataclass
class DemoBrowserSession:
    id: str
    playwright: Playwright
    browser: Browser
    context: BrowserContext
    page: Page
    target_id: str
    live_url: str
    created_at: str
    tracking_id: str
    browser_mode: BrowserMode = "browserless"
    external_system_name: str = ""
    external_login_url: str = ""
    auth_success_text: str = ""
    auth_success_selector: str = ""
    storage_state_path: Path = field(default_factory=Path)
    manual_login_confirmed: bool = False
    status: str = "aguardando_login"
    recording: bool = False
    steps: list[dict[str, str]] = field(default_factory=list)
    learning_events: list[dict[str, Any]] = field(default_factory=list)
    observer_tasks: set[asyncio.Task[Any]] = field(default_factory=set)
    last_screenshot_path: str = ""
    last_page_count: int = 0
    download_detected: bool = False
    operator_recording_suppressed_until: float = 0.0


class DemoSessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, DemoBrowserSession] = {}

    def _get(self, session_id: str) -> DemoBrowserSession:
        session = self._sessions.get(str(session_id))
        if session is None:
            raise DemoSessionError("Sessao de demonstracao nao encontrada ou encerrada.")
        return session

    def _append_step(self, session: DemoBrowserSession, raw: Any) -> int | None:
        if (
            not session.recording
            or time.monotonic() < session.operator_recording_suppressed_until
            or not isinstance(raw, dict)
            or len(session.steps) >= _MAX_RECORDED_STEPS
        ):
            return None
        step_type = str(raw.get("tipo") or "").strip().lower()
        selector = str(raw.get("seletor") or "").strip()
        if step_type not in {"clicar", "preencher", "teclar", "extrair_texto"}:
            return None
        if step_type != "teclar" and (not selector or _is_sensitive_selector(selector)):
            return None
        step = {
            "tipo": step_type,
            "seletor": selector,
            "valor": str(raw.get("valor") or ""),
        }
        name = str(raw.get("nome") or "").strip()
        if name:
            step["nome"] = name

        if step_type == "preencher" and session.steps:
            previous = session.steps[-1]
            if previous.get("tipo") == "preencher" and previous.get("seletor") == selector:
                session.steps[-1] = step
                return len(session.steps) - 1
        if session.steps and session.steps[-1] == step:
            return len(session.steps) - 1
        session.steps.append(step)
        return len(session.steps) - 1

    async def _record_live_step(self, session: DemoBrowserSession, raw: Any, source: Any = None) -> None:
        step_index = self._append_step(session, raw)
        if step_index is None or not isinstance(raw, dict):
            return

        page = source.get("page") if isinstance(source, dict) else None
        if not isinstance(page, Page) or page.is_closed():
            page = session.page
        live_pages = [item for item in session.context.pages if not item.is_closed()]
        opened_new_page = len(live_pages) > session.last_page_count
        if opened_new_page and live_pages:
            newest_page = live_pages[-1]
            if newest_page is not page:
                page = newest_page
        active_page_changed = page is not session.page
        if active_page_changed:
            await self._set_active_page(session, page)

        event_number = len(session.learning_events)
        screenshot_after = session.storage_state_path.parent / "learning" / f"step_{event_number}_after.png"
        screenshot_after.parent.mkdir(parents=True, exist_ok=True)
        screenshot_after_path = ""
        try:
            await page.screenshot(path=str(screenshot_after), full_page=False, timeout=_REPLAY_STEP_TIMEOUT_MS)
            screenshot_after_path = str(screenshot_after.relative_to(_ROOT))
        except Exception:
            pass

        elapsed_ms = max(0, int(raw.get("elapsed_ms") or 0))
        event_type = str(raw.get("event_type") or "").strip().lower()
        if event_type not in {"fill", "click", "extract", "download", "navigation", "popup", "new_tab", "modal", "wait"}:
            event_type = {
                "preencher": "fill",
                "clicar": "click",
                "extrair_texto": "extract",
                "teclar": "wait",
            }.get(str(raw.get("tipo") or ""), "wait")
        event: dict[str, Any] = {
            "step_index": step_index,
            "event_type": event_type,
            "selector": str(raw.get("seletor") or ""),
            "value_template": str(raw.get("value_template") or "") if event_type == "fill" else "",
            "variable_key": "",
            "timestamp_before": str(raw.get("timestamp_before") or _utc_now()),
            "timestamp_after": str(raw.get("timestamp_after") or _utc_now()),
            "elapsed_ms": elapsed_ms,
            "url_before": _safe_page_url(str(raw.get("url_before") or page.url)),
            "url_after": _safe_page_url(str(raw.get("url_after") or page.url)),
            "title_before": str(raw.get("title_before") or "")[:200],
            "title_after": str(raw.get("title_after") or "")[:200],
            "dom_summary_before": raw.get("dom_summary_before") if isinstance(raw.get("dom_summary_before"), dict) else {},
            "dom_summary_after": raw.get("dom_summary_after") if isinstance(raw.get("dom_summary_after"), dict) else {},
            "screenshot_before_path": session.last_screenshot_path,
            "screenshot_after_path": screenshot_after_path,
            "opened_new_page": opened_new_page,
            "active_page_changed": active_page_changed,
            "download_detected": session.download_detected,
        }
        from backend.services.ai_observer import deterministic_observe_learning_step, observe_learning_step_with_ai

        event.update(deterministic_observe_learning_step(event))
        session.learning_events.append(event)
        session.last_screenshot_path = screenshot_after_path or session.last_screenshot_path
        session.last_page_count = len(live_pages)
        session.download_detected = False

        async def apply_live_review() -> None:
            review = await observe_learning_step_with_ai(
                event,
                {"previous_events": len(session.learning_events) - 1},
            )
            event.update(review)

        task = asyncio.create_task(apply_live_review())
        session.observer_tasks.add(task)
        task.add_done_callback(session.observer_tasks.discard)

    async def _page_is_authenticated(self, session: DemoBrowserSession, page: Page) -> bool:
        """Valida os sinais publicos aceitos pela demo sem depender do status em memoria."""

        try:
            if page.is_closed():
                return False
            if session.external_login_url:
                if session.auth_success_selector:
                    locator = page.locator(session.auth_success_selector)
                    return await locator.count() > 0 and await locator.first.is_visible()
                if session.auth_success_text:
                    body_text = await page.locator("body").inner_text(timeout=_REPLAY_STEP_TIMEOUT_MS)
                    return session.auth_success_text in body_text
                parsed = urlsplit(str(page.url or ""))
                return (
                    session.manual_login_confirmed
                    and parsed.scheme in {"http", "https"}
                    and bool(parsed.netloc)
                )
            if await page.locator("[data-cotasync-authenticated='true']").count() > 0:
                return True
            if await page.get_by_text("Consulta de Pedidos", exact=False).count() > 0:
                return True
            has_order_input = await page.locator("input#pedido-codigo").count() > 0
            has_search_button = await page.locator("button#buscar-pedido").count() > 0
            if has_order_input and has_search_button:
                return True

            # Sinal generico minimo para futuras paginas assistidas: depois da
            # confirmacao humana, uma pagina HTTP carregada sem formulario de
            # senha visivel pode continuar. Integracoes reais poderao fornecer
            # marcadores de autenticacao mais fortes por sistema.
            is_demo_target = "/demo/alvo" in str(page.url or "")
            has_login_form = await page.locator("input[type='password']:visible, #demo-login:visible").count() > 0
            if is_demo_target:
                return not has_login_form
            parsed = urlsplit(str(page.url or ""))
            return parsed.scheme in {"http", "https"} and bool(parsed.netloc) and not has_login_form
        except Exception:
            return False

    async def _set_active_page(self, session: DemoBrowserSession, page: Page) -> None:
        session.page = page
        session.context = page.context
        cdp = await session.context.new_cdp_session(page)
        try:
            target_info = await cdp.send("Target.getTargetInfo")
            target_id = str(target_info.get("targetInfo", {}).get("targetId") or "")
        finally:
            await cdp.detach()
        if target_id:
            session.target_id = target_id
            session.live_url = browser_provider(session.browser_mode).live_url(target_id)

    async def _reconnect_live_browser(self, session: DemoBrowserSession) -> bool:
        if session.browser.is_connected():
            return True
        try:
            connection = await browser_provider(session.browser_mode).connect(session.playwright, session.id)
            browser = connection.browser
            context = connection.context
            await self._prepare_reconnected_context(session.id, context)
            session.browser = browser
            session.context = context
            if session.page.is_closed() or session.page.context != context:
                session.page = connection.page
            return True
        except Exception as exc:
            logger.info("Pagina CDP da sessao %s indisponivel: %s", session.id, type(exc).__name__)
            return False

    async def _find_authenticated_live_page(
        self,
        session: DemoBrowserSession,
        expected_url: str,
    ) -> Page | None:
        if not await self._reconnect_live_browser(session):
            return None

        candidates = [session.page]
        for context in session.browser.contexts:
            candidates.extend(context.pages)

        seen: set[int] = set()
        valid_candidates: list[Page] = []
        for page in candidates:
            identity = id(page)
            if identity in seen:
                continue
            seen.add(identity)
            url_matches = _page_matches_url(page, expected_url)
            if session.external_login_url and (session.auth_success_selector or session.auth_success_text):
                url_matches = True
            elif session.external_login_url:
                expected_origin = urlsplit(session.external_login_url)
                page_origin = urlsplit(str(page.url or ""))
                url_matches = (page_origin.scheme, page_origin.netloc) == (
                    expected_origin.scheme,
                    expected_origin.netloc,
                )
            if url_matches and await self._page_is_authenticated(session, page):
                valid_candidates.append(page)

        if not valid_candidates:
            return None
        return next((page for page in valid_candidates if page is session.page), valid_candidates[0])

    async def _save_storage_state(self, session: DemoBrowserSession, *, required: bool) -> bool:
        path = session.storage_state_path
        tmp_path: Path | None = None
        try:
            state = await session.context.storage_state()
            path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
                json.dump(state, tmp, ensure_ascii=False, indent=2)
                tmp.write("\n")
                tmp_path = Path(tmp.name)
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, path)
            tmp_path = None
            return True
        except Exception as exc:
            logger.warning("Falha ao persistir storage_state da sessao %s: %s", session.id, exc)
            if required:
                raise DemoSessionError("Login reconhecido, mas nao foi possivel salvar a sessao.") from exc
            return False
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

    async def _prepare_reconnected_context(self, session_id: str, context: BrowserContext) -> None:
        async def record_binding(source: Any, payload: Any) -> None:
            current = self._sessions.get(session_id)
            if current is not None:
                await self._record_live_step(current, payload, source)

        await context.expose_binding("__cotasyncRecord", record_binding)
        await context.add_init_script(_RECORDER_SCRIPT)

    async def _restore_storage_state(self, session: DemoBrowserSession, expected_url: str) -> Page | None:
        path = session.storage_state_path
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(state, dict):
            return None

        try:
            if not await self._reconnect_live_browser(session):
                return None
            context = session.context

            cookies = state.get("cookies", [])
            if isinstance(cookies, list) and cookies:
                await context.add_cookies(cookies)

            local_storage_by_origin: dict[str, dict[str, str]] = {}
            origins = state.get("origins", [])
            if isinstance(origins, list):
                for origin_state in origins:
                    if not isinstance(origin_state, dict):
                        continue
                    origin = str(origin_state.get("origin") or "")
                    entries = origin_state.get("localStorage", [])
                    if not origin or not isinstance(entries, list):
                        continue
                    local_storage_by_origin[origin] = {
                        str(item.get("name")): str(item.get("value"))
                        for item in entries
                        if isinstance(item, dict) and item.get("name") is not None
                    }
            if local_storage_by_origin:
                serialized = json.dumps(local_storage_by_origin, ensure_ascii=False)
                await context.add_init_script(
                    f"""() => {{
                      const stored = {serialized};
                      const entries = stored[window.location.origin] || {{}};
                      for (const [key, value] of Object.entries(entries)) localStorage.setItem(key, value);
                    }}"""
                )

            page = session.page if not session.page.is_closed() and session.page.context == context else None
            if page is None:
                page = next((item for item in context.pages if not item.is_closed()), None)
            if page is None:
                page = await context.new_page()
            await page.goto(expected_url, wait_until="domcontentloaded", timeout=15000)
            if not await self._page_is_authenticated(session, page):
                return None
            return page
        except Exception as exc:
            logger.info("storage_state nao restaurou a sessao %s: %s", session.id, exc)
            return None

    async def _revalidate_for_replay(
        self,
        session: DemoBrowserSession,
        expected_url: str,
    ) -> tuple[bool, bool]:
        was_authenticated = session.status in {"autenticada", "gravando"}
        previous_page = session.page
        page = await self._find_authenticated_live_page(session, expected_url)
        restored = False
        if page is None:
            page = await self._restore_storage_state(session, expected_url)
            restored = page is not None
        if page is None:
            session.status = "expirada"
            return False, False

        await self._set_active_page(session, page)
        session.status = "autenticada"
        await self._save_storage_state(session, required=False)
        automatically_revalidated = not was_authenticated or restored or page is not previous_page
        if automatically_revalidated:
            logger.info(
                "Sessao %s revalidada automaticamente via %s",
                session.id,
                "storage_state" if restored else "pagina CDP ativa",
            )
        return True, automatically_revalidated

    async def create(self) -> dict[str, Any]:
        session_id = str(uuid4())
        from backend.services.external_systems import (
            ExternalSystemConfigError,
            load_current_external_system,
        )

        try:
            external_config = load_current_external_system()
        except ExternalSystemConfigError as exc:
            raise DemoSessionError(str(exc)) from exc
        external_login_url = str(external_config.get("external_login_url") or "").strip()
        external_system_name = str(external_config.get("external_system_name") or "").strip()
        target_url = external_login_url or _demo_target_url()
        storage_state_path = (
            _external_storage_state_path(external_system_name, session_id)
            if external_login_url
            else _storage_state_path(session_id)
        )
        playwright = await async_playwright().start()
        browser: Browser | None = None
        selected_mode = configured_browser_mode()
        provider = browser_provider(selected_mode)
        try:
            connection = await provider.connect(playwright, session_id)
            browser = connection.browser
            context = connection.context
            page = connection.page
            await self._prepare_reconnected_context(session_id, context)
            await page.goto(target_url, wait_until="domcontentloaded", timeout=15000)
            cdp = await context.new_cdp_session(page)
            target_info = await cdp.send("Target.getTargetInfo")
            target_id = str(target_info.get("targetInfo", {}).get("targetId") or "")
            if not target_id:
                raise DemoSessionError("O provider nao informou o identificador da pagina.")

            session = DemoBrowserSession(
                id=session_id,
                playwright=playwright,
                browser=browser,
                context=context,
                page=page,
                target_id=target_id,
                live_url=provider.live_url(target_id),
                created_at=_utc_now(),
                tracking_id=_tracking_id(session_id),
                browser_mode=selected_mode,
                external_system_name=external_system_name,
                external_login_url=external_login_url,
                auth_success_text=str(external_config.get("auth_success_text") or "").strip(),
                auth_success_selector=str(external_config.get("auth_success_selector") or "").strip(),
                storage_state_path=storage_state_path,
            )
            self._sessions[session_id] = session
            session.last_page_count = len(context.pages)

            def watch_download(item: Page) -> None:
                item.on(
                    "download",
                    lambda _download: setattr(session, "download_detected", True),
                )

            for current_page in context.pages:
                watch_download(current_page)
            context.on("page", watch_download)
            logger.info(
                "Sessao assistida criada: session=%s mode=%s target=%s pages=%s live_url_kind=%s",
                session_id,
                selected_mode,
                target_id,
                len(context.pages),
                _live_url_kind(session.live_url),
            )
            return await self.status(session_id)
        except Exception as exc:
            if browser is not None and provider.close_browser_on_session_end:
                await browser.close()
            await playwright.stop()
            if isinstance(exc, (DemoSessionError, BrowserProviderError)):
                if isinstance(exc, BrowserProviderError):
                    raise DemoSessionError(str(exc)) from exc
                raise
            logger.exception("Falha ao criar sessao assistida")
            raise DemoSessionError("Nao foi possivel abrir a sessao do navegador.") from exc

    async def status(self, session_id: str) -> dict[str, Any]:
        session = self._get(session_id)
        if session.page.is_closed() or not session.browser.is_connected():
            session.status = "expirada"
        title = ""
        if session.status != "expirada":
            try:
                title = await session.page.title()
            except Exception:
                session.status = "expirada"
        return {
            "id": session.id,
            "status": session.status,
            "created_at": session.created_at,
            "tracking_id": session.tracking_id,
            "browser_mode": session.browser_mode,
            "live_url": session.live_url,
            "public_devtools_host": (
                public_devtools_host(session.live_url) if session.browser_mode == "browserless" else ""
            ),
            "page_url": _safe_page_url(session.page.url),
            "page_title": title,
            "recording": session.recording,
            "steps_count": len(session.steps),
            "learning_events_count": len(session.learning_events),
            "external_system_name": session.external_system_name,
            "external_login_url": session.external_login_url,
            "using_external_system": bool(session.external_login_url),
            "auth_validation_mode": (
                "selector"
                if session.auth_success_selector
                else "text"
                if session.auth_success_text
                else "manual_confirmation"
                if session.external_login_url
                else "demo_target_markers"
            ),
            "storage_state_saved": session.storage_state_path.is_file(),
            "manual_confirmed": session.manual_login_confirmed,
        }

    async def operator_diagnostics(self, session_id: str) -> dict[str, Any]:
        """Diagnostico seguro do target usado pela janela remota e pelo modo operador."""

        session = self._get(session_id)
        live_pages = [page for page in session.context.pages if not page.is_closed()]
        return {
            "session_id": session.id,
            "browser_mode": session.browser_mode,
            "target_id": session.target_id,
            "page_id": session.target_id,
            "current_url": _safe_page_url(session.page.url),
            "pages_count": len(live_pages),
            "steps_count": len(session.steps),
            "learning_events_count": len(session.learning_events),
            "live_url": session.live_url,
            "live_url_kind": _live_url_kind(session.live_url),
            "public_devtools_host": (
                public_devtools_host(session.live_url) if session.browser_mode == "browserless" else ""
            ),
            "browserless_public_url_set": bool(os.getenv("COTASYNC_BROWSERLESS_PUBLIC_URL", "").strip()),
        }

    def _prepare_operator_utility(self, session: DemoBrowserSession, duration: float = 2.0) -> None:
        session.operator_recording_suppressed_until = max(
            session.operator_recording_suppressed_until,
            time.monotonic() + duration,
        )

    def _validate_operator_session(self, session: DemoBrowserSession) -> None:
        if session.status == "expirada" or session.page.is_closed() or not session.browser.is_connected():
            raise DemoSessionError("A sessão do navegador não está disponível.")

    async def _operator_locator(
        self,
        session: DemoBrowserSession,
        selector: str,
        *,
        record_action: bool,
    ) -> Locator:
        self._validate_operator_session(session)
        if record_action and (not session.recording or session.status != "gravando"):
            raise DemoSessionError("Inicie a gravação antes de capturar ações do Modo operador.")
        safe_selector = str(selector or "").strip()
        if (
            not safe_selector
            or len(safe_selector) > 500
            or (record_action and _is_sensitive_selector(safe_selector))
        ):
            raise DemoSessionError("Seletor inválido ou protegido para o Modo operador.")
        try:
            locator = session.page.locator(safe_selector)
            await locator.first.wait_for(state="visible", timeout=_REPLAY_STEP_TIMEOUT_MS)
            count = await locator.count()
            if count == 1:
                visible = True
                enabled = await locator.first.is_enabled()
            else:
                visible = False
                enabled = False
        except Exception as exc:
            raise DemoSessionError("Seletor inválido para a página ativa.") from exc
        if count != 1:
            raise DemoSessionError(f"O seletor deve identificar exatamente um elemento; encontrados: {count}.")
        locator = locator.first
        if not visible or not enabled:
            raise DemoSessionError("O elemento precisa estar visível e habilitado.")
        return locator

    async def operator_insert_active(self, session_id: str, value: str) -> dict[str, Any]:
        session = self._get(session_id)
        self._validate_operator_session(session)
        safe_value = str(value or "")
        if len(safe_value) > 20_000:
            raise DemoSessionError("O texto excede o limite do Modo operador.")
        self._prepare_operator_utility(session)
        try:
            editable = await session.page.evaluate(
                """() => {
                    const el = document.activeElement;
                    if (!el) return false;
                    const tag = String(el.tagName || '').toLowerCase();
                    return tag === 'input' || tag === 'textarea' || el.isContentEditable;
                }"""
            )
            if not editable:
                raise DemoSessionError("Foque um campo editável no navegador remoto antes de inserir.")
            try:
                await session.page.keyboard.insert_text(safe_value)
            except Exception:
                await session.page.evaluate(
                    """text => {
                        const el = document.activeElement;
                        if (!el) throw new Error('active element unavailable');
                        const tag = String(el.tagName || '').toLowerCase();
                        if (tag === 'input' || tag === 'textarea') {
                            const prototype = tag === 'input'
                                ? HTMLInputElement.prototype
                                : HTMLTextAreaElement.prototype;
                            const setter = Object.getOwnPropertyDescriptor(prototype, 'value').set;
                            setter.call(el, text);
                        } else if (el.isContentEditable) {
                            el.textContent = text;
                        } else {
                            throw new Error('active element is not editable');
                        }
                        el.dispatchEvent(new Event('input', {bubbles: true}));
                        el.dispatchEvent(new Event('change', {bubbles: true}));
                    }""",
                    safe_value,
                )
            await asyncio.sleep(0.4)
        except DemoSessionError:
            raise
        except Exception as exc:
            raise DemoSessionError("Não foi possível inserir texto no campo ativo.") from exc
        logger.info("Modo operador inseriu texto no campo ativo: session=%s", session.id)
        return {
            "session_id": session.id,
            "operation": "insert_active_text",
            "recorded": False,
        }

    async def operator_fill(
        self,
        session_id: str,
        selector: str,
        value: str,
        *,
        record_action: bool = True,
    ) -> dict[str, Any]:
        session = self._get(session_id)
        safe_value = str(value or "")
        if len(safe_value) > 20_000:
            raise DemoSessionError("O texto excede o limite do Modo operador.")
        locator = await self._operator_locator(session, selector, record_action=record_action)
        if not record_action:
            self._prepare_operator_utility(session)
        try:
            await locator.fill(safe_value, timeout=_REPLAY_STEP_TIMEOUT_MS)
            await locator.evaluate(
                "element => element.dispatchEvent(new Event('change', {bubbles: true}))"
            )
            await asyncio.sleep(0.4)
        except Exception as exc:
            raise DemoSessionError("Não foi possível preencher o campo na página ativa.") from exc
        logger.info(
            "Modo operador preencheu elemento: session=%s recorded=%s",
            session.id,
            record_action,
        )
        return {
            "session_id": session.id,
            "operation": "fill",
            "recording": session.recording,
            "recorded": bool(record_action and session.recording),
        }

    async def operator_click(
        self,
        session_id: str,
        selector: str,
        *,
        record_action: bool = True,
    ) -> dict[str, Any]:
        session = self._get(session_id)
        locator = await self._operator_locator(session, selector, record_action=record_action)
        if not record_action:
            self._prepare_operator_utility(session, duration=2.5)
        try:
            await locator.click(timeout=_REPLAY_STEP_TIMEOUT_MS)
            await asyncio.sleep(1.1)
        except Exception as exc:
            raise DemoSessionError("Não foi possível clicar no elemento da página ativa.") from exc
        logger.info("Modo operador clicou em elemento: session=%s recorded=%s", session.id, record_action)
        return {
            "session_id": session.id,
            "operation": "click",
            "recording": session.recording,
            "recorded": bool(record_action and session.recording),
        }

    async def confirm_login(self, session_id: str) -> dict[str, Any]:
        session = self._get(session_id)
        if session.external_login_url and not (session.auth_success_selector or session.auth_success_text):
            session.manual_login_confirmed = True
        expected_url = session.external_login_url or _demo_target_url()
        page = await self._find_authenticated_live_page(session, _safe_page_url(expected_url))
        if page is None:
            session.manual_login_confirmed = False
            raise DemoSessionError("O login ainda nao foi concluido na pagina aberta.")
        await self._set_active_page(session, page)
        session.status = "autenticada"
        await self._save_storage_state(session, required=True)
        logger.info("Login manual confirmado para a sessao %s", session_id)
        return await self.status(session_id)

    async def start_recording(self, session_id: str) -> dict[str, Any]:
        session = self._get(session_id)
        if session.status != "autenticada":
            raise DemoSessionError("Confirme o login manual antes de iniciar o aprendizado.")
        session.steps = []
        session.learning_events = []
        for task in list(session.observer_tasks):
            task.cancel()
        session.observer_tasks.clear()
        session.operator_recording_suppressed_until = 0.0
        session.recording = True
        session.status = "gravando"
        await session.page.evaluate(_RECORDER_SCRIPT)
        baseline_path = session.storage_state_path.parent / "learning" / "recording_before.png"
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            await session.page.screenshot(path=str(baseline_path), full_page=False)
            session.last_screenshot_path = str(baseline_path.relative_to(_ROOT))
        except Exception:
            session.last_screenshot_path = ""
        session.last_page_count = len([page for page in session.context.pages if not page.is_closed()])
        session.download_detected = False
        logger.info("Gravacao iniciada na sessao %s", session_id)
        return await self.status(session_id)

    async def stop_recording(self, session_id: str) -> dict[str, Any]:
        session = self._get(session_id)
        if not session.recording:
            raise DemoSessionError("Nao existe gravacao ativa nesta sessao.")
        await asyncio.sleep(0.7)
        outputs = await session.page.evaluate(
            """() => Array.from(document.querySelectorAll('[data-cotasync-output]'))
              .map((el) => ({
                tipo: 'extrair_texto',
                seletor: window.__cotasyncSelectorFor ? window.__cotasyncSelectorFor(el) : '',
                valor: '',
                nome: el.getAttribute('data-cotasync-output') || 'resultado',
                texto: String(el.innerText || el.value || '').trim()
              }))
              .filter((item) => item.seletor && item.texto)"""
        )
        if isinstance(outputs, list):
            for output in outputs:
                if not isinstance(output, dict):
                    continue
                selector = str(output.get("seletor") or "")
                if any(
                    step.get("tipo") == "extrair_texto" and step.get("seletor") == selector
                    for step in session.steps
                ):
                    continue
                await self._record_live_step(session, output)
        session.recording = False
        session.status = "autenticada"
        if not session.steps:
            raise DemoSessionError("Nenhum passo foi capturado. Repita a rotina com a gravacao ativa.")
        logger.info("Gravacao finalizada na sessao %s com %s passos", session_id, len(session.steps))
        return {
            "session": await self.status(session_id),
            "steps": [dict(step, index=index) for index, step in enumerate(session.steps)],
            "learning_events": [dict(event) for event in session.learning_events],
        }

    async def save_action(
        self,
        session_id: str,
        name: str,
        description: str,
        variable_names: dict[str, str],
    ) -> dict[str, Any]:
        session = self._get(session_id)
        action_name = str(name or "").strip()
        if not action_name:
            raise DemoSessionError("Informe um nome para a acao aprendida.")
        if not session.steps:
            raise DemoSessionError("Nao existem passos capturados para salvar.")

        steps = [dict(step) for step in session.steps]
        learning_events = [dict(event) for event in session.learning_events]
        variables: list[str] = []
        for index_raw, variable_raw in variable_names.items():
            try:
                index = int(index_raw)
            except (TypeError, ValueError):
                continue
            variable = re.sub(r"[^a-zA-Z0-9_]+", "_", str(variable_raw or "").strip()).strip("_")
            if not variable or index < 0 or index >= len(steps) or steps[index].get("tipo") != "preencher":
                continue
            steps[index]["variavel"] = variable
            steps[index]["valor"] = ""
            for event in learning_events:
                if event.get("step_index") == index and event.get("event_type") == "fill":
                    event["variable_key"] = variable
                    event["value_template"] = f"{{{{{variable}}}}}"
            if variable not in variables:
                variables.append(variable)

        robust_steps: list[dict[str, Any]] = []
        for index, step in enumerate(steps):
            event = next(
                (item for item in reversed(learning_events) if item.get("step_index") == index),
                {},
            )
            robust_step = dict(step)
            robust_step.update(
                {
                    "elapsed_ms": max(0, int(event.get("elapsed_ms") or 0)),
                    "wait_hint": str(event.get("wait_hint") or "Aguardar seletor visível e habilitado."),
                    "replay_hint": str(event.get("replay_hint") or "Revalidar página ativa."),
                    "expected_url_before": str(event.get("url_before") or ""),
                    "expected_url_after": str(event.get("url_after") or ""),
                    "opened_new_page": bool(event.get("opened_new_page")),
                    "download_detected": bool(event.get("download_detected")),
                    "expected_selector_after": str(
                        steps[index + 1].get("seletor") if index + 1 < len(steps) else ""
                    ),
                }
            )
            robust_steps.append(robust_step)

        learned_action: dict[str, Any] = {
            "nome_amigavel": action_name,
            "descricao": str(description or "Rotina aprendida por demonstracao manual.").strip(),
            "url_inicial": _safe_page_url(session.page.url),
            "passos_playwright": steps,
            "robust_steps": robust_steps,
            "learning_events": learning_events,
            "variaveis_necessarias": variables,
            "modo_aprendizado": "gravacao_manual_observada_por_ia_em_tempo_real",
            "learning_mode": (
                "desktop_browser_live_ai_observed"
                if session.browser_mode == "desktop_browser"
                else "human_demo_live_ai_observed"
            ),
            "browser_mode": session.browser_mode,
            "external_system_name": session.external_system_name,
            "external_login_url": session.external_login_url,
        }
        from backend.services.ai_observer import analyze_recorded_action_with_ai

        ai_review = await analyze_recorded_action_with_ai(learned_action)
        learned_action.update(ai_review)
        learned_action["wait_strategies"] = learned_action.get("waits", [])
        learned_action["risks_detected"] = learned_action.get("ai_risk_notes", [])
        learned_action["slow_system_notes"] = learned_action.get("ai_slow_system_notes", [])
        learned_action["new_tab_or_popup_notes"] = [
            str(event.get("ai_note") or event.get("replay_hint") or "")
            for event in learning_events
            if event.get("opened_new_page") or event.get("event_type") in {"popup", "new_tab"}
        ] or ["Nenhuma nova aba ou popup foi detectado durante esta demonstração."]

        payload = _load_ui_map()
        payload["acoes_conhecidas"][action_name] = learned_action
        screenshot_path = _DATA_DIR / f"mapeamento_{_safe_file_name(action_name)}.png"
        await session.page.screenshot(path=str(screenshot_path), full_page=False)
        _save_ui_map(payload)

        from backend.services.actions_repository import slugify_action_id

        logger.info("Acao aprendida salva: %s", action_name)
        return {
            "id": slugify_action_id(action_name),
            "key": action_name,
            "name": action_name,
            "steps_count": len(steps),
            "variables": variables,
            "evidence": str(screenshot_path.relative_to(_ROOT)),
            "learning_mode": learned_action["learning_mode"],
            "ai_reviewed": bool(learned_action.get("ai_reviewed")),
            "ai_observer_summary": str(learned_action.get("ai_observer_summary") or ""),
            "replay_hints": learned_action.get("replay_hints", []),
            "waits": learned_action.get("waits", []),
            "wait_strategies": learned_action.get("wait_strategies", []),
            "variable_schema": learned_action.get("variable_schema", []),
            "extraction_target": str(learned_action.get("extraction_target") or ""),
            "robust_steps_count": len(robust_steps),
            "learning_events_count": len(learning_events),
            "external_system_name": learned_action["external_system_name"],
            "external_login_url": learned_action["external_login_url"],
        }

    async def execute_action(
        self,
        session_id: str,
        action_key: str,
        variables: dict[str, Any],
        run_id: str,
    ) -> dict[str, Any]:
        session = self._get(session_id)
        if session.recording:
            raise DemoSessionError("Pare a gravacao antes de executar a rotina aprendida.")

        payload = _load_ui_map()
        action = payload["acoes_conhecidas"].get(action_key)
        if not isinstance(action, dict):
            raise DemoSessionError("Acao aprendida nao encontrada.")
        steps = action.get("robust_steps") or action.get("passos_playwright", [])
        if not isinstance(steps, list) or not steps:
            raise DemoSessionError("A acao aprendida nao possui passos executaveis.")

        action_external_url = str(action.get("external_login_url") or "").strip()
        if action_external_url != session.external_login_url:
            raise DemoSessionError("Selecione a sessao do sistema externo usada por esta acao.")

        expected_url = _expected_replay_url(action.get("url_inicial"))
        extracted: dict[str, str] = {}
        selector_diagnostics: list[dict[str, Any]] = []
        automatically_revalidated = False
        for step_index, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            step_type = str(step.get("tipo") or "").strip().lower()
            selector = str(step.get("seletor") or "").strip()
            try:
                step_expected_url = _expected_replay_url(step.get("expected_url_before") or expected_url)
                authenticated, revalidated = await self._revalidate_for_replay(session, step_expected_url)
                automatically_revalidated = automatically_revalidated or revalidated
                if not authenticated:
                    raise DemoSessionError("A sessao nao esta autenticada para executar a rotina.")
                page = session.page
                await page.wait_for_load_state("domcontentloaded", timeout=_REPLAY_STEP_TIMEOUT_MS)
                if not _page_matches_url(page, step_expected_url) or not await self._page_is_authenticated(session, page):
                    raise DemoSessionError("A pagina CDP da sessao nao esta pronta para o replay.")

                locator: Locator | None = None
                state: dict[str, Any] | None = None
                if selector:
                    locator, state = await self._wait_actionable_locator(page, selector)
                    state.update({"step_index": step_index, "step_type": step_type})
                    selector_diagnostics.append(state)

                if step_type == "preencher":
                    variable = str(step.get("variavel") or "").strip()
                    value = variables.get(variable) if variable else step.get("valor", "")
                    if variable and (value is None or str(value) == ""):
                        raise DemoSessionError(f"Valor obrigatorio ausente: {variable}.")
                    assert locator is not None
                    await locator.fill(str(value), timeout=_REPLAY_STEP_TIMEOUT_MS)
                elif step_type == "clicar":
                    assert locator is not None and state is not None
                    pages_before = {id(item) for item in session.context.pages if not item.is_closed()}
                    await locator.scroll_into_view_if_needed(timeout=_REPLAY_STEP_TIMEOUT_MS)
                    click_marker = f"__cotasyncReplayClick_{run_id.replace('-', '')}_{step_index}"
                    await locator.evaluate(
                        """(element, marker) => {
                          delete window[marker];
                          element.addEventListener('click', () => { window[marker] = true; }, {
                            capture: true,
                            once: true
                          });
                        }""",
                        click_marker,
                    )
                    try:
                        await locator.click(timeout=_REPLAY_STEP_TIMEOUT_MS)
                        state["click_confirmation"] = "cdp"
                    except PlaywrightTimeoutError:
                        click_observed = bool(await page.evaluate("marker => window[marker] === true", click_marker))
                        state["click_event_observed"] = click_observed
                        if not click_observed:
                            raise
                        state["click_confirmation"] = "dom_event_after_cdp_timeout"
                        logger.warning(
                            "Clique da sessao %s no seletor %s ocorreu no DOM sem confirmacao CDP",
                            session.id,
                            selector,
                        )
                    finally:
                        try:
                            await page.evaluate("marker => { delete window[marker]; }", click_marker)
                        except Exception:
                            pass
                    recorded_wait_ms = min(max(int(step.get("elapsed_ms") or 0), 500), 5000)
                    await page.wait_for_timeout(recorded_wait_ms)
                    new_pages = [
                        item
                        for item in session.context.pages
                        if not item.is_closed() and id(item) not in pages_before
                    ]
                    if new_pages:
                        page = new_pages[-1]
                        await page.wait_for_load_state("domcontentloaded", timeout=_REPLAY_STEP_TIMEOUT_MS)
                        await self._set_active_page(session, page)
                        state["new_page_detected"] = True
                    expected_after = str(step.get("expected_url_after") or "").strip()
                    if expected_after and _safe_page_url(page.url) != _safe_page_url(expected_after):
                        await page.wait_for_url(_safe_page_url(expected_after), timeout=_REPLAY_STEP_TIMEOUT_MS)
                    expected_selector = str(step.get("expected_selector_after") or "").strip()
                    if expected_selector:
                        await page.locator(expected_selector).first.wait_for(
                            state="visible",
                            timeout=_REPLAY_STEP_TIMEOUT_MS,
                        )
                    state["recorded_wait_ms"] = recorded_wait_ms
                    state["wait_hint"] = str(step.get("wait_hint") or "")
                    state["replay_hint"] = str(step.get("replay_hint") or "")
                elif step_type == "teclar":
                    await page.keyboard.press(str(step.get("valor") or "Enter"))
                    await page.wait_for_timeout(300)
                elif step_type == "extrair_texto":
                    assert locator is not None
                    text = await locator.inner_text(timeout=_REPLAY_STEP_TIMEOUT_MS)
                    extracted[str(step.get("nome") or selector)] = text.strip()
            except DemoSessionError:
                raise
            except Exception as exc:
                diagnostics = await self._capture_step_diagnostics(
                    session,
                    run_id,
                    step_index,
                    step_type,
                    selector,
                    exc,
                )
                raise DemoReplayStepError(
                    f"Falha ao executar o passo '{step_type}'. Consulte o diagnostico da run.",
                    diagnostics,
                ) from exc

        evidence_path = _DATA_DIR / "runs" / f"{run_id}.png"
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        await session.page.screenshot(path=str(evidence_path), full_page=False)
        logger.info("Replay concluido na sessao %s, run %s", session_id, run_id)
        return {
            "texto": "Execucao assistida concluida com sucesso.",
            "evidencia": str(evidence_path.relative_to(_ROOT)),
            "dados_extraidos": extracted,
            "passos_executados": len(steps),
            "session_revalidated": automatically_revalidated,
            "selector_diagnostics": selector_diagnostics,
        }

    async def _wait_actionable_locator(self, page: Page, selector: str) -> tuple[Locator, dict[str, Any]]:
        locator = page.locator(selector).first
        await locator.wait_for(state="visible", timeout=_REPLAY_STEP_TIMEOUT_MS)
        deadline = asyncio.get_running_loop().time() + (_REPLAY_STEP_TIMEOUT_MS / 1000)
        while not await locator.is_enabled():
            if asyncio.get_running_loop().time() >= deadline:
                raise PlaywrightTimeoutError(f"Seletor nao ficou habilitado: {selector}")
            await page.wait_for_timeout(100)
        return locator, await self._selector_state(page, selector)

    async def _selector_state(self, page: Page, selector: str) -> dict[str, Any]:
        locator = page.locator(selector)
        count = await locator.count()
        first = locator.first
        visible = await first.is_visible() if count else False
        enabled = await first.is_enabled() if count else False
        return {
            "current_url": _safe_page_url(page.url),
            "selector": selector,
            "count": count,
            "visible": visible,
            "enabled": enabled,
        }

    async def _capture_step_diagnostics(
        self,
        session: DemoBrowserSession,
        run_id: str,
        step_index: int,
        step_type: str,
        selector: str,
        exc: Exception,
    ) -> dict[str, Any]:
        page = session.page
        diagnostics: dict[str, Any] = {
            "step_index": step_index,
            "step_type": step_type,
            "selector": selector,
            "current_url": _safe_page_url(page.url),
            "page_title": "",
            "count": 0,
            "visible": False,
            "enabled": False,
            "screenshot_path": "",
            "safe_dom_summary": {},
            "error_type": type(exc).__name__,
        }
        try:
            diagnostics["page_title"] = (await page.title())[:200]
        except Exception:
            pass
        try:
            diagnostics.update(await self._selector_state(page, selector))
        except Exception:
            pass
        evidence_path = _DATA_DIR / "runs" / f"{run_id}_step_{step_index}_{_safe_file_name(step_type)}_error.png"
        try:
            evidence_path.parent.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(evidence_path), full_page=False, timeout=_REPLAY_STEP_TIMEOUT_MS)
            diagnostics["screenshot_path"] = str(evidence_path.relative_to(_ROOT))
        except Exception:
            pass
        try:
            diagnostics["safe_dom_summary"] = await page.evaluate(
                """() => ({
                  ready_state: document.readyState,
                  body: {
                    authenticated: document.body?.dataset?.cotasyncAuthenticated === 'true',
                    element_count: document.body?.querySelectorAll('*').length || 0
                  },
                  interactive_elements: Array.from(document.querySelectorAll(
                    'button, input, select, textarea, a, [role="button"], [data-cotasync-output]'
                  )).slice(0, 30).map((element) => ({
                    tag: element.tagName.toLowerCase(),
                    id: String(element.id || '').slice(0, 100),
                    type: String(element.getAttribute('type') || '').slice(0, 40),
                    role: String(element.getAttribute('role') || '').slice(0, 40),
                    disabled: Boolean(element.disabled || element.getAttribute('aria-disabled') === 'true')
                  }))
                })"""
            )
        except Exception:
            pass
        logger.error("Diagnostico seguro de replay: %s", json.dumps(diagnostics, ensure_ascii=False))
        return diagnostics

    async def close(self, session_id: str) -> None:
        session = self._sessions.pop(str(session_id), None)
        if session is None:
            return
        session.status = "encerrada"
        for task in list(session.observer_tasks):
            task.cancel()
        session.observer_tasks.clear()
        try:
            provider = browser_provider(session.browser_mode)
            if provider.close_browser_on_session_end:
                await session.browser.close()
        finally:
            await session.playwright.stop()
            if not session.external_login_url:
                shutil.rmtree(session.storage_state_path.parent, ignore_errors=True)
        logger.info("Sessao assistida encerrada: %s", session_id)

    async def close_all(self) -> None:
        for session_id in list(self._sessions):
            try:
                await self.close(session_id)
            except Exception:
                logger.exception("Falha ao encerrar sessao assistida %s", session_id)


demo_session_manager = DemoSessionManager()
