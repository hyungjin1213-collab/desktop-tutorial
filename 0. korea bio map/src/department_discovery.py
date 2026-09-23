from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import requests

from config import DATA_DIR, OUTPUT_DIR, REQUEST_TIMEOUT

SERPAPI_KEY = os.getenv("SERPAPI_KEY", "").strip()

TARGET_KEYWORDS = [
    "의과대학", "의학과", "의예과", "medicine", "medical school", "college of medicine",
    "약학대학", "약학과", "pharmacy", "college of pharmacy",
    "생명과학", "생명공학", "생명시스템", "바이오", "bioengineering", "bioscience",
    "biological science", "biotechnology", "biomedical", "의생명", "융합생명",
]

# Keep only pages whose Google result title itself says that this is a faculty page.
PAGE_TITLE_REQUIRED = ["교수진", "교수소개", "교수", "faculty"]
PAGE_TITLE_EXCLUDE = ["보직교수", "겸임교수"]


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str).fillna("")


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.casefold().removeprefix("www.")
    except Exception:
        return ""


def _looks_official(url: str, official_domain: str = "") -> bool:
    host = _domain(url)
    if not host:
        return False
    if official_domain and (host == official_domain or host.endswith("." + official_domain)):
        return True
    return host.endswith(".ac.kr") or host.endswith(".edu")


def _valid_page_title(title: str) -> bool:
    normalized = (title or "").casefold().strip()
    if any(word.casefold() in normalized for word in PAGE_TITLE_EXCLUDE):
        return False
    return any(word.casefold() in normalized for word in PAGE_TITLE_REQUIRED)


def _search_google(query: str, num: int = 10) -> list[dict]:
    if not SERPAPI_KEY:
        return []
    try:
        r = requests.get(
            "https://serpapi.com/search.json",
            params={
                "engine": "google",
                "q": query,
                "hl": "ko",
                "gl": "kr",
                "num": num,
                "api_key": SERPAPI_KEY,
            },
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": "AboutBio-DepartmentDiscovery/0.2"},
        )
        r.raise_for_status()
        payload = r.json()
    except (requests.RequestException, ValueError):
        return []
    if payload.get("error"):
        return []
    return payload.get("organic_results") or []


def discover_departments() -> pd.DataFrame:
    universities = _read_csv(DATA_DIR / "universities_seed.csv")
    rows: list[dict[str, str]] = []
    seen: set[str] = set()

    for _, uni in universities.iterrows():
        university = uni.get("university", "").strip()
        domain = uni.get("official_domain", "").strip().casefold()
        if not university:
            continue

        queries = [
            f'"{university}" (의과대학 OR 의학과 OR 약학대학 OR 약학과) 교수진',
            f'"{university}" (생명과학 OR 생명공학 OR 바이오 OR 의생명) 교수진',
            f'"{university}" (medicine OR pharmacy OR bioscience OR bioengineering) faculty',
        ]

        for query in queries:
            for item in _search_google(query, num=10):
                title = str(item.get("title", ""))
                snippet = str(item.get("snippet", ""))
                url = str(item.get("link", ""))
                hay = f"{title} {snippet} {url}".casefold()

                if not _looks_official(url, domain):
                    continue
                if not any(k.casefold() in hay for k in TARGET_KEYWORDS):
                    continue
                if not _valid_page_title(title):
                    continue

                key = url.rstrip("/")
                if not key or key in seen:
                    continue
                seen.add(key)

                rows.append(
                    {
                        "university": university,
                        "official_domain": domain,
                        "page_title": title,
                        "department_url": url,
                        "department_or_school": title,
                        "faculty_page_signal": "yes",
                        "search_query": query,
                        "source": "serpapi_google",
                    }
                )

    columns = [
        "university",
        "official_domain",
        "page_title",
        "department_url",
        "department_or_school",
        "faculty_page_signal",
        "search_query",
        "source",
    ]
    out = pd.DataFrame(rows, columns=columns)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUTPUT_DIR / "department_candidates.csv", index=False, encoding="utf-8-sig")
    return out


if __name__ == "__main__":
    df = discover_departments()
    print(f"Department candidates: {len(df)}")
