from __future__ import annotations

import re

import pandas as pd
from openpyxl import load_workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

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
    result.to_csv(OUTPUT_DIR / "candidate_review.csv", index=False)

    # Preserve any manual yes/no choices already made in the previous template.
    previous_path = OUTPUT_DIR / "candidate_approval_template.csv"
    previous = {}
    if previous_path.exists() and previous_path.stat().st_size:
        try:
            prev_df = pd.read_csv(previous_path, dtype=str).fillna("")
            previous = {
                row["openalex_id"]: row.to_dict()
                for _, row in prev_df.iterrows()
                if row.get("openalex_id", "")
            }
        except pd.errors.EmptyDataError:
            pass

    shortlist = result[result["triage_tier"].isin(["A_review_first", "B_review", "C_manual"])].copy()
    rows = []
    for _, row in shortlist.iterrows():
        oid = row.get("openalex_id", "")
        prior = previous.get(oid, {})
        approved = prior.get("approved", "")
        if not approved:
            auto_decision = row.get("auto_decision", "")
            auto_conf = float(row.get("auto_confidence", 0) or 0)
            if auto_decision == "yes" and auto_conf >= AUTO_YES_CONFIDENCE:
                approved = "yes"
            elif auto_decision == "no" and auto_conf >= AUTO_NO_CONFIDENCE:
                approved = "no"

        rows.append({
            "openalex_id": oid,
            "approved": approved,
            "name_ko": prior.get("name_ko", ""),
            "name_en": prior.get("name_en", "") or row.get("display_name", ""),
            "university": prior.get("university", "") or row.get("current_affiliation", ""),
            "department": prior.get("department", ""),
            "primary_field": prior.get("primary_field", ""),
            "source_url": prior.get("source_url", "") or row.get("web_url", "") or row.get("scholar_profile_url", ""),
            "auto_decision": row.get("auto_decision", ""),
            "auto_confidence": row.get("auto_confidence", ""),
            "auto_reason": row.get("auto_reason", ""),
            "triage_tier": row.get("triage_tier", ""),
            "shared_paper_count": row.get("shared_paper_count", ""),
            "connected_seed_professor_ids": row.get("connected_seed_professor_ids", ""),
            "web_title": row.get("web_title", ""),
            "current_affiliation": row.get("current_affiliation", ""),
        })

    approval_template = pd.DataFrame(rows)
    approval_template.to_csv(previous_path, index=False)

    # Excel version for painless human review.
    xlsx_path = OUTPUT_DIR / "candidate_approval_template.xlsx"
    approval_template.to_excel(xlsx_path, index=False, sheet_name="Candidates")
    wb = load_workbook(xlsx_path)
    ws = wb["Candidates"]
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    widths = {
        "A": 16, "B": 12, "C": 14, "D": 24, "E": 42, "F": 24, "G": 20,
        "H": 45, "I": 14, "J": 14, "K": 48, "L": 16, "M": 14, "N": 24,
        "O": 45, "P": 42,
    }
    for col, width in widths.items():
        ws.column_dimensions[col].width = width

    dv = DataValidation(type="list", formula1='"yes,no"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(f"B2:B{max(ws.max_row, 2)}")

    green = PatternFill("solid", fgColor="C6EFCE")
    red = PatternFill("solid", fgColor="FFC7CE")
    yellow = PatternFill("solid", fgColor="FFEB9C")
    ws.conditional_formatting.add(f"B2:B{ws.max_row}", FormulaRule(formula=['B2="yes"'], fill=green))
    ws.conditional_formatting.add(f"B2:B{ws.max_row}", FormulaRule(formula=['B2="no"'], fill=red))
    ws.conditional_formatting.add(f"B2:B{ws.max_row}", FormulaRule(formula=['B2=""'], fill=yellow))
    wb.save(xlsx_path)

    return result
