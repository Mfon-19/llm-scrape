"""Browser automation utilities for the scraping engine."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

import httpx

from .types import InteractionStep, PageContent

logger = logging.getLogger(__name__)

try:  # pragma: no cover - optional dependency is exercised at runtime
    from playwright.async_api import (  # type: ignore
        TimeoutError as PlaywrightTimeoutError,
        Page,
        async_playwright,
    )
except Exception:  # pragma: no cover - handled gracefully in runtime paths
    PlaywrightTimeoutError = Exception  # type: ignore[assignment]
    Page = object  # type: ignore[assignment]
    async_playwright = None  # type: ignore[assignment]


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass
class BrowserSettings:
    """Settings controlling browser automation."""

    browser: str = "chromium"
    headless: bool = True
    navigation_timeout_ms: int = 20_000
    wait_until: str = "networkidle"
    max_concurrent_pages: int = 2
    viewport: Tuple[int, int] = (1280, 720)
    auto_scroll_pause: float = 0.35


class BrowserCollector:
    """Fetch rendered pages using Playwright with graceful degradation."""

    def __init__(
        self,
        *,
        settings: Optional[BrowserSettings] = None,
        http_timeout: float = 15.0,
        http_headers: Optional[dict] = None,
    ) -> None:
        self._settings = settings or BrowserSettings()
        self._http_fallback = _HttpFallbackFetcher(timeout=http_timeout, headers=http_headers)

    async def fetch_all(
        self,
        urls: Iterable[str],
        interactions: Sequence[InteractionStep],
    ) -> Tuple[List[PageContent], List[str], dict]:
        urls_list = list(dict.fromkeys(urls))
        if not urls_list:
            return [], [], {"transport": "browser"}

        warnings: List[str] = []

        if async_playwright is None:
            warnings.append("Playwright is unavailable; falling back to HTTP fetching.")
            pages = await self._http_fallback.fetch_all(urls_list)
            return pages, warnings, {"transport": "http"}

        try:
            async with BrowserSession(self._settings) as session:
                semaphore = asyncio.Semaphore(max(1, self._settings.max_concurrent_pages))

                async def run(url: str) -> PageContent:
                    async with semaphore:
                        return await session.open(url, interactions)

                tasks = [asyncio.create_task(run(url)) for url in urls_list]
                results = await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as exc:  # pragma: no cover - depends on runtime environment
            logger.exception("Browser automation failed; using HTTP fallback.")
            warnings.append(
                "Browser automation failed; falling back to static HTTP fetching."
                f" ({exc.__class__.__name__}: {exc})",
            )
            pages = await self._http_fallback.fetch_all(urls_list)
            return pages, warnings, {"transport": "http"}

        pages: List[PageContent] = []
        fallback_urls: List[str] = []
        for url, result in zip(urls_list, results):
            if isinstance(result, Exception):
                warnings.append(f"{url}: browser task raised {result!r}; using HTTP fallback.")
                fallback = await self._http_fallback.fetch_all([url])
                pages.extend(fallback)
                fallback_urls.append(url)
            else:
                pages.append(result)

        metadata = {"transport": "browser"}
        if fallback_urls:
            metadata["fallback_urls"] = fallback_urls
        return pages, warnings, metadata


class BrowserSession:
    """Thin wrapper around Playwright to orchestrate automation flows."""

    def __init__(self, settings: BrowserSettings) -> None:
        if async_playwright is None:  # pragma: no cover - guarded earlier
            raise RuntimeError("Playwright is not installed.")
        self._settings = settings
        self._playwright = None
        self._browser = None
        self._context = None

    async def __aenter__(self) -> "BrowserSession":
        self._playwright = await async_playwright().start()
        browser_getter = getattr(self._playwright, self._settings.browser)
        self._browser = await browser_getter.launch(headless=self._settings.headless)
        viewport = {"width": self._settings.viewport[0], "height": self._settings.viewport[1]}
        self._context = await self._browser.new_context(viewport=viewport, ignore_https_errors=True)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - teardown
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def open(self, url: str, interactions: Sequence[InteractionStep]) -> PageContent:
        if not self._context:  # pragma: no cover - safety guard
            raise RuntimeError("Browser context has not been initialized.")

        page = await self._context.new_page()
        try:
            response = await page.goto(
                url,
                wait_until=self._settings.wait_until,
                timeout=self._settings.navigation_timeout_ms,
            )
            await self._perform_interactions(page, interactions)
            html = await page.content()
            final_url = page.url
            status = response.status if response else None
            return PageContent(url=url, final_url=final_url, status_code=status, html=html, error=None)
        except PlaywrightTimeoutError as exc:
            return PageContent(url=url, final_url=url, status_code=None, html="", error=f"timeout: {exc}")
        except Exception as exc:  # noqa: BLE001 - propagate as payload error
            return PageContent(url=url, final_url=url, status_code=None, html="", error=str(exc))
        finally:
            await page.close()

    async def _perform_interactions(self, page: Page, interactions: Sequence[InteractionStep]) -> None:
        for step in interactions:
            try:
                if step.kind == "scroll":
                    await self._scroll(page, count=max(1, step.count), pause=step.wait_ms / 1000 if step.wait_ms else None)
                elif step.kind == "wait_for_selector" and step.selector:
                    await page.wait_for_selector(step.selector, timeout=self._settings.navigation_timeout_ms)
                elif step.kind == "wait":
                    await asyncio.sleep(max(step.wait_ms, 0) / 1000 if step.wait_ms else self._settings.auto_scroll_pause)
                elif step.kind == "click" and step.selector:
                    await page.click(step.selector, timeout=self._settings.navigation_timeout_ms)
                elif step.kind == "type" and step.selector and step.value is not None:
                    await page.fill(step.selector, step.value, timeout=self._settings.navigation_timeout_ms)
                # Unrecognized actions are ignored but logged for transparency.
                else:
                    if step.kind not in {"scroll", "wait_for_selector", "wait", "click", "type"}:
                        logger.debug("Ignoring unsupported interaction step: %s", step)
            except Exception as exc:  # pragma: no cover - depends on site behaviour
                logger.warning("Interaction '%s' failed on %s: %s", step.kind, page.url, exc)

    async def _scroll(self, page: Page, *, count: int, pause: Optional[float]) -> None:
        for _ in range(count):
            await page.mouse.wheel(0, 8000)
            await asyncio.sleep(pause or self._settings.auto_scroll_pause)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight);")


class _HttpFallbackFetcher:
    """Fallback HTML fetcher used when browser automation is unavailable."""

    def __init__(self, *, timeout: float, headers: Optional[dict]) -> None:
        self._timeout = timeout
        self._headers = {**DEFAULT_HEADERS, **(headers or {})}
        self._limits = httpx.Limits(max_connections=6, max_keepalive_connections=6)

    @asynccontextmanager
    async def client(self) -> httpx.AsyncClient:
        async with httpx.AsyncClient(headers=self._headers, timeout=self._timeout, limits=self._limits, follow_redirects=True) as client:
            yield client

    async def fetch_all(self, urls: Iterable[str]) -> List[PageContent]:
        urls_list = list(urls)
        if not urls_list:
            return []

        async with self.client() as client:
            tasks = [self._fetch_single(client, url) for url in urls_list]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        pages: List[PageContent] = []
        for url, result in zip(urls_list, results):
            if isinstance(result, Exception):
                pages.append(PageContent(url=url, final_url=url, status_code=None, html="", error=str(result)))
            else:
                pages.append(result)
        return pages

    async def _fetch_single(self, client: httpx.AsyncClient, url: str) -> PageContent:
        try:
            response = await client.get(url)
            response.raise_for_status()
            final_url = str(response.url)
            return PageContent(
                url=url,
                final_url=final_url,
                status_code=response.status_code,
                html=response.text,
                error=None,
            )
        except httpx.HTTPStatusError as exc:
            return PageContent(
                url=url,
                final_url=str(exc.response.url),
                status_code=exc.response.status_code,
                html=exc.response.text,
                error=f"HTTP {exc.response.status_code}: {exc.response.reason_phrase}",
            )
        except Exception as exc:  # noqa: BLE001 - propagate as payload error
            return PageContent(url=url, final_url=url, status_code=None, html="", error=str(exc))
