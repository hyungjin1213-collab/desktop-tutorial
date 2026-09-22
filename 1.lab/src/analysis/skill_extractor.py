from collections import Counter


def extract_keyword_profile(keywords: list[str], top_n: int = 15) -> list[tuple[str, int]]:
    cleaned = [k.strip().lower() for k in keywords if k and k.strip()]
    return Counter(cleaned).most_common(top_n)
