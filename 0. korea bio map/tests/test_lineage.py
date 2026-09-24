import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pipeline  # noqa: E402
from lineage import Authorship, infer_lineage, lineage_relationships  # noqa: E402

SNU, HARVARD = ("Seoul National University",), ("Harvard University",)


def paper(year, pos, last, inst=SNU, title="t", doi="10.1/x"):
    return Authorship(year, pos, last, inst, title, doi)


def records():
    return {
        # ADV: senior professor, publishing since 1990
        "ADV": [paper(1990, "first", "")] + [paper(2005 + i, "last", "ADV") for i in range(4)],
        # MENTOR: senior professor abroad
        "MENTOR": [paper(1992, "first", "", HARVARD)],
        # PEER: started at the same time as STU -> co-publishing is not mentorship
        "PEER": [paper(2004, "first", "")],
        # STU: PhD 2005-2009 with ADV (3 first-author papers), postdoc at Harvard with MENTOR,
        # plus 3 papers with PEER as last author
        "STU": [
            paper(2005, "first", "ADV"), paper(2007, "first", "ADV"), paper(2009, "first", "ADV"),
            paper(2012, "first", "MENTOR", HARVARD), paper(2013, "first", "MENTOR", HARVARD),
            paper(2013, "first", "MENTOR", HARVARD, doi="10.1/pd"),
            paper(2008, "first", "PEER"), paper(2009, "first", "PEER"), paper(2010, "first", "PEER"),
        ],
        # STU2: only 2 papers with ADV -> review, not auto
        "STU2": [paper(2006, "first", "ADV"), paper(2008, "first", "ADV")],
    }


def test_infers_phd_and_postdoc_and_skips_peers():
    out = infer_lineage(records(), {"ADV": "김교수", "STU": "이제자"})
    got = {(r.professor_a_id, r.professor_b_id, r.relationship_type): (r.evidence_papers, r.status) for r in out.itertuples()}
    assert got == {
        ("ADV", "STU", "advisor_student"): (3, "auto"),
        ("MENTOR", "STU", "postdoc_mentor"): (3, "auto"),
        ("ADV", "STU2", "advisor_student"): (2, "review"),
    }


def test_decisions_override_status():
    decisions = pd.DataFrame([
        {"professor_a_id": "ADV", "professor_b_id": "STU", "relationship_type": "advisor_student", "decision": "no"},
        {"professor_a_id": "ADV", "professor_b_id": "STU2", "relationship_type": "advisor_student", "decision": "yes"},
    ])
    out = infer_lineage(records(), {}, decisions)
    status = {(r.professor_a_id, r.professor_b_id): r.status for r in out.itertuples() if r.relationship_type == "advisor_student"}
    assert status == {("ADV", "STU"): "rejected", ("ADV", "STU2"): "approved"}
    rel = lineage_relationships(out)
    assert set(zip(rel.professor_b_id, rel.verified)) == {("STU2", "yes"), ("STU", "auto")}  # STU: postdoc link stays auto


def test_collect_writes_lineage_from_same_works(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(pipeline, "DATA_DIR", tmp_path)

    def work(i, year, first, last):
        return {"id": f"W{i}", "publication_year": year, "display_name": f"paper {i}", "doi": None,
                "authorships": [
                    {"author": {"id": first}, "author_position": "first", "institutions": [{"display_name": "SNU"}]},
                    {"author": {"id": last}, "author_position": "last", "institutions": [{"display_name": "SNU"}]}]}

    works = [work(0, 1990, "A_ADV", "X")] + [work(i, 2005 + i, "A_STU", "A_ADV") for i in range(1, 4)]

    class Client:
        def iter_works_by_authors(self, ids):
            return iter(works)

    professors = pd.DataFrame([{"professor_id": "P1", "openalex_id": "A_ADV", "name_ko": "김교수"},
                               {"professor_id": "P2", "openalex_id": "A_STU", "name_ko": "이제자"}])
    pipeline.collect_collaborations(Client(), professors)
    rel = pd.read_csv(tmp_path / "relationships_lineage.csv", dtype=str)
    assert list(zip(rel.professor_a_id, rel.professor_b_id, rel.relationship_type, rel.verified)) == [
        ("P1", "P2", "advisor_student", "auto")]
