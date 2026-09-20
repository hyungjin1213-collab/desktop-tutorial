from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import requests

from config import OPENALEX_BASE_URL, OPENALEX_EMAIL, REQUEST_TIMEOUT


def normalize_openalex_id(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    return value.rstrip("/").split("/")[-1]


class OpenAlexClient:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "AboutBio-KoreaBioMap/0.1",
            }
        )

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

    def search_author(self, name: str, institution: str = "") -> dict[str, Any] | None:
        data = self._get("authors", {"search": name, "per-page": 10})
        results = data.get("results", [])
        if not results:
            return None

        if institution:
            target = institution.casefold()
            for author in results:
                institutions = author.get("last_known_institutions") or []
                haystack = " ".join(
                    item.get("display_name", "")
                    for item in institutions
                    if isinstance(item, dict)
                ).casefold()
                if target in haystack:
                    return author

        return results[0]

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
