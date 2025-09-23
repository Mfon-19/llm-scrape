"""LLM-backed intent discovery helpers."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from .planner import IntentModel, IntentSuggestion
from .types import InteractionStep

logger = logging.getLogger(__name__)


@dataclass
class OpenAIIntentModel(IntentModel):
    """Intent discovery powered by OpenAI's Chat Completions API.

    The model requests a structured JSON response describing the target URL,
    fields, and browser interactions required to satisfy a user's prompt. If
    the API key is not configured or the request fails, ``None`` is returned so
    that heuristic planning can take over.
    """

    api_key: Optional[str] = None
    model: str = "gpt-4o-mini"
    timeout: float = 20.0

    async def analyze(self, prompt: str) -> Optional[IntentSuggestion]:
        api_key = self.api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            logger.debug("OpenAIIntentModel skipped: no API key configured.")
            return None

        payload = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an assistant that converts natural language scraping requests "
                        "into structured extraction plans. Return JSON with keys seed_url, "
                        "additional_urls, fields, max_pages, interactions, and notes."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
            except Exception as exc:  # pragma: no cover - depends on network availability
                logger.warning("OpenAI intent analysis failed: %s", exc)
                return None

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
        except (KeyError, json.JSONDecodeError) as exc:  # pragma: no cover - depends on API output
            logger.warning("Failed to parse OpenAI intent response: %s", exc)
            return None

        suggestion = self._from_payload(parsed)
        suggestion.notes.append("Intent derived from OpenAI model response.")
        return suggestion

    def _from_payload(self, payload: Dict[str, Any]) -> IntentSuggestion:
        suggestion = IntentSuggestion()
        suggestion.seed_url = self._as_optional_str(payload.get("seed_url"))
        suggestion.extra_urls = [url for url in self._as_list(payload.get("additional_urls")) if isinstance(url, str)]
        suggestion.field_names = [str(name).lower() for name in self._as_list(payload.get("fields"))]
        max_pages = payload.get("max_pages")
        if isinstance(max_pages, int):
            suggestion.max_pages = max_pages

        for raw in self._as_list(payload.get("interactions")):
            if not isinstance(raw, dict):
                continue
            kind = self._as_optional_str(raw.get("kind"))
            if not kind:
                continue
            selector = self._as_optional_str(raw.get("selector"))
            value = self._as_optional_str(raw.get("value"))
            note = self._as_optional_str(raw.get("note"))
            count = raw.get("count", 1)
            wait_ms = raw.get("wait_ms", 0)
            try:
                count_int = max(1, int(count))
            except (TypeError, ValueError):
                count_int = 1
            try:
                wait_int = max(0, int(wait_ms))
            except (TypeError, ValueError):
                wait_int = 0
            suggestion.interactions.append(
                InteractionStep(kind=kind, selector=selector, count=count_int, wait_ms=wait_int, value=value, note=note)
            )

        for note in self._as_list(payload.get("notes")):
            if isinstance(note, str):
                suggestion.notes.append(note)

        return suggestion

    def _as_optional_str(self, value: Any) -> Optional[str]:
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    def _as_list(self, value: Any) -> List[Any]:
        if isinstance(value, list):
            return value
        if value is None:
            return []
        return [value]
