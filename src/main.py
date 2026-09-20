import argparse

from src.collectors.openalex import search_author


def main() -> None:
    parser = argparse.ArgumentParser(description="About Bio v0.1")
    parser.add_argument("--name", required=True, help="Professor name")
    parser.add_argument("--institution", required=False, default="", help="Institution name")
    args = parser.parse_args()

    result = search_author(args.name, args.institution)
    if not result:
        print("No matching author found.")
        return

    print(f"Matched: {result['display_name']}")
    print(f"OpenAlex ID: {result['id']}")
    print(f"Works count: {result.get('works_count', 0)}")


if __name__ == "__main__":
    main()
