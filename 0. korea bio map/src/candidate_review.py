from __future__ import annotations

import re

import pandas as pd

from config import OUTPUT_DIR
from openalex_client import OpenAlexClient, normalize_openalex_id
from scholar_client import SCHOLAR_LOOKUP_LIMIT, ScholarClient


ACADEMIC_WORDS = (
    "university", "college", "school of", "hospital", "medical center",
    "institute", "research center", "research centre", "kaist", "postech",
    "gist", "unist", "dgist", "kist", "kribb", "ibs",
)
PI_WORDS = (
    "professor", "principal investigator", "group leader",
    "laboratory head", "lab head", "director", "faculty",
)
BIO_WORDS = (
    "cancer", "tumor", "immune", "immun", "cell", "protein", "rna", "dna",
    "gene", "bio", "medical", "drug", "therap", "microb", "metabol",
    "biomaterial", "nanoparticle", "vaccine", "disease", "stem cell",
)
NONBIO_WORDS = (
    "semiconductor", "solar cell", "electrical", "payment system",
    "postal service", "dram", "soc design", "ecg waveform soundwave",
)


def _safe_int(value: object) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return 0


def _academic_signal(text: str) -> bool:
    lower = (text or "").casefold()
    return any(word in lower for word in ACADEMIC_WORDS)


def _pi_signal(text: str) -> bool:
    lower = (text or "").casefold()
    return any(word in lower for word in PI_WORDS)


def _bio_signal(text: str) -> bool:
    lower = (text or "").casefold()
    bio = sum(word in lower for word in BIO_WORDS)
    nonbio = sum(word in lower for word in NONBIO_WORDS)
    return bio > nonbio


def _norm_tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z]{4,}", (text or "").casefold())
        if token not in {
            "university", "college", "institute", "hospital", "center",
            "centre", "national", "research", "medical",
        }
    }


def _affiliation_conflict(old: str, current: str) -> bool:
    if not old or not current:
        return False
    a, b = _norm_tokens(old), _norm_tokens(current)
    return bool(a and b and not (a & b))


def classify_candidates(
    openalex: OpenAlexClient,
    scholar: ScholarClient,
) -> pd.DataFrame:
    path = OUTPUT_DIR / "collaborator_candidates.csv"
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()

    df = pd.read_csv(path, dtype=str).fillna("")
    rows = []

    for idx, (_, row) in enumerate(df.iterrows()):
        item = row.to_dict()
        oid = normalize_openalex_id(item.get("openalex_id", ""))
        author = openalex.get_author(oid) if oid else None

        last_known = ""
        current_country = ""
        if author:
            insts = author.get("last_known_institutions") or []
            last_known = "; ".join(
                i.get("display_name", "") for i in insts if i.get("display_name")
            )
            countries = [i.get("country_code", "") for i in insts if i.get("country_code")]
            current_country = "; ".join(sorted(set(countries)))

        scholar_profile = None
        if idx < SCHOLAR_LOOKUP_LIMIT and scholar.enabled:
            scholar_profile = scholar.search_profile(
                item.get("display_name", ""),
                item.get("institutions", ""),
            )

        scholar_affiliation = ""
        scholar_url = ""
        scholar_email = ""
        scholar_cited_by = ""
        if scholar_profile:
            scholar_affiliation = scholar_profile.get("affiliations", "") or ""
            scholar_url = scholar_profile.get("link", "") or ""
            scholar_email = scholar_profile.get("email", "") or ""
            scholar_cited_by = str(scholar_profile.get("cited_by", "") or "")

        if scholar_affiliation:
            current_affiliation = scholar_affiliation
            affiliation_source = "google_scholar_serpapi"
        elif last_known:
            current_affiliation = last_known
            affiliation_source = "openalex_last_known"
        else:
            current_affiliation = item.get("institutions", "")
            affiliation_source = "authorship_history"

        shared = _safe_int(item.get("shared_paper_count", 0))
        seed_count = _safe_int(item.get("seed_connection_count", 0))
        academic = _academic_signal(current_affiliation)
        pi_hint = _pi_signal(current_affiliation)
        bio = _bio_signal(item.get("example_work", ""))
        conflict = _affiliation_conflict(item.get("institutions", ""), current_affiliation)

        score = 0
        score += min(shared, 10)
        score += max(seed_count - 1, 0) * 5
        score += 3 if academic else 0
        score += 2 if bio else -3
        score += 2 if pi_hint else 0
        score -= 3 if conflict else 0

        if current_country and "KR" not in current_country and scholar_affiliation == "":
            tier = "C_manual"
            reason = "current OpenAlex affiliation is not clearly Korea-based"
        elif academic and bio and (seed_count >= 2 or shared >= 10):
            tier = "A_review_first"
            reason = "strong collaboration signal + academic affiliation + bio relevance"
        elif academic and bio and (seed_count >= 2 or shared >= 5):
            tier = "B_review"
            reason = "moderate collaboration signal + academic affiliation + bio relevance"
        elif not bio and shared >= 5:
            tier = "D_noise_check"
            reason = "collaboration signal exists but example work looks outside bio"
        else:
            tier = "C_manual"
            reason = "insufficient evidence for automatic PI/professor inference"

        item.update(
            {
                "current_affiliation": current_affiliation,
                "affiliation_source": affiliation_source,
                "scholar_affiliation": scholar_affiliation,
                "scholar_profile_url": scholar_url,
                "scholar_email": scholar_email,
                "scholar_cited_by": scholar_cited_by,
                "openalex_last_known_affiliation": last_known,
                "current_country_codes": current_country,
                "academic_affiliation_signal": "yes" if academic else "no",
                "pi_title_signal": "yes" if pi_hint else "no",
                "bio_relevance_signal": "yes" if bio else "no",
                "affiliation_conflict_warning": "yes" if conflict else "no",
                "triage_score": score,
                "triage_tier": tier,
                "triage_reason": reason,
                "human_decision": "",
            }
        )
        rows.append(item)

    result = pd.DataFrame(rows)
    order = {"A_review_first": 0, "B_review": 1, "C_manual": 2, "D_noise_check": 3}
    result["_tier_order"] = result["triage_tier"].map(order).fillna(9)
    result = result.sort_values(
        ["_tier_order", "triage_score", "shared_paper_count"],
        ascending=[True, False, False],
    ).drop(columns=["_tier_order"])

    result.to_csv(OUTPUT_DIR / "candidate_review.csv", index=False)

    # Human-friendly approval sheet. Only A/B candidates are surfaced here.
    # The user only needs to change approved from blank to yes for confirmed PIs.
    shortlist = result[result["triage_tier"].isin(["A_review_first", "B_review"])].copy()
    approval_template = pd.DataFrame(
        {
            "openalex_id": shortlist.get("openalex_id", ""),
            "approved": "",
            "name_ko": "",
            "name_en": shortlist.get("display_name", ""),
            "university": shortlist.get("current_affiliation", ""),
            "department": "",
            "primary_field": "",
            "source_url": shortlist.get("scholar_profile_url", ""),
            "triage_tier": shortlist.get("triage_tier", ""),
            "shared_paper_count": shortlist.get("shared_paper_count", ""),
            "connected_seed_professor_ids": shortlist.get("connected_seed_professor_ids", ""),
            "triage_reason": shortlist.get("triage_reason", ""),
        }
    )
    approval_template.to_csv(
        OUTPUT_DIR / "candidate_approval_template.csv",
        index=False,
    )
    return result
