from __future__ import annotations

import os
import re
from difflib import SequenceMatcher
from typing import Any

import requests

from config import REQUEST_TIMEOUT

SERPAPI_KEY = os.getenv("SERPAPI_KEY", "").strip()
ORCID_CLIENT_ID = os.getenv("ORCID_CLIENT_ID", "").strip()
ORCID_CLIENT_SECRET = os.getenv("ORCID_CLIENT_SECRET", "").strip()

ORCID_RE = re.compile(r"(?:https?://orcid\.org/)?(\d{4}-\d{4}-\d{4}-\d{3}[\dX])", re.I)


def normalize_orcid(value: str) -> str:
    m = ORCID_RE.search(value or "")
    return m.group(1).upper() if m else ""


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9가-힣]+", "", (value or "").casefold())


def _name_score(a: str, b: str) -> float:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def _institution_tokens(value: str) -> set[str]:
    stop = {"university", "college", "school", "hospital", "institute", "department", "national"}
    return {
        t for t in re.findall(r"[a-z0-9가-힣]+", (value or "").casefold())
        if len(t) >= 3 and t not in stop
    }


class ORCIDClient:
    """ORCID identity lookup.

    Preferred path: official ORCID Public API when credentials are configured.
    Practical fallback: Google/SerpApi constrained to orcid.org, which works with
    the project's existing SERPAPI_KEY and never writes to ORCID.
    """

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "AboutBio-ORCIDMatcher/0.1"})
        self._token: str | None = None

    def _get_token(self) -> str:
        if self._token:
            return self._token
        if not ORCID_CLIENT_ID or not ORCID_CLIENT_SECRET:
            return ""
        try:
            r = self.session.post(
                "https://orcid.org/oauth/token",
                data={
                    "client_id": ORCID_CLIENT_ID,
                    "client_secret": ORCID_CLIENT_SECRET,
                    "grant_type": "client_credentials",
                    "scope": "/read-public",
                },
                headers={"Accept": "application/json"},
                timeout=REQUEST_TIMEOUT,
            )
            r.raise_for_status()
            self._token = str(r.json().get("access_token", ""))
        except (requests.RequestException, ValueError):
            self._token = ""
        return self._token

    def _official_search(self, name: str, institution: str) -> list[dict[str, Any]]:
        token = self._get_token()
        if not token:
            return []
        query = f'given-and-family-names:"{name}"'
        if institution:
            query += f' AND affiliation-org-name:"{institution}"'
        try:
            r = self.session.get(
                "https://pub.orcid.org/v3.0/expanded-search/",
                params={"q": query, "rows": 10},
                headers={
                    "Accept": "application/vnd.orcid+json",
                    "Authorization": f"Bearer {token}",
                },
                timeout=REQUEST_TIMEOUT,
            )
            r.raise_for_status()
            data = r.json()
        except (requests.RequestException, ValueError):
            return []

        results = []
        for item in data.get("expanded-result", []) or []:
            oid = normalize_orcid(str(item.get("orcid-id", "")))
            if not oid:
                continue
            results.append(
                {
                    "orcid": oid,
                    "name": " ".join(filter(None, [item.get("given-names", ""), item.get("family-names", "")])),
                    "institution": "; ".join(item.get("institution-name", []) or []),
                    "source": "orcid_public_api",
                    "url": f"https://orcid.org/{oid}",
                }
            )
        return results

    def _serpapi_search(self, name: str, institution: str) -> list[dict[str, Any]]:
        if not SERPAPI_KEY:
            return []
        q = f'site:orcid.org "{name}"'
        if institution:
            q += f' "{institution}"'
        try:
            r = self.session.get(
                "https://serpapi.com/search.json",
                params={
                    "engine": "google",
                    "q": q,
                    "hl": "en",
                    "num": 10,
                    "api_key": SERPAPI_KEY,
                },
                timeout=REQUEST_TIMEOUT,
            )
            r.raise_for_status()
            data = r.json()
        except (requests.RequestException, ValueError):
            return []
        if data.get("error"):
            return []

        results = []
        for item in data.get("organic_results", []) or []:
            link = str(item.get("link", ""))
            oid = normalize_orcid(link)
            if not oid:
                oid = normalize_orcid(str(item.get("snippet", "")))
            if not oid:
                continue
            results.append(
                {
                    "orcid": oid,
                    "name": str(item.get("title", "")),
                    "institution": str(item.get("snippet", "")),
                    "source": "serpapi_orcid_search",
                    "url": f"https://orcid.org/{oid}",
                }
            )
        return results

    def search_best(self, name: str, institution: str = "", email: str = "") -> dict[str, Any] | None:
        candidates = self._official_search(name, institution)
        if not candidates:
            candidates = self._serpapi_search(name, institution)
        if not candidates:
            return None

        inst_tokens = _institution_tokens(institution)
        email_domain = email.split("@", 1)[-1].casefold() if "@" in email else ""
        ranked = []
        for item in candidates:
            text = f"{item.get('name','')} {item.get('institution','')}".casefold()
            score = _name_score(name, str(item.get("name", ""))) * 0.65
            if inst_tokens:
                overlap = len(inst_tokens & _institution_tokens(text))
                score += min(overlap, 2) * 0.15
            if email_domain and email_domain in text:
                score += 0.15
            ranked.append((score, item))

        ranked.sort(key=lambda x: x[0], reverse=True)
        score, best = ranked[0]
        if score < 0.55:
            return None
        best = dict(best)
        best["match_score"] = round(score, 3)
        return best
