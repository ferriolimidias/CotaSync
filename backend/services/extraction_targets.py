from __future__ import annotations

import html
import re
import unicodedata
from html.parser import HTMLParser
from typing import Any


_CELL_RE = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", re.I | re.S)
_ROW_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_ABBREVIATIONS = {
    "qtd": "Quantidade",
    "qtde": "Quantidade",
    "qde": "Quantidade",
    "pcls": "parcelas",
    "pcl": "parcela",
}
_UPPERCASE_LABELS = {"cpf", "cnpj", "rg", "id", "url"}


def normalize_label_key(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    text = re.sub(r"[^a-zA-Z0-9]+", " ", text).casefold()
    return re.sub(r"\s+", " ", text).strip()


def friendly_extraction_label(value: Any) -> str:
    raw = str(value or "").replace("_", " ").strip()
    tokens = re.findall(r"[A-Za-zÀ-ÿ0-9]+", raw)
    if not tokens:
        return raw

    words: list[str] = []
    for index, token in enumerate(tokens):
        lowered = normalize_label_key(token)
        if lowered in _ABBREVIATIONS:
            words.append(_ABBREVIATIONS[lowered])
        elif lowered in _UPPERCASE_LABELS:
            words.append(lowered.upper())
        elif index == 0:
            words.append(token[:1].upper() + token[1:].lower())
        else:
            words.append(token.lower())

    if words and words[0] == "Quantidade" and len(words) > 1 and words[1].casefold() != "de":
        words.insert(1, "de")
    return " ".join(words)


def readable_extraction_target(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("_", " ")).strip()


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"br", "div", "p", "li", "tr", "td", "th", "label", "section", "article"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"div", "p", "li", "tr", "td", "th", "label", "section", "article"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if data:
            self.parts.append(data)

    def text(self) -> str:
        return "\n".join(
            line for line in (_clean_text(part) for part in self.parts) if line
        )


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def _strip_tags(value: str) -> str:
    return _clean_text(_TAG_RE.sub(" ", value))


def _html_to_text(value: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(value)
        return parser.text()
    except Exception:
        return _strip_tags(value)


def _table_rows(value: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for row_match in _ROW_RE.finditer(value):
        cells = [_strip_tags(match.group(1)) for match in _CELL_RE.finditer(row_match.group(1))]
        cells = [cell for cell in cells if cell]
        if cells:
            rows.append(cells)
    return rows


def _target_pattern(extraction_target: str) -> str:
    tokens = re.findall(r"[A-Za-zÀ-ÿ0-9]+", str(extraction_target or ""))
    return r"[\s\W_]*".join(re.escape(token) for token in tokens)


def _clean_candidate(value: Any, target_key: str) -> str:
    candidate = _clean_text(value)
    candidate = re.sub(r"^[\s:;,\-|–—]+", "", candidate).strip()
    candidate = re.sub(r"[\s|;]+$", "", candidate).strip()
    if not candidate:
        return ""
    if normalize_label_key(candidate) == target_key:
        return ""
    if len(candidate) > 300:
        return ""
    return candidate


def _extract_from_text_line(line: str, extraction_target: str, target_key: str) -> str:
    pattern = _target_pattern(extraction_target)
    if not pattern:
        return ""
    match = re.search(
        rf"{pattern}\s*[:\-–—]?\s*(?P<value>[^\n\r;|]{{1,300}})",
        line,
        flags=re.I,
    )
    if not match:
        return ""
    return _clean_candidate(match.group("value"), target_key)


def extract_value_near_label(final_page_dom_or_text: Any, extraction_target: Any) -> str:
    """Return the visible value nearest to a configured label in final DOM/text.

    The matcher is label-driven and product-generic: it ignores accents and most
    punctuation, then checks table rows, inline `Label: value` text and the next
    visible line after an isolated label.
    """

    target = str(extraction_target or "").strip()
    if not target:
        return ""
    source = str(final_page_dom_or_text or "")
    if not source.strip():
        return ""

    target_key = normalize_label_key(target)
    for row in _table_rows(source):
        for index, cell in enumerate(row):
            cell_key = normalize_label_key(cell)
            inline = _extract_from_text_line(cell, target, target_key)
            if inline:
                return inline
            if target_key and (cell_key == target_key or target_key in cell_key):
                for next_cell in row[index + 1 :]:
                    candidate = _clean_candidate(next_cell, target_key)
                    if candidate:
                        return candidate

    text = _html_to_text(source) if "<" in source and ">" in source else source
    lines = [_clean_text(line) for line in re.split(r"[\r\n]+", text)]
    lines = [line for line in lines if line]

    for line in lines:
        candidate = _extract_from_text_line(line, target, target_key)
        if candidate:
            return candidate

    for index, line in enumerate(lines):
        line_key = normalize_label_key(line)
        if target_key and (line_key == target_key or target_key in line_key):
            for next_line in lines[index + 1 : index + 4]:
                candidate = _clean_candidate(next_line, target_key)
                if candidate:
                    return candidate
    return ""
