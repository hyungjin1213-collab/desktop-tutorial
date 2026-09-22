from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

import pandas as pd

from config import (
    DATA_DIR,
    KOREA_COUNTRY_CODE,
    MAX_REVIEW_CANDIDATES,
    MIN_SHARED_PAPERS,
    OUTPUT_DIR,
    WEB_DIR,
)
from openalex_client import OpenAlexClient, normalize_openalex_id


PROFESSOR_COLUMNS = [
    "professor_id",
    "name_ko",
    "name_en",
    "university",
    "department",
    "primary_field",
    "openalex_id",
    "source_url",
]

REL_COLUMNS = [
    "relationship_id",
    "professor_a_id",
    "professor_b_id",
    "relationship_type",
    "collaboration_paper_count",
    "evidence_url",
    "verified",
    "notes",
]


def _read_csv(path: Path, columns: list[str] | None = None) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=columns or [])
    try:
        df = pd.read_csv(path, dtype=str).fillna("")
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=columns or [])
    if columns:
        for column in columns:
            if column not in df.columns:
                df[column] = ""
        df = df[columns]
    return df


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return default


def _next_professor_id(existing_ids: set[str]) -> str:
    nums = []
    for pid in existing_ids:
        match = re.fullmatch(r"P(\d+)", str(pid).strip(), flags=re.I)
        if match:
            nums.append(int(match.group(1)))
    return f"P{(max(nums) if nums else 0) + 1:04d}"


def resolve_professors(client: OpenAlexClient) -> pd.DataFrame:
    professors = _read_csv(DATA_DIR / "professors_seed.csv", PROFESSOR_COLUMNS).copy()
    resolved_rows: list[dict[str, str]] = []

    for _, row in professors.iterrows():
        item = row.to_dict()
        current_id = normalize_openalex_id(item.get("openalex_id", ""))

        if not current_id:
            query_name = item.get("name_en") or item.get("name_ko")
            institution = item.get("university", "")
            match = client.search_author(query_name, institution) if query_name else None
            if match:
                current_id = normalize_openalex_id(match.get("id", ""))

        item["openalex_id"] = current_id
        resolved_rows.append(item)

    resolved = pd.DataFrame(resolved_rows, columns=PROFESSOR_COLUMNS)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    resolved.to_csv(OUTPUT_DIR / "professors_enriched.csv", index=False)
    return resolved


def collect_collaborations(
    client: OpenAlexClient,
    professors: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    confirmed_by_openalex = {
        normalize_openalex_id(row["openalex_id"]): row["professor_id"]
        for _, row in professors.iterrows()
        if normalize_openalex_id(row["openalex_id"])
    }

    pair_to_works: dict[tuple[str, str], set[str]] = defaultdict(set)
    candidate_stats: dict[str, dict[str, object]] = {}

    for _, professor in professors.iterrows():
        professor_id = professor["professor_id"]
        openalex_id = normalize_openalex_id(professor["openalex_id"])
        if not openalex_id:
            continue

        for work in client.iter_works_by_author(openalex_id):
            work_id = normalize_openalex_id(work.get("id", ""))
            work_title = work.get("display_name", "")
            authorships = work.get("authorships") or []

            for authorship in authorships:
                author = authorship.get("author") or {}
                coauthor_openalex_id = normalize_openalex_id(author.get("id", ""))
                if not coauthor_openalex_id or coauthor_openalex_id == openalex_id:
                    continue

                confirmed_id = confirmed_by_openalex.get(coauthor_openalex_id)
                if confirmed_id:
                    pair = tuple(sorted((professor_id, confirmed_id)))
                    if pair[0] != pair[1]:
                        pair_to_works[pair].add(work_id or work_title)
                    continue

                stats = candidate_stats.setdefault(
                    coauthor_openalex_id,
                    {
                        "openalex_id": coauthor_openalex_id,
                        "display_name": author.get("display_name", ""),
                        "shared_work_ids": set(),
                        "seed_professor_ids": set(),
                        "institutions": set(),
                        "country_codes": set(),
                        "example_work": "",
                    },
                )
                stats["shared_work_ids"].add(work_id or work_title)
                stats["seed_professor_ids"].add(professor_id)

                if not stats["example_work"] and work_title:
                    stats["example_work"] = work_title

                for institution in authorship.get("institutions") or []:
                    name = institution.get("display_name", "")
                    country = institution.get("country_code", "")
                    if name:
                        stats["institutions"].add(name)
                    if country:
                        stats["country_codes"].add(country)

    auto_rows = []
    for index, ((professor_a_id, professor_b_id), work_ids) in enumerate(
        sorted(pair_to_works.items()),
        start=1,
    ):
        auto_rows.append(
            {
                "relationship_id": f"AUTO{index:06d}",
                "professor_a_id": professor_a_id,
                "professor_b_id": professor_b_id,
                "relationship_type": "collaboration",
                "collaboration_paper_count": len(work_ids),
                "evidence_url": "",
                "verified": "auto",
                "notes": "OpenAlex coauthorship between confirmed professors",
            }
        )

    candidate_rows = []
    for stats in candidate_stats.values():
        shared = len(stats["shared_work_ids"])
        seed_count = len(stats["seed_professor_ids"])
        country_codes = sorted(stats["country_codes"])
        is_korea = KOREA_COUNTRY_CODE in country_codes
        candidate_rows.append(
            {
                "openalex_id": stats["openalex_id"],
                "display_name": stats["display_name"],
                "shared_paper_count": shared,
                "seed_connection_count": seed_count,
                "connected_seed_professor_ids": "; ".join(sorted(stats["seed_professor_ids"])),
                "institutions": "; ".join(sorted(stats["institutions"])),
                "country_codes": "; ".join(country_codes),
                "korea_affiliated": "yes" if is_korea else "no",
                "review_priority": shared + max(seed_count - 1, 0) * 3,
                "example_work": stats["example_work"],
                "review_status": "needs_review" if is_korea else "out_of_scope",
            }
        )

    candidate_columns = [
        "openalex_id",
        "display_name",
        "shared_paper_count",
        "seed_connection_count",
        "connected_seed_professor_ids",
        "institutions",
        "country_codes",
        "korea_affiliated",
        "review_priority",
        "example_work",
        "review_status",
    ]

    auto_df = pd.DataFrame(auto_rows, columns=REL_COLUMNS)
    all_candidates_df = pd.DataFrame(candidate_rows, columns=candidate_columns)

    if not all_candidates_df.empty:
        all_candidates_df = all_candidates_df.sort_values(
            by=["korea_affiliated", "review_priority", "shared_paper_count"],
            ascending=[False, False, False],
        )

    review_df = all_candidates_df[
        (all_candidates_df["korea_affiliated"] == "yes")
        & (all_candidates_df["shared_paper_count"].map(_safe_int) >= MIN_SHARED_PAPERS)
    ].head(MAX_REVIEW_CANDIDATES).copy()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    auto_df.to_csv(OUTPUT_DIR / "relationships_auto.csv", index=False)
    all_candidates_df.to_csv(OUTPUT_DIR / "collaborator_candidates_all.csv", index=False)
    review_df.to_csv(OUTPUT_DIR / "collaborator_candidates.csv", index=False)
    return auto_df, review_df


def promote_approved_candidates() -> int:
    professors_path = DATA_DIR / "professors_seed.csv"
    approvals_path = DATA_DIR / "candidate_approvals.csv"

    professors = _read_csv(professors_path, PROFESSOR_COLUMNS).copy()
    approvals = _read_csv(
        approvals_path,
        [
            "openalex_id",
            "approved",
            "name_ko",
            "name_en",
            "university",
            "department",
            "primary_field",
            "source_url",
        ],
    )

    if approvals.empty:
        return 0

    candidate_lookup = {}
    # Prefer the triaged review file because it contains the resolved current
    # affiliation (Google Scholar via SerpApi when available, otherwise OpenAlex).
    candidate_path = OUTPUT_DIR / "candidate_review.csv"
    if not candidate_path.exists():
        candidate_path = OUTPUT_DIR / "collaborator_candidates_all.csv"

    if candidate_path.exists():
        candidate_df = _read_csv(candidate_path)
        if not candidate_df.empty and "openalex_id" in candidate_df.columns:
            candidate_lookup = {
                normalize_openalex_id(row["openalex_id"]): row.to_dict()
                for _, row in candidate_df.iterrows()
            }

    existing_openalex = {
        normalize_openalex_id(value)
        for value in professors["openalex_id"]
        if normalize_openalex_id(value)
    }
    existing_ids = set(professors["professor_id"])
    new_rows = []

    for _, approval in approvals.iterrows():
        if str(approval.get("approved", "")).strip().casefold() not in {
            "yes", "y", "true", "1", "approve", "approved"
        }:
            continue

        oid = normalize_openalex_id(approval.get("openalex_id", ""))
        if not oid or oid in existing_openalex:
            continue

        candidate = candidate_lookup.get(oid, {})
        name_en = approval.get("name_en", "") or candidate.get("display_name", "")
        # A manually entered university always wins. If it is left blank,
        # use the current affiliation resolved during candidate review.
        university = (
            approval.get("university", "")
            or candidate.get("current_affiliation", "")
            or candidate.get("institutions", "")
        )
        if not name_en or not university:
            continue

        pid = _next_professor_id(existing_ids)
        existing_ids.add(pid)
        existing_openalex.add(oid)

        new_rows.append(
            {
                "professor_id": pid,
                "name_ko": approval.get("name_ko", ""),
                "name_en": name_en,
                "university": university,
                "department": approval.get("department", ""),
                "primary_field": approval.get("primary_field", ""),
                "openalex_id": oid,
                "source_url": approval.get("source_url", ""),
            }
        )

    if new_rows:
        professors = pd.concat(
            [professors, pd.DataFrame(new_rows, columns=PROFESSOR_COLUMNS)],
            ignore_index=True,
        )
        professors.to_csv(professors_path, index=False)

    return len(new_rows)


def export_web_data(nodes: pd.DataFrame, links: pd.DataFrame) -> None:
    WEB_DIR.mkdir(parents=True, exist_ok=True)

    node_records = []
    for _, row in nodes.iterrows():
        node_records.append(
            {
                "id": row.get("professor_id", ""),
                "name": row.get("name_ko", "") or row.get("name_en", ""),
                "name_en": row.get("name_en", ""),
                "university": row.get("university", ""),
                "field": row.get("primary_field", ""),
                "score": _safe_int(row.get("network_score", 0)),
                "collaborator_count": _safe_int(row.get("collaborator_count", 0)),
                "faculty_trainee_count": _safe_int(row.get("faculty_trainee_count", 0)),
                "postdoc_PI_count": _safe_int(row.get("postdoc_PI_count", 0)),
            }
        )

    link_records = []
    if not links.empty:
        for _, row in links.iterrows():
            link_records.append(
                {
                    "source": row.get("professor_a_id", ""),
                    "target": row.get("professor_b_id", ""),
                    "type": row.get("relationship_type", ""),
                    "paper_count": _safe_int(row.get("collaboration_paper_count", 0), 0),
                }
            )

    payload = {"nodes": node_records, "links": link_records}
    text = "window.KOREA_BIO_MAP = " + json.dumps(payload, ensure_ascii=False, indent=2) + ";\n"
    (WEB_DIR / "network-data.js").write_text(text, encoding="utf-8")


def build_network(professors: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    auto = _read_csv(OUTPUT_DIR / "relationships_auto.csv", REL_COLUMNS)
    manual = _read_csv(DATA_DIR / "relationships_manual.csv")

    if not manual.empty:
        manual = manual.copy()
        if "collaboration_paper_count" not in manual.columns:
            manual["collaboration_paper_count"] = ""

    relationships = pd.concat([auto, manual], ignore_index=True, sort=False).fillna("")

    valid_professor_ids = set(professors["professor_id"])
    if not relationships.empty:
        relationships = relationships[
            relationships["professor_a_id"].isin(valid_professor_ids)
            & relationships["professor_b_id"].isin(valid_professor_ids)
        ].copy()

    rules = _read_csv(DATA_DIR / "score_rules.csv")
    rule_weights = {
        row["relationship_type"]: _safe_int(row["weight"])
        for _, row in rules.iterrows()
    }

    collaborator_sets: dict[str, set[str]] = defaultdict(set)
    faculty_trainees: dict[str, set[str]] = defaultdict(set)
    postdoc_pi: dict[str, set[str]] = defaultdict(set)

    for _, edge in relationships.iterrows():
        edge_type = edge.get("relationship_type", "")
        a = edge.get("professor_a_id", "")
        b = edge.get("professor_b_id", "")
        verified = str(edge.get("verified", "")).casefold()

        if edge_type == "collaboration":
            collaborator_sets[a].add(b)
            collaborator_sets[b].add(a)
        elif edge_type == "advisor_student" and verified in {"yes", "true", "1", "verified"}:
            faculty_trainees[a].add(b)
        elif edge_type == "postdoc_mentor" and verified in {"yes", "true", "1", "verified"}:
            postdoc_pi[a].add(b)

    nodes = professors.copy()
    nodes["collaborator_count"] = nodes["professor_id"].map(
        lambda pid: len(collaborator_sets[pid])
    )
    nodes["faculty_trainee_count"] = nodes["professor_id"].map(
        lambda pid: len(faculty_trainees[pid])
    )
    nodes["postdoc_PI_count"] = nodes["professor_id"].map(
        lambda pid: len(postdoc_pi[pid])
    )
    nodes["network_score"] = (
        nodes["collaborator_count"] * rule_weights.get("collaboration", 0)
        + nodes["faculty_trainee_count"] * rule_weights.get("advisor_student", 0)
        + nodes["postdoc_PI_count"] * rule_weights.get("postdoc_mentor", 0)
    )

    links = relationships.copy()
    if not links.empty:
        links["source"] = links["professor_a_id"]
        links["target"] = links["professor_b_id"]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    relationships.to_csv(OUTPUT_DIR / "relationships.csv", index=False)
    nodes.to_csv(OUTPUT_DIR / "network_nodes.csv", index=False)
    links.to_csv(OUTPUT_DIR / "network_links.csv", index=False)
    export_web_data(nodes, links)
    return nodes, links
