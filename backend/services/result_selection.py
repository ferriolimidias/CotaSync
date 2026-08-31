from __future__ import annotations

import html
import json
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from backend.db import Action as DbAction, ActionVersion, SessionLocal

from backend.services.extraction_targets import normalize_label_key


SELECTION_TYPES = {"field_value", "table_footer_total", "table_cell", "block_text"}
NORMALIZATION_TYPES = {"exact_text", "digits_only"}
HEADER_WORDS = {
    "ocorrencia",
    "valor pagar",
    "parcela paga",
    "modalidad",
    "na",
    "pr",
    "rt",
}
TECHNICAL_DOM_PATTERNS = (
    "max-width",
    "webkit",
    "chrome",
    "safari",
    "css",
    "javascript",
    "function(",
    "document.",
    "window.",
    "@media",
    "font-family",
    "stylesheet",
)


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def clean_label(value: Any) -> str:
    return re.sub(r"[\s:;|\-–—]+$", "", clean_text(value)).strip()


def normalize_extracted_value(value: Any, normalization: str = "exact_text") -> dict[str, Any]:
    text = clean_text(value)
    if normalization != "digits_only":
        return {"value": text, "needs_attention": False, "reason": ""}
    groups = re.findall(r"\d+", text)
    if len(groups) == 1:
        return {"value": groups[0], "needs_attention": False, "reason": ""}
    if not groups:
        return {"value": "", "needs_attention": True, "reason": "digits_not_found"}
    return {"value": "", "needs_attention": True, "reason": "multiple_numeric_groups", "groups": groups}


def infer_value_type(target_name: Any, screen_label: Any, value: Any = "") -> str:
    text = normalize_label_key(f"{target_name} {screen_label} {value}")
    if "%" in str(screen_label or "") or "percent" in text or "porcent" in text:
        return "decimal_percent"
    if "valor" in text or "pagar" in text or "r$" in str(value or "").casefold():
        return "money"
    if re.search(r"\d+,\d+|\d+\.\d+", str(value or "")):
        return "decimal"
    if re.fullmatch(r"\d+", str(value or "").strip()):
        return "integer"
    return "text"


def _looks_numeric(value: Any) -> bool:
    text = clean_text(value)
    return bool(re.fullmatch(r"(?:R\$\s*)?-?\d{1,3}(?:\.\d{3})*(?:,\d+)?%?|-?\d+(?:,\d+)?%?", text))


def is_technical_dom_text(value: Any) -> bool:
    text = clean_text(value)
    lowered = text.casefold()
    if not text:
        return False
    if any(pattern in lowered for pattern in TECHNICAL_DOM_PATTERNS):
        return True
    if re.search(r"[{};]\s*(?:/\*|[.#]?[a-z-]+\s*:)", text, flags=re.I):
        return True
    if re.search(r"</?(?:script|style|head|meta|link)\b", text, flags=re.I):
        return True
    return False


def is_candidate_text_valid(label: Any, value: Any, value_type: str = "", avoid_labels: list[str] | None = None) -> bool:
    label_text = clean_text(label)
    value_text = clean_text(value)
    if not label_text or not value_text:
        return False
    if is_technical_dom_text(label_text) or is_technical_dom_text(value_text):
        return False
    if normalize_label_key(label_text) == normalize_label_key(value_text):
        return False
    return bool(validate_candidate_value(value_text, value_type, avoid_labels)["valid"])


def validate_candidate_value(value: Any, value_type: str = "", avoid_labels: list[str] | None = None) -> dict[str, Any]:
    text = clean_text(value)
    normalized = normalize_label_key(text)
    avoid_keys = {normalize_label_key(item) for item in (avoid_labels or [])}
    avoid_keys.update(HEADER_WORDS)
    result = {"valid": True, "needs_attention": False, "reason": ""}
    if not text:
        return {"valid": False, "needs_attention": True, "reason": "empty_value"}
    if is_technical_dom_text(text):
        return {"valid": False, "needs_attention": True, "reason": "technical_dom_text"}
    if normalized in avoid_keys:
        return {"valid": False, "needs_attention": True, "reason": "header_or_avoid_label"}
    if normalized in {"na", "pr", "rt"} and value_type not in {"status", "code", "text"}:
        return {"valid": False, "needs_attention": True, "reason": "code_like_header"}
    if value_type in {"decimal_percent", "percent", "decimal", "money", "integer", "number"} and not _looks_numeric(text):
        return {"valid": False, "needs_attention": True, "reason": "type_mismatch"}
    return result


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[dict[str, Any]]]] = []
        self._current_table: list[list[dict[str, Any]]] | None = None
        self._current_row: list[dict[str, Any]] | None = None
        self._current_cell: dict[str, Any] | None = None
        self._table_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered == "table":
            self._table_depth += 1
            if self._table_depth == 1:
                self._current_table = []
            return
        if self._table_depth <= 0:
            return
        if lowered == "tr":
            self._current_row = []
        elif lowered in {"td", "th"}:
            self._current_cell = {"tag": lowered, "text_parts": []}

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if self._table_depth <= 0:
            return
        if lowered in {"td", "th"} and self._current_cell is not None:
            self._current_cell["text"] = clean_text(" ".join(self._current_cell.pop("text_parts", [])))
            if self._current_row is not None:
                self._current_row.append(self._current_cell)
            self._current_cell = None
        elif lowered == "tr" and self._current_row is not None:
            if self._current_table is not None and any(cell.get("text") for cell in self._current_row):
                self._current_table.append(self._current_row)
            self._current_row = None
        elif lowered == "table":
            if self._table_depth == 1 and self._current_table is not None:
                self.tables.append(self._current_table)
                self._current_table = None
            self._table_depth = max(0, self._table_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None and data:
            self._current_cell["text_parts"].append(data)


def _parse_tables(html_text: Any) -> list[list[list[dict[str, Any]]]]:
    parser = _TableParser()
    try:
        parser.feed(str(html_text or ""))
    except Exception:
        return []
    return parser.tables


def _strip_tags(value: str) -> str:
    return clean_text(re.sub(r"<[^>]+>", " ", value))


def _adjacent_label_value_candidates(source: str, *, wanted: str, target_name: str = "") -> list[dict[str, Any]]:
    if not wanted:
        return []
    candidates: list[dict[str, Any]] = []
    block_pattern = re.compile(
        r"<(?P<label_tag>label|span|td|th|div)\b[^>]*>(?P<label>[^<>]{2,120}:?)</(?P=label_tag)>\s*"
        r"<(?P<value_tag>span|strong|b|td|input|textarea|select)\b(?P<attrs>[^>]*)>"
        r"(?P<value>[^<>]{0,160})",
        flags=re.I | re.S,
    )
    for match in block_pattern.finditer(source):
        label = _strip_tags(match.group("label"))
        if wanted not in normalize_label_key(label):
            continue
        attrs = match.group("attrs") or ""
        value = _strip_tags(match.group("value"))
        value_attr = re.search(r"\bvalue\s*=\s*(['\"])(.*?)\1", attrs, flags=re.I | re.S)
        if value_attr:
            value = clean_text(value_attr.group(2))
        if value:
            candidates.append(
                _candidate(
                    label,
                    value,
                    "field_value",
                    0.9,
                    target_name=target_name,
                    nearby_text=f"{label} | {value}",
                )
            )
    return candidates


def _headers_for(table: list[list[dict[str, Any]]]) -> list[str]:
    for row in table[:3]:
        if row and any(cell.get("tag") == "th" for cell in row):
            return [clean_text(cell.get("text")) for cell in row]
    return [clean_text(cell.get("text")) for cell in table[0]] if table else []


def _candidate(label: str, value: str, ctype: str, confidence: float, **extra: Any) -> dict[str, Any]:
    cleaned_label = clean_label(label)
    cleaned_value = clean_text(value)
    value_type = infer_value_type(extra.get("target_name", ""), cleaned_label, value)
    validation = validate_candidate_value(value, value_type, extra.get("avoid_labels"))
    if is_technical_dom_text(cleaned_label):
        validation = {"valid": False, "needs_attention": True, "reason": "technical_dom_text"}
    if normalize_label_key(cleaned_label) == normalize_label_key(cleaned_value):
        validation = {"valid": False, "needs_attention": True, "reason": "label_without_value"}
    return {
        "label": cleaned_label,
        "value": cleaned_value,
        "type": ctype,
        "candidate_type": ctype,
        "confidence": round(confidence, 2),
        "value_type": value_type,
        "needs_attention": bool(validation["needs_attention"]),
        "validation": validation,
        **{key: item for key, item in extra.items() if item not in (None, "", [], {})},
    }


def detect_extraction_candidates(
    final_page_dom_or_text: Any,
    *,
    target_name: str = "",
    screen_label: str = "",
    selected_element: dict[str, Any] | None = None,
    limit: int = 30,
) -> list[dict[str, Any]]:
    source = re.sub(r"<(?:script|style|head|meta|link)\b[^>]*>.*?</(?:script|style|head|meta|link)>", " ", str(final_page_dom_or_text or ""), flags=re.I | re.S)
    wanted = normalize_label_key(screen_label or target_name)
    candidates: list[dict[str, Any]] = []

    candidates.extend(_adjacent_label_value_candidates(source, wanted=wanted, target_name=target_name))

    if selected_element:
        selected = dict(selected_element)
        label = str(selected.get("candidate_label") or selected.get("column_header") or screen_label or target_name or "selecionado")
        value = str(selected.get("candidate_value") or selected.get("selected_text") or "")
        ctype = str(selected.get("candidate_type") or "block_text")
        candidates.append(_candidate(label, value, ctype, 0.99, selected=True, selected_element=selected))

    for table_index, table in enumerate(_parse_tables(source)):
        headers = _headers_for(table)
        for row_index, row in enumerate(table):
            row_text = " ".join(clean_text(cell.get("text")) for cell in row if clean_text(cell.get("text")))
            row_key = normalize_label_key(row_text)
            is_header_row = any(cell.get("tag") == "th" for cell in row)
            is_footer = not is_header_row and (
                row_index >= max(1, len(table) - 2)
                or any(word in row_key for word in ("total", "totais", "cont"))
            )
            for col_index, cell in enumerate(row):
                text = clean_text(cell.get("text"))
                if not text or is_technical_dom_text(text):
                    continue
                header = headers[col_index] if col_index < len(headers) else ""
                label_match = wanted and (wanted == normalize_label_key(text) or wanted in normalize_label_key(text))
                if label_match and not is_header_row:
                    next_values = [clean_text(item.get("text")) for item in row[col_index + 1 :] if clean_text(item.get("text"))]
                    value = next((item for item in next_values if _looks_numeric(item)), next_values[0] if next_values else text)
                    ctype = "table_footer_total" if is_footer else "table_cell"
                    candidates.append(_candidate(text, value, ctype, 0.91 if is_footer else 0.75, table_headers=headers, row_context=row_text, table_row_index=row_index, table_col_index=col_index, column_header=header))
                if header:
                    confidence = 0.7 if _looks_numeric(text) else 0.45
                    candidates.append(_candidate(header, text, "table_column_or_cell", confidence, table_headers=headers, row_context=row_text, table_row_index=row_index, table_col_index=col_index, column_header=header))

    plain = re.sub(r"<[^>]+>", "\n", source)
    lines = [clean_text(line) for line in re.split(r"[\r\n]+", plain) if clean_text(line)]
    lines = [line for line in lines if not is_technical_dom_text(line)]
    for index, line in enumerate(lines):
        match = re.match(r"(?P<label>[^:;]{2,80})[:;]\s*(?P<value>.{1,120})$", line)
        if match:
            label = match.group("label")
            value = match.group("value")
            score = 0.82 if wanted and wanted in normalize_label_key(label) else 0.5
            candidates.append(_candidate(label, value, "field_value", score, line_index=index))
        elif wanted and wanted in normalize_label_key(line):
            for value in lines[index + 1 : index + 4]:
                candidates.append(_candidate(line, value, "field_value", 0.68, line_index=index))
                break

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in sorted(candidates, key=lambda raw: float(raw.get("confidence") or 0), reverse=True):
        if not is_candidate_text_valid(
            item.get("label"),
            item.get("value"),
            str(item.get("value_type") or ""),
            item.get("avoid_labels") if isinstance(item.get("avoid_labels"), list) else None,
        ):
            continue
        key = (normalize_label_key(item.get("label")), clean_text(item.get("value")), str(item.get("type") or ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= limit:
            break
    return deduped


def build_summary_instruction(contract: dict[str, Any]) -> str:
    label = clean_text(contract.get("screen_label") or contract.get("candidate_label") or contract.get("target_name") or "resultado")
    value_hint = "valor"
    if str(contract.get("value_type") or "") == "decimal_percent":
        value_hint = f"valor de {label}"
    return (
        f"Retorne somente o {value_hint} do resultado selecionado. "
        "Não retorne cabeçalhos, ocorrência ou outros dados da tabela."
    )


def build_extraction_contract(
    *,
    target_name: str,
    screen_label: str = "",
    candidate: dict[str, Any] | None = None,
    selection_type: str = "",
    return_format: str = "somente o valor",
) -> dict[str, Any]:
    selected = candidate if isinstance(candidate, dict) else {}
    selected_element = selected.get("selected_element") if isinstance(selected.get("selected_element"), dict) else {}
    # Captures from the browser keep locator metadata under selected_element;
    # older callers may still provide those fields at the candidate root.
    selected = {**selected_element, **selected}
    ctype = selection_type or str(selected.get("type") or selected.get("candidate_type") or "field_value")
    if ctype not in SELECTION_TYPES:
        ctype = "table_cell" if "table" in ctype else "field_value"
    label = clean_text(screen_label or selected.get("label") or selected.get("candidate_label") or target_name)
    value = clean_text(selected.get("value") or selected.get("candidate_value") or selected.get("selected_text") or "")
    read_mode = str(selected.get("read_mode") or ("value" if str(selected.get("tag_name") or selected.get("tag") or "").lower() in {"input", "textarea", "select"} else "text")).strip()
    normalization = str(selected.get("normalization") or selected.get("normalization_type") or "").strip()
    if normalization not in NORMALIZATION_TYPES:
        normalization = "digits_only" if re.fullmatch(r"\d+", value) else "exact_text"
    normalized = normalize_extracted_value(value, normalization)
    value_type = str(selected.get("value_type") or infer_value_type(target_name, label, value))
    avoid_labels = ["Ocorrência", "Valor Pagar", "Parcela Paga", "Modalidad.", "NA", "PR", "RT"]
    validation = validate_candidate_value(value, value_type, avoid_labels)
    if normalized.get("needs_attention"):
        validation = {"valid": False, "needs_attention": True, "reason": normalized.get("reason") or "normalization_failed"}
    if str(selected.get("input_type") or selected.get("type_attr") or "").casefold() == "password":
        validation = {"valid": False, "needs_attention": True, "reason": "password_field"}
    if not is_candidate_text_valid(label, value, value_type, avoid_labels):
        validation = {
            "valid": False,
            "needs_attention": True,
            "reason": validation.get("reason") or "invalid_candidate",
        }
    contract = {
        "selection_type": ctype,
        "target_name": clean_text(target_name),
        "screen_label": label,
        "selected_text": clean_text(selected.get("selected_text") or selected.get("label") or label),
        "example_value": value,
        "expected_example": value,
        "value_type": value_type,
        "read_mode": read_mode if read_mode in {"value", "text"} else "text",
        "normalization": {"type": normalization},
        "selector_data": {
            "primary": clean_text(selected.get("selector") or selected.get("css_path") or selected.get("selector_hint") or ""),
            "candidates": selected.get("locator_candidates") if isinstance(selected.get("locator_candidates"), list) else [],
            "tag": clean_text(selected.get("tag_name") or selected.get("tag") or ""),
            "id": clean_text(selected.get("id") or ""),
            "name": clean_text(selected.get("name") or ""),
            "aria_label": clean_text(selected.get("aria_label") or ""),
            "placeholder": clean_text(selected.get("placeholder") or ""),
            "stable_attributes": selected.get("stable_attributes") if isinstance(selected.get("stable_attributes"), dict) else {},
        },
        "anchor_data": {
            "context_label": label,
            "nearby_text": clean_text(selected.get("nearby_text") or ""),
            "nearby_text_before": selected.get("nearby_text_before") if isinstance(selected.get("nearby_text_before"), list) else [],
            "nearby_text_after": selected.get("nearby_text_after") if isinstance(selected.get("nearby_text_after"), list) else [],
            "parent_text": clean_text(selected.get("parent_text") or "")[:1200],
            "row_context": clean_text(selected.get("row_context") or selected.get("row_text") or ""),
            "column_header": clean_text(selected.get("column_header") or ""),
        },
        "selector_hint": clean_text(selected.get("selector") or selected.get("css_path") or selected.get("selector_hint") or ""),
        "label_selector": clean_text(selected.get("label_selector") or ""),
        "value_selector": clean_text(selected.get("value_selector") or selected.get("selector") or ""),
        "region_selector": clean_text(selected.get("region_selector") or ""),
        "table_headers": selected.get("table_headers") if isinstance(selected.get("table_headers"), list) else [],
        "row_context": clean_text(selected.get("row_context") or selected.get("row_text") or ""),
        "nearby_text": clean_text(selected.get("nearby_text") or ""),
        "column_header": clean_text(selected.get("column_header") or ""),
        "table_row_index": selected.get("table_row_index"),
        "table_col_index": selected.get("table_col_index"),
        "avoid_labels": avoid_labels,
        "return_format": return_format,
        "summary_instruction": build_summary_instruction({"screen_label": label, "target_name": target_name, "value_type": value_type}),
        "needs_attention": bool(validation["needs_attention"]),
        "validation": validation,
        "created_at": utc_now_iso(),
        "source": "visual_result_selection",
    }
    return contract


def build_extraction_contract_from_confirmed_result(
    *,
    target_name: str,
    screen_label: str,
    value: str,
    return_format: str = "somente o valor",
) -> dict[str, Any]:
    label = clean_text(screen_label or target_name or "resultado")
    example = clean_text(value)
    value_type = infer_value_type(target_name, label, example)
    return build_extraction_contract(
        target_name=target_name or label,
        screen_label=label,
        candidate={"label": label, "value": example, "type": "field_value", "value_type": value_type},
        selection_type="field_value",
        return_format=return_format,
    )


def extraction_contract_from_action(action_config: dict[str, Any]) -> dict[str, Any]:
    overlay = action_config.get("reviewed_overlay") if isinstance(action_config.get("reviewed_overlay"), dict) else {}
    extraction = overlay.get("extraction") if isinstance(overlay.get("extraction"), dict) else {}
    if extraction and str(extraction.get("source") or "") == "visual_result_selection":
        return extraction
    review = action_config.get("extraction_review") if isinstance(action_config.get("extraction_review"), dict) else {}
    if review and str(review.get("source") or "") == "visual_result_selection":
        return review
    if extraction:
        return extraction
    return review


def extract_with_contract(final_page_dom: Any, final_page_text: Any, contract: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(contract, dict) or not contract:
        return {"value": "", "needs_attention": False, "source": "none"}
    source = f"{final_page_dom or ''}\n{final_page_text or ''}"
    target = clean_text(contract.get("target_name") or "")
    label = clean_text(contract.get("screen_label") or contract.get("selected_text") or target)
    candidates = detect_extraction_candidates(source, target_name=target, screen_label=label, limit=50)
    selection_type = str(contract.get("selection_type") or "")
    best = None
    for item in candidates:
        if selection_type and str(item.get("type")) != selection_type:
            continue
        if normalize_label_key(item.get("label")) == normalize_label_key(label):
            best = item
            break
    if best is None:
        for item in candidates:
            if normalize_label_key(label) in normalize_label_key(item.get("label")):
                best = item
                break
    value = clean_text(best.get("value") if isinstance(best, dict) else "")
    normalization_type = "exact_text"
    normalization = contract.get("normalization") if isinstance(contract.get("normalization"), dict) else {}
    if isinstance(normalization, dict):
        normalization_type = str(normalization.get("type") or "exact_text")
    normalized = normalize_extracted_value(value, normalization_type)
    if not best:
        return {
            "value": "",
            "needs_attention": True,
            "validation": {"valid": False, "needs_attention": True, "reason": "locator_not_found"},
            "candidate": {},
            "source": "visual_contract",
        }
    value_type = str(contract.get("value_type") or infer_value_type(target, label, value))
    validation = validate_candidate_value(value, value_type, contract.get("avoid_labels") if isinstance(contract.get("avoid_labels"), list) else None)
    if normalized.get("needs_attention"):
        validation = {"valid": False, "needs_attention": True, "reason": normalized.get("reason") or "normalization_failed"}
    return {
        "value": str(normalized.get("value") if normalization_type == "digits_only" else value),
        "needs_attention": bool(validation["needs_attention"]),
        "validation": validation,
        "candidate": best or {},
        "source": "visual_contract",
    }


def save_visual_extraction_contract(action_key: str, contract: dict[str, Any], *, path: Path | None = None) -> dict[str, Any]:
    with SessionLocal.begin() as session:
        action = session.query(DbAction).filter(DbAction.key == action_key).first()
        version = session.get(ActionVersion, action.published_version_id) if action and action.published_version_id else None
        if version is None:
            raise RuntimeError("Acao publicada nao encontrada no PostgreSQL.")
        raw = dict(version.definition or {})
        overlay = dict(raw.get("reviewed_overlay") or {})
        overlay["review_status"] = "needs_attention" if contract.get("needs_attention") else "approved"
        overlay["reviewed_at"] = utc_now_iso()
        overlay["extraction"] = contract
        overlay["summary_instruction"] = contract.get("summary_instruction") or build_summary_instruction(contract)
        raw["reviewed_overlay"] = overlay
        raw["extraction_review"] = contract
        raw["final_summary_instruction"] = overlay["summary_instruction"]
        raw["review_status"] = overlay["review_status"]
        raw["ai_review_summary"] = "Contrato visual de extração salvo pelo operador."
        version.definition = raw
        return raw


def host_from_url(url: Any) -> str:
    try:
        return urlsplit(str(url or "")).hostname or ""
    except Exception:
        return ""
