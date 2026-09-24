from __future__ import annotations

import os
import re
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

from config import DATA_DIR, OUTPUT_DIR
from name_extraction import english_matches_korean, english_query_variants
from openalex_client import OpenAlexClient, normalize_openalex_id

BATCH_LIMIT = int(os.getenv("IDENTITY_BATCH_LIMIT", "20"))

# OpenAlex spells institutions out in full; faculty pages often use acronyms.
INSTITUTION_ALIASES = {
    "kaist": "korea advanced institute science technology",
    "postech": "pohang university science technology",
    "unist": "ulsan national institute science technology",
    "gist": "gwangju institute science technology",
    "dgist": "daegu gyeongbuk institute science technology",
    "skku": "sungkyunkwan",
    "snu": "seoul",
}

COLUMNS = [
    "source_id", "name", "name_ko", "name_en", "title", "university", "department", "email",
    "profile_url", "source_page", "orcid", "openalex_id", "openalex_name",
    "openalex_affiliation", "identity_confidence", "identity_status", "identity_reason",
]


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str).fillna("")


def _norm_name(value: str) -> str:
    return re.sub(r"[^a-z0-9가-힣]", "", (value or "").casefold())


def _name_similarity(a: str, b: str) -> float:
    na, nb = _norm_name(a), _norm_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def _tokens(value: str) -> set[str]:
    stop = {"university", "college", "school", "hospital", "institute", "department", "national",
            "research", "science", "technology", "and", "of", "the"}
    text = (value or "").casefold()
    for short, full in INSTITUTION_ALIASES.items():
        if re.search(rf"\b{short}\b", text):
            text += " " + full
    return {t for t in re.findall(r"[a-z0-9가-힣]+", text) if len(t) >= 3 and t not in stop}


def _affiliation(author: dict) -> str:
    institutions = author.get("last_known_institutions") or []
    return "; ".join(
        x.get("display_name", "") for x in institutions
        if isinstance(x, dict) and x.get("display_name")
    )


def _all_affiliations(author: dict) -> str:
    names = [_affiliation(author)]
    for aff in author.get("affiliations") or []:
        inst = aff.get("institution") if isinstance(aff, dict) else None
        if isinstance(inst, dict) and inst.get("display_name"):
            names.append(inst["display_name"])
    return "; ".join(n for n in names if n)


def _orcid(author: dict) -> str:
    value = str(author.get("orcid", "") or "").strip()
    return value.rstrip("/").split("/")[-1] if value else ""


def _key(row: pd.Series | dict) -> str:
    return "|".join([
        str(row.get("source_id", "")).strip().casefold(),
        str(row.get("name", "")).strip().casefold(),
        str(row.get("university", "")).strip().casefold(),
    ])


def _name_matches(author: dict, name_ko: str, name_en: str) -> tuple[bool, float]:
    names = [str(author.get("display_name", ""))] + [
        str(x) for x in author.get("display_name_alternatives") or []
    ]
    if name_ko:
        if name_ko in names:
            return True, 1.0
        if any(english_matches_korean(n, name_ko) for n in names):
            return True, 0.95
    if name_en:
        sim = max(_name_similarity(name_en, n) for n in names)
        return sim >= 0.85, sim
    return False, 0.0


def _search_queries(name_ko: str, name_en: str, name: str) -> list[str]:
    queries = [name_en] if name_en else english_query_variants(name_ko)
    return [q for q in dict.fromkeys(queries or [name]) if q]


def _best_openalex(
    client: OpenAlexClient, name_ko: str, name_en: str, university: str, fallback_name: str = "",
) -> tuple[dict | None, str]:
    """Pick the OpenAlex author whose romanized name and institution both fit.

    OpenAlex display names are English, so searching with a Hangul name
    returns nothing useful: search with the page's English name, or with
    romanization variants of the Korean name when the page has none.
    """
    candidates: dict[str, dict] = {}
    for query in _search_queries(name_ko, name_en, fallback_name):
        try:
            data = client._get("authors", {"search": query, "per-page": 25})
        except Exception as exc:
            return None, f"OpenAlex unavailable: {type(exc).__name__}"
        for author in data.get("results", []) or []:
            candidates.setdefault(str(author.get("id", "")), author)

    if not candidates:
        return None, "no OpenAlex candidates"

    target = _tokens(university)
    passing: list[tuple[int, int, float, dict]] = []
    name_hits = 0
    for author in candidates.values():
        ok, sim = _name_matches(author, name_ko, name_en)
        if not ok:
            continue
        name_hits += 1
        current = len(target & _tokens(_affiliation(author)))
        ever = len(target & _tokens(_all_affiliations(author)))
        if university and not ever:
            continue
        passing.append((current, ever, sim, author))

    if not passing:
        if name_hits:
            return None, f"{name_hits} name match(es) but none at {university}"
        return None, "no romanization-consistent name match"

    passing.sort(key=lambda x: (x[0] > 0, x[1], x[2], x[3].get("works_count", 0)), reverse=True)
    current, ever, sim, best = passing[0]
    same_level = [p for p in passing if (p[0] > 0) == (current > 0) and p[1] == ever]
    if len(same_level) > 1:
        return None, f"ambiguous: {len(same_level)} same-name authors at {university}"
    where = "current" if current else "past"
    return best, f"name match {sim:.2f}; {where} institution match"


def resolve_faculty_identities_v2() -> pd.DataFrame:
    faculty_path = OUTPUT_DIR / "faculty_directory_v2.csv"
    out_path = OUTPUT_DIR / "faculty_identity_v2.csv"
    faculty = _read_csv(faculty_path)
    existing = _read_csv(out_path)

    if faculty.empty:
        out = pd.DataFrame(columns=COLUMNS)
        out.to_csv(out_path, index=False, encoding="utf-8-sig")
        return out

    done = {_key(row) for _, row in existing.iterrows()} if not existing.empty else set()
    pending = faculty[faculty.apply(lambda r: _key(r) not in done, axis=1)].head(BATCH_LIMIT)
    print(f"Identity v2: {len(done)} done / {len(faculty)} total; processing {len(pending)}", flush=True)

    if pending.empty:
        return existing if not existing.empty else pd.DataFrame(columns=COLUMNS)

    client = OpenAlexClient()
    rows: list[dict[str, str]] = []

    for i, (_, person) in enumerate(pending.iterrows(), start=1):
        name = person.get("name", "").strip()
        name_ko = person.get("name_ko", "").strip()
        name_en = person.get("name_en", "").strip()
        if not name_ko and not name_en:
            # Rows from older scraper output only have "name".
            name_ko, name_en = (name, "") if re.search(r"[가-힣]", name) else ("", name)
        university = person.get("university", "").strip()
        print(f"[{i}/{len(pending)}] {name} | {university}", flush=True)

        author, reason = _best_openalex(client, name_ko, name_en, university, name)
        status = "manual_review"
        confidence = "low"
        orcid = oa_id = oa_name = oa_aff = ""

        if author:
            orcid = _orcid(author)
            oa_id = normalize_openalex_id(str(author.get("id", "")))
            oa_name = str(author.get("display_name", ""))
            oa_aff = _affiliation(author)
            if orcid:
                status = "verified"
                confidence = "high"
                reason += "; OpenAlex record has ORCID"
            else:
                status = "probable"
                confidence = "medium"
                reason += "; no ORCID on OpenAlex record"

        rows.append({
            "source_id": person.get("source_id", ""),
            "name": name,
            "name_ko": name_ko,
            "name_en": name_en,
            "title": person.get("title", ""),
            "university": university,
            "department": person.get("department", ""),
            "email": person.get("email", ""),
            "profile_url": person.get("profile_url", ""),
            "source_page": person.get("source_page", ""),
            "orcid": orcid,
            "openalex_id": oa_id,
            "openalex_name": oa_name,
            "openalex_affiliation": oa_aff,
            "identity_confidence": confidence,
            "identity_status": status,
            "identity_reason": reason,
        })

    batch = pd.DataFrame(rows, columns=COLUMNS)
    out = pd.concat([existing, batch], ignore_index=True) if not existing.empty else batch
    out = out.drop_duplicates(subset=["source_id", "name", "university"], keep="last")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"Saved {len(out)} identity v2 rows", flush=True)
    return out


def import_verified_faculty_v2() -> int:
    identity = _read_csv(OUTPUT_DIR / "faculty_identity_v2.csv")
    professors_path = DATA_DIR / "professors_seed.csv"
    professors = _read_csv(professors_path)
    if identity.empty or professors.empty:
        return 0

    existing_openalex = {normalize_openalex_id(x) for x in professors.get("openalex_id", []) if normalize_openalex_id(x)}
    existing_profiles = {str(x).strip() for x in professors.get("source_url", []) if str(x).strip()}
    nums = []
    for pid in professors.get("professor_id", []):
        m = re.fullmatch(r"P(\d+)", str(pid).strip(), flags=re.I)
        if m:
            nums.append(int(m.group(1)))
    next_num = max(nums) + 1 if nums else 1

    new_rows = []
    for _, row in identity.iterrows():
        if row.get("identity_status", "") != "verified":
            continue
        oa = normalize_openalex_id(row.get("openalex_id", ""))
        profile = row.get("profile_url", "").strip()
        if not oa or oa in existing_openalex or (profile and profile in existing_profiles):
            continue
        name = row.get("name", "")
        name_ko = row.get("name_ko", "") or (name if re.search(r"[가-힣]", name) else "")
        new_rows.append({
            "professor_id": f"P{next_num:04d}",
            "name_ko": name_ko,
            "name_en": row.get("openalex_name", "") or name,
            "university": row.get("university", ""),
            "department": row.get("department", ""),
            "primary_field": "",
            "openalex_id": oa,
            "source_url": profile or row.get("source_page", ""),
        })
        next_num += 1
        existing_openalex.add(oa)
        if profile:
            existing_profiles.add(profile)

    if new_rows:
        professors = pd.concat([professors, pd.DataFrame(new_rows)], ignore_index=True)
        professors.to_csv(professors_path, index=False, encoding="utf-8-sig")
    return len(new_rows)


if __name__ == "__main__":
    df = resolve_faculty_identities_v2()
    print(f"Faculty identity v2 rows: {len(df)}")
