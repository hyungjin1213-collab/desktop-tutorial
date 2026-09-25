import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from keywords import KeywordCollector  # noqa: E402


def work(year, mesh=(), keywords=()):
    return {"publication_year": year,
            "mesh": [{"descriptor_name": m, "is_major_topic": major} for m, major in mesh],
            "keywords": [{"display_name": k, "score": s} for k, s in keywords]}


def test_lab_specific_terms_rank_first_and_generic_terms_drop():
    c = KeywordCollector(now_year=2026)
    shared = ("Inflammation", False)
    # A: CAR-T lab (last author), B and C: other labs; everyone mentions inflammation
    for _ in range(3):
        c.add_work("A", "last", work(2025, [("Humans", False), ("Mice", False), shared,
                                            ("Receptors, Chimeric Antigen", True), ("T-Lymphocytes", True),
                                            ("Flow Cytometry", False)], [("CAR-T cell therapy", 0.9)]))
    c.add_work("B", "last", work(2024, [shared, ("Alzheimer Disease", True)]))
    c.add_work("C", "last", work(2024, [shared, ("Stroke", True)]))
    top = c.top_terms()["A"]
    kws = [t for t, _ in top["keywords"]]
    assert "Humans" not in kws and "Mice" not in kws
    assert kws.index("T-Lymphocytes") < kws.index("Inflammation")  # shared by all labs -> lower
    assert [t for t, _ in top["techniques"]] == ["CAR-T·입양세포치료", "유세포분석"]


def test_role_and_recency_weighting():
    c = KeywordCollector(now_year=2026)
    c.add_work("A", "last", work(2025, [("Microbiota", False)]))
    c.add_work("A", "middle", work(2025, [("Obesity", False)]))
    c.add_work("A", "last", work(2001, [("Asthma", False)]))
    c.add_work("B", "last", work(2025, [("Stroke", False)]))
    w = c.topics["A"]
    assert w["microbiota"] > w["obesity"]   # own lab's paper beats a middle-author paper
    assert w["microbiota"] > w["asthma"]    # recent beats 25 years old


def test_frame_output():
    c = KeywordCollector(now_year=2026)
    c.add_work("A", "last", work(2025, [("Microbiota", True)]))
    df = c.to_frame()
    assert list(df.columns) == ["professor_id", "kind", "rank", "term", "term_en", "score"]
    assert df.iloc[0].kind == "keyword" and df.iloc[0].term == "Microbiota"


def test_spellings_of_one_technique_are_merged_and_kept_apart_from_topics():
    c = KeywordCollector(now_year=2026)
    c.add_work("A", "last", work(2025, [("Flow Cytometry", False), ("T-Lymphocytes", True)],
                                 [("FACS analysis", 0.8), ("single-cell RNA sequencing", 0.9), ("scaffold protein", 0.7)]))
    c.add_work("B", "last", work(2025, [("Stroke", True)]))
    top = c.top_terms()["A"]
    assert sorted(t for t, _ in top["techniques"]) == ["단일세포 분석", "유세포분석"]
    kws = [t for t, _ in top["keywords"]]
    assert "T-Lymphocytes" in kws and "scaffold protein" in kws and "Flow Cytometry" not in kws
    df = c.to_frame()
    assert set(df[df.kind == "technique"].term_en) == {"Flow Cytometry", "Single-cell Analysis"}
