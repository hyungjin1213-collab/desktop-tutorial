from __future__ import annotations

import argparse

from openalex_client import OpenAlexClient
from pipeline import build_network, collect_collaborations, resolve_professors


def main() -> None:
    parser = argparse.ArgumentParser(description="About Bio - Korea Bio Map data pipeline")
    parser.add_argument(
        "command",
        choices=["resolve", "collect", "build", "all"],
        help="Pipeline step to run",
    )
    args = parser.parse_args()

    client = OpenAlexClient()

    if args.command == "resolve":
        professors = resolve_professors(client)
        print(f"Resolved {len(professors)} professors.")
        return

    if args.command == "collect":
        professors = resolve_professors(client)
        auto, candidates = collect_collaborations(client, professors)
        print(f"Auto relationships: {len(auto)}")
        print(f"Collaborator candidates: {len(candidates)}")
        return

    if args.command == "build":
        professors = resolve_professors(client)
        nodes, links = build_network(professors)
        print(f"Network nodes: {len(nodes)}")
        print(f"Network links: {len(links)}")
        return

    professors = resolve_professors(client)
    auto, candidates = collect_collaborations(client, professors)
    nodes, links = build_network(professors)
    print(f"Professors: {len(professors)}")
    print(f"Auto relationships: {len(auto)}")
    print(f"Collaborator candidates: {len(candidates)}")
    print(f"Network nodes: {len(nodes)}")
    print(f"Network links: {len(links)}")


if __name__ == "__main__":
    main()
