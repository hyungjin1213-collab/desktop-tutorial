from __future__ import annotations

import re
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
        self.session.headers.update({"User-Agent": "AboutBio-KoreaBioMap/0.2"})

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = dict(params or {})
        if OPENALEX_EMAIL:
            params["mailto"] = OPENALEX_EMAIL
        response = self.session.get(
            f"{OPENALEX_BASE_URL}/{path.lstrip('/')}",
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    def get_author(self, author_id: str) -> dict[str, Any] | None:
        author_id = normalize_openalex_id(author_id)
        if not author_id:
            return None
        try:
            return self._get(f"authors/{author_id}")
        except requests.HTTPError:
            return None

    def search_author(self, name: str, institution: str = "") -> dict[str, Any] | None:
        """Conservative identity resolution.

        Never falls back to the first same-name result when an institution was
        supplied. This prevents a bad seed match from contaminating the graph.
        """
        data = self._get("authors", {"search": name, "per-page": 10})
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
            data = self._get(
                "works",
                {
                    "filter": f"author.id:{author_id}",
                    "per-page": 200,
                    "cursor": cursor,
                },
            )
            for work in data.get("results", []):
                yield work
            cursor = (data.get("meta") or {}).get("next_cursor")
