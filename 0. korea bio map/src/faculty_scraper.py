from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup

from config import DATA_DIR, OUTPUT_DIR, REQUEST_TIMEOUT

FACULTY_WORDS = [
    "교수", "교수진", "faculty", "professor", "people", "members", "연구진", "전임교원",
]
TITLE_WORDS = [
    "정교수", "부교수", "조교수", "교수",
    "full professor", "associate professor", "assistant professor", "professor",
    "principal investigator", "pi",
]

# These categories should not become professor nodes in About Bio.
EXCLUDED_FACULTY_CATEGORIES = [
    "보직교수", "겸임교수", "겸임", "adjunct professor", "adjunct faculty",
    "visiting professor", "초빙교수", "명예교수", "emeritus professor",
]

NON_FACULTY_WORDS = [
    "학생", "대학원생", "연구원", "박사후", "포닥", "postdoc", "postdoctoral",
    "student", "graduate student", "research assistant",
]


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str).fillna("")


def _same_site(a: str, b: str) -> bool:
    try:
        ha = urlparse(a).netloc.casefold().removeprefix("www.")
        hb = urlparse(b).netloc.casefold().removeprefix("www.")
        return ha == hb or ha.endswith("." + hb) or hb.endswith("." + ha)
    except Exception:
        return False


def _fetch(url: str) -> str:
    try:
        r = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; AboutBioFacultyBot/0.2; research directory indexing)"
            },
        )
        r.raise_for_status()
        ctype = r.headers.get("content-type", "")
        if "html" not in ctype.casefold():
            return ""
        r.encoding = r.apparent_encoding or r.encoding
        return r.text
    except requests.RequestException:
        return ""


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _extract_name(text: str) -> str:
    text = _clean(text)
    m = re.search(r"([가-힣]{2,4})\s*(?:정교수|부교수|조교수|교수)", text)
    if m:
        return m.group(1)
    m = re.search(
        r"\b([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){1,3})\s*,?\s*(?:Ph\.?D\.?|M\.?D\.?)?\s*(?:Full Professor|Professor|Assistant Professor|Associate Professor)?",
        text,
    )
    return m.group(1).strip() if m else ""


def _candidate_faculty_pages(base_url: str, html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls = [base_url]
    for a in soup.find_all("a", href=True):
        label = _clean(a.get_text(" ", strip=True)).casefold()
        href = urljoin(base_url, a["href"])
        if not _same_site(base_url, href):
            continue
        if any(x.casefold() in label for x in EXCLUDED_FACULTY_CATEGORIES):
            continue
        if any(w.casefold() in label for w in FACULTY_WORDS):
            urls.append(href)
    return list(dict.fromkeys(urls))[:8]


def _extract_cards(page_url: str, html: str, university: str, department: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, str]] = []
    seen_names: set[str] = set()

    selectors = [
        "article", "li", ".faculty", ".professor", ".member", ".people",
        ".staff", ".profile", ".person", ".card", "tr",
    ]
    blocks = []
    for sel in selectors:
        blocks.extend(soup.select(sel))
    if not blocks:
        blocks = [soup]

    for block in blocks:
        text = _clean(block.get_text(" ", strip=True))
        low = text.casefold()
        if len(text) < 3 or len(text) > 1200:
            continue
        if any(x.casefold() in low for x in EXCLUDED_FACULTY_CATEGORIES):
            continue
        if not any(w.casefold() in low for w in TITLE_WORDS):
            continue
        if any(w.casefold() in low for w in NON_FACULTY_WORDS) and not any(
            w.casefold() in low for w in ["교수", "professor"]
        ):
            continue

        name = _extract_name(text)
        if not name or name in seen_names:
            continue
        seen_names.add(name)

        link = ""
        a = block.find("a", href=True)
        if a:
            link = urljoin(page_url, a["href"])

        email = ""
        em = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text, flags=re.I)
        if em:
            email = em.group(0)

        title = ""
        for t in TITLE_WORDS:
            if t.casefold() in low:
                title = t
                break

        rows.append(
            {
                "name": name,
                "title": title,
                "university": university,
                "department": department,
                "email": email,
                "profile_url": link or page_url,
                "source_page": page_url,
                "raw_text": text[:500],
                "faculty_confidence": "high" if title else "medium",
            }
        )
    return rows


def scrape_faculty() -> pd.DataFrame:
    departments = _read_csv(OUTPUT_DIR / "department_candidates.csv")
    approved = _read_csv(DATA_DIR / "department_sources.csv")

    if not approved.empty:
        sources = approved.copy()
    else:
        sources = departments.copy()

    if sources.empty:
        out = pd.DataFrame()
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out.to_csv(OUTPUT_DIR / "faculty_directory.csv", index=False, encoding="utf-8-sig")
        return out

    all_rows: list[dict[str, str]] = []
    seen_people: set[tuple[str, str, str]] = set()

    for _, row in sources.iterrows():
        university = row.get("university", "").strip()
        department = (
            row.get("department_or_school", "").strip()
            or row.get("department", "").strip()
            or row.get("page_title", "").strip()
        )
        base_url = (
            row.get("faculty_url", "").strip()
            or row.get("department_url", "").strip()
        )
        if not base_url:
            continue

        html = _fetch(base_url)
        if not html:
            continue
        for page_url in _candidate_faculty_pages(base_url, html):
            page_html = html if page_url == base_url else _fetch(page_url)
            if not page_html:
                continue
            for person in _extract_cards(page_url, page_html, university, department):
                key = (
                    person["name"].casefold(),
                    person["university"].casefold(),
                    person["department"].casefold(),
                )
                if key in seen_people:
                    continue
                seen_people.add(key)
                all_rows.append(person)

    columns = [
        "name", "title", "university", "department", "email",
        "profile_url", "source_page", "raw_text", "faculty_confidence",
    ]
    out = pd.DataFrame(all_rows, columns=columns)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUTPUT_DIR / "faculty_directory.csv", index=False, encoding="utf-8-sig")
    return out


if __name__ == "__main__":
    df = scrape_faculty()
    print(f"Faculty rows: {len(df)}")
