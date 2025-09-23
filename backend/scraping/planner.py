"""Prompt planning utilities for the scraping engine."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Protocol
from urllib.parse import urlparse

from .types import (
    FieldSpec,
    InteractionStep,
    PaginationPlan,
    ScrapePlan,
    default_field_library,
)

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_PAGE_RANGE_RE = re.compile(r"(?:first|top)\s+(\d+)\s+pages?", re.IGNORECASE)
_GENERIC_COUNT_RE = re.compile(r"(\d+)\s+pages?", re.IGNORECASE)


class IntentModel(Protocol):
    """Interface for LLM-backed intent discovery.

    Implementations should take a natural language prompt and return an
    :class:`IntentSuggestion` describing the desired extraction intent.
    """

    async def analyze(self, prompt: str) -> Optional["IntentSuggestion"]:  # pragma: no cover - interface only
        """Return an intent suggestion for the provided prompt."""


@dataclass
class IntentSuggestion:
    """Container describing the intent extracted from a user prompt."""

    seed_url: Optional[str] = None
    extra_urls: List[str] = field(default_factory=list)
    field_names: List[str] = field(default_factory=list)
    max_pages: Optional[int] = None
    interactions: List[InteractionStep] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def merge(self, other: Optional["IntentSuggestion"]) -> "IntentSuggestion":
        """Merge another suggestion into this one and return ``self``."""

        if not other:
            return self

        if other.seed_url:
            self.seed_url = other.seed_url
        if other.extra_urls:
            extras = list(dict.fromkeys(self.extra_urls + other.extra_urls))
            self.extra_urls = extras
        if other.field_names:
            combined = list(dict.fromkeys(self.field_names + other.field_names))
            self.field_names = combined
        if other.max_pages is not None:
            self.max_pages = other.max_pages
        if other.interactions:
            merged = {(step.kind, step.selector or "", step.value or ""): step for step in self.interactions}
            for step in other.interactions:
                merged[(step.kind, step.selector or "", step.value or "")] = step
            self.interactions = list(merged.values())
        if other.notes:
            self.notes.extend(other.notes)
        return self


@dataclass
class PlannerSettings:
    """Configuration for the prompt planner."""

    default_fields: List[str]


class PromptPlanner:
    """Translate natural language prompts into actionable scraping plans."""

    def __init__(
        self,
        *,
        field_library: Optional[Dict[str, FieldSpec]] = None,
        settings: Optional[PlannerSettings] = None,
        intent_model: Optional[IntentModel] = None,
    ) -> None:
        self._library = field_library or default_field_library()
        self._settings = settings or PlannerSettings(default_fields=["title", "description", "url"])
        self._intent_model = intent_model

    async def plan(self, prompt: str, *, max_pages: Optional[int] = None) -> ScrapePlan:
        if not prompt or not prompt.strip():
            raise ValueError("Prompt cannot be empty.")

        heuristic = self._heuristic_intent(prompt, max_pages=max_pages)
        model_suggestion = await self._query_intent_model(prompt)
        intent = heuristic.merge(model_suggestion)

        if max_pages is not None:
            intent.max_pages = max_pages

        if not intent.seed_url:
            raise ValueError("No URL found in the request. Please include at least one URL.")

        fields = self._resolve_fields(intent.field_names)
        if not fields:
            defaults = [self._library[name].clone() for name in self._settings.default_fields if name in self._library]
            fields = defaults

        pagination = self._infer_pagination(intent.seed_url)
        description = self._build_description(intent.seed_url, fields, pagination, intent.max_pages, intent.interactions)

        return ScrapePlan(
            seed_url=intent.seed_url,
            fields=fields,
            description=description,
            extra_urls=intent.extra_urls,
            interactions=intent.interactions,
            pagination=pagination,
            requested_page_count=intent.max_pages,
            notes=intent.notes,
        )

    # ------------------------------------------------------------------
    # Planning helpers
    # ------------------------------------------------------------------

    async def _query_intent_model(self, prompt: str) -> Optional[IntentSuggestion]:
        if not self._intent_model:
            return None
        try:
            suggestion = await self._intent_model.analyze(prompt)
        except Exception:  # pragma: no cover - depends on external implementations
            logger.exception("Intent model failed; falling back to heuristic planner.")
            return None
        if suggestion:
            suggestion.notes.append("Intent derived from language model analysis.")
        return suggestion

    def _heuristic_intent(self, prompt: str, *, max_pages: Optional[int]) -> IntentSuggestion:
        urls = self._extract_urls(prompt)
        field_specs = self._infer_fields(prompt)
        interactions = self._infer_interactions(prompt)
        requested_pages = max_pages or self._infer_requested_pages(prompt)

        notes: List[str] = []
        if not urls:
            notes.append("Heuristic planner could not detect a URL.")

        field_names = [spec.name for spec in field_specs]
        return IntentSuggestion(
            seed_url=urls[0] if urls else None,
            extra_urls=urls[1:],
            field_names=field_names,
            max_pages=requested_pages,
            interactions=interactions,
            notes=notes,
        )

    def _extract_urls(self, prompt: str) -> List[str]:
        urls = []
        for match in _URL_RE.findall(prompt):
            cleaned = match.rstrip(".,)'\"")
            urls.append(cleaned)
        return urls

    def _infer_fields(self, prompt: str) -> List[FieldSpec]:
        prompt_lower = prompt.lower()
        tokens = set(re.findall(r"[a-zA-Z0-9]+", prompt_lower))
        selected: List[FieldSpec] = []

        for name, field in self._library.items():
            if name in tokens or any(token in field.synonyms for token in tokens):
                selected.append(field.clone())

        # Look for comma-separated lists preceding "from" as an extra hint.
        before_from = prompt_lower.split(" from ")[0]
        candidates = re.split(r"[,/]| and ", before_from)
        for candidate in candidates:
            token = candidate.strip().split()[-1:] or []
            if not token:
                continue
            value = token[0]
            for name, field in self._library.items():
                if value in field.synonyms and not any(spec.name == name for spec in selected):
                    selected.append(field.clone())

        return selected

    def _infer_requested_pages(self, prompt: str) -> Optional[int]:
        match = _PAGE_RANGE_RE.search(prompt)
        if match:
            return int(match.group(1))

        generic = _GENERIC_COUNT_RE.search(prompt)
        if generic:
            return int(generic.group(1))
        return None

    def _infer_interactions(self, prompt: str) -> List[InteractionStep]:
        prompt_lower = prompt.lower()
        interactions: List[InteractionStep] = []

        if any(keyword in prompt_lower for keyword in ["scroll", "infinite", "load more", "keep loading"]):
            interactions.append(
                InteractionStep(kind="scroll", count=5, wait_ms=400, note="Auto-scroll inferred from prompt."),
            )

        if "wait" in prompt_lower and any(word in prompt_lower for word in ["appear", "render", "load"]):
            interactions.append(
                InteractionStep(kind="wait", wait_ms=1500, note="Extra wait inferred from prompt."),
            )

        if "click" in prompt_lower and "more" in prompt_lower:
            interactions.append(
                InteractionStep(kind="click", selector="text=Load more", note="Attempt to click 'Load more'."),
            )

        return interactions

    def _infer_pagination(self, url: str) -> Optional[PaginationPlan]:
        parsed = urlparse(url)
        query = parsed.query
        if "page=" in query:
            key = self._extract_page_parameter(query)
            try:
                start = int(self._extract_query_value(query, key) or "1")
            except ValueError:
                start = 1
            return PaginationPlan(mode="query", parameter=key, start=start)

        # Detect `/page/<number>` patterns in the path.
        match = re.search(r"/page/(\d+)", parsed.path)
        if match:
            start = int(match.group(1))
            template = parsed.path[: match.start(1)] + "{page}" + parsed.path[match.end(1) :]
            return PaginationPlan(mode="path", template=template, start=start)

        return None

    def _build_description(
        self,
        seed_url: str,
        fields: Iterable[FieldSpec],
        pagination: Optional[PaginationPlan],
        requested_pages: Optional[int],
        interactions: Iterable[InteractionStep],
    ) -> str:
        field_names = ", ".join(field.name for field in fields)
        parts = [f"Extract {field_names} from {seed_url}"]
        if pagination:
            parts.append("scan paginated content")
        if requested_pages:
            parts.append(f"limit to {requested_pages} page(s)")
        actions = [step.kind for step in interactions]
        if actions:
            parts.append("pre-actions: " + ", ".join(actions))
        return "; ".join(parts)

    def _extract_page_parameter(self, query: str) -> str:
        for candidate in ["page", "p", "pg"]:
            if f"{candidate}=" in query:
                return candidate
        return "page"

    def _extract_query_value(self, query: str, key: str) -> Optional[str]:
        for chunk in query.split("&"):
            if chunk.startswith(f"{key}="):
                return chunk.split("=", 1)[1]
        return None

    def _resolve_fields(self, field_names: Iterable[str]) -> List[FieldSpec]:
        resolved: List[FieldSpec] = []
        for name in field_names:
            candidate = self._library.get(name)
            if candidate and not any(spec.name == candidate.name for spec in resolved):
                resolved.append(candidate.clone())
                continue

            for field in self._library.values():
                if name.lower() in field.synonyms and not any(spec.name == field.name for spec in resolved):
                    resolved.append(field.clone())
                    break

        return resolved
