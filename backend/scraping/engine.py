"""High-level orchestration for the scraping engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .analyzer import PageAnalyzer
from .fetcher import BrowserCollector, BrowserSettings
from .pipeline import DataRefiner
from .planner import IntentModel, PlannerSettings, PromptPlanner
from .types import FieldSpec, ScrapeOutcome, ScrapePlan, default_field_library


@dataclass
class ScrapingEngineConfig:
    """Configuration options controlling the scraping engine."""

    default_page_limit: int = 1
    max_page_limit: int = 5
    http_timeout: float = 20.0
    browser_settings: BrowserSettings = field(default_factory=BrowserSettings)
    http_headers: Optional[dict[str, str]] = None


class ScrapingEngine:
    """An intelligent data extraction system for arbitrary web pages."""

    def __init__(
        self,
        *,
        config: Optional[ScrapingEngineConfig] = None,
        field_library: Optional[dict[str, FieldSpec]] = None,
        intent_model: Optional[IntentModel] = None,
    ) -> None:
        self._config = config or ScrapingEngineConfig()
        library = field_library or default_field_library()
        self._planner = PromptPlanner(
            field_library=library,
            settings=PlannerSettings(default_fields=["title", "description", "url"]),
            intent_model=intent_model,
        )
        self._fetcher = BrowserCollector(
            settings=self._config.browser_settings,
            http_timeout=self._config.http_timeout,
            http_headers=self._config.http_headers,
        )
        self._analyzer = PageAnalyzer()
        self._refiner = DataRefiner()

    async def run(self, prompt: str, *, max_pages: Optional[int] = None) -> ScrapeOutcome:
        """Execute the scraping pipeline for the given natural language prompt."""

        plan = await self._planner.plan(prompt, max_pages=max_pages)
        effective_page_limit = self._resolve_page_limit(plan)
        urls = plan.expand_urls(effective_page_limit)

        warnings: List[str] = list(plan.notes)
        if plan.pagination is None and effective_page_limit > 1 and not plan.extra_urls:
            warnings.append(
                "Pagination requested but no pagination pattern was detected; scraping only the seed URL."
            )

        pages, fetch_warnings, fetch_metadata = await self._fetcher.fetch_all(urls, plan.interactions)
        warnings.extend(fetch_warnings)
        items: List[dict] = []
        errors: List[str] = []
        source_urls: List[str] = []

        for page in pages:
            page_url = page.final_url or page.url
            source_urls.append(page_url)
            if not page.success():
                errors.append(f"{page_url}: {page.error or 'unknown error'}")
                continue

            extracted, page_warnings = self._analyzer.extract_items(page.html, plan, base_url=page_url)
            if not extracted:
                warnings.append(f"{page_url}: no matching data located.")
            else:
                items.extend(extracted)
            warnings.extend(f"{page_url}: {message}" for message in page_warnings)

        refined_items, cleaning_stats, cleaning_warnings = self._refiner.refine(items, plan)
        warnings.extend(cleaning_warnings)

        stats = {
            "fetch": fetch_metadata,
            "cleaning": cleaning_stats,
        }

        return ScrapeOutcome(
            plan=plan,
            items=refined_items,
            warnings=warnings,
            errors=errors,
            source_urls=source_urls,
            stats=stats,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_page_limit(self, plan: ScrapePlan) -> int:
        requested = plan.requested_page_count or self._config.default_page_limit
        requested = max(1, requested)
        return min(requested, self._config.max_page_limit)
