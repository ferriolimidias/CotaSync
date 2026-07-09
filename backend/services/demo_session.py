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
    Frame,
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
from backend.services.session_guardian import (
    SessionGuardian,
    SessionGuardianError,
    session_failure_message,
)
from backend.services.actions_repository import enrich_action_access_profile
from backend.services.extraction_targets import extract_value_near_label
from backend.services.file_names import safe_file_name
from backend.services.result_selection import (
    detect_extraction_candidates,
    extraction_contract_from_action,
    extract_with_contract,
    host_from_url,
)


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
_LONG_ACTION_MAX_MS = _env_seconds("COTASYNC_LONG_ACTION_MAX_SECONDS", 300) * 1000
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
  const textOf = (el) => String(el?.innerText || el?.textContent || '').replace(/\s+/g, ' ').trim();
  const labelFor = (el) => {
    if (!el || !el.ownerDocument) return '';
    const id = el.id ? String(el.id) : '';
    if (id) {
      const explicit = el.ownerDocument.querySelector(`label[for="${attrValue(id)}"]`);
      if (explicit) return textOf(explicit).slice(0, 120);
    }
    const wrapping = el.closest('label');
    if (wrapping) return textOf(wrapping).slice(0, 120);
    const aria = el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('placeholder');
    if (aria) return String(aria).slice(0, 120);
    const parentText = textOf(el.parentElement);
    return parentText.replace(String(el.value || ''), '').slice(0, 120);
  };
  const fieldMetadata = (el) => ({
    tag: String(el?.tagName || '').toLowerCase(),
    type: String(el?.type || '').toLowerCase(),
    id: String(el?.id || '').slice(0, 160),
    name: String(el?.name || '').slice(0, 160),
    label: labelFor(el),
    placeholder: String(el?.getAttribute?.('placeholder') || '').slice(0, 160),
    aria_label: String(el?.getAttribute?.('aria-label') || '').slice(0, 160)
  });
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
    if (!el || !['INPUT', 'TEXTAREA'].includes(el.tagName) || sensitive(el)) return;
    const previousTimer = inputTimers.get(el);
    if (previousTimer) clearTimeout(previousTimer);
    const before = inputBefore.get(el) || snapshot();
    inputTimers.set(el, setTimeout(() => {
      send({
        tipo: 'preencher',
        event_type: 'fill',
        seletor: selectorFor(el),
        valor: '',
        value_template: '{{input_value}}',
        field_metadata: fieldMetadata(el)
      }, before);
      inputBefore.delete(el);
    }, 250));
  }, true);

  document.addEventListener('change', (event) => {
    const el = event.target;
    if (!el || el.tagName !== 'SELECT' || sensitive(el)) return;
    const before = snapshot();
    send({
      tipo: 'selecionar',
      event_type: 'select',
      seletor: selectorFor(el),
      valor: '',
      value_template: '{{input_value}}',
      field_metadata: fieldMetadata(el)
    }, before);
  }, true);

  document.addEventListener('click', (event) => {
    const el = event.target && event.target.closest
      ? event.target.closest('button, a, input, [role="button"]')
      : null;
    if (!el || sensitive(el)) return;
    const type = String(el.type || '').toLowerCase();
    if (['text', 'email', 'password', 'search', 'number'].includes(type)) return;
    const before = snapshot();
    send({
      tipo: 'clicar',
      event_type: 'click',
      seletor: selectorFor(el),
      valor: '',
      target_text: textOf(el).slice(0, 200),
      target_label: labelFor(el),
      field_metadata: fieldMetadata(el)
    }, before, 500);
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

_RESULT_SELECTION_SCRIPT = r"""
() => {
  const attrValue = (value) => String(value || '').replace(/\\/g, '\\\\').replace(/"/g, '\\"');
  const textOf = (el) => String(el?.innerText || el?.textContent || el?.value || '').replace(/\s+/g, ' ').trim();
  const selectorFor = (el) => {
    if (!el || !el.tagName) return '';
    const tag = el.tagName.toLowerCase();
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
  const tableInfo = (el) => {
    const cell = el.closest && el.closest('td,th');
    const row = cell && cell.parentElement;
    const table = row && row.closest('table');
    if (!cell || !row || !table) return {};
    const rows = Array.from(table.querySelectorAll('tr'));
    const cells = Array.from(row.children).filter((item) => /^(TD|TH)$/.test(item.tagName));
    const colIndex = cells.indexOf(cell);
    const rowIndex = rows.indexOf(row);
    const headerRow = rows.find((candidate) => candidate.querySelector('th')) || rows[0];
    const headers = headerRow ? Array.from(headerRow.children).filter((item) => /^(TD|TH)$/.test(item.tagName)).map(textOf) : [];
    const rowCells = cells.map(textOf);
    const rowKey = rowCells.join(' ').toLowerCase();
    const isFooter = rowIndex >= Math.max(1, rows.length - 2) || /total|totais|cont/.test(rowKey);
    const nextCells = rowCells.slice(colIndex + 1).filter(Boolean);
    const numeric = nextCells.find((item) => /^(?:R\$\s*)?-?\d{1,3}(?:\.\d{3})*(?:,\d+)?%?$|-?\d+(?:,\d+)?%?$/.test(item));
    return {
      row_text: rowCells.join(' | '),
      table_row_cells: rowCells,
      column_header: headers[colIndex] || '',
      table_headers: headers,
      table_row_index: rowIndex,
      table_col_index: colIndex,
      table_is_footer: isFooter,
      next_cell_text: nextCells[0] || '',
      next_numeric_text: numeric || ''
    };
  };
  window.__cotasyncResultSelection = {active: true, captured: null};
  if (!document.getElementById('__cotasync_result_selection_style')) {
    const style = document.createElement('style');
    style.id = '__cotasync_result_selection_style';
    style.textContent = '.__cotasync-result-hover{outline:3px solid #0ea5e9!important;cursor:crosshair!important;}';
    document.documentElement.appendChild(style);
  }
  let last = null;
  const clear = () => { if (last) last.classList.remove('__cotasync-result-hover'); last = null; };
  const onMove = (event) => {
    if (!window.__cotasyncResultSelection?.active) return;
    const el = event.target;
    if (!el || el === document.documentElement || el === document.body) return;
    if (last !== el) clear();
    last = el;
    el.classList.add('__cotasync-result-hover');
  };
  const onClick = (event) => {
    if (!window.__cotasyncResultSelection?.active) return;
    event.preventDefault();
    event.stopPropagation();
    const el = event.target;
    const rect = el.getBoundingClientRect();
    const parent = el.parentElement;
    const before = [];
    const after = [];
    if (parent) {
      const siblings = Array.from(parent.children);
      const index = siblings.indexOf(el);
      siblings.slice(Math.max(0, index - 3), index).forEach((item) => before.push(textOf(item)));
      siblings.slice(index + 1, index + 4).forEach((item) => after.push(textOf(item)));
    }
    const table = tableInfo(el);
    const selectedText = textOf(el);
    const candidateLabel = table.column_header || before.filter(Boolean).slice(-1)[0] || selectedText;
    const selectedKey = selectedText.toLowerCase().replace(/[^a-z0-9à-ÿ%]+/g, ' ').trim();
    const headerKey = String(table.column_header || '').toLowerCase().replace(/[^a-z0-9à-ÿ%]+/g, ' ').trim();
    const clickedLooksLikeLabel = selectedKey && (selectedKey === headerKey || /[%a-zà-ÿ]/.test(selectedKey));
    const tableValue = clickedLooksLikeLabel ? (table.next_numeric_text || table.next_cell_text || selectedText) : selectedText;
    window.__cotasyncResultSelection = {
      active: false,
      captured: {
        selected_text: selectedText,
        selected_html: String(el.outerHTML || '').slice(0, 5000),
        selector: selectorFor(el),
        css_path: selectorFor(el),
        tag_name: String(el.tagName || '').toLowerCase(),
        id: String(el.id || ''),
        name: String(el.getAttribute('name') || ''),
        class: String(el.getAttribute('class') || ''),
        aria_label: String(el.getAttribute('aria-label') || ''),
        title: String(el.getAttribute('title') || ''),
        bounding_box: {x: rect.x, y: rect.y, width: rect.width, height: rect.height},
        nearby_text: [...before, selectedText, ...after].filter(Boolean).join(' | '),
        nearby_text_before: before.filter(Boolean),
        nearby_text_after: after.filter(Boolean),
        parent_text: textOf(parent).slice(0, 1200),
        candidate_label: clickedLooksLikeLabel ? selectedText : candidateLabel,
        candidate_value: table.table_headers ? tableValue : selectedText,
        candidate_type: table.table_headers ? (table.table_is_footer ? 'table_footer_total' : 'table_cell') : 'block_text',
        current_url: String(location.href || '').split(/[?#]/, 1)[0],
        current_host: String(location.host || ''),
        page_title: String(document.title || ''),
        ...table
      }
    };
    clear();
    document.removeEventListener('mousemove', onMove, true);
    document.removeEventListener('click', onClick, true);
    return false;
  };
  document.addEventListener('mousemove', onMove, true);
  document.addEventListener('click', onClick, true);
  return {status: 'active', current_url: String(location.href || '').split(/[?#]/, 1)[0], page_title: String(document.title || '')};
}
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


def _full_page_url(url: Any) -> str:
    return str(url or "")


def _safe_url_host(url: str) -> str:
    try:
        return urlsplit(str(url or "")).hostname or ""
    except Exception:
        return ""


def _business_host(value: Any) -> str:
    raw = str(value or "").strip().lower().rstrip(".")
    host = _safe_url_host(raw) or raw
    if not host or "/" in host or "?" in host:
        return ""
    microsoft_suffixes = (
        "login.microsoftonline.com",
        "login.live.com",
        "login.microsoft.com",
        "login.windows.net",
        "m365.cloud.microsoft",
    )
    if any(host == suffix or host.endswith(f".{suffix}") for suffix in microsoft_suffixes):
        return ""
    return host


def _host_matches(host: str, expected_host: str) -> bool:
    current = str(host or "").strip().lower().rstrip(".")
    expected = str(expected_host or "").strip().lower().rstrip(".")
    return bool(current and expected and (current == expected or current.endswith(f".{expected}")))


def _storage_state_last_saved_at(path: Path) -> str | None:
    try:
        if not path.is_file():
            return None
        return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
    except OSError:
        return None


def _expected_replay_url(saved_url: Any) -> str:
    candidate = str(saved_url or "").strip()
    if urlsplit(candidate).scheme in {"http", "https"}:
        return candidate
    return _demo_target_url()


def _initial_url_for_learned_action(
    session: "DemoBrowserSession",
    learning_events: list[dict[str, Any]],
    robust_steps: list[dict[str, Any]],
) -> str:
    configured_url = str(session.external_login_url or "")
    first_event_url = next(
        (
            str(event.get("url_before") or "")
            for event in learning_events
            if str(event.get("url_before") or "").strip()
        ),
        "",
    )
    first_step_url = next(
        (
            str(step.get("expected_url_before") or "")
            for step in robust_steps
            if str(step.get("expected_url_before") or "").strip()
        ),
        "",
    )
    if configured_url:
        first_reference = first_event_url or first_step_url
        if not first_reference or _safe_page_url(first_reference) == _safe_page_url(configured_url):
            return configured_url
    if first_event_url:
        return first_event_url
    if first_step_url:
        return first_step_url
    return _full_page_url(session.page.url)


def _page_matches_url(page: Page, expected_url: str) -> bool:
    return _safe_page_url(page.url) == _safe_page_url(expected_url)


def _safe_file_name(value: str) -> str:
    return safe_file_name(value)


def _is_sensitive_selector(selector: str) -> bool:
    return bool(re.search(r"password|senha|secret|token|otp|captcha", selector, flags=re.IGNORECASE))


def _title_label(value: str) -> str:
    text = re.sub(r"[_\-]+", " ", str(value or "")).strip()
    if not text:
        return "Campo"
    return " ".join(part.capitalize() for part in text.split())


def _suggest_variable_key(selector: str, index: int = 0, metadata: dict[str, Any] | None = None) -> str:
    metadata = metadata if isinstance(metadata, dict) else {}
    has_metadata_hint = any(
        str(metadata.get(key) or "").strip()
        for key in ("label", "placeholder", "aria_label", "name", "id")
    )
    raw = " ".join(
        str(part or "")
        for part in (
            metadata.get("label"),
            metadata.get("placeholder"),
            metadata.get("aria_label"),
            metadata.get("name"),
            metadata.get("id"),
            selector,
        )
    )
    lowered = raw.casefold()
    direct = (
        ("edtgrupo", "grupo"),
        ("grupo", "grupo"),
        ("edtcota", "cota"),
        ("cota", "cota"),
        ("cpf", "cpf"),
        ("cliente", "cliente"),
        ("codigo", "codigo"),
        ("código", "codigo"),
        ("nome", "nome"),
        ("data", "data"),
        ("data_base", "data_base"),
        ("data base", "data_base"),
    )
    for needle, key in direct:
        if needle in lowered:
            return key
    if str(metadata.get("tag") or "").casefold() == "select" or "select" in lowered:
        return "tipo_consulta"
    if not has_metadata_hint:
        return f"campo_{index + 1}"
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


def _normalize_label_key(value: Any) -> str:
    normalized = str(value or "").casefold()
    normalized = re.sub(r"[^a-z0-9à-ÿ]+", " ", normalized, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", normalized).strip()


def _suggest_variable_key_for_step(step: dict[str, Any], index: int) -> str:
    metadata = step.get("field_metadata") if isinstance(step.get("field_metadata"), dict) else {}
    return _suggest_variable_key(str(step.get("seletor") or ""), index, metadata)


_INPUT_DESCRIPTION_VARIABLE_TERMS = (
    "grupo",
    "cota",
    "cpf",
    "cliente",
    "codigo",
    "código",
    "tipo",
    "opção",
    "opcao",
    "data",
)


def _expected_input_terms(text: str) -> list[str]:
    lowered = str(text or "").casefold()
    return [term for term in _INPUT_DESCRIPTION_VARIABLE_TERMS if term in lowered]


def _missing_input_capture_warnings(input_description: str, variables: list[dict[str, Any]]) -> list[str]:
    terms = _expected_input_terms(input_description)
    if not terms or variables:
        return []
    return [
        "Não identifiquei os campos digitados. Revise a gravação ou configure os campos manualmente."
    ]


def _frame_metadata(frame: Frame | None) -> dict[str, str]:
    if frame is None:
        return {}
    try:
        name = str(frame.name or "").strip()
    except Exception:
        name = ""
    try:
        url = _safe_page_url(str(frame.url or ""))
    except Exception:
        url = ""
    return {"frame_name": name, "frame_url": url}


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
    access_profile_name: str = ""
    access_profile_email_or_identifier: str = ""
    microsoft_saved_account_identifier: str = ""
    microsoft_saved_account_selector: str = ""
    microsoft_saved_account_text: str = ""
    expected_system_host: str = ""
    microsoft_hosts: list[str] = field(default_factory=list)
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
    recorder_watched_pages: set[int] = field(default_factory=set)
    recorder_context_watched: bool = False
    recorder_errors: list[str] = field(default_factory=list)
    final_page_snapshot: dict[str, Any] = field(default_factory=dict)
    operator_fill_attempt_count: int = 0
    operator_fill_recorded_count: int = 0
    operator_click_attempt_count: int = 0
    operator_click_recorded_count: int = 0
    active_recording_session_id: str = ""
    last_operator_result: dict[str, Any] = field(default_factory=dict)
    last_backend_recorded_event: dict[str, Any] = field(default_factory=dict)
    last_recorded_event_session_id: str = ""


class DemoSessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, DemoBrowserSession] = {}

    def _get(self, session_id: str) -> DemoBrowserSession:
        session = self._sessions.get(str(session_id))
        if session is None:
            raise DemoSessionError("Sessao de demonstracao nao encontrada ou encerrada.")
        return session

    async def start_result_selection(self, session_id: str) -> dict[str, Any]:
        session = self._get(session_id)
        if session.page.is_closed():
            raise DemoSessionError("Pagina da sessao nao esta disponivel para selecao.")
        result = await session.page.evaluate(_RESULT_SELECTION_SCRIPT)
        return result if isinstance(result, dict) else {"status": "active"}

    async def capture_result_selection(
        self,
        session_id: str,
        *,
        target_name: str = "",
        screen_label: str = "",
    ) -> dict[str, Any]:
        session = self._get(session_id)
        if session.page.is_closed():
            raise DemoSessionError("Pagina da sessao nao esta disponivel para captura.")
        captured = await session.page.evaluate(
            "() => window.__cotasyncResultSelection && window.__cotasyncResultSelection.captured"
        )
        if not isinstance(captured, dict) or not captured:
            return {"captured": None, "candidates": [], "status": "waiting"}
        captured.setdefault("current_url", _safe_page_url(session.page.url))
        captured.setdefault("current_host", host_from_url(session.page.url))
        captured.setdefault("page_title", await self._current_title(session.page))
        try:
            source = await session.page.content()
        except Exception:
            source = str(captured.get("parent_text") or captured.get("nearby_text") or "")
        candidates = detect_extraction_candidates(
            source,
            target_name=target_name,
            screen_label=screen_label,
            selected_element=captured,
        )
        return {"captured": captured, "candidates": candidates, "status": "captured"}

    async def detect_result_candidates(
        self,
        session_id: str,
        *,
        target_name: str = "",
        screen_label: str = "",
    ) -> dict[str, Any]:
        session = self._get(session_id)
        if session.page.is_closed():
            raise DemoSessionError("Pagina da sessao nao esta disponivel para detectar candidatos.")
        try:
            source = await session.page.content()
        except Exception:
            source = await session.page.locator("body").inner_text(timeout=5000)
        return {
            "candidates": detect_extraction_candidates(source, target_name=target_name, screen_label=screen_label),
            "current_url": _safe_page_url(session.page.url),
            "current_host": host_from_url(session.page.url),
            "page_title": await self._current_title(session.page),
        }

    def _append_step(
        self,
        session: DemoBrowserSession,
        raw: Any,
        *,
        bypass_operator_suppression: bool = False,
    ) -> int | None:
        if (
            not session.recording
            or (not bypass_operator_suppression and time.monotonic() < session.operator_recording_suppressed_until)
            or not isinstance(raw, dict)
            or len(session.steps) >= _MAX_RECORDED_STEPS
        ):
            return None
        step_type = str(raw.get("tipo") or "").strip().lower()
        selector = str(raw.get("seletor") or "").strip()
        if step_type not in {"clicar", "preencher", "selecionar", "teclar", "extrair_texto"}:
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
        value_template = str(raw.get("value_template") or "").strip()
        if value_template and step_type in {"preencher", "selecionar"}:
            step["value_template"] = value_template
        variable_key = str(raw.get("variable_key") or "").strip()
        if variable_key and step_type in {"preencher", "selecionar"}:
            step["variavel"] = variable_key
        field_metadata = raw.get("field_metadata")
        if isinstance(field_metadata, dict):
            step["field_metadata"] = {
                str(key): str(value or "")[:200]
                for key, value in field_metadata.items()
                if key in {"tag", "type", "id", "name", "label", "placeholder", "aria_label"}
            }

        if step_type in {"preencher", "selecionar"} and session.steps:
            previous = session.steps[-1]
            if previous.get("tipo") == step_type and previous.get("seletor") == selector:
                session.steps[-1] = step
                return len(session.steps) - 1
        if session.steps and session.steps[-1] == step:
            return len(session.steps) - 1
        session.steps.append(step)
        return len(session.steps) - 1

    def _existing_field_variables(self, session: DemoBrowserSession) -> dict[str, str]:
        variables: dict[str, str] = {}
        for step in session.steps:
            if not isinstance(step, dict):
                continue
            selector = str(step.get("seletor") or "").strip()
            variable = str(step.get("variavel") or "").strip()
            if selector and variable:
                variables[selector] = variable
        for event in session.learning_events:
            if not isinstance(event, dict):
                continue
            selector = str(event.get("selector") or "").strip()
            variable = str(event.get("variable_key") or "").strip()
            if selector and variable:
                variables[selector] = variable
        return variables

    def _unique_variable_key(
        self,
        session: DemoBrowserSession,
        selector: str,
        suggested: str,
    ) -> str:
        existing_by_selector = self._existing_field_variables(session)
        if selector in existing_by_selector:
            return existing_by_selector[selector]
        used = {value for value in existing_by_selector.values() if value}
        if suggested not in used:
            return suggested
        suffix = 2
        while f"{suggested}_{suffix}" in used:
            suffix += 1
        return f"{suggested}_{suffix}"

    def _normalize_field_variable_raw(
        self,
        session: DemoBrowserSession,
        raw: dict[str, Any],
        *,
        field_kind: str = "",
        source: str = "",
    ) -> dict[str, Any]:
        step_type = str(raw.get("tipo") or "").strip().lower()
        event_type = str(raw.get("event_type") or "").strip().lower()
        field_kind = str(field_kind or "").strip().lower()
        if field_kind in {"select", "dropdown", "operator_select"}:
            step_type = "selecionar"
            event_type = "select"
        elif field_kind in {"input", "textarea", "fill", "operator_fill"}:
            step_type = "preencher"
            event_type = "fill"
        if step_type not in {"preencher", "selecionar"}:
            return raw
        selector = str(raw.get("seletor") or raw.get("selector") or "").strip()
        metadata = raw.get("field_metadata") if isinstance(raw.get("field_metadata"), dict) else {}
        next_index = len(session.steps)
        suggested = _suggest_variable_key(selector, next_index, metadata)
        variable_key = self._unique_variable_key(session, selector, suggested)
        normalized = dict(raw)
        normalized["tipo"] = "selecionar" if event_type == "select" or step_type == "selecionar" else "preencher"
        normalized["event_type"] = "select" if normalized["tipo"] == "selecionar" else "fill"
        normalized["seletor"] = selector
        normalized["valor"] = ""
        normalized["variable_key"] = variable_key
        normalized["value_template"] = f"{{{{{variable_key}}}}}"
        normalized["source"] = str(source or raw.get("source") or "browser_recorder")
        return normalized

    async def record_field_variable_event(
        self,
        session_id: str,
        selector: str,
        *,
        field_kind: str = "input",
        source: str = "browser_recorder",
        example_value: str = "",
        field_metadata: dict[str, Any] | None = None,
        frame_metadata: dict[str, str] | None = None,
        bypass_operator_suppression: bool = False,
    ) -> dict[str, Any] | None:
        session = self._get(session_id)
        now = _utc_now()
        kind = str(field_kind or "").strip().lower()
        is_select = kind in {"select", "dropdown", "operator_select"}
        raw = self._normalize_field_variable_raw(
            session,
            {
                "tipo": "selecionar" if is_select else "preencher",
                "event_type": "select" if is_select else "fill",
                "seletor": selector,
                "valor": str(example_value or ""),
                "example_value": str(example_value or ""),
                "timestamp_before": now,
                "timestamp_after": now,
                "elapsed_ms": 0,
                "url_before": session.page.url,
                "url_after": session.page.url,
                "field_metadata": field_metadata or {},
                "source": source,
            },
            field_kind=kind,
            source=source,
        )
        return await self._record_live_step(
            session,
            raw,
            {"page": session.page, "frame_metadata": frame_metadata or {}},
            bypass_operator_suppression=bypass_operator_suppression,
        )

    async def _record_live_step(
        self,
        session: DemoBrowserSession,
        raw: Any,
        source: Any = None,
        *,
        bypass_operator_suppression: bool = False,
    ) -> dict[str, Any] | None:
        if isinstance(raw, dict) and str(raw.get("tipo") or "").strip().lower() in {"preencher", "selecionar"}:
            raw = self._normalize_field_variable_raw(
                session,
                raw,
                source=str(raw.get("source") or "browser_recorder"),
            )
        step_index = self._append_step(
            session,
            raw,
            bypass_operator_suppression=bypass_operator_suppression,
        )
        if step_index is None or not isinstance(raw, dict):
            return None

        page = source.get("page") if isinstance(source, dict) else None
        source_frame = source.get("frame") if isinstance(source, dict) else None
        if not isinstance(page, Page) or page.is_closed():
            page = session.page
        if not isinstance(source_frame, Frame):
            source_frame = None
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
        if event_type not in {"fill", "select", "click", "extract", "download", "navigation", "popup", "new_tab", "modal", "wait"}:
            event_type = {
                "preencher": "fill",
                "selecionar": "select",
                "clicar": "click",
                "extrair_texto": "extract",
                "teclar": "wait",
            }.get(str(raw.get("tipo") or ""), "wait")
        event: dict[str, Any] = {
            "session_id": session.id,
            "step_index": step_index,
            "event_type": event_type,
            "selector": str(raw.get("seletor") or ""),
            "target_text": str(raw.get("target_text") or "")[:200],
            "target_label": str(raw.get("target_label") or "")[:200],
            "value_template": str(raw.get("value_template") or "") if event_type in {"fill", "select"} else "",
            "variable_key": str(raw.get("variable_key") or "") if event_type in {"fill", "select"} else "",
            "example_value": str(raw.get("example_value") or "")[:500] if event_type in {"fill", "select"} else "",
            "field_metadata": raw.get("field_metadata") if isinstance(raw.get("field_metadata"), dict) else {},
            "timestamp_before": str(raw.get("timestamp_before") or _utc_now()),
            "timestamp_after": str(raw.get("timestamp_after") or _utc_now()),
            "elapsed_ms": elapsed_ms,
            "url_before": _full_page_url(raw.get("url_before") or page.url),
            "url_after": _full_page_url(raw.get("url_after") or page.url),
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
        event["source"] = str(raw.get("source") or "browser_recorder")
        event.update(_frame_metadata(source_frame))
        if isinstance(source, dict) and isinstance(source.get("frame_metadata"), dict):
            for key, value in source["frame_metadata"].items():
                if key in {"frame_name", "frame_url"} and value:
                    event[key] = str(value)
        field_metadata = event["field_metadata"] if isinstance(event.get("field_metadata"), dict) else {}
        if not event["target_label"]:
            event["target_label"] = str(
                field_metadata.get("label")
                or field_metadata.get("aria_label")
                or field_metadata.get("placeholder")
                or ""
            )[:200]
        from backend.services.ai_observer import deterministic_observe_learning_step

        event.update(deterministic_observe_learning_step(event))
        session.learning_events.append(event)
        session.last_recorded_event_session_id = session.id
        session.last_backend_recorded_event = {
            "session_id": session.id,
            "event_id": len(session.learning_events) - 1,
            "event_type": event_type,
            "selector": str(event.get("selector") or ""),
            "source": str(event.get("source") or ""),
            "variable_key": str(event.get("variable_key") or ""),
        }
        session.last_screenshot_path = screenshot_after_path or session.last_screenshot_path
        session.last_page_count = len(live_pages)
        session.download_detected = False
        return event

    async def _page_is_authenticated(self, session: DemoBrowserSession, page: Page) -> bool:
        """Valida os sinais publicos aceitos pela demo sem depender do status em memoria."""

        try:
            if page.is_closed():
                return False
            if session.external_login_url:
                if session.auth_validation_mode == "manual_confirmation":
                    current_host = _safe_url_host(str(page.url or ""))
                    if session.expected_system_host and _host_matches(current_host, session.expected_system_host):
                        return await self._page_is_valid_for_manual_confirmation(session, page)
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
            session.recorder_context_watched = False
            session.recorder_watched_pages.clear()
            if session.page.is_closed() or session.page.context != context:
                session.page = connection.page
            self._watch_recording_context(session)
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

    def _target_url_for_saved_session(self, session: DemoBrowserSession) -> str:
        if session.external_login_url:
            return session.external_login_url
        if session.expected_system_host:
            return f"https://{session.expected_system_host.strip().strip('/')}/"
        return _demo_target_url()

    def _saved_session_test_status(self, session: DemoBrowserSession, current_url: str) -> str:
        if not session.storage_state_path.is_file():
            return "missing"
        current_host = _safe_url_host(current_url)
        if session.expected_system_host and _host_matches(current_host, session.expected_system_host):
            return "authenticated"
        microsoft_hosts = (
            session.microsoft_hosts
            if isinstance(session.microsoft_hosts, list) and session.microsoft_hosts
            else ["login.microsoftonline.com", "m365.cloud.microsoft"]
        )
        if any(_host_matches(current_host, str(host)) for host in microsoft_hosts):
            return "microsoft_login"
        if session.status in {"autenticada", "gravando"}:
            return "authenticated"
        return "available"

    async def _apply_saved_storage_state(self, session: DemoBrowserSession) -> bool:
        path = session.storage_state_path
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if not isinstance(state, dict):
            return False

        cookies = state.get("cookies", [])
        if isinstance(cookies, list) and cookies:
            await session.context.add_cookies(cookies)

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
            await session.context.add_init_script(
                f"""() => {{
                  const stored = {serialized};
                  const entries = stored[window.location.origin] || {{}};
                  for (const [key, value] of Object.entries(entries)) localStorage.setItem(key, value);
                }}"""
            )
        return True

    async def _prepare_reconnected_context(self, session_id: str, context: BrowserContext) -> None:
        async def record_binding(source: Any, payload: Any) -> None:
            current = self._sessions.get(session_id)
            if current is not None:
                await self._record_live_step(current, payload, source)

        await context.expose_binding("__cotasyncRecord", record_binding)
        await context.add_init_script(_RECORDER_SCRIPT)

    async def _install_recorder_on_frame(self, session: DemoBrowserSession, frame: Frame) -> None:
        if not session.recording:
            return
        try:
            await frame.evaluate(_RECORDER_SCRIPT)
        except Exception as exc:
            message = f"frame_inaccessible:{type(exc).__name__}"
            if message not in session.recorder_errors:
                session.recorder_errors.append(message)
            logger.debug("Recorder nao pode ser instalado no frame da sessao %s", session.id, exc_info=True)

    def _watch_page_recording(self, session: DemoBrowserSession, page: Page) -> None:
        page_id = id(page)
        if page_id in session.recorder_watched_pages:
            return
        session.recorder_watched_pages.add(page_id)

        def on_frame_navigated(frame: Frame) -> None:
            if not session.recording:
                return
            task = asyncio.create_task(self._install_recorder_on_frame(session, frame))
            session.observer_tasks.add(task)
            task.add_done_callback(session.observer_tasks.discard)

        page.on("framenavigated", on_frame_navigated)

    def _watch_recording_context(self, session: DemoBrowserSession) -> None:
        if not session.recorder_context_watched:
            session.recorder_context_watched = True

            def on_page(page: Page) -> None:
                self._watch_page_recording(session, page)
                if not session.recording:
                    return
                task = asyncio.create_task(self._install_recorder_for_session(session))
                session.observer_tasks.add(task)
                task.add_done_callback(session.observer_tasks.discard)

            session.context.on("page", on_page)
        for current_page in session.context.pages:
            if not current_page.is_closed():
                self._watch_page_recording(session, current_page)

    async def _install_recorder_for_session(self, session: DemoBrowserSession) -> None:
        self._watch_recording_context(session)
        for current_page in [page for page in session.context.pages if not page.is_closed()]:
            self._watch_page_recording(session, current_page)
            for frame in current_page.frames:
                await self._install_recorder_on_frame(session, frame)

    async def _evaluate_all_frames(
        self,
        session: DemoBrowserSession,
        script: str,
    ) -> list[tuple[Page, Frame, Any]]:
        results: list[tuple[Page, Frame, Any]] = []
        for current_page in [page for page in session.context.pages if not page.is_closed()]:
            self._watch_page_recording(session, current_page)
            for frame in current_page.frames:
                try:
                    results.append((current_page, frame, await frame.evaluate(script)))
                except Exception:
                    logger.debug("Nao foi possivel avaliar frame da sessao %s", session.id, exc_info=True)
        return results

    async def _restore_storage_state(self, session: DemoBrowserSession, expected_url: str) -> Page | None:
        try:
            if not await self._reconnect_live_browser(session):
                return None
            if not await self._apply_saved_storage_state(session):
                return None
            context = session.context
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
        external_login_url = str(external_config.get("external_login_url") or "")
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
                access_profile_name=str(external_config.get("access_profile_name") or "").strip(),
                access_profile_email_or_identifier=str(
                    external_config.get("access_profile_email_or_identifier") or ""
                ).strip(),
                microsoft_saved_account_identifier=str(
                    external_config.get("microsoft_saved_account_identifier")
                    or external_config.get("access_profile_email_or_identifier")
                    or ""
                ).strip(),
                microsoft_saved_account_selector=str(
                    external_config.get("microsoft_saved_account_selector") or ""
                ).strip(),
                microsoft_saved_account_text=str(external_config.get("microsoft_saved_account_text") or "").strip(),
                expected_system_host=str(external_config.get("expected_system_host") or "").strip(),
                microsoft_hosts=(
                    external_config.get("microsoft_hosts")
                    if isinstance(external_config.get("microsoft_hosts"), list)
                    else []
                ),
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
        page_url = _safe_page_url(session.page.url)
        saved_session_exists = session.storage_state_path.is_file()
        saved_session_last_saved_at = _storage_state_last_saved_at(session.storage_state_path)
        saved_session_test_status = self._saved_session_test_status(session, page_url)
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
            "page_url": page_url,
            "page_title": title,
            "recording": session.recording,
            "steps_count": len(session.steps),
            "learning_events_count": len(session.learning_events),
            "external_system_name": session.external_system_name,
            "external_login_url": session.external_login_url,
            "using_external_system": bool(session.external_login_url),
            "access_profile_name": session.access_profile_name,
            "microsoft_saved_account_text": session.microsoft_saved_account_text,
            "microsoft_saved_account_identifier": session.microsoft_saved_account_identifier,
            "expected_system_host": session.expected_system_host,
            "auth_validation_mode": session.auth_validation_mode or "demo_target_markers",
            "storage_state_saved": saved_session_exists,
            "saved_session_exists": saved_session_exists,
            "saved_session_last_saved_at": saved_session_last_saved_at,
            "saved_session_test_status": saved_session_test_status,
            "saved_session_current_url": page_url,
            "saved_session_current_title": title,
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

    async def recording_diagnostics(self, session_id: str) -> dict[str, Any]:
        session = self._get(session_id)
        live_pages = [page for page in session.context.pages if not page.is_closed()]
        active_title = ""
        try:
            active_title = await session.page.title()
        except Exception:
            pass
        instrumented_frames = 0
        frame_count = 0
        for current_page in live_pages:
            for frame in current_page.frames:
                frame_count += 1
                try:
                    if bool(await frame.evaluate("() => window.__cotasyncRecorderInstalled === true")):
                        instrumented_frames += 1
                except Exception as exc:
                    message = f"frame_diagnostic_inaccessible:{type(exc).__name__}"
                    if message not in session.recorder_errors:
                        session.recorder_errors.append(message)
        last_event = session.learning_events[-1] if session.learning_events else {}
        event_types = [str(event.get("event_type") or "") for event in session.learning_events]
        source_types = [str(event.get("source") or "") for event in session.learning_events]
        last_operator_result = getattr(session, "last_operator_result", {}) or {}
        last_backend_recorded_event = getattr(session, "last_backend_recorded_event", {}) or {}
        fill_count = event_types.count("fill")
        select_count = event_types.count("select")
        if fill_count + select_count > 0:
            direct_typing_status = "field_events_observed"
        elif frame_count <= 0:
            direct_typing_status = "wrong_page_or_no_frames"
        elif instrumented_frames <= 0:
            direct_typing_status = "recorder_not_installed"
        elif any("frame_diagnostic_inaccessible" in item for item in session.recorder_errors):
            direct_typing_status = "cross_origin_or_inaccessible_frame"
        elif not session.recording:
            direct_typing_status = "recording_inactive"
        else:
            direct_typing_status = "no_input_events_observed"
        return {
            "active_recording_session_id": str(
                getattr(session, "active_recording_session_id", "") or (session.id if session.recording else "")
            ),
            "reviewed_session_id": session.id,
            "operator_request_session_id": str(
                last_operator_result.get("operator_request_session_id")
                or last_operator_result.get("session_id")
                or ""
            ),
            "last_recorded_event_session_id": str(getattr(session, "last_recorded_event_session_id", "") or ""),
            "recorder_installed": instrumented_frames > 0,
            "active_page_url": _safe_page_url(session.page.url),
            "active_page_title": active_title[:200],
            "frame_count": frame_count,
            "instrumented_frame_count": instrumented_frames,
            "raw_event_count": len(session.learning_events),
            "click_event_count": event_types.count("click"),
            "fill_event_count": fill_count,
            "select_event_count": select_count,
            "operator_fill_count": sum(
                1
                for event in session.learning_events
                if event.get("event_type") in {"fill", "select"}
                and str(event.get("source") or "") == "operator_mode"
            ),
            "operator_fill_attempt_count": int(getattr(session, "operator_fill_attempt_count", 0)),
            "operator_fill_recorded_count": int(getattr(session, "operator_fill_recorded_count", 0)),
            "operator_click_attempt_count": int(getattr(session, "operator_click_attempt_count", 0)),
            "operator_click_recorded_count": int(getattr(session, "operator_click_recorded_count", 0)),
            "browser_recorder_event_count": source_types.count("browser_recorder"),
            "last_event_type": str(last_event.get("event_type") or ""),
            "last_event_selector": str(last_event.get("selector") or ""),
            "last_event_frame_url": str(last_event.get("frame_url") or ""),
            "last_operator_result": dict(last_operator_result),
            "last_backend_recorded_event": dict(last_backend_recorded_event),
            "direct_typing_capture_status": direct_typing_status,
            "recorder_errors": list(session.recorder_errors[-20:]),
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
            locator, state = await self._wait_actionable_locator(session.page, safe_selector, {})
            count = int(state.get("count") or 0)
            visible = bool(state.get("visible"))
            enabled = bool(state.get("enabled"))
        except Exception as exc:
            raise DemoSessionError("Seletor inválido para a página ativa.") from exc
        if count != 1:
            raise DemoSessionError(f"O seletor deve identificar exatamente um elemento; encontrados: {count}.")
        if not visible or not enabled:
            raise DemoSessionError("O elemento precisa estar visível e habilitado.")
        return locator

    async def operator_insert_active(self, session_id: str, value: str, *, sensitive: bool = False) -> dict[str, Any]:
        session = self._get(session_id)
        self._validate_operator_session(session)
        safe_value = str(value or "")
        if len(safe_value) > 20_000:
            raise DemoSessionError("O texto excede o limite do Modo operador.")
        if not session.recording:
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
        logger.info(
            "Modo operador inseriu texto no campo ativo: session=%s chars=%s sensitive=%s",
            session.id,
            len(safe_value),
            bool(sensitive),
        )
        result = {
            "session_id": session.id,
            "operator_request_session_id": session.id,
            "active_recording_session_id": str(
                getattr(session, "active_recording_session_id", "") or (session.id if session.recording else "")
            ),
            "operation": "insert_active_text",
            "typed_chars": len(safe_value),
            "sensitive": bool(sensitive),
            "recording": session.recording,
            "recording_active": session.recording,
            "recorded": False,
        }
        session.last_operator_result = dict(result)
        return result

    async def operator_press(self, session_id: str, key: str) -> dict[str, Any]:
        session = self._get(session_id)
        self._validate_operator_session(session)
        safe_key = str(key or "").strip()
        if safe_key not in {"Enter", "Tab"}:
            raise DemoSessionError("Tecla não permitida no Modo operador.")
        if not session.recording:
            self._prepare_operator_utility(session)
        try:
            await session.page.keyboard.press(safe_key)
            await asyncio.sleep(0.2)
        except Exception as exc:
            raise DemoSessionError("Não foi possível pressionar a tecla no navegador.") from exc
        logger.info("Modo operador pressionou tecla: session=%s key=%s", session.id, safe_key)
        result = {
            "session_id": session.id,
            "operator_request_session_id": session.id,
            "active_recording_session_id": str(
                getattr(session, "active_recording_session_id", "") or (session.id if session.recording else "")
            ),
            "operation": "press_key",
            "key": safe_key,
            "recording": session.recording,
            "recording_active": session.recording,
            "recorded": False,
        }
        session.last_operator_result = dict(result)
        return result

    async def operator_clear_active(self, session_id: str) -> dict[str, Any]:
        session = self._get(session_id)
        self._validate_operator_session(session)
        if not session.recording:
            self._prepare_operator_utility(session)
        try:
            cleared = await session.page.evaluate(
                """() => {
                    const el = document.activeElement;
                    if (!el) return false;
                    const tag = String(el.tagName || '').toLowerCase();
                    if (tag === 'input' || tag === 'textarea') {
                        const prototype = tag === 'input'
                            ? HTMLInputElement.prototype
                            : HTMLTextAreaElement.prototype;
                        const setter = Object.getOwnPropertyDescriptor(prototype, 'value').set;
                        setter.call(el, '');
                    } else if (el.isContentEditable) {
                        el.textContent = '';
                    } else {
                        return false;
                    }
                    el.dispatchEvent(new Event('input', {bubbles: true}));
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                    return true;
                }"""
            )
            if not cleared:
                raise DemoSessionError("Foque um campo editável no navegador remoto antes de limpar.")
            await asyncio.sleep(0.2)
        except DemoSessionError:
            raise
        except Exception as exc:
            raise DemoSessionError("Não foi possível limpar o campo ativo.") from exc
        logger.info("Modo operador limpou campo ativo: session=%s", session.id)
        result = {
            "session_id": session.id,
            "operator_request_session_id": session.id,
            "active_recording_session_id": str(
                getattr(session, "active_recording_session_id", "") or (session.id if session.recording else "")
            ),
            "operation": "clear_active",
            "recording": session.recording,
            "recording_active": session.recording,
            "recorded": False,
        }
        session.last_operator_result = dict(result)
        return result

    async def operator_fill(
        self,
        session_id: str,
        selector: str,
        value: str,
        *,
        record_action: bool = True,
        active_recording_session_id: str = "",
    ) -> dict[str, Any]:
        session = self._get(session_id)
        requested_active_session = str(active_recording_session_id or "").strip()
        if requested_active_session and requested_active_session != session.id:
            raise DemoSessionError("Sessao ativa da gravacao difere da sessao usada no Modo operador.")
        effective_record_action = bool(session.recording)
        if effective_record_action:
            session.operator_fill_attempt_count += 1
        safe_value = str(value or "")
        if len(safe_value) > 20_000:
            raise DemoSessionError("O texto excede o limite do Modo operador.")
        locator = await self._operator_locator(session, selector, record_action=effective_record_action)
        field_metadata: dict[str, str] = {}
        field_kind = "operator_fill"
        try:
            field_info = await locator.evaluate(
                """element => {
                    const textOf = (el) => String(el?.innerText || el?.textContent || '').replace(/\\s+/g, ' ').trim();
                    const attr = (name) => String(element.getAttribute(name) || '').slice(0, 160);
                    let label = '';
                    if (element.id) {
                        const explicit = element.ownerDocument.querySelector(`label[for="${CSS.escape(element.id)}"]`);
                        if (explicit) label = textOf(explicit).slice(0, 120);
                    }
                    if (!label && element.closest) {
                        const wrapping = element.closest('label');
                        if (wrapping) label = textOf(wrapping).slice(0, 120);
                    }
                    if (!label) label = attr('aria-label') || attr('title') || attr('placeholder');
                    return {
                        tag: String(element.tagName || '').toLowerCase(),
                        type: String(element.type || '').toLowerCase(),
                        id: String(element.id || '').slice(0, 160),
                        name: String(element.name || '').slice(0, 160),
                        label,
                        placeholder: attr('placeholder'),
                        aria_label: attr('aria-label')
                    };
                }"""
            )
            if isinstance(field_info, dict):
                field_metadata = {
                    str(key): str(field_info.get(key) or "")[:200]
                    for key in ("tag", "type", "id", "name", "label", "placeholder", "aria_label")
                }
                if str(field_metadata.get("tag") or "").casefold() == "select":
                    field_kind = "operator_select"
        except Exception:
            field_metadata = {}
        if effective_record_action:
            # Evita duplicar o evento emitido pelo listener do navegador; o
            # evento de operador abaixo é gravado diretamente com bypass.
            self._prepare_operator_utility(session, duration=1.5)
        else:
            self._prepare_operator_utility(session)
        event_count_before = len(session.learning_events)
        recorded_event: dict[str, Any] | None = None
        try:
            if field_kind == "operator_select":
                await locator.select_option(safe_value, timeout=_REPLAY_STEP_TIMEOUT_MS)
            else:
                await locator.fill(safe_value, timeout=_REPLAY_STEP_TIMEOUT_MS)
            await locator.evaluate(
                """element => {
                    element.dispatchEvent(new Event('input', {bubbles: true}));
                    element.dispatchEvent(new Event('change', {bubbles: true}));
                }"""
            )
            await asyncio.sleep(0.4)
        except Exception as exc:
            raise DemoSessionError("Não foi possível preencher o campo na página ativa.") from exc
        if effective_record_action and session.recording:
            recorded_event = await self.record_field_variable_event(
                session.id,
                selector,
                field_kind=field_kind,
                source="operator_mode",
                example_value=safe_value,
                field_metadata=field_metadata,
                bypass_operator_suppression=True,
            )
            if not recorded_event or recorded_event.get("session_id") != session.id:
                raise DemoSessionError("Modo operador retornaria sucesso sem evento na sessão ativa.")
            session.operator_fill_recorded_count += 1
        event_id = len(session.learning_events) - 1 if len(session.learning_events) > event_count_before else None
        recorded = bool(recorded_event and effective_record_action and session.recording)
        result = {
            "session_id": session.id,
            "operator_request_session_id": session.id,
            "active_recording_session_id": str(
                getattr(session, "active_recording_session_id", "") or (session.id if session.recording else "")
            ),
            "operation": "fill",
            "recording": session.recording,
            "recording_active": session.recording,
            "recorded": recorded,
            "event_id": event_id,
            "event_type": str(recorded_event.get("event_type") or "") if recorded_event else "",
            "last_recorded_event_session_id": str(getattr(session, "last_recorded_event_session_id", "") or ""),
        }
        session.last_operator_result = dict(result)
        logger.info(
            "Modo operador preencheu elemento: session=%s recorded=%s",
            session.id,
            recorded,
        )
        return result

    async def operator_click(
        self,
        session_id: str,
        selector: str,
        *,
        record_action: bool = True,
        active_recording_session_id: str = "",
    ) -> dict[str, Any]:
        session = self._get(session_id)
        requested_active_session = str(active_recording_session_id or "").strip()
        if requested_active_session and requested_active_session != session.id:
            raise DemoSessionError("Sessao ativa da gravacao difere da sessao usada no Modo operador.")
        effective_record_action = bool(session.recording)
        if effective_record_action:
            session.operator_click_attempt_count += 1
        locator = await self._operator_locator(session, selector, record_action=effective_record_action)
        if effective_record_action:
            self._prepare_operator_utility(session, duration=1.5)
        else:
            self._prepare_operator_utility(session, duration=2.5)
        event_count_before = len(session.learning_events)
        recorded_event: dict[str, Any] | None = None
        target_metadata: dict[str, str] = {}
        try:
            target_metadata = await locator.evaluate(
                r"""el => {
                  const textOf = node => String(node?.innerText || node?.textContent || '').replace(/\s+/g, ' ').trim();
                  const id = el.id ? String(el.id) : '';
                  let label = '';
                  if (id) {
                    const explicit = el.ownerDocument.querySelector(`label[for="${CSS.escape(id)}"]`);
                    if (explicit) label = textOf(explicit).slice(0, 120);
                  }
                  if (!label) {
                    const wrapping = el.closest('label');
                    if (wrapping) label = textOf(wrapping).slice(0, 120);
                  }
                  if (!label) {
                    label = String(el.getAttribute('aria-label') || el.getAttribute('title') || '').slice(0, 120);
                  }
                  return {target_text: textOf(el).slice(0, 200), target_label: label};
                }"""
            )
            if not isinstance(target_metadata, dict):
                target_metadata = {}
        except Exception:
            target_metadata = {}
        try:
            await locator.click(timeout=_REPLAY_STEP_TIMEOUT_MS)
            await asyncio.sleep(1.1)
        except Exception as exc:
            raise DemoSessionError("Não foi possível clicar no elemento da página ativa.") from exc
        if effective_record_action and session.recording:
            now = _utc_now()
            recorded_event = await self._record_live_step(
                session,
                {
                    "tipo": "clicar",
                    "event_type": "click",
                    "seletor": selector,
                    "valor": "",
                    "target_text": str(target_metadata.get("target_text") or ""),
                    "target_label": str(target_metadata.get("target_label") or ""),
                    "timestamp_before": now,
                    "timestamp_after": now,
                    "elapsed_ms": 0,
                    "url_before": session.page.url,
                    "url_after": session.page.url,
                    "source": "operator_mode",
                },
                {"page": session.page},
                bypass_operator_suppression=True,
            )
            if not recorded_event or recorded_event.get("session_id") != session.id:
                raise DemoSessionError("Modo operador retornaria sucesso sem evento na sessão ativa.")
            session.operator_click_recorded_count += 1
        event_id = len(session.learning_events) - 1 if len(session.learning_events) > event_count_before else None
        recorded = bool(recorded_event and effective_record_action and session.recording)
        result = {
            "session_id": session.id,
            "operator_request_session_id": session.id,
            "active_recording_session_id": str(
                getattr(session, "active_recording_session_id", "") or (session.id if session.recording else "")
            ),
            "operation": "click",
            "recording": session.recording,
            "recording_active": session.recording,
            "recorded": recorded,
            "event_id": event_id,
            "event_type": str(recorded_event.get("event_type") or "") if recorded_event else "",
            "last_recorded_event_session_id": str(getattr(session, "last_recorded_event_session_id", "") or ""),
        }
        session.last_operator_result = dict(result)
        logger.info("Modo operador clicou em elemento: session=%s recorded=%s", session.id, record_action)
        return result

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

    async def clear_saved_session(self, session_id: str) -> dict[str, Any]:
        session = self._get(session_id)
        existed = session.storage_state_path.is_file()
        try:
            session.storage_state_path.unlink(missing_ok=True)
        except OSError as exc:
            raise DemoSessionError("Nao foi possivel limpar a sessao salva.") from exc
        return {
            "cleared": existed,
            "storage_state_saved": session.storage_state_path.is_file(),
        }

    async def reopen_with_saved_session(self, session_id: str) -> dict[str, Any]:
        session = self._get(session_id)
        if not await self._reconnect_live_browser(session):
            session.status = "expirada"
            raise DemoSessionError("A sessão do navegador não está disponível.")

        storage_applied = False
        if session.storage_state_path.is_file():
            try:
                storage_applied = await self._apply_saved_storage_state(session)
            except Exception as exc:
                logger.info("Nao foi possivel aplicar sessao salva %s: %s", session.id, exc)

        page = session.page if not session.page.is_closed() and session.page.context == session.context else None
        if page is None:
            page = next((item for item in session.context.pages if not item.is_closed()), None)
        if page is None:
            page = await session.context.new_page()

        target_url = self._target_url_for_saved_session(session)
        navigation_error = ""
        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=15000)
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
        except Exception as exc:
            navigation_error = type(exc).__name__

        await self._set_active_page(session, page)
        current_url = _safe_page_url(page.url)
        current_host = _safe_url_host(current_url)
        microsoft_hosts = (
            session.microsoft_hosts
            if isinstance(session.microsoft_hosts, list) and session.microsoft_hosts
            else ["login.microsoftonline.com", "m365.cloud.microsoft"]
        )
        reached_expected_host = bool(
            session.expected_system_host and _host_matches(current_host, session.expected_system_host)
        )
        microsoft_login_visible = any(_host_matches(current_host, str(host)) for host in microsoft_hosts)
        authenticated = await self._page_is_authenticated(session, page)
        if reached_expected_host or authenticated:
            session.status = "autenticada"
            await self._save_storage_state(session, required=False)
        elif session.status != "gravando":
            session.status = "aguardando_login"

        title = ""
        try:
            title = await page.title()
        except Exception:
            pass
        return {
            "reopen_status": (
                "authenticated"
                if session.status == "autenticada"
                else "microsoft_login"
                if microsoft_login_visible
                else "opened"
            ),
            "target_url": target_url,
            "current_url": current_url,
            "current_title": title,
            "expected_system_host": session.expected_system_host,
            "storage_applied": storage_applied,
            "saved_session_exists": session.storage_state_path.is_file(),
            "reached_expected_host": reached_expected_host,
            "microsoft_login_visible": microsoft_login_visible,
            "navigation_error": navigation_error,
            "session": await self.status(session_id),
        }

    async def start_recording(
        self,
        session_id: str,
        guided_learning: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session = self._get(session_id)
        if session.status == "expirada" or session.page.is_closed() or not session.browser.is_connected():
            raise DemoSessionError("A sessão do navegador não está disponível.")
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
            "ai_result_summary_enabled": bool(raw_instruction.get("ai_result_summary_enabled", True)),
            "ai_recovery_enabled": bool(raw_instruction.get("ai_recovery_enabled", False)),
        }
        session.output_candidates = []
        session.learning_synthesis = {}
        session.final_page_snapshot = {}
        session.recorder_errors = []
        session.operator_fill_attempt_count = 0
        session.operator_fill_recorded_count = 0
        session.operator_click_attempt_count = 0
        session.operator_click_recorded_count = 0
        session.active_recording_session_id = session.id
        session.last_operator_result = {}
        session.last_backend_recorded_event = {}
        session.last_recorded_event_session_id = ""
        session.recording = True
        session.status = "gravando"
        await self._install_recorder_for_session(session)
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
        output_results = await self._evaluate_all_frames(
            session,
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
        for output_page, output_frame, outputs in output_results:
            if not isinstance(outputs, list):
                continue
            for output in outputs:
                if not isinstance(output, dict):
                    continue
                selector = str(output.get("seletor") or "")
                if any(
                    step.get("tipo") == "extrair_texto" and step.get("seletor") == selector
                    for step in session.steps
                ):
                    continue
                await self._record_live_step(session, output, {"page": output_page, "frame": output_frame})
        candidate_results = await self._evaluate_all_frames(
            session,
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
        session.output_candidates = []
        seen_candidates: set[tuple[str, str]] = set()
        for _candidate_page, candidate_frame, candidates in candidate_results:
            if not isinstance(candidates, list):
                continue
            frame_info = _frame_metadata(candidate_frame)
            for item in candidates:
                if not isinstance(item, dict) or not str(item.get("selector") or "").strip():
                    continue
                candidate = {
                    "label": str(item.get("label") or "resultado")[:100],
                    "selector": str(item.get("selector") or "")[:500],
                    "preview": str(item.get("preview") or "")[:160],
                }
                if frame_info.get("frame_url"):
                    candidate["frame_url"] = frame_info["frame_url"][:500]
                if frame_info.get("frame_name"):
                    candidate["frame_name"] = frame_info["frame_name"][:200]
                candidate_key = (candidate["selector"], candidate.get("frame_url", ""))
                if candidate_key in seen_candidates:
                    continue
                seen_candidates.add(candidate_key)
                session.output_candidates.append(candidate)
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
        final_snapshot_results = await self._evaluate_all_frames(
            session,
            r"""() => ({
              url: String(location.href || '').split(/[?#]/, 1)[0],
              title: String(document.title || '').slice(0, 200),
              text: String(document.body ? document.body.innerText || '' : '').replace(/\s+/g, ' ').trim().slice(0, 20000),
              html: String(document.documentElement ? document.documentElement.outerHTML || '' : '').slice(0, 50000),
              element_count: document.body ? document.body.querySelectorAll('*').length : 0
            })"""
        )
        final_pages: list[dict[str, Any]] = []
        for snapshot_page, snapshot_frame, snapshot in final_snapshot_results:
            if not isinstance(snapshot, dict):
                continue
            frame_info = _frame_metadata(snapshot_frame)
            final_pages.append(
                {
                    "url": _safe_page_url(str(snapshot.get("url") or snapshot_page.url)),
                    "title": str(snapshot.get("title") or "")[:200],
                    "text": str(snapshot.get("text") or "")[:20000],
                    "html": str(snapshot.get("html") or "")[:50000],
                    "element_count": max(0, int(snapshot.get("element_count") or 0)),
                    "frame_name": frame_info.get("frame_name", ""),
                    "frame_url": frame_info.get("frame_url", ""),
                }
            )
        session.final_page_snapshot = {
            "captured": bool(final_pages),
            "pages": final_pages,
        }
        latest_diagnostics = await self.recording_diagnostics(session_id)
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
        event_types = [str(event.get("event_type") or "") for event in session.learning_events]
        operator_variable_events = [
            event
            for event in session.learning_events
            if event.get("event_type") in {"fill", "select"}
            and str(event.get("source") or "") == "operator_mode"
        ]
        detected_variables = []
        for index, step in enumerate(session.steps):
            if not isinstance(step, dict) or str(step.get("tipo") or "") not in {"preencher", "selecionar"}:
                continue
            key = str(step.get("variavel") or "").strip() or _suggest_variable_key_for_step(step, index)
            detected_variables.append(
                {
                    "step_index": index,
                    "selector": str(step.get("seletor") or ""),
                    "event_type": "select" if str(step.get("tipo") or "") == "selecionar" else "fill",
                    "suggested_key": key,
                    "label": _title_label(key),
                }
            )
        hard_warning = ""
        diagnostic_error = ""
        if event_types.count("fill") + event_types.count("select") == 0:
            hard_warning = "Nenhum campo digitado foi capturado. Esta ação não terá variáveis na execução rápida."
            if int(getattr(session, "operator_fill_attempt_count", 0)) > 0:
                diagnostic_error = "Modo operador foi usado durante a gravação, mas não gerou evento de variável."
        review_summary = {
            "total_steps": len(session.steps),
            "clicks_captured": event_types.count("click"),
            "fills_captured": event_types.count("fill"),
            "selects_captured": event_types.count("select"),
            "operator_fill_count": len(operator_variable_events),
            "operator_fill_attempt_count": int(getattr(session, "operator_fill_attempt_count", 0)),
            "operator_fill_recorded_count": int(getattr(session, "operator_fill_recorded_count", 0)),
            "downloads": bool(
                session.download_detected
                or any(event.get("download_detected") for event in session.learning_events)
            ),
            "new_tabs": sum(1 for event in session.learning_events if event.get("opened_new_page")),
            "final_page_captured": bool(final_pages),
            "detected_variables": detected_variables,
            "hard_warning": hard_warning,
            "diagnostic_error": diagnostic_error,
            "raw_event_summary": [
                {
                    "session_id": str(event.get("session_id") or session.id),
                    "event_type": str(event.get("event_type") or ""),
                    "selector": str(event.get("selector") or ""),
                    "source": str(event.get("source") or ""),
                    "variable_key": str(event.get("variable_key") or ""),
                }
                for event in session.learning_events
            ],
        }
        review_summary.update(
            {
                "active_recording_session_id": str(getattr(session, "active_recording_session_id", "") or session.id),
                "operator_request_session_id": str(
                    (getattr(session, "last_operator_result", {}) or {}).get("operator_request_session_id")
                    or (getattr(session, "last_operator_result", {}) or {}).get("session_id")
                    or ""
                ),
                "reviewed_session_id": session.id,
                "last_recorded_event_session_id": str(getattr(session, "last_recorded_event_session_id", "") or ""),
                "last_operator_result": dict(getattr(session, "last_operator_result", {}) or {}),
                "last_backend_recorded_event": dict(getattr(session, "last_backend_recorded_event", {}) or {}),
                "diagnostics": latest_diagnostics,
            }
        )
        logger.info("Gravacao finalizada na sessao %s com %s passos", session_id, len(session.steps))
        return {
            "session": await self.status(session_id),
            "steps": [dict(step, index=index) for index, step in enumerate(session.steps)],
            "learning_events": [dict(event) for event in session.learning_events],
            "guided_learning": dict(session.guided_learning),
            "review_summary": review_summary,
            "output_candidates": list(session.output_candidates),
            "final_page": dict(session.final_page_snapshot),
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
        ai_result_summary_enabled: bool = True,
        ai_recovery_enabled: bool = False,
        extraction_targets: list[dict[str, str]] | None = None,
        extract_visible_text: bool = False,
        return_downloaded_file: bool = False,
        requires_authenticated_session: bool | None = None,
        action_timeout_seconds: int | None = None,
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
        explicit_variable_names = variable_names if isinstance(variable_names, dict) else {}
        auto_variable_names: dict[str, str] = {}
        for index, step in enumerate(steps):
            if not isinstance(step, dict) or str(step.get("tipo") or "") not in {"preencher", "selecionar"}:
                continue
            event_variable = next(
                (
                    str(event.get("variable_key") or "").strip()
                    for event in learning_events
                    if event.get("step_index") == index and event.get("event_type") in {"fill", "select"}
                    and str(event.get("variable_key") or "").strip()
                ),
                "",
            )
            auto_variable_names[str(index)] = (
                str(step.get("variavel") or "").strip()
                or event_variable
                or _suggest_variable_key_for_step(step, index)
            )
        variable_name_inputs = {**auto_variable_names, **explicit_variable_names}

        for index_raw, variable_raw in variable_name_inputs.items():
            try:
                index = int(index_raw)
            except (TypeError, ValueError):
                continue
            selector = str(steps[index].get("seletor") or "") if 0 <= index < len(steps) else ""
            variable = _normalize_variable_key(variable_raw, selector, index)
            if not variable or index < 0 or index >= len(steps) or steps[index].get("tipo") not in {"preencher", "selecionar"}:
                continue
            steps[index]["variavel"] = variable
            steps[index]["valor"] = ""
            steps[index]["value_template"] = f"{{{{{variable}}}}}"
            for event in learning_events:
                if event.get("step_index") == index and event.get("event_type") in {"fill", "select"}:
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
                raw_label = str(raw_target.get("label") or raw_target.get("name") or f"resultado_{index + 1}").strip()
                label = raw_label or f"resultado_{index + 1}"
                if label and (selector or raw_label) and not _is_sensitive_selector(selector):
                    extraction_step = {
                        "tipo": "extrair_texto",
                        "seletor": selector,
                        "valor": "",
                        "nome": label,
                    }
                    if not selector:
                        extraction_step["extraction_strategy"] = "near_label"
                        extraction_step["target_label"] = raw_label
                    frame_url = str(raw_target.get("frame_url") or "").strip()
                    frame_name = str(raw_target.get("frame_name") or "").strip()
                    if frame_url:
                        extraction_step["frame_url"] = frame_url
                    if frame_name:
                        extraction_step["frame_name"] = frame_name
                    steps.append(extraction_step)
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
                    "target_text": str(event.get("target_text") or step.get("target_text") or "")[:200],
                    "target_label": str(event.get("target_label") or step.get("target_label") or "")[:200],
                    "opened_new_page": bool(event.get("opened_new_page")),
                    "download_detected": bool(event.get("download_detected")),
                    "expected_selector_after": str(
                        steps[index + 1].get("seletor") if index + 1 < len(steps) else ""
                    ),
                    "frame_url": str(event.get("frame_url") or step.get("frame_url") or ""),
                    "frame_name": str(event.get("frame_name") or step.get("frame_name") or ""),
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
        learning_warnings = _missing_input_capture_warnings(input_description_text, variables)
        if return_downloaded_file and output_type_text == "texto/dados da tela":
            output_type_text = "ambos"
        if return_downloaded_file and not extraction_targets and not extract_visible_text:
            output_type_text = "arquivo/PDF"
        if return_downloaded_file:
            output_schema["main_file"] = {"type": "file", "format": "pdf"}
        access_profile_name = str(getattr(session, "access_profile_name", "") or "").strip()
        access_profile_email = str(getattr(session, "access_profile_email_or_identifier", "") or "").strip()
        saved_account_identifier = str(getattr(session, "microsoft_saved_account_identifier", "") or "").strip()
        saved_account_selector = str(getattr(session, "microsoft_saved_account_selector", "") or "").strip()
        saved_account_text = str(getattr(session, "microsoft_saved_account_text", "") or "").strip()
        expected_system_host = _business_host(getattr(session, "expected_system_host", "")) or _business_host(
            session.page.url
        )
        microsoft_hosts = (
            list(getattr(session, "microsoft_hosts", []))
            if isinstance(getattr(session, "microsoft_hosts", []), list)
            else []
        )

        learned_action: dict[str, Any] = {
            "nome_amigavel": action_name,
            "descricao": str(description or "Rotina aprendida por demonstracao manual.").strip(),
            "url_inicial": _initial_url_for_learned_action(session, learning_events, robust_steps),
            "passos_playwright": steps,
            "robust_steps": robust_steps,
            "original_steps": [dict(step) for step in steps],
            "learning_events": learning_events,
            "variaveis_necessarias": variables,
            "mechanical_map": {
                "passos_playwright": [dict(step) for step in steps],
                "robust_steps": [dict(step) for step in robust_steps],
                "learning_events": [dict(event) for event in learning_events],
                "variable_schema": [dict(item) for item in variable_schema],
                "url_inicial": _initial_url_for_learned_action(session, learning_events, robust_steps),
            },
            "review_status": "not_reviewed",
            "review_last_run_id": "",
            "reviewed_overlay": {},
            "ai_review_summary": "",
            "final_summary_instruction": "",
            "extraction_review": {},
            "objective": objective_text,
            "input_description": input_description_text,
            "expected_result": expected_result_text,
            "success_criteria": success_criteria_text,
            "output_type": output_type_text,
            "output_schema": output_schema,
            "extraction_targets": extraction_targets,
            "extraction_target": extraction_targets[0] if extraction_targets else "",
            "user_result_summary_template": str(user_result_summary_template or "").strip() or None,
            "ai_result_summary_enabled": bool(ai_result_summary_enabled),
            "ai_recovery_enabled": bool(ai_recovery_enabled),
            "learning_warnings": learning_warnings,
            "requires_authenticated_session": (
                bool(requires_authenticated_session)
                if requires_authenticated_session is not None
                else bool(session.external_login_url)
            ),
            "action_timeout_seconds": (
                max(1, int(action_timeout_seconds))
                if isinstance(action_timeout_seconds, int) and action_timeout_seconds > 0
                else None
            ),
            "download_expected": bool(return_downloaded_file),
            "download_detected_during_learning": download_detected,
            "final_page_snapshot": dict(session.final_page_snapshot),
            "modo_aprendizado": "gravacao_mecanica_revisada_por_ia_apos_captura",
            "learning_mode": (
                "desktop_browser_mechanical_ai_reviewed"
                if session.browser_mode == "desktop_browser"
                else "human_demo_mechanical_ai_reviewed"
            ),
            "browser_mode": session.browser_mode,
            "external_system_name": session.external_system_name,
            "external_login_url": session.external_login_url,
            "access_profile_name": access_profile_name,
            "access_profile_email_or_identifier": (
                access_profile_email
                or saved_account_identifier
            ),
            "microsoft_saved_account_identifier": saved_account_identifier or access_profile_email,
            "microsoft_saved_account_selector": saved_account_selector,
            "microsoft_saved_account_text": saved_account_text,
            "expected_system_host": expected_system_host,
            "microsoft_hosts": microsoft_hosts,
            "session_guardian_enabled": bool(session.external_login_url or session.browser_mode == "desktop_browser"),
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
            "learning_warnings": learned_action["learning_warnings"],
            "download_expected": learned_action["download_expected"],
            "requires_authenticated_session": learned_action["requires_authenticated_session"],
            "action_timeout_seconds": learned_action["action_timeout_seconds"],
            "robust_steps_count": len(robust_steps),
            "learning_events_count": len(learning_events),
            "external_system_name": learned_action["external_system_name"],
            "external_login_url": learned_action["external_login_url"],
            "access_profile_name": learned_action["access_profile_name"],
            "access_profile_email_or_identifier": learned_action["access_profile_email_or_identifier"],
            "microsoft_saved_account_identifier": learned_action["microsoft_saved_account_identifier"],
            "microsoft_saved_account_text": learned_action["microsoft_saved_account_text"],
            "expected_system_host": learned_action["expected_system_host"],
            "session_guardian_enabled": learned_action["session_guardian_enabled"],
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
        action = enrich_action_access_profile(action)
        steps = action.get("robust_steps") or action.get("passos_playwright", [])
        if not isinstance(steps, list) or not steps:
            raise DemoSessionError("A acao aprendida nao possui passos executaveis.")

        action_browser_mode = str(action.get("browser_mode") or "browserless").strip()
        if action_browser_mode != session.browser_mode:
            raise DemoSessionError("A acao deve ser executada no modo de navegador em que foi gravada.")

        action_external_url = str(action.get("external_login_url") or "")
        if action_external_url != session.external_login_url:
            raise DemoSessionError("Selecione a sessao do sistema externo usada por esta acao.")

        if action_browser_mode == "desktop_browser":
            try:
                action_page = await select_desktop_page_for_action(action, session.context, session.page)
                await self._set_active_page(session, action_page)
            except ActionPageError as exc:
                if getattr(exc, "diagnostics", {}).get("reason") != "reauthentication_required":
                    raise DemoSessionError(str(exc)) from exc

        expected_url = _expected_replay_url(action.get("url_inicial"))
        extracted: dict[str, str] = {}
        downloaded_files: list[dict[str, object]] = []
        selector_diagnostics: list[dict[str, Any]] = []
        step_diagnostics: list[dict[str, Any]] = []
        step_trace: list[dict[str, Any]] = []
        checkpoint_diagnostics: list[dict[str, Any]] = []
        automatically_revalidated = False
        recovery_attempted = False
        total_recovery_attempts = 0
        recovery_steps: list[dict[str, Any]] = []
        last_session_state = ""
        last_page_title = ""
        current_host = ""
        last_successful_step_index: int | str = ""
        guardian = SessionGuardian() if action_browser_mode == "desktop_browser" else None
        action_timeout_ms = _REPLAY_ACTION_TIMEOUT_MS
        if action_browser_mode == "desktop_browser":
            raw_action_timeout = action.get("action_timeout_seconds")
            if str(raw_action_timeout or "").strip().isdigit():
                action_timeout_ms = max(1, int(raw_action_timeout)) * 1000
            else:
                action_timeout_ms = _LONG_ACTION_MAX_MS
        action_deadline = time.monotonic() + (action_timeout_ms / 1000)

        async def run_session_checkpoint(checkpoint: str, next_step: dict[str, Any] | None = None) -> None:
            nonlocal automatically_revalidated
            nonlocal recovery_attempted
            nonlocal total_recovery_attempts
            nonlocal recovery_steps
            nonlocal last_session_state
            nonlocal last_page_title
            nonlocal current_host
            if (
                guardian is None
                or not bool(action.get("requires_authenticated_session", True))
                or not bool(action.get("session_guardian_enabled", True))
            ):
                return
            started_at = time.monotonic()
            authenticated = await self._page_is_authenticated(session, session.page)
            state = await guardian.classify(
                session.page,
                action,
                authenticated=authenticated,
            )
            if state.state == "authenticated_system":
                last_session_state = state.state
                last_page_title = state.title
                current_host = state.current_host
                checkpoint_diagnostics.append(
                    {
                        "checkpoint": checkpoint,
                        "session_state": state.state,
                        "elapsed_ms": max(0, int((time.monotonic() - started_at) * 1000)),
                        "recovery_attempted": False,
                        "recovery_attempts": 0,
                        "result": "success",
                        "current_host": state.current_host,
                        "last_page_title": state.title,
                    }
                )
                return
            learned_step_diagnostic = await guardian.learned_microsoft_step_diagnostic(
                session.page,
                action,
                next_step,
                state=state,
                authenticated=authenticated,
            )
            if learned_step_diagnostic.get("learned_microsoft_step_compatible") is True:
                last_session_state = state.state
                last_page_title = state.title
                current_host = state.current_host
                checkpoint_diagnostics.append(
                    {
                        "checkpoint": checkpoint,
                        "session_state": state.state,
                        "elapsed_ms": max(0, int((time.monotonic() - started_at) * 1000)),
                        "recovery_attempted": False,
                        "recovery_attempts": 0,
                        "result": "learned_microsoft_step_allowed",
                        "current_host": state.current_host,
                        "last_page_title": state.title,
                        "next_step_index": learned_step_diagnostic.get("next_step_index"),
                        "next_step_type": learned_step_diagnostic.get("next_step_type"),
                        "next_step_selector": learned_step_diagnostic.get("next_step_selector"),
                        "next_step_url_before": learned_step_diagnostic.get("next_step_url_before"),
                        "next_step_host_before": learned_step_diagnostic.get("next_step_host_before"),
                        "next_step_expected_selector": learned_step_diagnostic.get("next_step_expected_selector"),
                        "next_step_expected_url_or_host": learned_step_diagnostic.get(
                            "next_step_expected_url_or_host"
                        ),
                        "next_step_expected_text": learned_step_diagnostic.get("next_step_expected_text"),
                        "whether_next_step_was_microsoft_click": learned_step_diagnostic.get(
                            "whether_next_step_was_microsoft_click"
                        ),
                        "learned_microsoft_step_compatible": learned_step_diagnostic.get(
                            "learned_microsoft_step_compatible"
                        ),
                        "matched_by": learned_step_diagnostic.get("matched_by"),
                    }
                )
                return
            if state.state.startswith("microsoft_") or state.state == "unknown_microsoft_auth":
                last_session_state = state.state
                last_page_title = state.title
                current_host = state.current_host
                learned_step_diagnostic["checkpoint_diagnostics"] = checkpoint_diagnostics + [
                    {
                        "checkpoint": checkpoint,
                        "session_state": state.state,
                        "elapsed_ms": max(0, int((time.monotonic() - started_at) * 1000)),
                        "recovery_attempted": False,
                        "recovery_attempts": 0,
                        "result": "failed",
                        "current_host": state.current_host,
                        "last_page_title": state.title,
                        "reason": learned_step_diagnostic.get("reason"),
                        "next_step_index": learned_step_diagnostic.get("next_step_index"),
                        "next_step_type": learned_step_diagnostic.get("next_step_type"),
                        "next_step_selector": learned_step_diagnostic.get("next_step_selector"),
                        "next_step_url_before": learned_step_diagnostic.get("next_step_url_before"),
                        "next_step_host_before": learned_step_diagnostic.get("next_step_host_before"),
                        "next_step_expected_selector": learned_step_diagnostic.get("next_step_expected_selector"),
                        "next_step_expected_url_or_host": learned_step_diagnostic.get(
                            "next_step_expected_url_or_host"
                        ),
                        "next_step_expected_text": learned_step_diagnostic.get("next_step_expected_text"),
                        "whether_next_step_was_microsoft_click": learned_step_diagnostic.get(
                            "whether_next_step_was_microsoft_click"
                        ),
                    }
                ]
                raise SessionGuardianError(
                    session_failure_message(state.state, str(learned_step_diagnostic.get("reason") or state.reason)),
                    learned_step_diagnostic,
                )
            result = await guardian.ensure_authenticated(
                session.page,
                action,
                is_authenticated=lambda _page: asyncio.sleep(0, result=authenticated),
                checkpoint=checkpoint,
            )
            last_session_state = result.state.state
            last_page_title = result.state.title
            current_host = result.state.current_host
            total_recovery_attempts += result.recovery_attempts
            recovery_attempted = recovery_attempted or result.recovery_attempted
            automatically_revalidated = automatically_revalidated or result.recovery_attempted
            recovery_steps.extend(result.recovery_steps)
            checkpoint_diagnostics.append(
                {
                    "checkpoint": checkpoint,
                    "session_state": result.state.state,
                    "elapsed_ms": max(0, int((time.monotonic() - started_at) * 1000)),
                    "recovery_attempted": result.recovery_attempted,
                    "recovery_attempts": result.recovery_attempts,
                    "result": "success" if result.ok else "failed",
                    "current_host": result.state.current_host,
                    "last_page_title": result.state.title,
                }
            )
            if result.ok:
                return
            diagnostics = result.diagnostics()
            diagnostics["checkpoint_diagnostics"] = checkpoint_diagnostics
            raise SessionGuardianError(
                session_failure_message(result.state.state, result.state.reason),
                diagnostics,
            )

        async def validate_or_allow_learned_microsoft_step(
            next_step: dict[str, Any] | None,
            checkpoint: str,
        ) -> None:
            try:
                validate_action_page_url(action, session.page.url)
                await run_session_checkpoint(checkpoint, next_step)
                return
            except ActionPageError:
                await run_session_checkpoint(checkpoint, next_step)

        def step_for_diagnostic(step: dict[str, Any] | None, index: int | None) -> dict[str, Any] | None:
            if not isinstance(step, dict):
                return None
            enriched = dict(step)
            if index is not None:
                enriched["__cotasync_step_index"] = index
            return enriched

        first_step = step_for_diagnostic(steps[0] if steps and isinstance(steps[0], dict) else None, 0)
        await run_session_checkpoint("before_action_auth_check", first_step)
        for step_index, step in enumerate(steps):
            if time.monotonic() >= action_deadline:
                diagnostic = {
                    "step_index": step_index,
                    "action_type": "timeout",
                    "target_label": "Ação",
                    "wait_strategy": "action_timeout",
                    "waited_ms": action_timeout_ms,
                    "result": "timeout",
                    "condition": (
                        "COTASYNC_LONG_ACTION_MAX_SECONDS"
                        if action_browser_mode == "desktop_browser"
                        else "COTASYNC_ACTION_TIMEOUT_SECONDS"
                    ),
                }
                raise DemoReplayStepError(
                    "O sistema demorou para abrir a próxima tela dentro do tempo total da ação.",
                    {
                        "step_diagnostics": [diagnostic],
                        "checkpoint_diagnostics": checkpoint_diagnostics,
                        "session_state": last_session_state,
                        "recovery_attempts": total_recovery_attempts,
                        "recovery_steps": recovery_steps,
                        "last_page_title": last_page_title,
                        "current_host": current_host,
                        "recovery_attempted": recovery_attempted,
                        "step_trace": step_trace,
                        "last_successful_step_index": last_successful_step_index,
                        "retryable": True,
                    },
                )
            if not isinstance(step, dict):
                continue
            next_step = (
                steps[step_index + 1]
                if step_index + 1 < len(steps) and isinstance(steps[step_index + 1], dict)
                else None
            )
            current_step_diagnostic = step_for_diagnostic(step, step_index)
            next_step_diagnostic = step_for_diagnostic(next_step, step_index + 1 if next_step is not None else None)
            step_type = str(step.get("tipo") or "").strip().lower()
            selector = str(step.get("seletor") or "").strip()
            step_diag: dict[str, Any] | None = None
            trace_item: dict[str, Any] = {}
            step_started_at = time.monotonic()
            try:
                step_expected_url = _expected_replay_url(step.get("expected_url_before") or expected_url)
                if action_browser_mode == "desktop_browser":
                    await run_session_checkpoint("before_step_auth_check", current_step_diagnostic)
                else:
                    authenticated, revalidated = await self._revalidate_for_replay(session, step_expected_url)
                    automatically_revalidated = automatically_revalidated or revalidated
                    if not authenticated:
                        raise DemoSessionError("A sessao nao esta autenticada para executar a rotina.")
                page = session.page
                await page.wait_for_load_state("domcontentloaded", timeout=_REPLAY_STEP_TIMEOUT_MS)
                trace_item = {
                    "step_index": step_index,
                    "step_type": step_type,
                    "selector": selector,
                    "variable_key": str(step.get("variavel") or ""),
                    "value_template": str(step.get("valor") or ""),
                    "current_url": _safe_page_url(page.url),
                    "current_host": _safe_url_host(page.url),
                    "title": await self._current_title(page),
                    "timestamp": datetime.now(UTC).isoformat(),
                    "status": "running",
                }
                step_trace.append(trace_item)
                if action_browser_mode == "desktop_browser":
                    await validate_or_allow_learned_microsoft_step(current_step_diagnostic, "before_step_page_check")
                if (
                    action_browser_mode != "desktop_browser"
                    and (not _page_matches_url(page, step_expected_url) or not await self._page_is_authenticated(session, page))
                ):
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
                has_learned_click_text = bool(
                    step_type == "clicar"
                    and (
                        str(step.get("target_text") or "").strip()
                        or str(step.get("target_label") or "").strip()
                    )
                )
                if step_type != "extrair_texto" and (selector or has_learned_click_text):
                    locator, state = await self._wait_actionable_locator(page, selector, step)
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
                elif step_type == "selecionar":
                    variable = str(step.get("variavel") or "").strip()
                    value = variables.get(variable) if variable else step.get("valor", "")
                    if variable and (value is None or str(value) == ""):
                        raise DemoSessionError(f"Valor obrigatorio ausente: {variable}.")
                    assert locator is not None
                    await locator.select_option(str(value), timeout=_REPLAY_STEP_TIMEOUT_MS)
                    step_diagnostics.append(
                        await self._finish_step_diagnostic(
                            session.page,
                            step_diag,
                            wait_strategy="actionable_select",
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
                            if action_browser_mode == "desktop_browser":
                                await run_session_checkpoint("after_new_page_check", next_step_diagnostic)
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
                    if action_browser_mode == "desktop_browser":
                        await run_session_checkpoint("before_extraction_check")
                    label = str(step.get("nome") or selector)
                    result = "success"
                    try:
                        if selector:
                            locator, _state = await self._wait_actionable_locator(
                                page,
                                selector,
                                step,
                                require_enabled=False,
                            )
                            await locator.wait_for(state="visible", timeout=_REPLAY_STEP_TIMEOUT_MS)
                            text = await locator.inner_text(timeout=_REPLAY_STEP_TIMEOUT_MS)
                        else:
                            text = await self._extract_text_near_label(
                                page,
                                str(step.get("target_label") or label),
                                step,
                            )
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
                    await validate_or_allow_learned_microsoft_step(next_step_diagnostic, "after_step_stability_check")
                if trace_item:
                    trace_item.update(
                        {
                            "status": "success",
                            "elapsed_ms": max(0, int((time.monotonic() - step_started_at) * 1000)),
                            "current_url": _safe_page_url(session.page.url),
                            "current_host": _safe_url_host(session.page.url),
                            "title": await self._current_title(session.page),
                        }
                    )
                    last_successful_step_index = step_index
            except ActionPageError as exc:
                if trace_item:
                    trace_item.update(
                        {
                            "status": "error",
                            "elapsed_ms": max(0, int((time.monotonic() - step_started_at) * 1000)),
                            "current_url": _safe_page_url(session.page.url),
                            "current_host": _safe_url_host(session.page.url),
                            "title": await self._current_title(session.page),
                            "error_message": str(exc)[:500],
                        }
                    )
                raise DemoSessionError(str(exc)) from exc
            except SessionGuardianError as exc:
                if trace_item:
                    trace_item.update(
                        {
                            "status": "error",
                            "elapsed_ms": max(0, int((time.monotonic() - step_started_at) * 1000)),
                            "current_url": _safe_page_url(session.page.url),
                            "current_host": _safe_url_host(session.page.url),
                            "title": await self._current_title(session.page),
                            "error_message": str(exc)[:500],
                        }
                    )
                if step_diag is not None:
                    step_diagnostics.append(
                        await self._finish_step_diagnostic(
                            session.page,
                            step_diag,
                            wait_strategy=str(step_diag.get("wait_strategy") or "session_checkpoint"),
                            result="error",
                            error=str(exc),
                        )
                    )
                diagnostics = dict(exc.diagnostics)
                diagnostics["step_diagnostics"] = step_diagnostics
                diagnostics["selector_diagnostics"] = selector_diagnostics
                diagnostics["step_trace"] = step_trace
                diagnostics["last_successful_step_index"] = last_successful_step_index
                raise DemoReplayStepError(str(exc), diagnostics) from exc
            except DemoSessionError:
                if trace_item:
                    trace_item.update(
                        {
                            "status": "error",
                            "elapsed_ms": max(0, int((time.monotonic() - step_started_at) * 1000)),
                            "current_url": _safe_page_url(session.page.url),
                            "current_host": _safe_url_host(session.page.url),
                            "title": await self._current_title(session.page),
                        }
                    )
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
                if trace_item:
                    trace_item.update(
                        {
                            "status": "error",
                            "elapsed_ms": max(0, int((time.monotonic() - step_started_at) * 1000)),
                            "current_url": _safe_page_url(session.page.url),
                            "current_host": _safe_url_host(session.page.url),
                            "title": await self._current_title(session.page),
                            "screenshot_path": diagnostics.get("screenshot_path", ""),
                            "error_message": str(exc)[:500],
                        }
                    )
                raise DemoReplayStepError(
                    f"Falha ao executar o passo '{step_type}'. Consulte o diagnostico da run.",
                    {
                        "selector_diagnostics": [diagnostics],
                        "step_diagnostics": step_diagnostics,
                        "step_trace": step_trace,
                        "checkpoint_diagnostics": checkpoint_diagnostics,
                        "session_state": last_session_state,
                        "recovery_attempts": total_recovery_attempts,
                        "recovery_steps": recovery_steps,
                        "last_page_title": last_page_title,
                        "current_host": current_host,
                        "recovery_attempted": recovery_attempted,
                        "last_successful_step_index": last_successful_step_index,
                        "retryable": isinstance(exc, PlaywrightTimeoutError),
                    },
                ) from exc

        if action_browser_mode == "desktop_browser":
            await run_session_checkpoint("final_auth_check")
            try:
                validate_action_page_url(action, session.page.url)
            except ActionPageError as exc:
                raise DemoSessionError(str(exc)) from exc

        evidence_path = _DATA_DIR / "runs" / f"{run_id}.png"
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        await session.page.screenshot(path=str(evidence_path), full_page=False)
        final_title = (await session.page.title()).strip()[:200]
        final_page_text = ""
        final_page_dom = ""
        try:
            final_page_text = (await session.page.locator("body").inner_text(timeout=5000)).strip()[:20000]
        except Exception:
            final_page_text = ""
        try:
            final_page_dom = (await session.page.content()).strip()[:50000]
        except Exception:
            final_page_dom = ""
        extraction_attention: dict[str, Any] = {}
        contract = extraction_contract_from_action(action)
        if contract:
            contract_result = extract_with_contract(final_page_dom, final_page_text, contract)
            contract_value = str(contract_result.get("value") or "").strip()
            contract_key = str(
                contract.get("target_name")
                or contract.get("screen_label")
                or contract.get("selected_text")
                or "resultado"
            ).strip()
            if contract_key and contract_value:
                extracted[contract_key] = contract_value
            if contract_result.get("needs_attention"):
                extraction_attention = {
                    "needs_attention": True,
                    "contract": contract,
                    "validation": contract_result.get("validation", {}),
                    "candidate": contract_result.get("candidate", {}),
                }
        logger.info("Replay concluido na sessao %s, run %s", session_id, run_id)
        result_payload = {
            "texto": "Execucao assistida concluida com sucesso.",
            "evidencia": str(evidence_path.relative_to(_ROOT)),
            "dados_extraidos": extracted,
            "arquivos": [str(item["path"]) for item in downloaded_files],
            "downloaded_files": downloaded_files,
            "main_file": downloaded_files[0] if downloaded_files else None,
            "passos_executados": len(steps),
            "session_revalidated": automatically_revalidated,
            "session_state": last_session_state or "authenticated_system",
            "recovery_attempts": total_recovery_attempts,
            "recovery_steps": recovery_steps,
            "recovery_attempted": recovery_attempted,
            "operator_action_required": False,
            "variables_used": sorted(str(key) for key in variables.keys()),
            "selector_diagnostics": selector_diagnostics,
            "step_diagnostics": step_diagnostics,
            "step_trace": step_trace,
            "checkpoint_diagnostics": checkpoint_diagnostics,
            "input_variables": {str(key): "[informado]" for key in variables.keys()},
            "last_successful_step_index": last_successful_step_index,
            "browser_mode": action_browser_mode,
            "runner": "demo_session_replay",
            "whether_fast_track_used": False,
            "whether_desktop_browser_used": action_browser_mode == "desktop_browser",
            "retryable": False,
            "evidence": str(evidence_path.relative_to(_ROOT)),
            "final_page": {"title": final_title, "url": _safe_page_url(session.page.url)},
            "final_page_text": final_page_text,
            "final_page_dom": final_page_dom,
        }
        if extraction_attention:
            result_payload["extraction_attention"] = extraction_attention
        return result_payload

    def _candidate_frames_for_step(self, page: Page, step: dict[str, Any]) -> list[Frame]:
        frames = list(page.frames)
        frame_url = _safe_page_url(str(step.get("frame_url") or ""))
        frame_name = str(step.get("frame_name") or "").strip()
        preferred: list[Frame] = []
        if frame_url or frame_name:
            for frame in frames:
                metadata = _frame_metadata(frame)
                if frame_url and metadata.get("frame_url") == frame_url:
                    preferred.append(frame)
                elif frame_name and metadata.get("frame_name") == frame_name:
                    preferred.append(frame)
        preferred_ids = {id(frame) for frame in preferred}
        return preferred + [frame for frame in frames if id(frame) not in preferred_ids]

    async def _extract_text_near_label(self, page: Page, label: str, step: dict[str, Any]) -> str:
        label_text = str(label or "").strip()
        if not label_text:
            return ""
        script = """() => ({
          html: String(document.documentElement ? document.documentElement.outerHTML || '' : ''),
          text: String(document.body ? document.body.innerText || '' : '')
        })"""
        for owner in [page] + self._candidate_frames_for_step(page, step):
            try:
                snapshot = await owner.evaluate(script)
            except Exception:
                continue
            if isinstance(snapshot, dict):
                value = extract_value_near_label(
                    f"{snapshot.get('html') or ''}\n{snapshot.get('text') or ''}",
                    label_text,
                )
            else:
                value = extract_value_near_label(snapshot, label_text)
            if str(value or "").strip():
                return str(value).strip()
        return ""

    async def _wait_actionable_locator(
        self,
        page: Page,
        selector: str,
        step: dict[str, Any] | None = None,
        *,
        require_enabled: bool = True,
    ) -> tuple[Locator, dict[str, Any]]:
        step_data = step if isinstance(step, dict) else {}
        owners: list[Page | Frame] = [page] + self._candidate_frames_for_step(page, step_data)
        if not selector:
            fallback = await self._wait_learned_text_locator(
                owners,
                step_data,
                require_enabled=require_enabled,
            )
            if fallback is not None:
                return fallback
            raise PlaywrightTimeoutError("Passo de clique aprendido sem seletor e sem texto visivel.")
        selected_owner: Page | Frame | None = None
        for owner in owners:
            try:
                if await owner.locator(selector).count() > 0:
                    selected_owner = owner
                    break
            except Exception:
                continue
        if selected_owner is None:
            selected_owner = page
        locator = selected_owner.locator(selector).first
        try:
            await locator.wait_for(state="visible", timeout=_REPLAY_STEP_TIMEOUT_MS)
        except PlaywrightTimeoutError:
            fallback = await self._wait_learned_text_locator(
                owners,
                step_data,
                require_enabled=require_enabled,
            )
            if fallback is not None:
                return fallback
            raise
        deadline = asyncio.get_running_loop().time() + (_REPLAY_STEP_TIMEOUT_MS / 1000)
        while require_enabled and not await locator.is_enabled():
            if asyncio.get_running_loop().time() >= deadline:
                raise PlaywrightTimeoutError(f"Seletor nao ficou habilitado: {selector}")
            await page.wait_for_timeout(100)
        state = await self._selector_state(selected_owner, selector)
        if isinstance(selected_owner, Frame):
            state.update(_frame_metadata(selected_owner))
        return locator, state

    async def _wait_learned_text_locator(
        self,
        owners: list[Page | Frame],
        step_data: dict[str, Any],
        *,
        require_enabled: bool = True,
    ) -> tuple[Locator, dict[str, Any]] | None:
        if str(step_data.get("tipo") or "").strip().lower() != "clicar":
            return None
        texts: list[str] = []
        seen: set[str] = set()
        for key in ("target_text", "target_label"):
            text = str(step_data.get(key) or "").strip()
            lowered = text.casefold()
            if text and lowered not in seen:
                seen.add(lowered)
                texts.append(text)
        if not texts:
            return None
        for owner in owners:
            for text in texts:
                for method_name in ("get_by_text", "get_by_label"):
                    method = getattr(owner, method_name, None)
                    if method is None:
                        continue
                    try:
                        locator = method(text, exact=False).first
                        count = await locator.count()
                        if count <= 0:
                            continue
                        await locator.wait_for(state="visible", timeout=2500)
                        deadline = asyncio.get_running_loop().time() + 2.5
                        while require_enabled and not await locator.is_enabled():
                            if asyncio.get_running_loop().time() >= deadline:
                                break
                            wait_page = owner.page if isinstance(owner, Frame) else owner
                            await wait_page.wait_for_timeout(100)
                        if require_enabled and not await locator.is_enabled():
                            continue
                        current_url = owner.page.url if isinstance(owner, Frame) else owner.url
                        state: dict[str, Any] = {
                            "current_url": _safe_page_url(current_url),
                            "selector": str(step_data.get("seletor") or ""),
                            "count": count,
                            "visible": True,
                            "enabled": not require_enabled or await locator.is_enabled(),
                            "fallback": method_name,
                            "target_text": text,
                        }
                        if isinstance(owner, Frame):
                            state.update(_frame_metadata(owner))
                        return locator, state
                    except Exception:
                        continue
        return None

    async def _selector_state(self, page: Page | Frame, selector: str) -> dict[str, Any]:
        locator = page.locator(selector)
        count = await locator.count()
        first = locator.first
        visible = await first.is_visible() if count else False
        enabled = await first.is_enabled() if count else False
        current_url = page.url if isinstance(page, Page) else page.page.url
        return {
            "current_url": _safe_page_url(current_url),
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
        try:
            evidence_path = _DATA_DIR / "runs" / f"{run_id}_step_{step_index}_{_safe_file_name(step_type)}_error.png"
            evidence_path.parent.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(evidence_path), full_page=False, timeout=_REPLAY_STEP_TIMEOUT_MS)
            diagnostics["screenshot_path"] = str(evidence_path.relative_to(_ROOT))
        except Exception as exc:
            logger.warning(
                "Falha ao salvar screenshot de erro do replay no passo %s: %s",
                step_index,
                type(exc).__name__,
            )
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
