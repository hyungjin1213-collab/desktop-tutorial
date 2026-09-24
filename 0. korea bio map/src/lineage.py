"""Infer PhD-advisor and postdoc-mentor links between professors from their papers.

Uses the works already fetched for the collaboration graph (no extra API
calls). For professor B:

- first_year: year of B's earliest first-author paper.
- PhD window [first_year, first_year + PHD_YEARS]: papers where B is first
  author and professor A is last (senior) author -> A is a PhD advisor candidate.
- Postdoc window (first_year + PHD_YEARS, first_year + POSTDOC_END]: same
  pattern, but only at an institution other than B's PhD institution ->
  A is a postdoc mentor candidate.

A must have published at least SENIORITY_GAP years before B. Candidates with
>= LINEAGE_AUTO_MIN papers are drawn on the map as auto-inferred; the rest
wait for review. data/lineage_decisions.csv (decision = yes / no) overrides
both ways.
"""
from __future__ import annotations

import os
from collections import Counter, defaultdict
from dataclasses import dataclass

import pandas as pd

PHD_YEARS = 5
POSTDOC_END = 11
SENIORITY_GAP = 5
LINEAGE_MIN_PAPERS = int(os.getenv("LINEAGE_MIN_PAPERS", "2"))
LINEAGE_AUTO_MIN = int(os.getenv("LINEAGE_AUTO_MIN", "3"))

CANDIDATE_COLUMNS = [
    "professor_a_id", "a_name", "professor_b_id", "b_name", "relationship_type",
    "evidence_papers", "b_first_year", "years", "b_institution", "example_title",
    "evidence_url", "status",
]


@dataclass
class Authorship:
    """One paper from the point of view of one professor on it."""
    year: int
    position: str          # first / middle / last
    last_author_pid: str   # professor ID of the paper's last author ("" if not a professor)
    institutions: tuple    # this professor's institution names on the paper
    title: str
    doi: str


def _first_year(records: list[Authorship]) -> int | None:
    years = [r.year for r in records if r.position == "first" and r.year]
    return min(years) if years else None


def _any_first_year(records: list[Authorship]) -> int | None:
    years = [r.year for r in records if r.year]
    return min(years) if years else None


def infer_lineage(records: dict[str, list[Authorship]], names: dict[str, str],
                  decisions: pd.DataFrame | None = None) -> pd.DataFrame:
    """Return lineage candidates with status auto / review / approved / rejected."""
    rows = []
    for b, recs in records.items():
        fy = _first_year(recs)
        if fy is None:
            continue
        early = [r for r in recs if r.year and fy <= r.year <= fy + 3]
        inst_counts = Counter(i for r in early for i in r.institutions)
        phd_inst = inst_counts.most_common(1)[0][0] if inst_counts else ""

        phd: dict[str, list[Authorship]] = defaultdict(list)
        postdoc: dict[str, list[Authorship]] = defaultdict(list)
        for r in recs:
            a = r.last_author_pid
            if r.position != "first" or not a or a == b or not r.year:
                continue
            if r.year <= fy + PHD_YEARS:
                phd[a].append(r)
            elif r.year <= fy + POSTDOC_END and phd_inst and phd_inst not in r.institutions:
                postdoc[a].append(r)

        for kind, found in (("advisor_student", phd), ("postdoc_mentor", postdoc)):
            for a, papers in found.items():
                if len(papers) < LINEAGE_MIN_PAPERS:
                    continue
                if kind == "postdoc_mentor" and len(phd.get(a, [])) >= len(papers):
                    continue  # same senior author already explains it as PhD advisor
                a_start = _any_first_year(records.get(a, []))
                if a_start is None or a_start > fy - SENIORITY_GAP:
                    continue  # not clearly senior: peers co-publishing, not mentorship
                papers = sorted(papers, key=lambda r: r.year)
                example = papers[0]
                rows.append({
                    "professor_a_id": a,
                    "a_name": names.get(a, ""),
                    "professor_b_id": b,
                    "b_name": names.get(b, ""),
                    "relationship_type": kind,
                    "evidence_papers": len(papers),
                    "b_first_year": fy,
                    "years": f"{papers[0].year}-{papers[-1].year}",
                    "b_institution": "; ".join(example.institutions) or phd_inst,
                    "example_title": example.title[:200],
                    "evidence_url": f"https://doi.org/{example.doi}" if example.doi else "",
                    "status": "auto" if len(papers) >= LINEAGE_AUTO_MIN else "review",
                })

    out = pd.DataFrame(rows, columns=CANDIDATE_COLUMNS)
    if decisions is not None and not decisions.empty and not out.empty:
        verdict = {
            (str(d.get("professor_a_id", "")), str(d.get("professor_b_id", "")), str(d.get("relationship_type", ""))):
            str(d.get("decision", "")).strip().casefold()
            for _, d in decisions.iterrows()
        }
        def apply(row):
            v = verdict.get((row.professor_a_id, row.professor_b_id, row.relationship_type), "")
            return "approved" if v == "yes" else "rejected" if v == "no" else row.status
        out["status"] = out.apply(apply, axis=1)
    if not out.empty:
        out = out.sort_values(["status", "evidence_papers"], ascending=[True, False])
    return out


def lineage_relationships(candidates: pd.DataFrame) -> pd.DataFrame:
    """auto / approved candidates as relationship rows for the network."""
    keep = candidates[candidates["status"].isin(["auto", "approved"])] if not candidates.empty else candidates
    rows = []
    for i, c in enumerate(keep.itertuples(), start=1):
        rows.append({
            "relationship_id": f"LIN{i:06d}",
            "professor_a_id": c.professor_a_id,
            "professor_b_id": c.professor_b_id,
            "relationship_type": c.relationship_type,
            "collaboration_paper_count": c.evidence_papers,
            "evidence_url": c.evidence_url,
            "verified": "yes" if c.status == "approved" else "auto",
            "notes": f"inferred from {c.evidence_papers} first-author papers ({c.years}) with A as last author",
        })
    return pd.DataFrame(rows, columns=[
        "relationship_id", "professor_a_id", "professor_b_id", "relationship_type",
        "collaboration_paper_count", "evidence_url", "verified", "notes",
    ])
