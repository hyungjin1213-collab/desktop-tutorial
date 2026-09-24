from __future__ import annotations

import os
import re
from difflib import SequenceMatcher
from typing import Any

import requests

from name_extraction import (
    english_matches_korean,
    given_name_initials,
    split_korean_name,
    surname_romanizations,
)

SERPAPI_KEY = os.getenv("SERPAPI_KEY", "").strip()
ORCID_CLIENT_ID = os.getenv("ORCID_CLIENT_ID", "").strip()
ORCID_CLIENT_SECRET = os.getenv("ORCID_CLIENT_SECRET", "").strip()
ORCID_TIMEOUT = 15
ORCID_SEARCH_URL = "https://pub.orcid.org/v3.0/expanded-search/"

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
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "AboutBio-ORCIDMatcher/0.2"})
        self._token: str | None = None

    def _get_token(self) -> str:
        if self._token is not None:
            return self._token
        if not ORCID_CLIENT_ID or not ORCID_CLIENT_SECRET:
            self._token = ""
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
                timeout=ORCID_TIMEOUT,
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
                timeout=ORCID_TIMEOUT,
            )
            r.raise_for_status()
            data = r.json()
        except (requests.RequestException, ValueError):
            return []

        results = []
        for item in data.get("expanded-result", []) or []:
            oid = normalize_orcid(str(item.get("orcid-id", "")))
            if oid:
                results.append({
                    "orcid": oid,
                    "name": " ".join(filter(None, [item.get("given-names", ""), item.get("family-names", "")])),
                    "institution": "; ".join(item.get("institution-name", []) or []),
                    "source": "orcid_public_api",
                    "url": f"https://orcid.org/{oid}",
                })
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
                params={"engine": "google", "q": q, "hl": "en", "num": 5, "api_key": SERPAPI_KEY},
                timeout=ORCID_TIMEOUT,
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
            oid = normalize_orcid(link) or normalize_orcid(str(item.get("snippet", "")))
            if oid:
                results.append({
                    "orcid": oid,
                    "name": str(item.get("title", "")),
                    "institution": str(item.get("snippet", "")),
                    "source": "serpapi_orcid_search",
                    "url": f"https://orcid.org/{oid}",
                })
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
                score += min(len(inst_tokens & _institution_tokens(text)), 2) * 0.15
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


def _expanded_to_candidate(item: dict[str, Any]) -> dict[str, Any] | None:
    oid = normalize_orcid(str(item.get("orcid-id", "")))
    if not oid:
        return None
    given = str(item.get("given-names", "") or "")
    family = str(item.get("family-names", "") or "")
    return {
        "orcid": oid,
        "name": " ".join(filter(None, [given, family])),
        "other_names": [str(x) for x in item.get("other-name", []) or []],
        "credit_name": str(item.get("credit-name", "") or ""),
        "emails": [str(x).casefold() for x in item.get("email", []) or []],
        "institution": "; ".join(item.get("institution-name", []) or []),
        "url": f"https://orcid.org/{oid}",
    }


def korean_orcid_query(name_ko: str, university: str, surname_hint: str = "") -> str:
    """family-name:(Kim OR Gim) AND given-names:(K* OR G*) AND affiliation-org-name:"..."."""
    families = list(dict.fromkeys(([surname_hint] if surname_hint else []) + surname_romanizations(name_ko)))
    initials = given_name_initials(name_ko)
    if not families or not initials:
        return ""
    q = f"family-name:({' OR '.join(families)}) AND given-names:({' OR '.join(i + '*' for i in initials)})"
    if university:
        q += f' AND affiliation-org-name:"{university}"'
    return q


def _korean_name_fits(candidate: dict[str, Any], name_ko: str, name_en: str) -> bool:
    names = [candidate["name"], candidate["credit_name"], *candidate["other_names"]]
    compact = [re.sub(r"\s+", "", n) for n in names]
    surname, given = split_korean_name(name_ko)
    if name_ko and (name_ko in compact or f"{given}{surname}" in compact):
        return True
    if name_ko and any(english_matches_korean(n, name_ko) for n in names if n):
        return True
    return bool(name_en) and any(_name_score(name_en, n) >= 0.9 for n in names if n)


class KoreanORCIDSearch(ORCIDClient):
    """ORCID lookup tuned for Korean faculty.

    The public search endpoint works without credentials; a token (if
    configured) only raises the rate limit.
    """

    def _search(self, query: str, rows: int = 200) -> list[dict[str, Any]]:
        headers = {"Accept": "application/vnd.orcid+json"}
        token = self._get_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            r = self.session.get(ORCID_SEARCH_URL, params={"q": query, "rows": rows},
                                 headers=headers, timeout=ORCID_TIMEOUT)
            r.raise_for_status()
            data = r.json()
        except (requests.RequestException, ValueError):
            return []
        out = []
        for item in data.get("expanded-result", []) or []:
            cand = _expanded_to_candidate(item)
            if cand:
                out.append(cand)
        return out

    def find(self, name_ko: str, name_en: str, university: str, email: str = "",
             surname_hint: str = "") -> tuple[dict[str, Any] | None, str]:
        """Return (candidate, reason). candidate is None when absent or ambiguous."""
        email = (email or "").casefold()
        if email:
            hits = [c for c in self._search(f'email:"{email}"', rows=5)
                    if _korean_name_fits(c, name_ko, name_en)]
            if len(hits) == 1:
                return hits[0], "ORCID public email matches"

        queries = []
        q = korean_orcid_query(name_ko, university, surname_hint)
        if q:
            queries.append(q)
        if name_ko:
            queries.append(f'other-names:"{name_ko}"' + (f' AND affiliation-org-name:"{university}"' if university else ""))
        if name_en and not name_ko:
            queries.append(f'given-and-family-names:"{name_en}"' + (f' AND affiliation-org-name:"{university}"' if university else ""))

        found: dict[str, dict[str, Any]] = {}
        for query in queries:
            for c in self._search(query):
                if _korean_name_fits(c, name_ko, name_en):
                    found.setdefault(c["orcid"], c)

        if not found:
            return None, "no ORCID record with this name at this institution"
        if email:
            same_email = [c for c in found.values() if email in c["emails"]]
            if len(same_email) == 1:
                return same_email[0], "ORCID public email matches"
        if len(found) == 1:
            return next(iter(found.values())), "only ORCID record with this name at this institution"
        return None, f"ambiguous ORCID: {len(found)} records ({', '.join(sorted(found))})"
