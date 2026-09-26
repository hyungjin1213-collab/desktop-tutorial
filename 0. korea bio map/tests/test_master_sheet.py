import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import master_sheet as ms  # noqa: E402

PROFS = pd.DataFrame([
    {"professor_id": "P0001", "name_ko": "김철수", "name_en": "Chulsoo Kim", "university": "Seoul National University"},
    {"professor_id": "P0002", "name_ko": "이영희", "name_en": "Younghee Lee", "university": "KAIST"},
    {"professor_id": "P0003", "name_ko": "김철수", "name_en": "Chulsoo Kim", "university": "Yonsei University"},
])


def _book(tmp_path, monkeypatch, **sheets):
    monkeypatch.setattr(ms, "OUTPUT_DIR", tmp_path)
    path = tmp_path / "master.xlsx"
    ms.write_template(path)
    with pd.ExcelWriter(path, engine="openpyxl", mode="a", if_sheet_exists="replace") as w:
        for name, rows in sheets.items():
            pd.DataFrame(rows).to_excel(w, sheet_name=name, index=False)
    return path


def test_template_has_tabs(tmp_path):
    path = tmp_path / "m.xlsx"
    ms.write_template(path)
    sheets = pd.read_excel(path, sheet_name=None)
    assert list(sheets) == ["안내", "교수추가", "관계추가", "연구실정보"]
    assert list(sheets["연구실정보"].columns) == ms.LAB_HEADERS


def test_matcher_uses_korean_or_english_organisation():
    m = ms.ProfessorMatcher(PROFS)
    assert m.find("김철수", "서울대학교") == "P0001"
    assert m.find("김철수", "서울대") == "P0001"
    assert m.find("김철수", "연세대학교") == "P0003"
    assert m.find("김철수", "") == ""          # two people: organisation needed
    assert m.find("이영희", "") == "P0002"


def test_relationships_and_lab_info(tmp_path, monkeypatch):
    path = _book(tmp_path, monkeypatch,
                 관계추가=[{"A 이름": "김철수", "A 소속": "서울대학교", "B 이름": "이영희", "B 소속": "KAIST",
                          "관계": "지도교수-제자"},
                         {"A 이름": "홍길동", "A 소속": "서울대", "B 이름": "이영희", "B 소속": "KAIST", "관계": "공동연구"}],
                 연구실정보=[{"이름": "김철수", "소속": "서울대학교", "박사 평균 졸업기간(년)": "5.5",
                            "학생당 평균 논문 수": "4", "모집 중": "예"}])
    rel = ms.master_relationships(PROFS, path)
    assert rel[["professor_a_id", "professor_b_id", "relationship_type", "verified"]].values.tolist() == [
        ["P0001", "P0002", "advisor_student", "yes"]]
    unmatched = pd.read_csv(tmp_path / "master_unmatched.csv")
    assert unmatched["values"].str.contains("홍길동").any()
    assert ms.lab_info(PROFS, path) == {"P0001": {"phd_years": 5.5, "papers_per_student": 4.0, "recruiting": "예"}}


def test_new_professors_are_appended_once(tmp_path, monkeypatch):
    path = _book(tmp_path, monkeypatch,
                 교수추가=[{"이름": "박민수", "소속": "KIST", "ORCID": "0000-0001-0000-0009"},
                         {"이름": "김철수", "소속": "서울대학교"}])      # already there
    seed = tmp_path / "professors_seed.csv"
    PROFS.to_csv(seed, index=False)
    cols = ["professor_id", "name_ko", "name_en", "university", "department", "primary_field",
            "openalex_id", "source_url", "orcid", "identity_status", "scopus_id"]
    assert ms.add_master_professors(seed, cols, path) == 1
    assert ms.add_master_professors(seed, cols, path) == 0
    out = pd.read_csv(seed, dtype=str).fillna("")
    assert out.iloc[-1][["professor_id", "name_ko", "orcid"]].tolist() == ["P0004", "박민수", "0000-0001-0000-0009"]
