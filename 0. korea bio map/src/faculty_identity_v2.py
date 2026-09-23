from __future__ import annotations

import os
import re
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

from config import OUTPUT_DIR
from openalex_client import OpenAlexClient, normalize_openalex_id

BATCH_LIMIT = int(os.getenv("IDENTITY_BATCH_LIMIT", "20"))

COLUMNS = [
    "source_id", "name", "title", "university", "department", "email",
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
    stop = {"university", "college", "school", "hospital", "institute", "department", "national", "research"}
    return {
        t for t in re.findall(r"[a-z0-9가-힣]+", (value or "").casefold())
        if len(t) >= 3 and t not in stop
    }


def _affiliation(author: dict) -> str:
    institutions = author.get("last_known_institutions") or []
    return "; ".join(
        x.get("display_name", "") for x in institutions
        if isinstance(x, dict) and x.get("display_name")
    )


def _orcid(author: dict) -> str:
    value = str(author.get("orcid", "") or "").strip()
    return value.rstrip("/").split("/")[-1] if value else ""


def _key(row: pd.Series | dict) -> str:
    return "|".join([
        str(row.get("source_id", "")).strip().casefold(),
        str(row.get("name", "")).strip().casefold(),
        str(row.get("university", "")).strip().casefold(),
    ])


def _best_openalex(client: OpenAlexClient, name: str, university: str) -> tuple[dict | None, str]:
    try:
        data = client._get("authors", {"search": name, "per-page": 10})
    except Exception as exc:
        return None, f"OpenAlex unavailable: {type(exc).__name__}"

    target_tokens = _tokens(university)
    ranked: list[tuple[float, int, dict]] = []
    for author in data.get("results", []) or []:
        oa_name = str(author.get("display_name", ""))
        aff = _affiliation(author)
        overlap = len(target_tokens & _tokens(aff))
        sim = _name_similarity(name, oa_name)
        score = sim + min(overlap, 2) * 0.35
        ranked.append((score, overlap, author))

    if not ranked:
        return None, "no OpenAlex candidates"

    ranked.sort(key=lambda x: x[0], reverse=True)
    score, overlap, best = ranked[0]
    sim = _name_similarity(name, str(best.get("display_name", "")))

    if sim < 0.72:
        return None, f"best name similarity too low ({sim:.2f})"
    if university and overlap < 1:
        return None, "name candidate found but current institution does not match"
    return best, f"name similarity {sim:.2f}; institution overlap {overlap}"


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
        university = person.get("university", "").strip()
        print(f"[{i}/{len(pending)}] {name} | {university}", flush=True)

        author, reason = _best_openalex(client, name, university)
        status = "manual_review"
        confidence = "low"
        orcid = ""
        oa_id = ""
        oa_name = ""
        oa_aff = ""

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


if __name__ == "__main__":
    df = resolve_faculty_identities_v2()
    print(f"Faculty identity v2 rows: {len(df)}")
