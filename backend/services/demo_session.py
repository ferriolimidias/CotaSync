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
from backend.services.action_pages import (
    ActionPageError,
    select_desktop_page_for_action,
    validate_action_page_url,
)
from backend.services.browser_providers import (
    BrowserMode,
    BrowserProviderError,
    browser_provider,
    configured_browser_mode,
    desktop_profile_dir,
)
from backend.services.runtime_files import runtime_download_path, runtime_file_metadata


logger = logging.getLogger("cotasync.demo")
_ROOT = Path(__file__).resolve().parents[2]
_DATA_DIR = _ROOT / "data"
_UI_MAP_PATH = _DATA_DIR / "ui_map.json"
_DEMO_SESSIONS_DIR = _DATA_DIR / "demo_sessions"
_MAX_RECORDED_STEPS = 200


def _env_seconds(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


_REPLAY_STEP_TIMEOUT_MS = _env_seconds("COTASYNC_STEP_TIMEOUT_SECONDS", 30) * 1000
_REPLAY_ACTION_TIMEOUT_MS = _env_seconds("COTASYNC_ACTION_TIMEOUT_SECONDS", 180) * 1000
_REPLAY_NAVIGATION_TIMEOUT_MS = _env_seconds("COTASYNC_NAVIGATION_TIMEOUT_SECONDS", 45) * 1000
_REPLAY_FALLBACK_DELAY_MS = 1200
_MANUAL_CONFIRMATION_BLOCK_TEXTS = (
    "acesso bloqueado",
    "access blocked",
    "access denied",
    "acesso negado",
    "site can't be reached",
    "não é possível acessar esse site",
    "nao e possivel acessar esse site",
)


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


def _safe_url_host(url: str) -> str:
    try:
        return urlsplit(str(url or "")).hostname or ""
    except Exception:
        return ""


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


def _title_label(value: str) -> str:
    text = re.sub(r"[_\-]+", " ", str(value or "")).strip()
    if not text:
        return "Campo"
    return " ".join(part.capitalize() for part in text.split())


def _suggest_variable_key(selector: str, index: int = 0) -> str:
    raw = str(selector or "")
    lowered = raw.casefold()
    direct = (
        ("edtgrupo", "grupo"),
        ("grupo", "grupo"),
        ("edtcota", "cota"),
        ("cota", "cota"),
        ("cpf", "cpf"),
        ("cliente", "cliente"),
        ("data_base", "data_base"),
        ("data base", "data_base"),
    )
    for needle, key in direct:
        if needle in lowered:
            return key
    if "select" in lowered:
        return "tipo_consulta" if index <= 1 else f"select_{index + 1}"
    tokens = [
        token.lower()
        for token in re.findall(r"[A-Za-zÀ-ÿ0-9]+", raw)
        if token.lower() not in {"input", "textarea", "select", "name", "nth", "of", "type", "ctl00", "conteudo"}
    ]
    cleaned = "_".join(tokens[-2:]).strip("_")
    return cleaned or f"campo_{index + 1}"


def _normalize_variable_key(value: Any, fallback_selector: str = "", index: int = 0) -> str:
    candidate = re.sub(r"[^a-zA-Z0-9_]+", "_", str(value or "").strip()).strip("_").lower()
    if candidate.startswith("conteudo_edtgrupo") or candidate == "edtgrupo":
        return "grupo"
    if candidate.startswith("conteudo_edtcota") or candidate == "edtcota":
        return "cota"
    if candidate in {"select", "select_1"}:
        return "tipo_consulta"
    return candidate or _suggest_variable_key(fallback_selector, index)


def _objective_extraction_keywords(objective: str) -> list[str]:
    lowered = str(objective or "").casefold()
    keywords = ["valor", "parcela", "valor da parcela", "parcela atual", "vencimento", "número de parcelas", "numero de parcelas", "status"]
    if "parcela" in lowered or "valor" in lowered:
        return keywords
    return ["resultado", "status", "valor", "vencimento"]


def _target_label(step: dict[str, Any], step_type: str, selector: str) -> str:
    if step.get("nome"):
        return _title_label(str(step.get("nome")))
    if step.get("variavel"):
        return _title_label(str(step.get("variavel")))
    if step_type == "download_pdf":
        return "Download"
    if selector:
        return "Elemento da rotina"
    return "Página"


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
    auth_validation_mode: str = ""
    auth_success_text: str = ""
    auth_success_selector: str = ""
    storage_state_path: Path = field(default_factory=Path)
    profile_reference: str = ""
    confirmed_page_url: str = ""
    confirmed_page_title: str = ""
    manual_login_confirmed: bool = False
    status: str = "aguardando_login"
    recording: bool = False
    steps: list[dict[str, str]] = field(default_factory=list)
    learning_events: list[dict[str, Any]] = field(default_factory=list)
    observer_tasks: set[asyncio.Task[Any]] = field(default_factory=set)
    last_screenshot_path: str = ""
    last_page_count: int = 0
    download_detected: bool = False
    guided_learning: dict[str, Any] = field(default_factory=dict)
    output_candidates: list[dict[str, str]] = field(default_factory=list)
    learning_synthesis: dict[str, Any] = field(default_factory=dict)
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
                {
                    "previous_events": len(session.learning_events) - 1,
                    "guided_instruction": session.guided_learning,
                },
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
                if session.auth_validation_mode == "manual_confirmation":
                    return (
                        session.manual_login_confirmed
                        and await self._page_is_valid_for_manual_confirmation(session, page)
                    )
                if session.auth_validation_mode == "selector" and session.auth_success_selector:
                    locator = page.locator(session.auth_success_selector)
                    return await locator.count() > 0 and await locator.first.is_visible()
                if session.auth_validation_mode == "text" and session.auth_success_text:
                    body_text = await page.locator("body").inner_text(timeout=_REPLAY_STEP_TIMEOUT_MS)
                    return session.auth_success_text in body_text
                return False
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

    async def _page_is_valid_for_manual_confirmation(
        self,
        session: DemoBrowserSession,
        page: Page,
    ) -> bool:
        """Aceita a confirmacao humana somente para uma pagina web carregada e utilizavel."""

        if page.is_closed():
            return False
        current_url = str(page.url or "").strip()
        parsed = urlsplit(current_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False

        title = (await page.title()).strip()
        url_changed = _safe_page_url(current_url) != _safe_page_url(session.external_login_url)
        if not title and not url_changed:
            return False

        try:
            body_text = await page.locator("body").inner_text(timeout=_REPLAY_STEP_TIMEOUT_MS)
        except Exception:
            body_text = ""
        normalized_body = body_text.casefold()
        return not any(block_text in normalized_body for block_text in _MANUAL_CONFIRMATION_BLOCK_TEXTS)

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
            if session.external_login_url:
                url_matches = True
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
                auth_validation_mode=str(external_config.get("validation") or "").strip(),
                auth_success_text=str(external_config.get("auth_success_text") or "").strip(),
                auth_success_selector=str(external_config.get("auth_success_selector") or "").strip(),
                storage_state_path=storage_state_path,
                profile_reference=desktop_profile_dir() if selected_mode == "desktop_browser" else "",
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
            "auth_validation_mode": session.auth_validation_mode or "demo_target_markers",
            "storage_state_saved": session.storage_state_path.is_file(),
            "profile_reference": session.profile_reference,
            "manual_confirmed": session.manual_login_confirmed,
            "confirmed_page_url": session.confirmed_page_url,
            "confirmed_page_title": session.confirmed_page_title,
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
        if session.external_login_url and session.auth_validation_mode == "manual_confirmation":
            session.manual_login_confirmed = True
        expected_url = session.external_login_url or _demo_target_url()
        page = await self._find_authenticated_live_page(session, _safe_page_url(expected_url))
        if page is None:
            session.manual_login_confirmed = False
            raise DemoSessionError("O login ainda nao foi concluido na pagina aberta.")
        await self._set_active_page(session, page)
        session.confirmed_page_url = _safe_page_url(page.url)
        try:
            session.confirmed_page_title = (await page.title()).strip()[:200]
        except Exception:
            session.confirmed_page_title = ""
        session.status = "autenticada"
        await self._save_storage_state(session, required=True)
        logger.info("Login manual confirmado para a sessao %s", session_id)
        return await self.status(session_id)

    async def start_recording(
        self,
        session_id: str,
        guided_learning: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session = self._get(session_id)
        if session.status != "autenticada":
            raise DemoSessionError("Confirme o login manual antes de iniciar o aprendizado.")
        session.steps = []
        session.learning_events = []
        for task in list(session.observer_tasks):
            task.cancel()
        session.observer_tasks.clear()
        session.operator_recording_suppressed_until = 0.0
        raw_instruction = guided_learning if isinstance(guided_learning, dict) else {}
        output_type = str(raw_instruction.get("output_type") or "apenas abrir tela").strip()
        if output_type not in {"texto/dados da tela", "arquivo/PDF", "ambos", "apenas abrir tela"}:
            raise DemoSessionError("Selecione um tipo de retorno esperado valido.")
        session.guided_learning = {
            "name": str(raw_instruction.get("name") or "").strip()[:200],
            "objective": str(raw_instruction.get("objective") or "").strip()[:1000],
            "input_description": str(raw_instruction.get("input_description") or "").strip()[:1000],
            "expected_result": str(raw_instruction.get("expected_result") or "").strip()[:1000],
            "success_criteria": str(raw_instruction.get("success_criteria") or "").strip()[:1000],
            "output_type": output_type,
            "ai_result_summary_enabled": bool(raw_instruction.get("ai_result_summary_enabled", False)),
            "ai_recovery_enabled": bool(raw_instruction.get("ai_recovery_enabled", False)),
        }
        session.output_candidates = []
        session.learning_synthesis = {}
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
        candidates = await session.page.evaluate(
            """() => Array.from(document.querySelectorAll(
              '[data-cotasync-output], output, [role="status"], [aria-live], .result, table, h1, h2, h3'
            )).filter((el) => {
              const style = getComputedStyle(el);
              const text = String(el.innerText || el.value || '').trim();
              return text && style.display !== 'none' && style.visibility !== 'hidden';
            }).slice(0, 20).map((el, index) => ({
              label: el.getAttribute('data-cotasync-output') || el.getAttribute('aria-label') ||
                String(el.id || '') || `resultado_${index + 1}`,
              selector: window.__cotasyncSelectorFor ? window.__cotasyncSelectorFor(el) : '',
              preview: String(el.innerText || el.value || '').trim().slice(0, 160)
            })).filter((item) => item.selector)"""
        )
        session.output_candidates = [
            {
                "label": str(item.get("label") or "resultado")[:100],
                "selector": str(item.get("selector") or "")[:500],
                "preview": str(item.get("preview") or "")[:160],
            }
            for item in candidates
            if isinstance(item, dict) and str(item.get("selector") or "").strip()
        ] if isinstance(candidates, list) else []
        objective_keywords = _objective_extraction_keywords(str(session.guided_learning.get("objective") or ""))
        focused: list[dict[str, str]] = []
        for item in session.output_candidates:
            haystack = f"{item.get('label', '')} {item.get('preview', '')}".casefold()
            if any(keyword.casefold() in haystack for keyword in objective_keywords):
                focused.append({**item, "objective_match": "true"})
        if focused:
            focused_selectors = {item.get("selector") for item in focused}
            session.output_candidates = focused + [
                item for item in session.output_candidates if item.get("selector") not in focused_selectors
            ]
        session.recording = False
        session.status = "autenticada"
        if not session.steps:
            raise DemoSessionError("Nenhum passo foi capturado. Repita a rotina com a gravacao ativa.")
        if session.observer_tasks:
            await asyncio.gather(*list(session.observer_tasks), return_exceptions=True)
        from backend.services.ai_observer import analyze_recorded_action_with_ai

        provisional_action = {
            "nome_amigavel": session.guided_learning.get("name", ""),
            **session.guided_learning,
            "passos_playwright": session.steps,
            "learning_events": session.learning_events,
            "output_candidates": session.output_candidates,
        }
        session.learning_synthesis = await analyze_recorded_action_with_ai(provisional_action)
        logger.info("Gravacao finalizada na sessao %s com %s passos", session_id, len(session.steps))
        return {
            "session": await self.status(session_id),
            "steps": [dict(step, index=index) for index, step in enumerate(session.steps)],
            "learning_events": [dict(event) for event in session.learning_events],
            "guided_learning": dict(session.guided_learning),
            "output_candidates": list(session.output_candidates),
            "download_detected": bool(
                session.download_detected
                or any(event.get("download_detected") for event in session.learning_events)
            ),
            "ai_synthesis": dict(session.learning_synthesis),
        }

    async def save_action(
        self,
        session_id: str,
        name: str,
        description: str,
        variable_names: dict[str, str],
        *,
        objective: str = "",
        input_description: str = "",
        expected_result: str = "",
        success_criteria: str = "",
        output_type: str = "",
        user_result_summary_template: str | None = None,
        ai_result_summary_enabled: bool = False,
        ai_recovery_enabled: bool = False,
        extraction_targets: list[dict[str, str]] | None = None,
        extract_visible_text: bool = False,
        return_downloaded_file: bool = False,
    ) -> dict[str, Any]:
        session = self._get(session_id)
        action_name = str(name or "").strip()
        if not action_name:
            raise DemoSessionError("Informe um nome para a acao aprendida.")
        if not session.steps:
            raise DemoSessionError("Nao existem passos capturados para salvar.")

        steps = [dict(step) for step in session.steps]
        learning_events = [dict(event) for event in session.learning_events]
        variable_schema: list[dict[str, Any]] = []
        variables: list[dict[str, Any]] = []
        for index_raw, variable_raw in variable_names.items():
            try:
                index = int(index_raw)
            except (TypeError, ValueError):
                continue
            selector = str(steps[index].get("seletor") or "") if 0 <= index < len(steps) else ""
            variable = _normalize_variable_key(variable_raw, selector, index)
            if not variable or index < 0 or index >= len(steps) or steps[index].get("tipo") != "preencher":
                continue
            steps[index]["variavel"] = variable
            steps[index]["valor"] = ""
            for event in learning_events:
                if event.get("step_index") == index and event.get("event_type") == "fill":
                    event["variable_key"] = variable
                    event["value_template"] = f"{{{{{variable}}}}}"
            if not any(item.get("key") == variable for item in variable_schema):
                variable_schema.append(
                    {
                        "key": variable,
                        "label": _title_label(variable),
                        "required": True,
                        "source_step_index": index,
                    }
                )
                variables.append({"key": variable, "label": _title_label(variable), "required": True})

        requested_extractions = extraction_targets if isinstance(extraction_targets, list) else []
        if requested_extractions or extract_visible_text:
            steps = [step for step in steps if str(step.get("tipo") or "") != "extrair_texto"]
            for index, raw_target in enumerate(requested_extractions):
                if not isinstance(raw_target, dict):
                    continue
                selector = str(raw_target.get("selector") or raw_target.get("seletor") or "").strip()
                label = re.sub(
                    r"[^a-zA-Z0-9_]+",
                    "_",
                    str(raw_target.get("label") or raw_target.get("name") or f"resultado_{index + 1}").strip(),
                ).strip("_")
                if selector and label and not _is_sensitive_selector(selector):
                    steps.append({"tipo": "extrair_texto", "seletor": selector, "valor": "", "nome": label})
            if extract_visible_text:
                steps.append(
                    {
                        "tipo": "extrair_texto",
                        "seletor": "body",
                        "valor": "",
                        "nome": "texto_tela_final",
                    }
                )

        download_detected = bool(
            session.download_detected
            or any(event.get("download_detected") for event in learning_events)
        )
        if return_downloaded_file:
            detected_indexes = [
                int(event.get("step_index"))
                for event in learning_events
                if event.get("download_detected") and str(event.get("step_index", "")).isdigit()
            ]
            click_indexes = [
                index for index, step in enumerate(steps) if str(step.get("tipo") or "") == "clicar"
            ]
            download_index = detected_indexes[-1] if detected_indexes else (click_indexes[-1] if click_indexes else -1)
            if download_index < 0 or download_index >= len(steps):
                raise DemoSessionError("Nao foi possivel associar o download a um clique gravado.")
            steps[download_index]["tipo"] = "download_pdf"

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

        extraction_targets = [
            str(step.get("nome") or "").strip()
            for step in steps
            if str(step.get("tipo") or "").strip().lower() == "extrair_texto"
            and str(step.get("nome") or "").strip()
        ]
        output_schema = {target: {"type": "string"} for target in extraction_targets}
        guided = session.guided_learning
        objective_text = str(objective or guided.get("objective") or "").strip()
        input_description_text = str(input_description or guided.get("input_description") or "").strip()
        expected_result_text = str(expected_result or guided.get("expected_result") or "").strip()
        success_criteria_text = str(success_criteria or guided.get("success_criteria") or "").strip()
        output_type_text = str(output_type or guided.get("output_type") or "apenas abrir tela").strip()
        if return_downloaded_file and output_type_text == "texto/dados da tela":
            output_type_text = "ambos"
        if return_downloaded_file and not extraction_targets and not extract_visible_text:
            output_type_text = "arquivo/PDF"
        if return_downloaded_file:
            output_schema["main_file"] = {"type": "file", "format": "pdf"}

        learned_action: dict[str, Any] = {
            "nome_amigavel": action_name,
            "descricao": str(description or "Rotina aprendida por demonstracao manual.").strip(),
            "url_inicial": _safe_page_url(session.page.url),
            "passos_playwright": steps,
            "robust_steps": robust_steps,
            "learning_events": learning_events,
            "variaveis_necessarias": variables,
            "objective": objective_text,
            "input_description": input_description_text,
            "expected_result": expected_result_text,
            "success_criteria": success_criteria_text,
            "output_type": output_type_text,
            "output_schema": output_schema,
            "extraction_targets": extraction_targets,
            "user_result_summary_template": str(user_result_summary_template or "").strip() or None,
            "ai_result_summary_enabled": bool(ai_result_summary_enabled),
            "ai_recovery_enabled": bool(ai_recovery_enabled),
            "download_expected": bool(return_downloaded_file),
            "download_detected_during_learning": download_detected,
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

        # A síntese final inclui nomes de variáveis e saídas editados após a
        # gravação; a pré-síntese de stop_recording continua disponível na UI.
        ai_review = await analyze_recorded_action_with_ai(learned_action)
        learned_action.update(ai_review)
        reviewed_variables = learned_action.get("variable_schema")
        if isinstance(reviewed_variables, list) and reviewed_variables:
            by_key = {str(item.get("key") or ""): item for item in reviewed_variables if isinstance(item, dict)}
            for item in variable_schema:
                reviewed = by_key.get(str(item.get("key") or ""))
                if isinstance(reviewed, dict):
                    item["label"] = str(reviewed.get("label") or item.get("label") or item.get("key")).strip()
        learned_action["variable_schema"] = variable_schema
        learned_action["variaveis_necessarias"] = variables
        if not learned_action["objective"]:
            learned_action["objective"] = str(
                learned_action.get("ai_observer_summary") or f"Executar a ação {action_name}"
            ).strip()
        if not learned_action["expected_result"]:
            learned_action["expected_result"] = (
                "Retornar " + ", ".join(extraction_targets)
                if extraction_targets
                else "Abrir a tela final da rotina"
            )
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
            "objective": learned_action["objective"],
            "input_description": learned_action["input_description"],
            "expected_result": learned_action["expected_result"],
            "success_criteria": learned_action["success_criteria"],
            "output_type": learned_action["output_type"],
            "output_schema": learned_action["output_schema"],
            "extraction_targets": learned_action["extraction_targets"],
            "user_result_summary_template": learned_action["user_result_summary_template"],
            "ai_result_summary_enabled": learned_action["ai_result_summary_enabled"],
            "ai_recovery_enabled": learned_action["ai_recovery_enabled"],
            "download_expected": learned_action["download_expected"],
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

        action_browser_mode = str(action.get("browser_mode") or "browserless").strip()
        if action_browser_mode != session.browser_mode:
            raise DemoSessionError("A acao deve ser executada no modo de navegador em que foi gravada.")

        action_external_url = str(action.get("external_login_url") or "").strip()
        if action_external_url != session.external_login_url:
            raise DemoSessionError("Selecione a sessao do sistema externo usada por esta acao.")

        if action_browser_mode == "desktop_browser":
            try:
                action_page = await select_desktop_page_for_action(action, session.context, session.page)
                await self._set_active_page(session, action_page)
            except ActionPageError as exc:
                raise DemoSessionError(str(exc)) from exc

        expected_url = _expected_replay_url(action.get("url_inicial"))
        extracted: dict[str, str] = {}
        downloaded_files: list[dict[str, object]] = []
        selector_diagnostics: list[dict[str, Any]] = []
        step_diagnostics: list[dict[str, Any]] = []
        automatically_revalidated = False
        action_deadline = time.monotonic() + (_REPLAY_ACTION_TIMEOUT_MS / 1000)
        for step_index, step in enumerate(steps):
            if time.monotonic() >= action_deadline:
                diagnostic = {
                    "step_index": step_index,
                    "action_type": "timeout",
                    "target_label": "Ação",
                    "wait_strategy": "action_timeout",
                    "waited_ms": _REPLAY_ACTION_TIMEOUT_MS,
                    "result": "timeout",
                    "condition": "COTASYNC_ACTION_TIMEOUT_SECONDS",
                }
                raise DemoReplayStepError(
                    "O sistema demorou para abrir a próxima tela dentro do tempo total da ação.",
                    {"step_diagnostics": [diagnostic], "retryable": True},
                )
            if not isinstance(step, dict):
                continue
            step_type = str(step.get("tipo") or "").strip().lower()
            selector = str(step.get("seletor") or "").strip()
            step_diag: dict[str, Any] | None = None
            try:
                step_expected_url = _expected_replay_url(step.get("expected_url_before") or expected_url)
                authenticated, revalidated = await self._revalidate_for_replay(session, step_expected_url)
                automatically_revalidated = automatically_revalidated or revalidated
                if not authenticated:
                    raise DemoSessionError("A sessao nao esta autenticada para executar a rotina.")
                page = session.page
                await page.wait_for_load_state("domcontentloaded", timeout=_REPLAY_STEP_TIMEOUT_MS)
                if action_browser_mode == "desktop_browser":
                    validate_action_page_url(action, page.url)
                if not _page_matches_url(page, step_expected_url) or not await self._page_is_authenticated(session, page):
                    raise DemoSessionError("A pagina CDP da sessao nao esta pronta para o replay.")

                locator: Locator | None = None
                state: dict[str, Any] | None = None
                step_diag = await self._base_step_diagnostic(
                    page,
                    step_index,
                    step_type,
                    _target_label(step, step_type, selector),
                    time.monotonic(),
                )
                if selector and step_type != "extrair_texto":
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
                    step_diagnostics.append(
                        await self._finish_step_diagnostic(
                            session.page,
                            step_diag,
                            wait_strategy="actionable_selector",
                            result="success",
                        )
                    )
                elif step_type == "clicar":
                    assert locator is not None and state is not None
                    page_task: asyncio.Task[Any] | None = asyncio.create_task(
                        session.context.wait_for_event("page", timeout=_REPLAY_STEP_TIMEOUT_MS)
                    )
                    download_task: asyncio.Task[Any] | None = asyncio.create_task(
                        page.wait_for_event("download", timeout=_REPLAY_STEP_TIMEOUT_MS)
                    )
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
                    wait_strategy = "dom_stable_then_fallback_delay"
                    wait_result = "success"
                    condition = ""
                    expected_after = str(step.get("expected_url_after") or "").strip()
                    expected_selector = str(step.get("expected_selector_after") or "").strip()
                    try:
                        opened_page = await self._await_new_page_if_ready(
                            session,
                            action,
                            page_task,
                            500 if not step.get("opened_new_page") else _REPLAY_STEP_TIMEOUT_MS,
                        )
                        if opened_page is not None:
                            page = opened_page
                            state["new_page_detected"] = True
                            wait_strategy = "new_page"
                            wait_result = "new_page"
                        if expected_selector:
                            await page.locator(expected_selector).first.wait_for(
                                state="visible",
                                timeout=_REPLAY_STEP_TIMEOUT_MS,
                            )
                            wait_strategy = "expected_selector_after"
                            condition = "expected_selector_after"
                        elif expected_after and _safe_page_url(page.url) != _safe_page_url(expected_after):
                            await page.wait_for_url(_safe_page_url(expected_after), timeout=_REPLAY_NAVIGATION_TIMEOUT_MS)
                            wait_strategy = "expected_url_after"
                            condition = _safe_page_url(expected_after)
                        elif await self._capture_download_if_ready(
                            download_task,
                            action_key,
                            run_id,
                            step_index,
                            downloaded_files,
                            timeout_ms=1200,
                        ):
                            wait_strategy = "download"
                            wait_result = "download"
                        else:
                            await self._wait_dom_stable(page, _REPLAY_STEP_TIMEOUT_MS)
                            recorded_wait_ms = min(
                                max(int(step.get("elapsed_ms") or 0), _REPLAY_FALLBACK_DELAY_MS),
                                5000,
                            )
                            await page.wait_for_timeout(recorded_wait_ms)
                            state["recorded_wait_ms"] = recorded_wait_ms
                    finally:
                        self._cancel_replay_task(page_task)
                        self._cancel_replay_task(download_task)
                    step_diagnostics.append(
                        await self._finish_step_diagnostic(
                            session.page,
                            step_diag,
                            wait_strategy=wait_strategy,
                            result=wait_result,
                            condition=condition,
                        )
                    )
                    state["wait_hint"] = str(step.get("wait_hint") or "")
                    state["replay_hint"] = str(step.get("replay_hint") or "")
                elif step_type == "teclar":
                    await page.keyboard.press(str(step.get("valor") or "Enter"))
                    await self._wait_dom_stable(page, _REPLAY_STEP_TIMEOUT_MS)
                    step_diagnostics.append(
                        await self._finish_step_diagnostic(
                            session.page,
                            step_diag,
                            wait_strategy="dom_stable",
                            result="success",
                        )
                    )
                elif step_type == "extrair_texto":
                    label = str(step.get("nome") or selector)
                    result = "success"
                    try:
                        locator = page.locator(selector).first
                        await locator.wait_for(state="visible", timeout=_REPLAY_STEP_TIMEOUT_MS)
                        text = await locator.inner_text(timeout=_REPLAY_STEP_TIMEOUT_MS)
                        extracted[label] = text.strip()
                        if not text.strip():
                            result = "target_empty"
                    except Exception as extraction_exc:
                        extracted[label] = ""
                        result = "target_not_found"
                        if step_diag is not None:
                            step_diag["error"] = str(extraction_exc)[:500]
                    step_diagnostics.append(
                        await self._finish_step_diagnostic(
                            session.page,
                            step_diag,
                            wait_strategy="extraction_target",
                            result=result,
                        )
                    )
                elif step_type == "download_pdf":
                    from backend.motor_browser import _extrator_universal_de_download

                    download_path = runtime_download_path(
                        action_key,
                        f"{run_id}-{step_index}",
                        ".pdf",
                    )
                    await _extrator_universal_de_download(page, selector, str(download_path))
                    downloaded_files.append(runtime_file_metadata(download_path))
                    step_diagnostics.append(
                        await self._finish_step_diagnostic(
                            session.page,
                            step_diag,
                            wait_strategy="download",
                            result="download",
                        )
                    )
                if action_browser_mode == "desktop_browser":
                    validate_action_page_url(action, session.page.url)
            except ActionPageError as exc:
                raise DemoSessionError(str(exc)) from exc
            except DemoSessionError:
                raise
            except Exception as exc:
                if step_diag is not None:
                    step_diagnostics.append(
                        await self._finish_step_diagnostic(
                            session.page,
                            step_diag,
                            wait_strategy=str(step_diag.get("wait_strategy") or "step_execution"),
                            result="timeout" if isinstance(exc, PlaywrightTimeoutError) else "error",
                            error=str(exc),
                        )
                    )
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
                    {
                        "selector_diagnostics": [diagnostics],
                        "step_diagnostics": step_diagnostics,
                        "retryable": isinstance(exc, PlaywrightTimeoutError),
                    },
                ) from exc

        if action_browser_mode == "desktop_browser":
            try:
                validate_action_page_url(action, session.page.url)
            except ActionPageError as exc:
                raise DemoSessionError(str(exc)) from exc

        evidence_path = _DATA_DIR / "runs" / f"{run_id}.png"
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        await session.page.screenshot(path=str(evidence_path), full_page=False)
        final_title = (await session.page.title()).strip()[:200]
        logger.info("Replay concluido na sessao %s, run %s", session_id, run_id)
        return {
            "texto": "Execucao assistida concluida com sucesso.",
            "evidencia": str(evidence_path.relative_to(_ROOT)),
            "dados_extraidos": extracted,
            "arquivos": [str(item["path"]) for item in downloaded_files],
            "downloaded_files": downloaded_files,
            "main_file": downloaded_files[0] if downloaded_files else None,
            "passos_executados": len(steps),
            "session_revalidated": automatically_revalidated,
            "selector_diagnostics": selector_diagnostics,
            "step_diagnostics": step_diagnostics,
            "input_variables": {str(key): "[informado]" for key in variables.keys()},
            "retryable": False,
            "final_page": {"title": final_title, "url": _safe_page_url(session.page.url)},
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

    async def _current_title(self, page: Page) -> str:
        try:
            return (await page.title()).strip()[:200]
        except Exception:
            return ""

    async def _base_step_diagnostic(
        self,
        page: Page,
        step_index: int,
        step_type: str,
        target_label: str,
        started_at: float,
    ) -> dict[str, Any]:
        return {
            "step_index": step_index,
            "action_type": step_type,
            "target_label": target_label,
            "wait_strategy": "not_started",
            "waited_ms": 0,
            "result": "running",
            "current_url_host": _safe_url_host(page.url),
            "current_title": await self._current_title(page),
            "_started_at": started_at,
        }

    async def _finish_step_diagnostic(
        self,
        page: Page,
        diagnostic: dict[str, Any],
        *,
        wait_strategy: str,
        result: str,
        error: str = "",
        condition: str = "",
    ) -> dict[str, Any]:
        started_at = float(diagnostic.pop("_started_at", time.monotonic()))
        diagnostic.update(
            {
                "wait_strategy": wait_strategy,
                "waited_ms": max(0, int((time.monotonic() - started_at) * 1000)),
                "result": result,
                "current_url_host": _safe_url_host(page.url),
                "current_title": await self._current_title(page),
            }
        )
        if error:
            diagnostic["error"] = str(error)[:500]
        if condition:
            diagnostic["condition"] = condition[:500]
        return diagnostic

    async def _wait_dom_stable(self, page: Page, timeout_ms: int) -> None:
        try:
            await page.wait_for_load_state("networkidle", timeout=min(timeout_ms, _REPLAY_NAVIGATION_TIMEOUT_MS))
            return
        except Exception:
            pass
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=min(timeout_ms, _REPLAY_NAVIGATION_TIMEOUT_MS))
        except Exception:
            await page.wait_for_timeout(_REPLAY_FALLBACK_DELAY_MS)

    async def _await_new_page_if_ready(
        self,
        session: DemoBrowserSession,
        action: dict[str, Any],
        page_task: asyncio.Task[Any] | None,
        timeout_ms: int,
    ) -> Page | None:
        if page_task is None:
            return None
        try:
            page = await asyncio.wait_for(asyncio.shield(page_task), timeout=timeout_ms / 1000)
        except asyncio.TimeoutError:
            return None
        except Exception:
            return None
        if not isinstance(page, Page) or page.is_closed():
            return None
        await page.wait_for_load_state("domcontentloaded", timeout=_REPLAY_NAVIGATION_TIMEOUT_MS)
        validate_action_page_url(action, page.url)
        await self._set_active_page(session, page)
        return page

    async def _capture_download_if_ready(
        self,
        download_task: asyncio.Task[Any] | None,
        action_key: str,
        run_id: str,
        step_index: int,
        downloaded_files: list[dict[str, object]],
        timeout_ms: int = 500,
    ) -> bool:
        if download_task is None:
            return False
        try:
            download = await asyncio.wait_for(asyncio.shield(download_task), timeout=timeout_ms / 1000)
        except asyncio.TimeoutError:
            return False
        except Exception:
            return False
        suffix = Path(str(getattr(download, "suggested_filename", "") or "")).suffix or ".pdf"
        download_path = runtime_download_path(action_key, f"{run_id}-{step_index}", suffix)
        await download.save_as(str(download_path))
        downloaded_files.append(runtime_file_metadata(download_path))
        return True

    def _cancel_replay_task(self, task: asyncio.Task[Any] | None) -> None:
        if task is not None and not task.done():
            task.cancel()

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
