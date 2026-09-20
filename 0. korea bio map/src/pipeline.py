from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pandas as pd

from config import DATA_DIR, OUTPUT_DIR
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


def _read_csv(path: Path, columns: list[str] | None = None) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=columns or [])
    df = pd.read_csv(path, dtype=str).fillna("")
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
                        "institutions": set(),
                        "country_codes": set(),
                        "example_work": "",
                    },
                )
                stats["shared_work_ids"].add(work_id or work_title)

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

    candidates = []
    for stats in candidate_stats.values():
        candidates.append(
            {
                "openalex_id": stats["openalex_id"],
                "display_name": stats["display_name"],
                "shared_paper_count": len(stats["shared_work_ids"]),
                "institutions": "; ".join(sorted(stats["institutions"])),
                "country_codes": "; ".join(sorted(stats["country_codes"])),
                "korea_affiliated": "yes" if "KR" in stats["country_codes"] else "no",
                "example_work": stats["example_work"],
                "review_status": "",
            }
        )

    auto_df = pd.DataFrame(auto_rows)
    candidate_df = pd.DataFrame(candidates)

    if not candidate_df.empty:
        candidate_df = candidate_df.sort_values(
            by=["korea_affiliated", "shared_paper_count"],
            ascending=[False, False],
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    auto_df.to_csv(OUTPUT_DIR / "relationships_auto.csv", index=False)
    candidate_df.to_csv(OUTPUT_DIR / "collaborator_candidates.csv", index=False)
    return auto_df, candidate_df


def build_network(professors: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    auto = _read_csv(OUTPUT_DIR / "relationships_auto.csv")
    manual = _read_csv(DATA_DIR / "relationships_manual.csv")
    rules = _read_csv(DATA_DIR / "score_rules.csv")

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

    rule_weights = {
        row["relationship_type"]: _safe_int(row["weight"])
        for _, row in rules.iterrows()
    }
    rule_colors = {
        row["relationship_type"]: row.get("graph_color", "")
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
        links["color"] = links["relationship_type"].map(
            lambda value: rule_colors.get(value, "#94A3B8")
        )
        links["directed"] = links["relationship_type"].map(
            lambda value: "no" if value == "collaboration" else "yes"
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    relationships.to_csv(OUTPUT_DIR / "relationships.csv", index=False)
    nodes.to_csv(OUTPUT_DIR / "network_nodes.csv", index=False)
    links.to_csv(OUTPUT_DIR / "network_links.csv", index=False)
    return nodes, links
