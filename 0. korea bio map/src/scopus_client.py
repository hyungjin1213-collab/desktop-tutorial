"""Optional Scopus (Elsevier) coauthor source.

Enabled only when SCOPUS_API_KEY is set. Listing every author of a paper
needs the COMPLETE view of the Scopus Search API, which Elsevier grants only
to subscribing institutions: requests must come from the institution's
network or carry an institutional token (SCOPUS_INSTTOKEN). GitHub Actions
runners are outside any campus network, so in practice SCOPUS_INSTTOKEN is
needed too. Without the entitlement the client reports it once and the
pipeline continues with OpenAlex only.
"""
from __future__ import annotations

import os
import re
import time
from collections.abc import Iterator
from typing import Any

import requests

from name_extraction import english_matches_korean

SCOPUS_API_KEY = os.getenv("SCOPUS_API_KEY", "").strip()
SCOPUS_INSTTOKEN = os.getenv("SCOPUS_INSTTOKEN", "").strip()
# Scopus quotas are weekly (Scopus Search ~20,000, Author Search ~5,000);
# cap requests per run so one run cannot use up the week.
SCOPUS_REQUEST_LIMIT = int(os.getenv("SCOPUS_REQUEST_LIMIT", "3000"))
BASE = "https://api.elsevier.com/content/search"
TIMEOUT = 20


class ScopusUnavailable(Exception):
    pass


def normalize_doi(value: str) -> str:
    value = (value or "").strip().casefold()
    return re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", value)


class ScopusClient:
    def __init__(self, api_key: str = SCOPUS_API_KEY, insttoken: str = SCOPUS_INSTTOKEN,
                 request_limit: int = SCOPUS_REQUEST_LIMIT) -> None:
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json", "X-ELS-APIKey": api_key})
        if insttoken:
            self.session.headers["X-ELS-Insttoken"] = insttoken
        self.remaining = request_limit
        self.disabled_reason = "" if api_key else "SCOPUS_API_KEY not set"
        self._last = 0.0

    @property
    def enabled(self) -> bool:
        return not self.disabled_reason

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            raise ScopusUnavailable(self.disabled_reason)
        if self.remaining <= 0:
            self.disabled_reason = "SCOPUS_REQUEST_LIMIT reached for this run"
            raise ScopusUnavailable(self.disabled_reason)
        wait = 0.15 - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self.remaining -= 1
        try:
            r = self.session.get(f"{BASE}/{path}", params=params, timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise ScopusUnavailable(f"network error: {type(exc).__name__}") from exc
        self._last = time.monotonic()
        if r.status_code in (401, 403):
            self.disabled_reason = (
                f"Scopus refused the request ({r.status_code}). The key needs institutional "
                "access: set SCOPUS_INSTTOKEN or run from the university network."
            )
            print(f"[scopus] {self.disabled_reason}", flush=True)
            raise ScopusUnavailable(self.disabled_reason)
        if r.status_code == 429:
            self.disabled_reason = "Scopus weekly quota exhausted (429)"
            print(f"[scopus] {self.disabled_reason}", flush=True)
            raise ScopusUnavailable(self.disabled_reason)
        r.raise_for_status()
        return r.json().get("search-results", {})

    # ------------------------------------------------------------ author id
    def find_author_id(self, orcid: str = "", name_ko: str = "", name_en: str = "",
                       affiliation: str = "") -> tuple[str, str]:
        """Scopus author ID by ORCID; else by name + affiliation when unique."""
        if orcid:
            ids = self._author_ids(f"ORCID({orcid})")
            if len(ids) == 1:
                return ids[0][0], "Scopus author by ORCID"
        if name_en and affiliation:
            parts = name_en.replace(",", " ").split()
            if len(parts) >= 2:
                first, last = " ".join(parts[:-1]), parts[-1]
                query = f'AUTHLASTNAME("{last}") AND AUTHFIRST("{first}") AND AFFIL("{affiliation}")'
                hits = [(aid, n) for aid, n in self._author_ids(query)
                        if not name_ko or english_matches_korean(n, name_ko)]
                if len(hits) == 1:
                    return hits[0][0], "unique Scopus author by name + affiliation"
                if len(hits) > 1:
                    return "", f"ambiguous: {len(hits)} Scopus authors"
        return "", "no Scopus author"

    def _author_ids(self, query: str) -> list[tuple[str, str]]:
        data = self._get("author", {"query": query, "count": 25})
        out = []
        for entry in data.get("entry", []) or []:
            if entry.get("error"):
                continue
            aid = str(entry.get("dc:identifier", "")).replace("AUTHOR_ID:", "").strip()
            pref = entry.get("preferred-name") or {}
            name = f"{pref.get('given-name', '')} {pref.get('surname', '')}".strip()
            if aid:
                out.append((aid, name))
        return out

    # ------------------------------------------------------------- documents
    def iter_documents(self, author_id: str) -> Iterator[dict[str, Any]]:
        """Documents of an author with every author's Scopus ID (COMPLETE view)."""
        cursor = "*"
        while cursor:
            data = self._get("scopus", {
                "query": f"AU-ID({author_id})", "view": "COMPLETE", "count": 25, "cursor": cursor,
                "field": "dc:identifier,prism:doi,dc:title,author",
            })
            entries = [e for e in data.get("entry", []) or [] if not e.get("error")]
            for entry in entries:
                yield {
                    "id": str(entry.get("dc:identifier", "")),
                    "doi": normalize_doi(entry.get("prism:doi", "")),
                    "title": entry.get("dc:title", ""),
                    "author_ids": [str(a.get("authid", "")) for a in entry.get("author", []) or [] if a.get("authid")],
                }
            nxt = (data.get("cursor") or {}).get("@next", "")
            cursor = nxt if entries and nxt and nxt != cursor else ""
