"""Core data structures for the scraping engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import ParseResult, parse_qsl, urlencode, urlparse, urlunparse


@dataclass
class FieldSpec:
    """Describes a single logical field to extract from a page."""

    name: str
    synonyms: List[str]
    value_type: str = "text"
    attribute_preferences: List[str] = field(default_factory=list)
    allow_partial: bool = False

    def __post_init__(self) -> None:
        self.synonyms = sorted({syn.lower() for syn in self.synonyms})
        self.attribute_preferences = list(dict.fromkeys(self.attribute_preferences))

    def clone(self, *, name: Optional[str] = None) -> "FieldSpec":
        """Return a shallow copy of the field specification."""

        return FieldSpec(
            name=name or self.name,
            synonyms=list(self.synonyms),
            value_type=self.value_type,
            attribute_preferences=list(self.attribute_preferences),
            allow_partial=self.allow_partial,
        )


@dataclass
class InteractionStep:
    """Describes a browser automation action executed before extraction."""

    kind: str
    selector: Optional[str] = None
    count: int = 1
    wait_ms: int = 0
    value: Optional[str] = None
    note: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "kind": self.kind,
            "selector": self.selector,
            "count": self.count,
            "wait_ms": self.wait_ms,
            "value": self.value,
            "note": self.note,
        }


@dataclass
class PaginationPlan:
    """Represents a simple pagination strategy."""

    mode: str  # "query" or "path"
    parameter: Optional[str] = None
    template: Optional[str] = None
    start: int = 1
    step: int = 1

    def to_dict(self) -> Dict[str, object]:
        return {
            "mode": self.mode,
            "parameter": self.parameter,
            "template": self.template,
            "start": self.start,
            "step": self.step,
        }

    def generate_urls(self, base_url: str, limit: int) -> List[str]:
        """Generate paginated URLs up to the provided limit."""

        if limit <= 0:
            return []

        urls: List[str] = []
        for offset in range(limit):
            page_number = self.start + offset * self.step
            if self.mode == "query" and self.parameter:
                urls.append(self._build_query_url(base_url, page_number))
            elif self.mode == "path" and self.template:
                urls.append(self._build_path_url(base_url, page_number))
            else:
                break
        return urls

    def _build_query_url(self, base_url: str, page_number: int) -> str:
        parsed = urlparse(base_url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query[self.parameter or "page"] = str(page_number)
        encoded = urlencode(query, doseq=True)
        return urlunparse(
            ParseResult(
                scheme=parsed.scheme,
                netloc=parsed.netloc,
                path=parsed.path,
                params=parsed.params,
                query=encoded,
                fragment=parsed.fragment,
            )
        )

    def _build_path_url(self, base_url: str, page_number: int) -> str:
        parsed = urlparse(base_url)
        path = (self.template or "{}").format(page=page_number)
        return urlunparse(
            ParseResult(
                scheme=parsed.scheme,
                netloc=parsed.netloc,
                path=path,
                params=parsed.params,
                query=parsed.query,
                fragment=parsed.fragment,
            )
        )


@dataclass
class ScrapePlan:
    """Contains the strategy the engine will use for a scraping job."""

    seed_url: str
    fields: List[FieldSpec]
    description: str
    extra_urls: List[str] = field(default_factory=list)
    interactions: List[InteractionStep] = field(default_factory=list)
    pagination: Optional[PaginationPlan] = None
    requested_page_count: Optional[int] = None
    notes: List[str] = field(default_factory=list)

    def summary(self) -> Dict[str, object]:
        return {
            "seed_url": self.seed_url,
            "fields": [field.name for field in self.fields],
            "description": self.description,
            "extra_urls": list(self.extra_urls),
            "interactions": [interaction.to_dict() for interaction in self.interactions],
            "pagination": self.pagination.to_dict() if self.pagination else None,
            "requested_page_count": self.requested_page_count,
            "notes": list(self.notes),
        }

    def expand_urls(self, limit: int) -> List[str]:
        """Expand the plan into concrete URLs to visit."""

        limit = max(1, limit)
        urls: List[str] = []

        # Primary seed URL with pagination support.
        if self.pagination:
            paginated = self.pagination.generate_urls(self.seed_url, limit)
            urls.extend(paginated[:limit])
        else:
            urls.append(self.seed_url)

        # Include any additional URLs requested explicitly in the prompt.
        for url in self.extra_urls:
            if len(urls) >= limit:
                break
            urls.append(url)

        # Deduplicate while preserving order.
        seen = set()
        ordered: List[str] = []
        for url in urls:
            if url not in seen:
                ordered.append(url)
                seen.add(url)
            if len(ordered) >= limit:
                break
        return ordered or [self.seed_url]


@dataclass
class PageContent:
    """Represents the outcome of fetching a page."""

    url: str
    final_url: str
    status_code: Optional[int]
    html: str
    error: Optional[str] = None

    def success(self) -> bool:
        return not self.error and bool(self.html)


@dataclass
class ScrapeOutcome:
    """Final result of a scraping attempt."""

    plan: ScrapePlan
    items: List[Dict[str, str]]
    warnings: List[str]
    errors: List[str]
    source_urls: List[str]
    stats: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        coverage: Dict[str, float] = {}
        total = len(self.items)
        if total:
            for field in self.plan.fields:
                hits = sum(1 for item in self.items if item.get(field.name))
                coverage[field.name] = round(hits / total, 3)
        else:
            for field in self.plan.fields:
                coverage[field.name] = 0.0

        metadata: Dict[str, Any] = {
            "item_count": len(self.items),
            "source_urls": self.source_urls,
            "field_coverage": coverage,
        }
        metadata.update(self.stats)

        return {
            "plan": self.plan.summary(),
            "items": self.items,
            "warnings": self.warnings,
            "errors": self.errors,
            "metadata": metadata,
        }


def default_field_library() -> Dict[str, FieldSpec]:
    """Return the built-in catalogue of supported fields."""

    return {
        "title": FieldSpec(
            name="title",
            synonyms=["title", "headline", "heading"],
            value_type="text",
        ),
        "name": FieldSpec(
            name="name",
            synonyms=["name", "names", "company", "product", "listing"],
            value_type="text",
        ),
        "description": FieldSpec(
            name="description",
            synonyms=["description", "summary", "details", "overview", "about"],
            value_type="text",
            allow_partial=True,
        ),
        "price": FieldSpec(
            name="price",
            synonyms=["price", "cost", "amount", "fee", "salary", "rate"],
            value_type="numeric",
        ),
        "rating": FieldSpec(
            name="rating",
            synonyms=["rating", "score", "review", "stars", "rank"],
            value_type="numeric",
        ),
        "date": FieldSpec(
            name="date",
            synonyms=["date", "posted", "published", "updated", "time", "deadline"],
            value_type="date",
        ),
        "author": FieldSpec(
            name="author",
            synonyms=["author", "by", "creator", "writer", "seller"],
            value_type="text",
        ),
        "location": FieldSpec(
            name="location",
            synonyms=["location", "city", "state", "country", "address", "region"],
            value_type="text",
        ),
        "url": FieldSpec(
            name="url",
            synonyms=["url", "link", "website", "websites", "href", "source"],
            value_type="link",
            attribute_preferences=["href"],
        ),
        "image": FieldSpec(
            name="image",
            synonyms=["image", "photo", "thumbnail", "picture", "logo"],
            value_type="image",
            attribute_preferences=["src", "data-src", "data-original", "data-lazy"],
        ),
        "category": FieldSpec(
            name="category",
            synonyms=["category", "type", "tag", "genre", "sector"],
            value_type="text",
        ),
    }
