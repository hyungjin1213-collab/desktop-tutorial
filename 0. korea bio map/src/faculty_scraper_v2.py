from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

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
    "전공", "대학소개", "학과소개", "연구", "교육", "입학", "공지", "뉴스",
    "faculty", "professor", "people", "profile",
}
IMAGE_BLACKLIST = {
    "logo", "icon", "banner", "arrow", "btn", "button", "sprite", "favicon",
    "symbol", "mark", "header", "footer", "menu", "nav", "sns", "facebook",
    "youtube", "instagram", "twitter", "linkedin", "search", "home",
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
        headers={"User-Agent": "Mozilla/5.0 (compatible; AboutBioFacultyCollector/2.1)"},
    )
    r.raise_for_status()
    r.encoding = r.apparent_encoding or r.encoding
    return r.text


def _looks_like_person_name(text: str) -> bool:
    t = _clean(text)
    if not t or len(t) > 60:
        return False

    low = t.casefold()
    if low in {x.casefold() for x in NAME_BLACKLIST}:
        return False
    if any(x.casefold() in low for x in EXCLUDED):
        return False

    # Korean personal name, optionally with English name in parentheses.
    if re.fullmatch(r"[가-힣]{2,4}(?:\([A-Za-z .'-]{3,40}\))?", t):
        return True

    # Latin-style personal name.
    if re.fullmatch(r"[A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){1,3}", t):
        return True

    return False


def _extract_title(text: str) -> str:
    low = text.casefold()
    for title in TITLE_PATTERNS:
        if title.casefold() in low:
            return title
    return ""


def _extract_email(text: str) -> str:
    m = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text, flags=re.I)
    return m.group(0) if m else ""


def _is_probable_person_photo(img: Tag) -> bool:
    src = str(img.get("src", "") or img.get("data-src", "") or img.get("data-original", ""))
    alt = _clean(str(img.get("alt", "")))
    hay = f"{src} {alt}".casefold()

    if not src:
        return False
    if any(word in hay for word in IMAGE_BLACKLIST):
        return False

    # Explicit tiny decorative images are ignored.
    try:
        width = int(str(img.get("width", "0")).replace("px", "") or 0)
    except ValueError:
        width = 0
    try:
        height = int(str(img.get("height", "0")).replace("px", "") or 0)
    except ValueError:
        height = 0
    if width and height and (width < 60 or height < 60):
        return False

    return True


def _name_candidates(card: Tag, img: Tag | None = None) -> list[str]:
    candidates: list[str] = []

    # Image alt/title often directly contains the professor name.
    if img is not None:
        for attr in ("alt", "title"):
            value = _clean(str(img.get(attr, "")))
            if _looks_like_person_name(value):
                candidates.append(value)

    selectors = [
        ".name", ".prof-name", ".faculty-name", ".member-name", ".person-name",
        "h1", "h2", "h3", "h4", "h5", "strong", "b",
    ]
    for sel in selectors:
        for node in card.select(sel):
            value = _clean(node.get_text(" ", strip=True))
            if _looks_like_person_name(value):
                candidates.append(value)

    for a in card.find_all("a", href=True):
        value = _clean(a.get_text(" ", strip=True))
        if _looks_like_person_name(value):
            candidates.append(value)

    # Last fallback only scans short standalone fragments.
    if not candidates:
        for s in card.stripped_strings:
            value = _clean(str(s))
            if len(value) <= 60 and _looks_like_person_name(value):
                candidates.append(value)

    return list(dict.fromkeys(candidates))


def _best_profile_url(card: Tag, page_url: str) -> str:
    preferred = []
    ordinary = []

    for a in card.find_all("a", href=True):
        href = urljoin(page_url, str(a.get("href", "")))
        label = _clean(a.get_text(" ", strip=True)).casefold()
        href_low = href.casefold()

        if href.startswith("mailto:") or href.startswith("javascript:"):
            continue

        if any(k in label or k in href_low for k in [
            "상세", "profile", "homepage", "faculty", "professor",
            "research", "lab", "연구실", "사이트",
        ]):
            preferred.append(href)
        else:
            ordinary.append(href)

    if preferred:
        return preferred[0]
    return ordinary[0] if ordinary else page_url


def _profile_link_score(card: Tag, page_url: str) -> int:
    profile = _best_profile_url(card, page_url)
    return 1 if profile and profile != page_url else 0


def _score_card(card: Tag, img: Tag, page_url: str) -> tuple[int, str, str, str]:
    text = _clean(card.get_text(" ", strip=True))
    low = text.casefold()

    if len(text) < 5 or len(text) > 1400:
        return 0, "", "", ""
    if any(x.casefold() in low for x in EXCLUDED):
        return 0, "", "", ""

    names = _name_candidates(card, img)
    name = names[0] if names else ""
    title = _extract_title(text)
    email = _extract_email(text)

    score = 0
    if name:
        score += 2
    if title:
        score += 2
    if email:
        score += 2
    score += _profile_link_score(card, page_url)
    if _is_probable_person_photo(img):
        score += 1

    return score, name, title, email


def _find_best_card_for_image(img: Tag, page_url: str) -> tuple[Tag | None, int, str, str, str]:
    node: Tag | None = img
    best: tuple[Tag | None, int, str, str, str] = (None, 0, "", "", "")

    # Walk upward from the photo and choose the smallest ancestor that
    # contains enough professor-specific signals.
    for _ in range(6):
        parent = node.parent if isinstance(node, Tag) else None
        if not isinstance(parent, Tag):
            break
        node = parent

        if parent.name in {"body", "html", "nav", "header", "footer"}:
            break

        score, name, title, email = _score_card(parent, img, page_url)
        if score > best[1]:
            best = (parent, score, name, title, email)

        # 5+ is strong enough to stop at this small local block.
        if score >= 5:
            return parent, score, name, title, email

    return best


def parse_photo_anchor(html: str, page_url: str, university: str, department: str, source_id: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for img in soup.find_all("img"):
        if not isinstance(img, Tag) or not _is_probable_person_photo(img):
            continue

        card, score, name, title, email = _find_best_card_for_image(img, page_url)
        if card is None or score < 5 or not name or not title:
            continue

        text = _clean(card.get_text(" ", strip=True))
        profile_url = _best_profile_url(card, page_url)
        key = (name.casefold(), profile_url.casefold())
        if key in seen:
            continue
        seen.add(key)

        confidence = "high" if score >= 7 else "medium"
        out.append({
            "source_id": source_id,
            "name": name,
            "title": title,
            "university": university,
            "department": department,
            "email": email,
            "profile_url": profile_url,
            "source_page": page_url,
            "photo_url": urljoin(page_url, str(img.get("src", "") or img.get("data-src", ""))),
            "evidence_score": str(score),
            "raw_text": text[:600],
            "faculty_confidence": confidence,
        })

    return out


PARSERS = {
    "photo_anchor": parse_photo_anchor,
    "generic_card": parse_photo_anchor,  # legacy source rows now use the safer parser too
}


def scrape_faculty_v2() -> pd.DataFrame:
    sources = _read_csv(DATA_DIR / "faculty_sources.csv")
    rows: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

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
        parser_name = src.get("parser", "photo_anchor").strip() or "photo_anchor"
        parser = PARSERS.get(parser_name, parse_photo_anchor)

        if not url:
            continue

        print(f"[faculty-photo] {source_id} | {university} | {department}", flush=True)
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
        "profile_url", "source_page", "photo_url", "evidence_score",
        "raw_text", "faculty_confidence",
    ]

    out = pd.DataFrame(rows, columns=columns)
    if not out.empty:
        out = out.drop_duplicates(
            subset=["name", "university", "department"],
            keep="first",
        )

    out.to_csv(
        OUTPUT_DIR / "faculty_directory_v2.csv",
        index=False,
        encoding="utf-8-sig",
    )
    pd.DataFrame(
        errors,
        columns=["source_id", "faculty_url", "error"],
    ).to_csv(
        OUTPUT_DIR / "faculty_source_errors.csv",
        index=False,
        encoding="utf-8-sig",
    )
    return out


if __name__ == "__main__":
    df = scrape_faculty_v2()
    print(f"Faculty v2 rows: {len(df)}")
