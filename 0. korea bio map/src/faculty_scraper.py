from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup

from config import DATA_DIR, OUTPUT_DIR, REQUEST_TIMEOUT

FACULTY_WORDS = ["교수", "교수진", "faculty", "professor", "people", "members", "연구진", "전임교원"]
TITLE_WORDS = [
    "정교수", "부교수", "조교수", "교수",
    "full professor", "associate professor", "assistant professor", "professor",
    "principal investigator", "pi",
]
EXCLUDED_FACULTY_CATEGORIES = [
    "보직교수", "겸임교수", "겸임", "adjunct professor", "adjunct faculty",
    "visiting professor", "초빙교수", "명예교수", "emeritus professor",
]
NON_FACULTY_WORDS = [
    "학생", "대학원생", "연구원", "박사후", "포닥", "postdoc", "postdoctoral",
    "student", "graduate student", "research assistant",
]
BAD_NAMES = {
    "교수진", "교수소개", "의과학과", "공학교실", "주임", "연구실", "전임교수",
    "교수", "학과", "대학", "의과대학", "약학대학",
}


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
            timeout=min(REQUEST_TIMEOUT, 15),
            headers={"User-Agent": "Mozilla/5.0 (compatible; AboutBioFacultyBot/0.3; research directory indexing)"},
        )
        r.raise_for_status()
        if "html" not in r.headers.get("content-type", "").casefold():
            return ""
        r.encoding = r.apparent_encoding or r.encoding
        return r.text
    except requests.RequestException:
        return ""


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _valid_korean_name(value: str) -> bool:
    return bool(re.fullmatch(r"[가-힣]{2,4}", value or "")) and value not in BAD_NAMES


def _extract_name(text: str) -> str:
    text = _clean(text)

    # Most Korean faculty cards start with the person's name.
    start = re.match(r"^([가-힣]{2,4})(?:\s|\(|$)", text)
    if start and _valid_korean_name(start.group(1)):
        return start.group(1)

    # Common pattern: "교수 홍길동" / "부교수 홍길동".
    after_title = re.search(r"(?:정교수|부교수|조교수|교수)\s+([가-힣]{2,4})(?:\s|\(|$)", text)
    if after_title and _valid_korean_name(after_title.group(1)):
        return after_title.group(1)

    # Common pattern on cards: "홍길동 사이트로 이동".
    before_site = re.search(r"([가-힣]{2,4})\s+(?:사이트로\s*이동|상세보기)", text)
    if before_site and _valid_korean_name(before_site.group(1)):
        return before_site.group(1)

    # English fallback.
    m = re.search(r"\b([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){1,3})\s*(?:\(|,|Professor|Ph\.?D\.?|M\.?D\.?)", text)
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

    selectors = ["article", "li", ".faculty", ".professor", ".member", ".people", ".staff", ".profile", ".person", ".card", "tr"]
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
        if any(w.casefold() in low for w in NON_FACULTY_WORDS) and not any(w.casefold() in low for w in ["교수", "professor"]):
            continue

        name = _extract_name(text)
        if not name or name in seen_names or name in BAD_NAMES:
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

        rows.append({
            "name": name,
            "title": title,
            "university": university,
            "department": department,
            "email": email,
            "profile_url": link or page_url,
            "source_page": page_url,
            "raw_text": text[:500],
            "faculty_confidence": "high" if title else "medium",
        })
    return rows


def scrape_faculty() -> pd.DataFrame:
    departments = _read_csv(OUTPUT_DIR / "department_candidates.csv")
    approved = _read_csv(DATA_DIR / "department_sources.csv")
    sources = approved.copy() if not approved.empty else departments.copy()

    columns = ["name", "title", "university", "department", "email", "profile_url", "source_page", "raw_text", "faculty_confidence"]
    if sources.empty:
        out = pd.DataFrame(columns=columns)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out.to_csv(OUTPUT_DIR / "faculty_directory.csv", index=False, encoding="utf-8-sig")
        return out

    all_rows: list[dict[str, str]] = []
    seen_people: set[tuple[str, str, str]] = set()

    for _, row in sources.iterrows():
        university = row.get("university", "").strip()
        department = row.get("department_or_school", "").strip() or row.get("department", "").strip() or row.get("page_title", "").strip()
        base_url = row.get("faculty_url", "").strip() or row.get("department_url", "").strip()
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
                key = (person["name"].casefold(), person["university"].casefold(), person["department"].casefold())
                if key not in seen_people:
                    seen_people.add(key)
                    all_rows.append(person)

    out = pd.DataFrame(all_rows, columns=columns)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUTPUT_DIR / "faculty_directory.csv", index=False, encoding="utf-8-sig")
    return out


if __name__ == "__main__":
    df = scrape_faculty()
    print(f"Faculty rows: {len(df)}")
