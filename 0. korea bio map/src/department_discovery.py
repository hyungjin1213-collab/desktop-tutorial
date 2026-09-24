"""Find official bio / medicine / pharmacy faculty-list pages for each university.

Primary method: crawl the university's own site (site_crawler.py, free).
Fallback: SerpAPI Google search, only when SERPAPI_KEY is set and the crawl
found nothing.

Discovered pages are appended to data/faculty_sources.csv (enabled=yes), so the
next scrape-faculty-v2 run picks them up. Set enabled=no on a row to skip it.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import requests

from config import DATA_DIR, OUTPUT_DIR, REQUEST_TIMEOUT
from site_crawler import SiteCrawler, department_label

SERPAPI_KEY = os.getenv("SERPAPI_KEY", "").strip()
# Universities explored per run (crawling takes ~1-2 minutes each).
DISCOVERY_UNIVERSITY_LIMIT = int(os.getenv("DISCOVERY_UNIVERSITY_LIMIT", "20"))
DISCOVERY_REFRESH = os.getenv("DISCOVERY_REFRESH", "").strip().casefold() in {"1", "yes", "true"}

BIO_KEYWORDS = [
    "의과대학", "의학과", "의학전문대학원", "의과학", "의생명", "약학", "약대", "제약",
    "생명과학", "생명공학", "생명시스템", "생명정보", "생물", "생화학", "분자", "바이오",
    "융합생명", "뇌", "신경과학", "유전", "면역", "수의",
    "medicine", "medical", "pharm", "bio", "life science", "biological", "neuro",
]
NON_BIO_KEYWORDS = [
    "간호", "경영", "경제", "인문", "사회과학", "사회학", "체육", "스포츠", "음악", "미술", "법학",
    "행정", "국어", "영어영문", "사범", "호텔", "관광", "디자인", "건축", "치의", "치과", "한의",
    "nursing", "business", "humanities", "economics", "law school",
]
PAGE_TITLE_REQUIRED = ["교수진", "교수소개", "교수", "faculty", "professor", "people"]
PAGE_TITLE_EXCLUDE = ["보직교수", "겸임", "명예교수", "초빙", "대학원생", "연구원", "직원"]

SOURCE_COLUMNS = ["source_id", "university", "department", "faculty_url", "parser", "enabled", "notes"]


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str).fillna("")


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.casefold().removeprefix("www.")
    except Exception:
        return ""


def _is_official(url: str, official_domain: str) -> bool:
    """Only the university's own domain: 고려대 pages must not count for 서울대."""
    host = _domain(url)
    official_domain = official_domain.casefold().removeprefix("www.")
    return bool(host and official_domain) and (host == official_domain or host.endswith("." + official_domain))


def is_bio_faculty_page(title: str, url: str) -> bool:
    title_low = (title or "").casefold()
    hay = f"{title_low} {urlparse(url).netloc.casefold()} {urlparse(url).path.casefold()}"
    if not any(w.casefold() in title_low for w in PAGE_TITLE_REQUIRED):
        return False
    if any(w.casefold() in title_low for w in PAGE_TITLE_EXCLUDE):
        return False
    if any(w.casefold() in title_low for w in NON_BIO_KEYWORDS):
        return False
    return any(w.casefold() in hay for w in BIO_KEYWORDS)


def _department_from_title(title: str, university_ko: str) -> str:
    parts = [p.strip() for p in re.split(r"[|>\-–·:]", title or "") if p.strip()]
    keep = [p for p in parts if not any(w in p for w in PAGE_TITLE_REQUIRED + [university_ko] if w)]
    return (keep or parts or [title])[0][:80]


def _source_id(domain: str, url: str) -> str:
    slug = re.sub(r"[^A-Z0-9]", "", domain.split(".")[0].upper())[:10] or "SRC"
    return f"AUTO_{slug}_{hashlib.sha1(url.encode()).hexdigest()[:6].upper()}"


def _search_google(query: str, num: int = 10) -> list[dict]:
    if not SERPAPI_KEY:
        _report("SERPAPI_KEY not set: department discovery skipped")
        return []
    try:
        r = requests.get(
            "https://serpapi.com/search.json",
            params={"engine": "google", "q": query, "hl": "ko", "gl": "kr", "num": num, "api_key": SERPAPI_KEY},
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": "AboutBio-DepartmentDiscovery/0.3"},
        )
        r.raise_for_status()
        payload = r.json()
    except (requests.RequestException, ValueError) as exc:
        _report(f"SerpAPI request failed: {type(exc).__name__}: {exc}")
        return []
    if payload.get("error"):
        # e.g. "Your account has run out of searches."
        _report(f"SerpAPI error: {payload['error']}")
        return []
    return payload.get("organic_results") or []


_reported: set[str] = set()


def _report(message: str) -> None:
    if message not in _reported:
        _reported.add(message)
        print(f"[discover] {message}", flush=True)


def _queries(university: str, name_ko: str, domain: str) -> list[str]:
    return [
        f"site:{domain} (의과대학 OR 약학대학 OR 의과학 OR 의생명) 교수진",
        f"site:{domain} (생명과학 OR 생명공학 OR 바이오 OR 약학과) 교수소개",
    ]


LOG_COLUMNS = ["university", "method", "pages_found", "run_at"]
CANDIDATE_COLUMNS = ["university", "official_domain", "page_title", "department_url", "department",
                     "faculty_count", "accepted", "method"]


def _count_faculty(html: str, url: str) -> int:
    from faculty_scraper_v2 import parse_photo_anchor

    try:
        return len(parse_photo_anchor(html, url, "", "", ""))
    except Exception:
        return 0


def _crawl_university(domain: str, name_ko: str, crawler) -> list[dict[str, str]]:
    starts = [f"https://www.{domain}/", f"https://{domain}/"]
    rows = []
    for page in crawler.crawl(domain, starts):
        rows.append({
            "page_title": page.title,
            "department_url": page.url,
            "department": department_label(page, name_ko),
            "faculty_count": str(page.faculty_count),
            "method": "crawl",
        })
    return rows


def _search_university(university: str, name_ko: str, domain: str, search) -> list[dict[str, str]]:
    rows = []
    for query in _queries(university, name_ko, domain):
        for item in search(query):
            title, url = str(item.get("title", "")), str(item.get("link", ""))
            if _is_official(url, domain) and is_bio_faculty_page(title, url):
                rows.append({"page_title": title, "department_url": url,
                             "department": _department_from_title(title, name_ko),
                             "faculty_count": "", "method": "serpapi"})
    return rows


def discover_departments(search=None, crawler=None) -> pd.DataFrame:
    """Crawl each university's site for bio faculty pages; SerpAPI only as a fallback."""
    from faculty_scraper_v2 import _fetch

    search = search or _search_google
    crawler = crawler or SiteCrawler(_fetch, _count_faculty)
    universities = _read_csv(DATA_DIR / "universities_seed.csv")
    sources_path = DATA_DIR / "faculty_sources.csv"
    log_path = DATA_DIR / "discovery_log.csv"
    sources = _read_csv(sources_path)
    for column in SOURCE_COLUMNS:
        if column not in sources.columns:
            sources[column] = ""
    log = _read_csv(log_path)
    done = set(log["university"]) if not log.empty else set()
    known_urls = {u.rstrip("/") for u in sources["faculty_url"]}

    rows: list[dict[str, str]] = []
    new_sources: list[dict[str, str]] = []
    new_log: list[dict[str, str]] = []
    searched = 0

    for _, uni in universities.iterrows():
        university = uni.get("university", "").strip()
        name_ko = uni.get("name_ko", "").strip()
        domain = uni.get("official_domain", "").strip().casefold()
        if not university or not domain:
            continue
        if university in done and not DISCOVERY_REFRESH:
            continue
        if searched >= DISCOVERY_UNIVERSITY_LIMIT:
            break
        searched += 1
        print(f"[discover] {university} ({domain})", flush=True)

        found = _crawl_university(domain, name_ko, crawler)
        method = "crawl"
        if not found and SERPAPI_KEY:
            found = _search_university(university, name_ko, domain, search)
            method = "serpapi"
        print(f"  -> {len(found)} faculty pages ({method})", flush=True)

        added = 0
        for f in found:
            key = f["department_url"].rstrip("/")
            accepted = key not in known_urls
            rows.append({"university": university, "official_domain": domain, **f,
                         "accepted": "yes" if accepted else "known"})
            if not accepted:
                continue
            known_urls.add(key)
            added += 1
            new_sources.append({
                "source_id": _source_id(domain, f["department_url"]),
                "university": university,
                "department": f["department"],
                "faculty_url": f["department_url"],
                "parser": "photo_anchor",
                "enabled": "yes",
                "notes": f"auto-{f['method']}: {f['page_title'][:60]} ({f['faculty_count'] or '?'} faculty)",
            })
        new_log.append({"university": university, "method": method, "pages_found": str(len(found)),
                        "run_at": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d")})

    out = pd.DataFrame(rows, columns=CANDIDATE_COLUMNS)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUTPUT_DIR / "department_candidates.csv", index=False, encoding="utf-8-sig")

    if new_sources:
        sources = pd.concat([sources, pd.DataFrame(new_sources)], ignore_index=True)[SOURCE_COLUMNS]
        sources.to_csv(sources_path, index=False, encoding="utf-8-sig")
    if new_log:
        log = pd.concat([log, pd.DataFrame(new_log)], ignore_index=True) if not log.empty else pd.DataFrame(new_log)
        log = log.drop_duplicates(subset=["university"], keep="last")[LOG_COLUMNS]
        log.to_csv(log_path, index=False, encoding="utf-8-sig")
    print(f"Explored {searched} universities; added {len(new_sources)} faculty sources", flush=True)
    return out


if __name__ == "__main__":
    df = discover_departments()
    print(f"Department candidates: {len(df)}")
