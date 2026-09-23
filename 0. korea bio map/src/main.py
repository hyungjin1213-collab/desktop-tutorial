from __future__ import annotations

import argparse

from candidate_review import classify_candidates
from department_discovery import discover_departments
from faculty_identity import import_verified_faculty, match_faculty_identities
from faculty_scraper import scrape_faculty
from openalex_client import OpenAlexClient
from pipeline import (
    build_network,
    collect_collaborations,
    promote_approved_candidates,
    resolve_professors,
)
from scholar_client import ScholarClient


def run_all(client: OpenAlexClient) -> None:
    professors = resolve_professors(client)
    auto, candidates = collect_collaborations(client, professors)
    reviewed = classify_candidates(client, ScholarClient())
    nodes, links = build_network(professors)
    print(f"Professors: {len(professors)}")
    print(f"Auto relationships: {len(auto)}")
    print(f"Review candidates: {len(candidates)}")
    print(f"Triaged candidates: {len(reviewed)}")
    print(f"Network nodes: {len(nodes)}")
    print(f"Network links: {len(links)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="About Bio - Korea Bio Map data pipeline")
    parser.add_argument(
        "command",
        choices=[
            "resolve",
            "collect",
            "review",
            "build",
            "promote",
            "promote-and-all",
            "all",
            "discover-departments",
            "scrape-faculty",
            "discover-and-scrape-faculty",
            "match-faculty-identities",
            "faculty-full",
            "import-faculty",
            "import-faculty-and-all",
        ],
        help="Pipeline step to run",
    )
    args = parser.parse_args()

    client = OpenAlexClient()

    if args.command == "discover-departments":
        df = discover_departments()
        print(f"Department candidates: {len(df)}")
        return

    if args.command == "scrape-faculty":
        df = scrape_faculty()
        print(f"Faculty rows: {len(df)}")
        return

    if args.command == "discover-and-scrape-faculty":
        departments = discover_departments()
        faculty = scrape_faculty()
        print(f"Department candidates: {len(departments)}")
        print(f"Faculty rows: {len(faculty)}")
        return

    if args.command == "match-faculty-identities":
        identities = match_faculty_identities()
        print(f"Faculty identities: {len(identities)}")
        if not identities.empty:
            print(f"High confidence: {(identities['identity_confidence'] == 'high').sum()}")
            print(f"Probable: {(identities['identity_status'] == 'probable').sum()}")
            print(f"Manual review: {(identities['identity_status'] == 'manual_review').sum()}")
        return

    if args.command == "faculty-full":
        departments = discover_departments()
        faculty = scrape_faculty()
        identities = match_faculty_identities()
        print(f"Department candidates: {len(departments)}")
        print(f"Faculty rows: {len(faculty)}")
        print(f"Faculty identities: {len(identities)}")
        return

    if args.command == "import-faculty":
        count = import_verified_faculty()
        print(f"Imported {count} faculty into professors_seed.csv")
        return

    if args.command == "import-faculty-and-all":
        count = import_verified_faculty()
        print(f"Imported {count} faculty into professors_seed.csv")
        run_all(client)
        return

    if args.command == "resolve":
        professors = resolve_professors(client)
        print(f"Resolved {len(professors)} professors.")
        return

    if args.command == "collect":
        professors = resolve_professors(client)
        auto, candidates = collect_collaborations(client, professors)
        print(f"Auto relationships: {len(auto)}")
        print(f"Review candidates: {len(candidates)}")
        return

    if args.command == "review":
        reviewed = classify_candidates(client, ScholarClient())
        print(f"Triaged candidates: {len(reviewed)}")
        return

    if args.command == "build":
        professors = resolve_professors(client)
        nodes, links = build_network(professors)
        print(f"Network nodes: {len(nodes)}")
        print(f"Network links: {len(links)}")
        return

    if args.command == "promote":
        count = promote_approved_candidates()
        print(f"Promoted {count} approved candidates.")
        return

    if args.command == "promote-and-all":
        count = promote_approved_candidates()
        print(f"Promoted {count} approved candidates.")
        run_all(client)
        return

    run_all(client)


if __name__ == "__main__":
    main()
