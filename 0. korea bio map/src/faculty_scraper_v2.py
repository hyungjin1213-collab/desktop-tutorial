from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup, Tag

from config import DATA_DIR, OUTPUT_DIR

REQUEST_TIMEOUT_SECONDS = 12
EXCLUDED = {
    "겸임교수", "보직교수", "초빙교수", "명예교수", "emeritus",
    "adjunct", "visiting professor", "postdoc", "postdoctoral",
}
TITLE_PATTERNS = [
    "정교수", "부교수", "조교수", "교수",
    "full professor", "associate professor", "assistant professor", "professor",
]
NAME_BLACKLIST = {
    "의과학과", "의학과", "약학과", "생명과학", "생명공학", "바이오엔지니어링",
    "교수진", "교수소개", "연구실", "상세보기", "사이트로 이동", "주임",
}


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str).fillna("")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _fetch(url: str) -> str:
    r = requests.get(
        url,
        timeout=REQUEST_TIMEOUT_SECONDS,
        headers={"User-Agent": "Mozilla/5.0 (compatible; AboutBioFacultyCollector/2.0)"},
    )
    r.raise_for_status()
    r.encoding = r.apparent_encoding or r.encoding
    return r.text


def _looks_like_person_name(text: str) -> bool:
    t = _clean(text)
    if not t or len(t) > 60:
        return False
    if t.casefold() in {x.casefold() for x in NAME_BLACKLIST}:
        return False
    if any(x.casefold() in t.casefold() for x in EXCLUDED):
        return False
    # Korean name or Latin personal name.
    if re.fullmatch(r"[가-힣]{2,4}(?:\([A-Za-z .'-]{3,40}\))?", t):
        return True
    if re.fullmatch(r"[A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){1,3}", t):
        return True
    return False


def _extract_title(text: str) -> str:
    low = text.casefold()
    for title in TITLE_PATTERNS:
        if title.casefold() in low:
            return title
    return ""


def _candidate_name_nodes(card: Tag) -> list[str]:
    candidates: list[str] = []
    selectors = [
        "h1", "h2", "h3", "h4", "h5", "strong", "b",
        ".name", ".prof-name", ".faculty-name", ".member-name", ".tit", ".title",
    ]
    for sel in selectors:
        for node in card.select(sel):
            t = _clean(node.get_text(" ", strip=True))
            if _looks_like_person_name(t):
                candidates.append(t)
    for a in card.find_all("a", href=True):
        t = _clean(a.get_text(" ", strip=True))
        if _looks_like_person_name(t):
            candidates.append(t)
    # Fallback: scan short text fragments, but never infer from arbitrary word before '교수'.
    if not candidates:
        for s in card.stripped_strings:
            t = _clean(str(s))
            if _looks_like_person_name(t):
                candidates.append(t)
    return list(dict.fromkeys(candidates))


def _find_cards(soup: BeautifulSoup) -> list[Tag]:
    selectors = [
        ".faculty", ".professor", ".member", ".person", ".profile", ".staff",
        ".faculty-item", ".prof-item", ".member-item", ".people-item",
        "article", "li", "tr",
    ]
    cards: list[Tag] = []
    seen: set[int] = set()
    for sel in selectors:
        for node in soup.select(sel):
            if not isinstance(node, Tag):
                continue
            ident = id(node)
            if ident in seen:
                continue
            seen.add(ident)
            text = _clean(node.get_text(" ", strip=True))
            low = text.casefold()
            if len(text) < 5 or len(text) > 1800:
                continue
            if any(x.casefold() in low for x in EXCLUDED):
                continue
            if not _extract_title(text):
                continue
            cards.append(node)
    return cards


def _extract_email(text: str) -> str:
    m = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text, flags=re.I)
    return m.group(0) if m else ""


def _best_profile_url(card: Tag, page_url: str) -> str:
    links = []
    for a in card.find_all("a", href=True):
        href = urljoin(page_url, str(a.get("href", "")))
        label = _clean(a.get_text(" ", strip=True)).casefold()
        if any(k in label for k in ["상세", "profile", "homepage", "site", "연구실", "사이트"]):
            return href
        links.append(href)
    return links[0] if links else page_url


def parse_generic_card(html: str, page_url: str, university: str, department: str, source_id: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict[str, str]] = []
    seen_names: set[str] = set()

    for card in _find_cards(soup):
        text = _clean(card.get_text(" ", strip=True))
        names = _candidate_name_nodes(card)
        if not names:
            continue
        name = names[0]
        if name in seen_names:
            continue
        seen_names.add(name)
        out.append(
            {
                "source_id": source_id,
                "name": name,
                "title": _extract_title(text),
                "university": university,
                "department": department,
                "email": _extract_email(text),
                "profile_url": _best_profile_url(card, page_url),
                "source_page": page_url,
                "raw_text": text[:600],
                "faculty_confidence": "high",
            }
        )
    return out


PARSERS = {"generic_card": parse_generic_card}


def scrape_faculty_v2() -> pd.DataFrame:
    sources = _read_csv(DATA_DIR / "faculty_sources.csv")
    rows: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []

    if sources.empty:
        out = pd.DataFrame()
        out.to_csv(OUTPUT_DIR / "faculty_directory_v2.csv", index=False, encoding="utf-8-sig")
        return out

    for _, src in sources.iterrows():
        if src.get("enabled", "yes").strip().casefold() not in {"yes", "true", "1"}:
            continue
        source_id = src.get("source_id", "").strip()
        university = src.get("university", "").strip()
        department = src.get("department", "").strip()
        url = src.get("faculty_url", "").strip()
        parser_name = src.get("parser", "generic_card").strip() or "generic_card"
        parser = PARSERS.get(parser_name)
        if not url or parser is None:
            continue
        print(f"[faculty] {source_id} | {university} | {department}", flush=True)
        try:
            html = _fetch(url)
            parsed = parser(html, url, university, department, source_id)
            rows.extend(parsed)
            print(f"  -> {len(parsed)} faculty", flush=True)
        except Exception as exc:
            errors.append({
                "source_id": source_id,
                "faculty_url": url,
                "error": f"{type(exc).__name__}: {exc}",
            })
            print(f"  -> ERROR: {type(exc).__name__}: {exc}", flush=True)

    columns = [
        "source_id", "name", "title", "university", "department", "email",
        "profile_url", "source_page", "raw_text", "faculty_confidence",
    ]
    out = pd.DataFrame(rows, columns=columns)
    if not out.empty:
        out = out.drop_duplicates(subset=["name", "university", "department"], keep="first")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUTPUT_DIR / "faculty_directory_v2.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(errors, columns=["source_id", "faculty_url", "error"]).to_csv(
        OUTPUT_DIR / "faculty_source_errors.csv", index=False, encoding="utf-8-sig"
    )
    return out


if __name__ == "__main__":
    df = scrape_faculty_v2()
    print(f"Faculty v2 rows: {len(df)}")
