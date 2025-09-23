"""Post-processing utilities for the scraping engine."""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Tuple

from .types import FieldSpec, ScrapePlan


class DataRefiner:
    """Normalize, validate, and deduplicate extracted records."""

    _WHITESPACE_RE = re.compile(r"\s+")

    def refine(self, items: List[Dict[str, str]], plan: ScrapePlan) -> Tuple[List[Dict[str, str]], Dict[str, object], List[str]]:
        if not items:
            return [], {"records_before_cleaning": 0, "records_after_cleaning": 0, "duplicates_removed": 0}, []

        cleaned: List[Dict[str, str]] = []
        seen_signatures = set()
        duplicates_removed = 0

        for item in items:
            normalized = {key: self._normalize_value(value) for key, value in item.items()}
            signature = self._signature(normalized, plan.fields)
            if signature in seen_signatures:
                duplicates_removed += 1
                continue
            seen_signatures.add(signature)
            cleaned.append(normalized)

        field_population = self._field_population(cleaned, plan.fields)
        warnings: List[str] = []
        for field, population in field_population.items():
            if population == 0:
                warnings.append(f"No values found for '{field}' after normalization.")

        stats = {
            "records_before_cleaning": len(items),
            "records_after_cleaning": len(cleaned),
            "duplicates_removed": duplicates_removed,
            "field_population": field_population,
        }

        return cleaned, stats, warnings

    def _normalize_value(self, value: str) -> str:
        if not isinstance(value, str):
            return value
        collapsed = self._WHITESPACE_RE.sub(" ", value)
        return collapsed.strip()

    def _signature(self, item: Dict[str, str], fields: Iterable[FieldSpec]) -> Tuple[str, ...]:
        signature_components: List[str] = []
        for field in fields:
            if field.value_type in {"image", "link"}:
                continue
            value = item.get(field.name, "").lower()
            signature_components.append(value)
        if not signature_components:
            signature_components = ["-".join(sorted(str(value) for value in item.values()))]
        return tuple(signature_components)

    def _field_population(self, items: List[Dict[str, str]], fields: Iterable[FieldSpec]) -> Dict[str, int]:
        population: Dict[str, int] = {}
        for field in fields:
            population[field.name] = sum(1 for item in items if item.get(field.name))
        return population
