"""DOM analysis and data extraction routines."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Iterable, List, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .types import FieldSpec, ScrapePlan

_TEXT_SPLIT_RE = re.compile(r"[\s/|>]+")
_NUMERIC_RE = re.compile(r"(?:[$€£]\s?)?\d[\d,]*(?:\.\d+)?")
_DATE_PATTERNS = [
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b\d{2}/\d{2}/\d{4}\b"),
    re.compile(r"\b\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{4}\b", re.IGNORECASE),
]


class PageAnalyzer:
    """Understand a page's structure and extract target fields."""

    ATTRIBUTE_TOKENS = (
        "class",
        "id",
        "name",
        "itemprop",
        "data-testid",
        "data-field",
        "data-component",
        "data-name",
        "aria-label",
        "rel",
        "property",
        "role",
    )

    def __init__(self) -> None:
        pass

    def extract_items(self, html: str, plan: ScrapePlan, *, base_url: str) -> Tuple[List[dict], List[str]]:
        soup = BeautifulSoup(html, "html.parser")
        warnings: List[str] = []

        candidate_groups = self._find_repeating_groups(soup)
        if not candidate_groups:
            warnings.append("No repeating layout detected; falling back to whole-page extraction.")
            item = self._extract_from_node(soup, plan.fields, base_url)
            return ([item] if item else [], warnings)

        # Try groups in order of highest repetition first.
        for group in candidate_groups:
            items: List[dict] = []
            for element in group:
                record = self._extract_from_node(element, plan.fields, base_url)
                if record:
                    items.append(record)
            if items:
                return items, warnings

        warnings.append("Structured clusters did not yield data; using single-shot extraction.")
        item = self._extract_from_node(soup, plan.fields, base_url)
        return ([item] if item else [], warnings)

    # ------------------------------------------------------------------
    # Container analysis
    # ------------------------------------------------------------------

    def _find_repeating_groups(self, soup: BeautifulSoup) -> List[List[Tag]]:
        signature_map: dict[Tuple[str, Tuple[str, ...], str], List[Tag]] = {}
        candidate_tags = ["article", "li", "tr", "section", "div"]
        for element in soup.find_all(candidate_tags):
            signature = self._signature(element)
            if not signature:
                continue
            signature_map.setdefault(signature, []).append(element)

        groups = [elements for elements in signature_map.values() if len(elements) >= 2]
        groups.sort(key=len, reverse=True)
        # Limit to the top few groups to avoid over-processing.
        return groups[:5]

    def _signature(self, element: Tag) -> Tuple[str, Tuple[str, ...], str] | None:
        classes = tuple(sorted(element.get("class", [])))
        role = element.get("role", "")
        if not classes and not role and element.name not in {"article", "li", "tr"}:
            return None
        return (element.name, classes, role)

    # ------------------------------------------------------------------
    # Field extraction
    # ------------------------------------------------------------------

    def _extract_from_node(self, node: Tag | BeautifulSoup, fields: Iterable[FieldSpec], base_url: str) -> dict:
        record: dict = {}
        for field in fields:
            value = self._extract_field(node, field, base_url)
            if value:
                record[field.name] = value
        return record

    def _extract_field(self, node: Tag | BeautifulSoup, field: FieldSpec, base_url: str) -> str | None:
        selector_value = self._extract_using_selectors(node, field, base_url)
        if selector_value:
            return selector_value.strip()

        extractor = {
            "link": self._extract_link,
            "image": self._extract_image,
            "numeric": self._extract_numeric,
            "date": self._extract_date,
        }.get(field.value_type, self._extract_text)
        value = extractor(node, field, base_url)
        if value:
            return value.strip()
        return None

    def _extract_using_selectors(self, node: Tag | BeautifulSoup, field: FieldSpec, base_url: str) -> str | None:
        selectors = self._candidate_selectors(field)
        if not selectors:
            return None

        for selector in selectors:
            matches = node.select(selector)
            if not matches:
                continue
            if field.value_type == "link":
                for element in matches:
                    href = element.get("href")
                    if href:
                        return urljoin(base_url, href)
            elif field.value_type == "image":
                for element in matches:
                    attr_names = field.attribute_preferences or ["src", "data-src", "data-original"]
                    for attr in attr_names:
                        value = element.get(attr)
                        if value:
                            return urljoin(base_url, value)
            else:
                for element in matches:
                    text = element.get_text(" ", strip=True)
                    if not text:
                        continue
                    if field.value_type == "numeric":
                        match = _NUMERIC_RE.search(text)
                        if match:
                            return match.group(0)
                    else:
                        return text
        return None

    def _extract_text(self, node: Tag | BeautifulSoup, field: FieldSpec, base_url: str) -> str | None:
        best_score = 0.0
        best_value: str | None = None
        for element in self._iter_elements(node):
            text = element.get_text(" ", strip=True)
            if not text:
                continue
            score = self._score_element(element, field, text)
            if score > 0.6 and (score > best_score or best_value is None):
                best_score = score
                best_value = text

        if best_value:
            return best_value

        # Fallback: pick the most informative chunk of text.
        text_content = node.get_text(" ", strip=True)
        if field.allow_partial and text_content:
            return " ".join(text_content.split()[:30])
        return None

    def _extract_numeric(self, node: Tag | BeautifulSoup, field: FieldSpec, base_url: str) -> str | None:
        best_value = None
        best_score = 0.0
        for element in self._iter_elements(node):
            text = element.get_text(" ", strip=True)
            if not text:
                continue
            match = _NUMERIC_RE.search(text)
            if not match:
                continue
            score = self._score_element(element, field, text)
            if score > 0.45 and score >= best_score:
                best_score = score
                best_value = match.group(0)
        if best_value:
            return best_value

        fallback = _NUMERIC_RE.search(node.get_text(" ", strip=True))
        if fallback:
            return fallback.group(0)
        return None

    def _extract_date(self, node: Tag | BeautifulSoup, field: FieldSpec, base_url: str) -> str | None:
        for element in self._iter_elements(node):
            text = element.get_text(" ", strip=True)
            if not text:
                continue
            for pattern in _DATE_PATTERNS:
                match = pattern.search(text)
                if match and self._score_element(element, field, text) > 0.4:
                    return match.group(0)
        text = node.get_text(" ", strip=True)
        for pattern in _DATE_PATTERNS:
            match = pattern.search(text)
            if match:
                return match.group(0)
        return None

    def _extract_link(self, node: Tag | BeautifulSoup, field: FieldSpec, base_url: str) -> str | None:
        best_value = None
        best_score = 0.0
        for element in node.find_all("a"):
            href = element.get("href")
            if not href:
                continue
            score = self._score_element(element, field, element.get_text(" ", strip=True))
            if score > 0.4 and score >= best_score:
                best_score = score
                best_value = urljoin(base_url, href)
        return best_value

    def _extract_image(self, node: Tag | BeautifulSoup, field: FieldSpec, base_url: str) -> str | None:
        best_value = None
        best_score = 0.0
        for element in node.find_all("img"):
            candidate_attrs = field.attribute_preferences or ["src", "data-src", "data-original"]
            for attr in candidate_attrs:
                value = element.get(attr)
                if not value:
                    continue
                score = self._score_element(element, field, element.get("alt", ""))
                if score > 0.3 and score >= best_score:
                    best_score = score
                    best_value = urljoin(base_url, value)
        return best_value

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    def _iter_elements(self, node: Tag | BeautifulSoup) -> Iterable[Tag]:
        if isinstance(node, BeautifulSoup):
            yield node
            iterable = node.find_all(True)
        else:
            yield node
            iterable = node.find_all(True, recursive=True)
        for element in iterable:
            yield element

    def _score_element(self, element: Tag, field: FieldSpec, text: str) -> float:
        attr_tokens: List[str] = []
        for attr in self.ATTRIBUTE_TOKENS:
            value = element.get(attr)
            if not value:
                continue
            if isinstance(value, list):
                attr_tokens.extend(value)
            else:
                attr_tokens.extend(_TEXT_SPLIT_RE.split(str(value)))

        text_tokens = _TEXT_SPLIT_RE.split(text.lower())
        tokens = [token for token in attr_tokens + text_tokens if token]
        best = 0.0
        for token in tokens:
            for synonym in field.synonyms:
                ratio = SequenceMatcher(None, token.lower(), synonym).ratio()
                best = max(best, ratio)
        return best

    def _candidate_selectors(self, field: FieldSpec) -> List[str]:
        tokens = {field.name.lower(), *field.synonyms}
        selectors: List[str] = []
        for token in tokens:
            normalized = re.sub(r"[^a-z0-9]+", " ", token.lower()).strip()
            if not normalized:
                continue
            slug = normalized.replace(" ", "-")
            selectors.extend(
                [
                    f'[class*="{slug}"]',
                    f'[data-testid*="{slug}"]',
                    f'[data-field*="{slug}"]',
                    f'[data-name*="{slug}"]',
                    f'[aria-label*="{normalized}"]',
                    f'[itemprop="{normalized}"]',
                    f'[name*="{slug}"]',
                ]
            )
        # Remove duplicates while preserving order.
        ordered: List[str] = []
        seen = set()
        for selector in selectors:
            if selector not in seen:
                ordered.append(selector)
                seen.add(selector)
        return ordered
