from __future__ import annotations

import os
import re
from urllib.parse import urlparse

import pandas as pd
import requests

from config import DATA_DIR, REQUEST_TIMEOUT, WEB_VERIFY_LIMIT

SERPAPI_KEY = os.getenv("SERPAPI_KEY", "").strip()
CACHE_PATH = DATA_DIR / "candidate_web_cache.csv"

POSITIVE_TITLE_WORDS = (
    "professor", "assistant professor", "associate professor", "full professor",
    "faculty", "principal investigator", "group leader", "lab director",
    "laboratory director", "교수", "조교수", "부교수", "정교수", "연구책임자",
)
NEGATIVE_TITLE_WORDS = (
    "student", "graduate student", "phd student", "master student",
    "postdoctoral", "postdoc", "research fellow", "doctoral candidate",
    "대학원생", "박사과정", "석사과정", "포닥", "박사후연구원",
)
ACADEMIC_DOMAIN_HINTS = (
    ".ac.kr", ".edu", "kaist.ac.kr", "postech.ac.kr", "snu.ac.kr",
    "yonsei.ac.kr", "korea.ac.kr", "skku.edu", "hanyang.ac.kr",
    "inha.ac.kr", "jejunu.ac.kr", "jnu.ac.kr",
)


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _load_cache() -> pd.DataFrame:
    if CACHE_PATH.exists() and CACHE_PATH.stat().st_size:
        try:
            return pd.read_csv(CACHE_PATH, dtype=str).fillna("")
        except pd.errors.EmptyDataError:
            pass
    return pd.DataFrame(columns=[
        "openalex_id", "query", "web_title", "web_snippet", "web_url",
        "official_domain_signal", "professor_title_signal",
        "trainee_title_signal", "web_checked",
    ])


def _save_cache(df: pd.DataFrame) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(CACHE_PATH, index=False)


def _is_academic_url(url: str) -> bool:
    host = urlparse(url or "").netloc.casefold()
    return any(hint in host for hint in ACADEMIC_DOMAIN_HINTS)


def _contains_any(text: str, words: tuple[str, ...]) -> bool:
    lower = (text or "").casefold()
    return any(word.casefold() in lower for word in words)


def verify_candidates_with_web(candidates: pd.DataFrame) -> pd.DataFrame:
    """Use SerpApi Google results to look for current official faculty/trainee evidence.

    Results are cached in data/candidate_web_cache.csv so repeated Actions runs
    do not burn API quota for the same OpenAlex author.
    """
    cache = _load_cache()
    cache_map = {
        row["openalex_id"]: row.to_dict()
        for _, row in cache.iterrows()
        if row.get("openalex_id", "")
    }

    if not SERPAPI_KEY or candidates.empty:
        return candidates

    new_rows = []
    lookups = 0

    for _, row in candidates.iterrows():
        oid = row.get("openalex_id", "")
        if oid in cache_map:
            continue
        if lookups >= WEB_VERIFY_LIMIT:
            break

        name = _norm(row.get("display_name", ""))
        affiliation = _norm(row.get("current_affiliation", ""))
        if not name:
            continue

        # Current institution terms plus faculty keywords make this much more
        # discriminative than a plain name search.
        institution_hint = affiliation.split(";")[0].strip()
        query = f'"{name}" "{institution_hint}" professor 교수'
        try:
            response = requests.get(
                "https://serpapi.com/search.json",
                params={
                    "engine": "google",
                    "q": query,
                    "hl": "en",
                    "num": 10,
                    "api_key": SERPAPI_KEY,
                },
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            results = response.json().get("organic_results") or []
        except requests.RequestException:
            results = []

        best = {}
        for result in results:
            title = result.get("title", "") or ""
            snippet = result.get("snippet", "") or ""
            url = result.get("link", "") or ""
            combined = f"{title} {snippet}"
            if _is_academic_url(url) and (
                _contains_any(combined, POSITIVE_TITLE_WORDS)
                or _contains_any(combined, NEGATIVE_TITLE_WORDS)
            ):
                best = result
                break

        if not best and results:
            best = results[0]

        title = best.get("title", "") or ""
        snippet = best.get("snippet", "") or ""
        url = best.get("link", "") or ""
        combined = f"{title} {snippet}"

        new_rows.append({
            "openalex_id": oid,
            "query": query,
            "web_title": title,
            "web_snippet": snippet,
            "web_url": url,
            "official_domain_signal": "yes" if _is_academic_url(url) else "no",
            "professor_title_signal": "yes" if _contains_any(combined, POSITIVE_TITLE_WORDS) else "no",
            "trainee_title_signal": "yes" if _contains_any(combined, NEGATIVE_TITLE_WORDS) else "no",
            "web_checked": "yes",
        })
        lookups += 1

    if new_rows:
        cache = pd.concat([cache, pd.DataFrame(new_rows)], ignore_index=True)
        cache = cache.drop_duplicates(subset=["openalex_id"], keep="last")
        _save_cache(cache)
        cache_map = {
            row["openalex_id"]: row.to_dict()
            for _, row in cache.iterrows()
            if row.get("openalex_id", "")
        }

    result = candidates.copy()
    result["web_title"] = result["openalex_id"].map(lambda x: cache_map.get(x, {}).get("web_title", ""))
    result["web_snippet"] = result["openalex_id"].map(lambda x: cache_map.get(x, {}).get("web_snippet", ""))
    result["web_url"] = result["openalex_id"].map(lambda x: cache_map.get(x, {}).get("web_url", ""))
    result["official_domain_signal"] = result["openalex_id"].map(lambda x: cache_map.get(x, {}).get("official_domain_signal", ""))
    result["professor_title_signal"] = result["openalex_id"].map(lambda x: cache_map.get(x, {}).get("professor_title_signal", ""))
    result["trainee_title_signal"] = result["openalex_id"].map(lambda x: cache_map.get(x, {}).get("trainee_title_signal", ""))
    return result
