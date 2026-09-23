from __future__ import annotations

import re
import time
from collections.abc import Iterator
from typing import Any

import requests

from config import OPENALEX_BASE_URL, OPENALEX_EMAIL, REQUEST_TIMEOUT


def normalize_openalex_id(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    return value.rstrip("/").split("/")[-1]


def _tokens(value: str) -> set[str]:
    stop = {"university", "college", "institute", "hospital", "school", "national", "research"}
    return {
        token
        for token in re.findall(r"[a-z0-9]+", (value or "").casefold())
        if len(token) >= 3 and token not in stop
    }


class OpenAlexClient:
    def __init__(self) -> None:
        self.session = requests.Session()
        user_agent = "AboutBio-KoreaBioMap/0.3"
        if OPENALEX_EMAIL:
            user_agent += f" (mailto:{OPENALEX_EMAIL})"
        self.session.headers.update({"User-Agent": user_agent})
        self.min_interval_seconds = 0.20
        self.max_retries = 6
        self._last_request_at = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_interval_seconds:
            time.sleep(self.min_interval_seconds - elapsed)

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = dict(params or {})
        if OPENALEX_EMAIL:
            params["mailto"] = OPENALEX_EMAIL

        url = f"{OPENALEX_BASE_URL}/{path.lstrip('/')}"
        last_error: requests.RequestException | None = None

        for attempt in range(self.max_retries):
            self._throttle()
            try:
                response = self.session.get(
                    url,
                    params=params,
                    timeout=REQUEST_TIMEOUT,
                )
                self._last_request_at = time.monotonic()

                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After", "")
                    try:
                        wait = float(retry_after)
                    except (TypeError, ValueError):
                        wait = min(2 ** attempt, 30)
                    time.sleep(max(wait, 1.0))
                    continue

                if 500 <= response.status_code < 600:
                    time.sleep(min(2 ** attempt, 20))
                    continue

                response.raise_for_status()
                return response.json()

            except requests.RequestException as exc:
                last_error = exc
                if attempt < self.max_retries - 1:
                    time.sleep(min(2 ** attempt, 20))
                    continue
                raise

        if last_error:
            raise last_error
        raise requests.HTTPError(f"OpenAlex request failed after {self.max_retries} retries: {url}")

    def get_author(self, author_id: str) -> dict[str, Any] | None:
        author_id = normalize_openalex_id(author_id)
        if not author_id:
            return None
        try:
            return self._get(f"authors/{author_id}")
        except requests.RequestException:
            return None

    def search_author(self, name: str, institution: str = "") -> dict[str, Any] | None:
        """Conservative identity resolution.

        Never falls back to the first same-name result when an institution was
        supplied. Rate limits or transient API failures return None so one
        identity lookup cannot kill the entire batch.
        """
        try:
            data = self._get("authors", {"search": name, "per-page": 10})
        except requests.RequestException:
            return None

        results = data.get("results", [])
        if not results:
            return None
        if not institution:
            return None

        target_tokens = _tokens(institution)
        best = None
        best_overlap = 0

        for author in results:
            institutions = author.get("last_known_institutions") or []
            haystack = " ".join(
                item.get("display_name", "")
                for item in institutions
                if isinstance(item, dict)
            )
            overlap = len(target_tokens & _tokens(haystack))
            if overlap > best_overlap:
                best = author
                best_overlap = overlap

        return best if best_overlap >= 1 else None

    def iter_works_by_author(self, author_id: str) -> Iterator[dict[str, Any]]:
        author_id = normalize_openalex_id(author_id)
        cursor = "*"
        while cursor:
            try:
                data = self._get(
                    "works",
                    {
                        "filter": f"author.id:{author_id}",
                        "per-page": 200,
                        "cursor": cursor,
                    },
                )
            except requests.RequestException:
                return
            for work in data.get("results", []):
                yield work
            cursor = (data.get("meta") or {}).get("next_cursor")
