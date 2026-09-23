from __future__ import annotations

import os
import re
from pathlib import Path

import pandas as pd

from config import DATA_DIR, OUTPUT_DIR
from openalex_client import OpenAlexClient, normalize_openalex_id
from orcid_client import ORCIDClient, normalize_orcid

IDENTITY_BATCH_LIMIT = int(os.getenv("IDENTITY_BATCH_LIMIT", "25"))

IDENTITY_COLUMNS = [
    "name", "title", "university", "department", "email", "profile_url", "source_page",
    "orcid", "orcid_url", "orcid_match_score", "orcid_source",
    "openalex_id", "openalex_name", "openalex_affiliation",
    "identity_confidence", "identity_status", "identity_reason",
]


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str).fillna("")


def _tokens(value: str) -> set[str]:
    stop = {"university", "college", "school", "hospital", "institute", "department", "national"}
    return {t for t in re.findall(r"[a-z0-9가-힣]+", (value or "").casefold()) if len(t) >= 3 and t not in stop}


def _openalex_affiliation(author: dict) -> str:
    institutions = author.get("last_known_institutions") or []
    return "; ".join(x.get("display_name", "") for x in institutions if isinstance(x, dict) and x.get("display_name"))


def _find_openalex_by_orcid(client: OpenAlexClient, orcid: str) -> dict | None:
    oid = normalize_orcid(orcid)
    if not oid:
        return None
    try:
        data = client._get("authors", {"filter": f"orcid:https://orcid.org/{oid}", "per-page": 5})
    except Exception:
        return None
    results = data.get("results", [])
    return results[0] if results else None


def _person_key(row: pd.Series | dict) -> str:
    profile = str(row.get("profile_url", "")).strip()
    if profile:
        return profile
    return "|".join([
        str(row.get("name", "")).strip().casefold(),
        str(row.get("university", "")).strip().casefold(),
        str(row.get("department", "")).strip().casefold(),
    ])


def match_faculty_identities() -> pd.DataFrame:
    faculty = _read_csv(OUTPUT_DIR / "faculty_directory.csv")
    out_path = OUTPUT_DIR / "faculty_identity.csv"
    existing = _read_csv(out_path)

    if faculty.empty:
        out = pd.DataFrame(columns=IDENTITY_COLUMNS)
        out.to_csv(out_path, index=False, encoding="utf-8-sig")
        return out

    done_keys = {_person_key(row) for _, row in existing.iterrows()} if not existing.empty else set()
    pending = faculty[faculty.apply(lambda r: _person_key(r) not in done_keys, axis=1)].head(IDENTITY_BATCH_LIMIT)

    print(f"Identity progress: {len(done_keys)} done / {len(faculty)} total; processing up to {len(pending)} now", flush=True)

    if pending.empty:
        return existing if not existing.empty else pd.DataFrame(columns=IDENTITY_COLUMNS)

    orcid_client = ORCIDClient()
    openalex = OpenAlexClient()
    rows: list[dict[str, str]] = []

    for i, (_, person) in enumerate(pending.iterrows(), start=1):
        name = person.get("name", "").strip()
        university = person.get("university", "").strip()
        department = person.get("department", "").strip()
        email = person.get("email", "").strip()
        profile_url = person.get("profile_url", "").strip()
        source_page = person.get("source_page", "").strip()
        print(f"[{i}/{len(pending)}] {name} | {university}", flush=True)

        orcid_hit = orcid_client.search_best(name, university, email) if name else None
        orcid = normalize_orcid(orcid_hit.get("orcid", "")) if orcid_hit else ""

        author = _find_openalex_by_orcid(openalex, orcid) if orcid else None
        reason_parts: list[str] = []
        confidence = "low"
        status = "manual_review"

        if author and orcid:
            confidence = "high"
            status = "verified"
            reason_parts.append("official faculty page + ORCID + OpenAlex ORCID match")
        elif name and university:
            author = openalex.search_author(name, university)
            if author:
                oa_aff = _openalex_affiliation(author)
                if len(_tokens(university) & _tokens(oa_aff)) >= 1:
                    confidence = "medium"
                    status = "probable"
                    reason_parts.append("official faculty page + OpenAlex institution match")
                else:
                    reason_parts.append("OpenAlex candidate found but institution evidence weak")
            else:
                reason_parts.append("no reliable OpenAlex match")
        else:
            reason_parts.append("insufficient name/institution data")

        if not orcid:
            reason_parts.append("ORCID not resolved")

        rows.append({
            "name": name,
            "title": person.get("title", ""),
            "university": university,
            "department": department,
            "email": email,
            "profile_url": profile_url,
            "source_page": source_page,
            "orcid": orcid,
            "orcid_url": orcid_hit.get("url", "") if orcid_hit else "",
            "orcid_match_score": str(orcid_hit.get("match_score", "")) if orcid_hit else "",
            "orcid_source": orcid_hit.get("source", "") if orcid_hit else "",
            "openalex_id": normalize_openalex_id(author.get("id", "")) if author else "",
            "openalex_name": str(author.get("display_name", "")) if author else "",
            "openalex_affiliation": _openalex_affiliation(author) if author else "",
            "identity_confidence": confidence,
            "identity_status": status,
            "identity_reason": "; ".join(reason_parts),
        })

    batch = pd.DataFrame(rows, columns=IDENTITY_COLUMNS)
    out = pd.concat([existing, batch], ignore_index=True) if not existing.empty else batch
    out = out.drop_duplicates(subset=["profile_url", "name", "university"], keep="last")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"Saved {len(out)} identity rows. Re-run this mode to process the next batch.", flush=True)
    return out


def import_verified_faculty() -> int:
    identity = _read_csv(OUTPUT_DIR / "faculty_identity.csv")
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
        if row.get("identity_status", "") not in {"verified", "probable"}:
            continue
        oa = normalize_openalex_id(row.get("openalex_id", ""))
        profile = row.get("profile_url", "").strip()
        if not oa or oa in existing_openalex or (profile and profile in existing_profiles):
            continue

        new_rows.append({
            "professor_id": f"P{next_num:04d}",
            "name_ko": row.get("name", "") if re.search(r"[가-힣]", row.get("name", "")) else "",
            "name_en": row.get("openalex_name", "") or row.get("name", ""),
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
    df = match_faculty_identities()
    print(f"Faculty identities: {len(df)}")
