from __future__ import annotations

import requests

from src.config import OPENALEX_BASE_URL


def search_author(name: str, institution: str = "") -> dict | None:
    params = {"search": name, "per-page": 10}
    response = requests.get(f"{OPENALEX_BASE_URL}/authors", params=params, timeout=30)
    response.raise_for_status()
    results = response.json().get("results", [])

    if not results:
        return None

    if institution:
        target = institution.lower()
        for author in results:
            institutions = author.get("last_known_institutions") or []
            names = " ".join(i.get("display_name", "") for i in institutions).lower()
            if target in names:
                return author

    return results[0]
