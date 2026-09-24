import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from faculty_identity_v2 import _best_openalex  # noqa: E402


def _author(aid, name, inst, past=(), orcid=""):
    return {
        "id": f"https://openalex.org/{aid}",
        "display_name": name,
        "orcid": orcid,
        "works_count": 50,
        "last_known_institutions": [{"display_name": inst}],
        "affiliations": [{"institution": {"display_name": p}} for p in past],
    }


class FakeClient:
    def __init__(self, results):
        self.results = results
        self.queries = []

    def _get(self, path, params):
        self.queries.append(params["search"])
        return {"results": self.results}


def test_korean_name_matches_romanized_openalex_author():
    client = FakeClient([
        _author("A1", "Kyung-Soo Kim", "Seoul National University"),
        _author("A2", "Kyung-Soo Kim", "Yonsei University"),
        _author("A3", "Kyung Min Kim", "Seoul National University"),
    ])
    best, reason = _best_openalex(client, "김경수", "", "Seoul National University")
    assert best["id"].endswith("A1"), reason
    # Searched with romanized English, not Hangul.
    assert client.queries == ["Gyeong-Su Kim", "Gyeongsu Kim"]


def test_acronym_institution_alias():
    client = FakeClient([_author("A1", "Won-Suk Chung", "Korea Advanced Institute of Science and Technology")])
    best, _ = _best_openalex(client, "정원석", "Won-Suk Chung", "KAIST")
    assert best is not None
    assert client.queries == ["Won-Suk Chung"]


def test_same_name_same_school_goes_to_review():
    client = FakeClient([
        _author("A1", "Jin Woo Kim", "Seoul National University"),
        _author("A2", "Jinwoo Kim", "Seoul National University"),
    ])
    best, reason = _best_openalex(client, "김진우", "", "Seoul National University")
    assert best is None and reason.startswith("ambiguous")


def test_wrong_surname_rejected():
    client = FakeClient([_author("A1", "Kyungsoo Park", "Seoul National University")])
    best, _ = _best_openalex(client, "김경수", "", "Seoul National University")
    assert best is None


def test_past_affiliation_used_when_current_differs():
    client = FakeClient([_author("A1", "Jaewon Lee", "Harvard University", past=["Pusan National University"])])
    best, reason = _best_openalex(client, "이재원", "Jaewon Lee", "Pusan National University")
    assert best is not None and "past" in reason
