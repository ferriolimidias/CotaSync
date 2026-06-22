"""Sessao assistida e recorder minimo para a demonstracao CotaSync v0.1."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright


logger = logging.getLogger("cotasync.demo")
_ROOT = Path(__file__).resolve().parents[2]
_DATA_DIR = _ROOT / "data"
_UI_MAP_PATH = _DATA_DIR / "ui_map.json"
_DEMO_SESSIONS_DIR = _DATA_DIR / "demo_sessions"
_MAX_RECORDED_STEPS = 200


class DemoSessionError(RuntimeError):
    """Erro operacional seguro no fluxo da demonstracao."""


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
  const send = (payload) => {
    if (!payload.seletor || typeof window.__cotasyncRecord !== 'function') return;
    Promise.resolve(window.__cotasyncRecord(payload)).catch(() => {});
  };

  document.addEventListener('input', (event) => {
    const el = event.target;
    if (!el || !['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName) || sensitive(el)) return;
    send({tipo: 'preencher', seletor: selectorFor(el), valor: String(el.value || '')});
  }, true);

  document.addEventListener('click', (event) => {
    const el = event.target && event.target.closest
      ? event.target.closest('button, a, input, [role="button"]')
      : null;
    if (!el || sensitive(el)) return;
    const type = String(el.type || '').toLowerCase();
    if (['text', 'email', 'password', 'search', 'number'].includes(type)) return;
    send({tipo: 'clicar', seletor: selectorFor(el), valor: ''});
    setTimeout(captureOutputs, 100);
    setTimeout(captureOutputs, 500);
  }, true);

  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' || sensitive(event.target)) return;
    send({tipo: 'teclar', seletor: '', valor: 'Enter'});
  }, true);

  const outputValues = new Map();
  const captureOutputs = () => {
    document.querySelectorAll('[data-cotasync-output]').forEach((el) => {
      const value = String(el.innerText || el.value || '').trim();
      const selector = selectorFor(el);
      if (!value || outputValues.get(selector) === value) return;
      outputValues.set(selector, value);
      send({
        tipo: 'extrair_texto',
        seletor: selector,
        valor: '',
        nome: el.getAttribute('data-cotasync-output') || 'resultado'
      });
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


def _browserless_ws_url(session_id: str) -> str:
    raw = os.getenv("BROWSERLESS_URL", "ws://cotasync_test_browserless:3000").strip()
    parsed = urlsplit(raw)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update({"trackingId": _tracking_id(session_id), "timeout": "600000"})
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


def _demo_target_url() -> str:
    return os.getenv(
        "COTASYNC_DEMO_TARGET_URL",
        "http://cotasync_test_backend:8000/demo/alvo",
    ).strip()


def _live_url(target_id: str) -> str:
    public_base = os.getenv(
        "COTASYNC_BROWSERLESS_PUBLIC_URL",
        "http://127.0.0.1:3010",
    ).strip().rstrip("/")
    parsed = urlsplit(public_base)
    ws_scheme = "wss" if parsed.scheme == "https" else "ws"
    ws_host = parsed.netloc
    ws_path = f"{parsed.path.rstrip('/')}/devtools/page/{target_id}"
    websocket_url = f"{ws_scheme}://{ws_host}{ws_path}"
    return f"{public_base}/devtools/inspector.html?ws={websocket_url.split('://', 1)[1]}"


def _safe_page_url(url: str) -> str:
    parsed = urlsplit(str(url or ""))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _safe_file_name(value: str) -> str:
    return re.sub(r"[^\w\-]+", "_", str(value or "acao"), flags=re.UNICODE).strip("_") or "acao"


def _is_sensitive_selector(selector: str) -> bool:
    return bool(re.search(r"password|senha|secret|token|otp|captcha", selector, flags=re.IGNORECASE))


def _storage_state_path(session_id: str) -> Path:
    return _DEMO_SESSIONS_DIR / str(session_id) / "storage_state.json"


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
    status: str = "aguardando_login"
    recording: bool = False
    steps: list[dict[str, str]] = field(default_factory=list)


class DemoSessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, DemoBrowserSession] = {}

    def _get(self, session_id: str) -> DemoBrowserSession:
        session = self._sessions.get(str(session_id))
        if session is None:
            raise DemoSessionError("Sessao de demonstracao nao encontrada ou encerrada.")
        return session

    def _append_step(self, session: DemoBrowserSession, raw: Any) -> None:
        if not session.recording or not isinstance(raw, dict) or len(session.steps) >= _MAX_RECORDED_STEPS:
            return
        step_type = str(raw.get("tipo") or "").strip().lower()
        selector = str(raw.get("seletor") or "").strip()
        if step_type not in {"clicar", "preencher", "teclar", "extrair_texto"}:
            return
        if step_type != "teclar" and (not selector or _is_sensitive_selector(selector)):
            return
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
                return
        if session.steps and session.steps[-1] == step:
            return
        session.steps.append(step)

    async def _page_is_authenticated(self, page: Page) -> bool:
        """Valida os sinais publicos aceitos pela demo sem depender do status em memoria."""

        try:
            if page.is_closed():
                return False
            if await page.locator("[data-cotasync-authenticated='true']").count() > 0:
                return True
            if await page.get_by_text("Consulta de Pedidos", exact=False).count() > 0:
                return True
            has_order_input = await page.locator("input#pedido-codigo").count() > 0
            has_search_button = await page.locator("button#buscar-pedido").count() > 0
            if has_order_input and has_search_button:
                return True

            # No alvo local a tela de login usa a mesma URL. Por isso a URL so e
            # sinal de pos-login quando o formulario de credenciais desapareceu.
            is_demo_target = "/demo/alvo" in str(page.url or "")
            has_login_form = await page.locator("input[type='password'], #demo-login").count() > 0
            return is_demo_target and not has_login_form
        except Exception:
            return False

    async def _set_active_page(self, session: DemoBrowserSession, page: Page) -> None:
        session.page = page
        session.context = page.context
        cdp = await session.context.new_cdp_session(page)
        target_info = await cdp.send("Target.getTargetInfo")
        target_id = str(target_info.get("targetInfo", {}).get("targetId") or "")
        if target_id:
            session.target_id = target_id
            session.live_url = _live_url(target_id)

    async def _find_authenticated_live_page(self, session: DemoBrowserSession) -> Page | None:
        if not session.browser.is_connected():
            return None

        candidates = [session.page]
        for context in session.browser.contexts:
            candidates.extend(context.pages)

        seen: set[int] = set()
        for page in candidates:
            identity = id(page)
            if identity in seen:
                continue
            seen.add(identity)
            if await self._page_is_authenticated(page):
                return page
        return None

    async def _save_storage_state(self, session: DemoBrowserSession, *, required: bool) -> bool:
        path = _storage_state_path(session.id)
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
        async def record_binding(_source: Any, payload: Any) -> None:
            current = self._sessions.get(session_id)
            if current is not None:
                self._append_step(current, payload)

        await context.expose_binding("__cotasyncRecord", record_binding)
        await context.add_init_script(_RECORDER_SCRIPT)

    async def _restore_storage_state(self, session: DemoBrowserSession) -> Page | None:
        path = _storage_state_path(session.id)
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(state, dict):
            return None

        try:
            if session.browser.is_connected():
                browser = session.browser
                context = session.context
            else:
                browser = await session.playwright.chromium.connect_over_cdp(_browserless_ws_url(session.id))
                context = browser.contexts[0] if browser.contexts else await browser.new_context(
                    viewport={"width": 1280, "height": 800}
                )
                await self._prepare_reconnected_context(session.id, context)
                session.browser = browser
                session.context = context

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
            await page.goto(_demo_target_url(), wait_until="domcontentloaded", timeout=15000)
            if not await self._page_is_authenticated(page):
                return None
            return page
        except Exception as exc:
            logger.info("storage_state nao restaurou a sessao %s: %s", session.id, exc)
            return None

    async def _revalidate_for_replay(self, session: DemoBrowserSession) -> tuple[bool, bool]:
        was_authenticated = session.status in {"autenticada", "gravando"}
        page = await self._find_authenticated_live_page(session)
        restored = False
        if page is None:
            page = await self._restore_storage_state(session)
            restored = page is not None
        if page is None:
            session.status = "expirada"
            return False, False

        await self._set_active_page(session, page)
        session.status = "autenticada"
        await self._save_storage_state(session, required=False)
        automatically_revalidated = not was_authenticated or restored
        if automatically_revalidated:
            logger.info(
                "Sessao %s revalidada automaticamente via %s",
                session.id,
                "storage_state" if restored else "pagina CDP ativa",
            )
        return True, automatically_revalidated

    async def create(self) -> dict[str, Any]:
        session_id = str(uuid4())
        playwright = await async_playwright().start()
        browser: Browser | None = None
        try:
            browser = await playwright.chromium.connect_over_cdp(_browserless_ws_url(session_id))
            context = browser.contexts[0] if browser.contexts else await browser.new_context(
                viewport={"width": 1280, "height": 800}
            )
            page = context.pages[0] if context.pages else await context.new_page()

            async def record_binding(_source: Any, payload: Any) -> None:
                current = self._sessions.get(session_id)
                if current is not None:
                    self._append_step(current, payload)

            await context.expose_binding("__cotasyncRecord", record_binding)
            await context.add_init_script(_RECORDER_SCRIPT)
            await page.goto(_demo_target_url(), wait_until="domcontentloaded", timeout=15000)
            cdp = await context.new_cdp_session(page)
            target_info = await cdp.send("Target.getTargetInfo")
            target_id = str(target_info.get("targetInfo", {}).get("targetId") or "")
            if not target_id:
                raise DemoSessionError("Browserless nao informou o identificador da pagina.")

            session = DemoBrowserSession(
                id=session_id,
                playwright=playwright,
                browser=browser,
                context=context,
                page=page,
                target_id=target_id,
                live_url=_live_url(target_id),
                created_at=_utc_now(),
                tracking_id=_tracking_id(session_id),
            )
            self._sessions[session_id] = session
            logger.info("Sessao assistida criada: %s", session_id)
            return await self.status(session_id)
        except Exception as exc:
            if browser is not None:
                await browser.close()
            await playwright.stop()
            if isinstance(exc, DemoSessionError):
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
            "live_url": session.live_url,
            "page_url": _safe_page_url(session.page.url),
            "page_title": title,
            "recording": session.recording,
            "steps_count": len(session.steps),
        }

    async def confirm_login(self, session_id: str) -> dict[str, Any]:
        session = self._get(session_id)
        page = await self._find_authenticated_live_page(session)
        if page is None:
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
        session.recording = True
        session.status = "gravando"
        await session.page.evaluate(_RECORDER_SCRIPT)
        logger.info("Gravacao iniciada na sessao %s", session_id)
        return await self.status(session_id)

    async def stop_recording(self, session_id: str) -> dict[str, Any]:
        session = self._get(session_id)
        if not session.recording:
            raise DemoSessionError("Nao existe gravacao ativa nesta sessao.")
        await asyncio.sleep(0.3)
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
                self._append_step(session, output)
        session.recording = False
        session.status = "autenticada"
        if not session.steps:
            raise DemoSessionError("Nenhum passo foi capturado. Repita a rotina com a gravacao ativa.")
        logger.info("Gravacao finalizada na sessao %s com %s passos", session_id, len(session.steps))
        return {
            "session": await self.status(session_id),
            "steps": [dict(step, index=index) for index, step in enumerate(session.steps)],
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
            if variable not in variables:
                variables.append(variable)

        payload = _load_ui_map()
        payload["acoes_conhecidas"][action_name] = {
            "nome_amigavel": action_name,
            "descricao": str(description or "Rotina aprendida por demonstracao manual.").strip(),
            "url_inicial": "sessao_assistida",
            "passos_playwright": steps,
            "variaveis_necessarias": variables,
            "modo_aprendizado": "gravacao_manual",
        }
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
        }

    async def execute_action(
        self,
        session_id: str,
        action_key: str,
        variables: dict[str, Any],
        run_id: str,
    ) -> dict[str, Any]:
        session = self._get(session_id)
        authenticated, automatically_revalidated = await self._revalidate_for_replay(session)
        if not authenticated:
            raise DemoSessionError("A sessao nao esta autenticada para executar a rotina.")
        if session.recording:
            raise DemoSessionError("Pare a gravacao antes de executar a rotina aprendida.")

        payload = _load_ui_map()
        action = payload["acoes_conhecidas"].get(action_key)
        if not isinstance(action, dict):
            raise DemoSessionError("Acao aprendida nao encontrada.")
        steps = action.get("passos_playwright", [])
        if not isinstance(steps, list) or not steps:
            raise DemoSessionError("A acao aprendida nao possui passos executaveis.")

        extracted: dict[str, str] = {}
        for step in steps:
            if not isinstance(step, dict):
                continue
            step_type = str(step.get("tipo") or "").strip().lower()
            selector = str(step.get("seletor") or "").strip()
            try:
                if step_type == "preencher":
                    variable = str(step.get("variavel") or "").strip()
                    value = variables.get(variable) if variable else step.get("valor", "")
                    if variable and (value is None or str(value) == ""):
                        raise DemoSessionError(f"Valor obrigatorio ausente: {variable}.")
                    await session.page.locator(selector).first.fill(str(value), timeout=5000)
                elif step_type == "clicar":
                    await session.page.locator(selector).first.click(timeout=5000)
                    await session.page.wait_for_timeout(500)
                elif step_type == "teclar":
                    await session.page.keyboard.press(str(step.get("valor") or "Enter"))
                    await session.page.wait_for_timeout(300)
                elif step_type == "extrair_texto":
                    locator = session.page.locator(selector).first
                    text = await locator.inner_text(timeout=5000)
                    extracted[str(step.get("nome") or selector)] = text.strip()
            except DemoSessionError:
                raise
            except Exception as exc:
                raise DemoSessionError(f"Falha ao executar o passo '{step_type}'.") from exc

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
        }

    async def close(self, session_id: str) -> None:
        session = self._sessions.pop(str(session_id), None)
        if session is None:
            return
        session.status = "encerrada"
        try:
            await session.browser.close()
        finally:
            await session.playwright.stop()
            shutil.rmtree(_storage_state_path(session_id).parent, ignore_errors=True)
        logger.info("Sessao assistida encerrada: %s", session_id)

    async def close_all(self) -> None:
        for session_id in list(self._sessions):
            try:
                await self.close(session_id)
            except Exception:
                logger.exception("Falha ao encerrar sessao assistida %s", session_id)


demo_session_manager = DemoSessionManager()
