import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pipeline  # noqa: E402


def _work(wid, *author_ids):
    return {"id": f"https://openalex.org/{wid}", "display_name": wid,
            "authorships": [{"author": {"id": f"https://openalex.org/{a}"}, "institutions": []} for a in author_ids]}


class FakeClient:
    works = {
        "A1": [_work("W1", "A1", "B1"), _work("W2", "A1", "C1"), _work("W9", *(["A1", "B1"] + [f"X{i}" for i in range(150)]))],
        "A9": [_work("W3", "A9", "B1")],   # second (split) profile of professor P1
        "B1": [_work("W1", "A1", "B1"), _work("W3", "A9", "B1")],
        "C1": [_work("W2", "A1", "C1")],
    }

    def iter_works_by_author(self, author_id):
        return iter(self.works.get(author_id, []))


def test_collaborations_use_all_openalex_ids_and_skip_consortium_papers(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "OUTPUT_DIR", tmp_path)
    professors = pd.DataFrame([
        {"professor_id": "P1", "openalex_id": "A1;A9"},
        {"professor_id": "P2", "openalex_id": "B1"},
        {"professor_id": "P3", "openalex_id": "C1"},
    ])
    auto, _ = pipeline.collect_collaborations(FakeClient(), professors)
    pairs = {(r.professor_a_id, r.professor_b_id): r.collaboration_paper_count for r in auto.itertuples()}
    # W1 + W3 (via split profile A9); W9 has 152 authors and is ignored.
    assert pairs == {("P1", "P2"): 2, ("P1", "P3"): 1}
