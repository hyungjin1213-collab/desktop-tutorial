from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
import urllib3
from bs4 import BeautifulSoup, Tag

from config import DATA_DIR, OUTPUT_DIR
from name_extraction import (
    EXCLUDED_TITLES,
    english_matches_korean,
    english_name_from_email,
    extract_person,
    frequent_hangul_tokens,
)

REQUEST_TIMEOUT_SECONDS = 12
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
# Detail pages fetched per run to find English names / emails missing on the list page.
PROFILE_FETCH_LIMIT = int(os.getenv("PROFILE_FETCH_LIMIT", "400"))

EXCLUDED = {
    "겸임교수", "보직교수", "초빙교수", "명예교수", "emeritus",
    "adjunct", "visiting professor", "postdoc", "postdoctoral", "retired",
}
TITLE_PATTERNS = [
    "정교수", "부교수", "조교수", "교수",
    "full professor", "associate professor", "assistant professor", "professor",
]
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
    headers = {"User-Agent": "Mozilla/5.0 (compatible; AboutBioFacultyCollector/2.1)"}
    try:
        r = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS, headers=headers)
    except requests.exceptions.SSLError:
        # Many Korean university sites serve an incomplete certificate chain.
        # These are public pages read without credentials, so retry unverified.
        r = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS, headers=headers, verify=False)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or r.encoding
    return r.text


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

    person = extract_person(text)
    name = person.display
    title = person.title or _extract_title(text)
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


def _drop_nested(cards: list[tuple[Tag, Tag | None]]) -> list[tuple[Tag, Tag | None]]:
    """Keep the smallest cards; a block that contains another card is a list wrapper."""
    ids = {id(c) for c, _ in cards}
    out = []
    for card, img in cards:
        if any(id(d) in ids for d in card.find_all(True)):
            continue
        out.append((card, img))
    return list({id(c): (c, i) for c, i in out}.values())


def _photo_cards(soup: BeautifulSoup, page_url: str) -> list[tuple[Tag, Tag | None]]:
    cards: list[tuple[Tag, Tag | None]] = []
    for img in soup.find_all("img"):
        if not isinstance(img, Tag) or not _is_probable_person_photo(img):
            continue
        card, score, name, title, _ = _find_best_card_for_image(img, page_url)
        if card is not None and score >= 5 and name and title:
            cards.append((card, img))
    return _drop_nested(cards)


def _row_cards(soup: BeautifulSoup) -> list[tuple[Tag, Tag | None]]:
    """Fallback for table / list layouts without photos."""
    cards: list[tuple[Tag, Tag | None]] = []
    for node in soup.find_all(["tr", "li", "dl"]):
        text = _clean(node.get_text(" ", strip=True))
        if 5 <= len(text) <= 400 and _extract_title(text):
            cards.append((node, None))
    return _drop_nested(cards)


def parse_photo_anchor(html: str, page_url: str, university: str, department: str, source_id: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    for junk in soup.find_all(["nav", "header", "footer", "script", "style"]):
        junk.decompose()

    cards = _photo_cards(soup, page_url)
    if len(cards) < 3:
        cards = cards + _row_cards(soup)
    texts = [_clean(c.get_text(" ", strip=True)) for c, _ in cards]
    # Field tags (분자세포, 면역) repeat across cards; names do not.
    frequent = frequent_hangul_tokens(texts)

    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for (card, img), text in zip(cards, texts):
        low = text.casefold()
        if any(x.casefold() in low for x in EXCLUDED):
            continue
        person = extract_person(text, frequent)
        if not person.ok or person.title in EXCLUDED_TITLES:
            continue
        if not person.title and person.confidence == "low":
            continue

        email = _extract_email(text)
        profile_url = _best_profile_url(card, page_url)
        key = (person.name_ko or person.name_en).casefold()
        if key in seen:
            continue
        seen.add(key)

        photo_url = ""
        if img is not None:
            photo_url = urljoin(page_url, str(img.get("src", "") or img.get("data-src", "")))
        score = sum([2 * bool(person.display), 2 * bool(person.title), 2 * bool(email),
                     int(profile_url != page_url), int(img is not None)])
        out.append({
            "source_id": source_id,
            "name": person.display,
            "name_ko": person.name_ko,
            "name_en": person.name_en,
            "title": person.title,
            "university": university,
            "department": department,
            "email": email,
            "profile_url": profile_url,
            "source_page": page_url,
            "photo_url": photo_url,
            "evidence_score": str(score),
            "name_reason": person.reason,
            "name_en_source": "list_page" if person.name_en else "",
            "raw_text": text[:600],
            "faculty_confidence": person.confidence,
        })

    return out


def _english_name_on_profile(html: str, name_ko: str) -> str:
    text = _clean(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))
    person = extract_person(f"{name_ko} 교수 {text[:3000]}")
    if person.name_ko == name_ko and person.name_en and english_matches_korean(person.name_en, name_ko):
        return person.name_en
    return ""


def enrich_from_profiles(rows: list[dict[str, str]], fetch=None) -> None:
    """Fill name_en / email from each professor's detail page, then from the email.

    Only same-site detail pages are fetched (lab homepages are skipped) and
    at most PROFILE_FETCH_LIMIT per run.
    """
    fetch = fetch or _fetch
    budget = PROFILE_FETCH_LIMIT
    for row in rows:
        name_ko = row.get("name_ko", "")
        if not name_ko or (row.get("name_en") and row.get("email")):
            continue
        profile, page = row.get("profile_url", ""), row.get("source_page", "")
        if budget > 0 and profile and profile != page and urlparse(profile).netloc == urlparse(page).netloc:
            budget -= 1
            try:
                html = fetch(profile)
            except Exception:
                html = ""
            if html:
                if not row.get("name_en"):
                    en = _english_name_on_profile(html, name_ko)
                    if en:
                        row["name_en"], row["name_en_source"] = en, "profile_page"
                if not row.get("email"):
                    row["email"] = _extract_email(_clean(BeautifulSoup(html, "html.parser").get_text(" ")))
        if not row.get("name_en") and row.get("email"):
            en = english_name_from_email(name_ko, row["email"])
            if en:
                row["name_en"], row["name_en_source"] = en, "email"


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

    seen_lists: dict[frozenset, str] = {}
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
            # The same list is often reachable at several URLs (http/https,
            # www.x.ac.kr/dept vs dept.x.ac.kr); scrape it once.
            names = frozenset((university, r["name"]) for r in parsed)
            if len(names) >= 3 and names in seen_lists:
                print(f"  -> duplicate of {seen_lists[names]}, skipped", flush=True)
                continue
            seen_lists.setdefault(names, source_id)
            rows.extend(parsed)
            print(f"  -> {len(parsed)} faculty", flush=True)
        except Exception as exc:
            errors.append({
                "source_id": source_id,
                "faculty_url": url,
                "error": f"{type(exc).__name__}: {exc}",
            })
            print(f"  -> ERROR: {type(exc).__name__}: {exc}", flush=True)

    enrich_from_profiles(rows)

    columns = [
        "source_id", "name", "name_ko", "name_en", "title", "university", "department", "email",
        "profile_url", "source_page", "photo_url", "evidence_score", "name_reason",
        "name_en_source", "raw_text", "faculty_confidence",
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
