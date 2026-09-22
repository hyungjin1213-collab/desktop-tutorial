from __future__ import annotations

import re

import pandas as pd

from candidate_web_verifier import verify_candidates_with_web
from config import AUTO_NO_CONFIDENCE, AUTO_YES_CONFIDENCE, OUTPUT_DIR
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


def _read_csv_flexible(path) -> pd.DataFrame:
    """Read CSVs edited by Excel/GitHub regardless of common Korean encodings."""
    last_error = None
    for encoding in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            return pd.read_csv(path, dtype=str, encoding=encoding).fillna("")
        except (UnicodeDecodeError, pd.errors.ParserError) as exc:
            last_error = exc
    if last_error:
        raise last_error
    return pd.DataFrame()


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

    # Second pass: verify likely candidates against current web evidence.
    result = verify_candidates_with_web(result)

    # Conservative auto-decision. "yes" requires explicit professor/PI evidence
    # on an academic/official domain. "no" requires explicit trainee evidence or
    # strong non-PI/noise signals. Everything else stays blank for human review.
    auto_decisions = []
    auto_confidences = []
    auto_reasons = []

    for _, row in result.iterrows():
        tier = row.get("triage_tier", "")
        official = row.get("official_domain_signal", "") == "yes"
        prof = row.get("professor_title_signal", "") == "yes"
        trainee = row.get("trainee_title_signal", "") == "yes"
        academic = row.get("academic_affiliation_signal", "") == "yes"
        bio = row.get("bio_relevance_signal", "") == "yes"
        conflict = row.get("affiliation_conflict_warning", "") == "yes"
        shared = _safe_int(row.get("shared_paper_count", 0))
        seed_count = _safe_int(row.get("seed_connection_count", 0))

        decision = ""
        confidence = 0.50
        reason = "manual review needed"

        if official and prof and not trainee:
            decision = "yes"
            confidence = 0.98
            reason = "official academic page/search result explicitly indicates professor/PI"
        elif official and trainee and not prof:
            decision = "no"
            confidence = 0.98
            reason = "official academic page/search result explicitly indicates trainee/postdoc"
        elif prof and academic and not trainee and not conflict:
            decision = "yes"
            confidence = 0.92
            reason = "professor/PI title signal + academic affiliation"
        elif trainee and not prof:
            decision = "no"
            confidence = 0.95
            reason = "trainee/postdoc title signal"
        elif tier == "D_noise_check" and not bio and seed_count <= 1:
            decision = "no"
            confidence = 0.93
            reason = "field mismatch/noise pattern without independent PI evidence"
        elif not academic and shared <= 3:
            decision = "no"
            confidence = 0.92
            reason = "non-academic current affiliation + weak collaboration signal"
        elif tier == "A_review_first" and academic and bio and seed_count >= 2 and not conflict:
            confidence = 0.82
            reason = "strong network signal, but no explicit professor title evidence"

        auto_decisions.append(decision)
        auto_confidences.append(round(confidence, 2))
        auto_reasons.append(reason)

    result["auto_decision"] = auto_decisions
    result["auto_confidence"] = auto_confidences
    result["auto_reason"] = auto_reasons

    # Human decisions live in one tiny durable file only. Generated review
    # outputs are read-only and can be regenerated safely at any time.
    decisions_path = OUTPUT_DIR.parent / "data" / "candidate_decisions.csv"
    human_map = {}
    if decisions_path.exists() and decisions_path.stat().st_size:
        try:
            decisions = _read_csv_flexible(decisions_path)
            if "openalex_id" in decisions.columns and "decision" in decisions.columns:
                human_map = {
                    str(row["openalex_id"]).strip(): str(row["decision"]).strip().casefold()
                    for _, row in decisions.iterrows()
                    if str(row.get("openalex_id", "")).strip()
                }
        except (UnicodeDecodeError, pd.errors.ParserError):
            human_map = {}

    result["human_decision"] = result["openalex_id"].map(
        lambda oid: human_map.get(str(oid).strip(), "")
    )

    def suggested(row):
        human = str(row.get("human_decision", "")).strip().casefold()
        if human in {"yes", "no"}:
            return human
        auto = str(row.get("auto_decision", "")).strip().casefold()
        conf = float(row.get("auto_confidence", 0) or 0)
        official = str(row.get("official_domain_signal", "")).strip().casefold() == "yes"
        if auto == "yes" and conf >= AUTO_YES_CONFIDENCE and official:
            return "yes"
        if auto == "no" and conf >= AUTO_NO_CONFIDENCE:
            return "no"
        return "review"

    result["suggested_decision"] = result.apply(suggested, axis=1)
    result.to_csv(
        OUTPUT_DIR / "candidate_review.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # Only unresolved people appear here. The user no longer edits this file;
    # it is simply the short checklist used to decide which IDs to add to
    # data/candidate_decisions.csv.
    reviewed_path = OUTPUT_DIR.parent / "data" / "manual_reviewed.csv"
    reviewed_ids = set()
    if reviewed_path.exists() and reviewed_path.stat().st_size:
        try:
            reviewed_df = _read_csv_flexible(reviewed_path)
            if "openalex_id" in reviewed_df.columns:
                reviewed_ids = {
                    str(x).strip()
                    for x in reviewed_df["openalex_id"]
                    if str(x).strip()
                }
        except (UnicodeDecodeError, pd.errors.ParserError):
            reviewed_ids = set()

    queue = result[
        (result["suggested_decision"] == "review")
        & (~result["human_decision"].isin(["yes", "no"]))
        & (~result["openalex_id"].isin(reviewed_ids))
    ].copy()

    queue_columns = [
        "openalex_id",
        "display_name",
        "current_affiliation",
        "shared_paper_count",
        "seed_connection_count",
        "connected_seed_professor_ids",
        "web_title",
        "web_url",
        "auto_confidence",
        "auto_reason",
        "triage_tier",
    ]
    for column in queue_columns:
        if column not in queue.columns:
            queue[column] = ""
    queue[queue_columns].to_csv(
        OUTPUT_DIR / "manual_review_queue.csv",
        index=False,
        encoding="utf-8-sig",
    )

    return result
