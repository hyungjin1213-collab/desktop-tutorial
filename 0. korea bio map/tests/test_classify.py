import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from classify import Classifier, position  # noqa: E402

DATA = Path(__file__).resolve().parents[1] / "data"


def test_category_from_subfield_department_and_override(tmp_path):
    c = Classifier(DATA)
    assert c.category("P1", "Cancer Research", "") == "암·종양"
    assert c.category("P1", "Pulmonary and Respiratory Medicine", "") == "임상의학"
    assert c.category("P1", "", "College of Pharmacy") == "약학·신약"
    assert c.category("P1", "", "신경과학교실") == "신경과학"
    assert c.category("P1", "", "") == "기타"

    for f in ("field_categories.csv", "universities_seed.csv"):
        (tmp_path / f).write_text((DATA / f).read_text(encoding="utf-8-sig"), encoding="utf-8")
    pd.DataFrame([{"professor_id": "P9", "category": "면역·감염", "notes": "T-cell"}]).to_csv(
        tmp_path / "field_overrides.csv", index=False)
    assert Classifier(tmp_path).category("P9", "Molecular Biology", "") == "면역·감염"


def test_region_and_korean_university_name():
    c = Classifier(DATA)
    assert c.region("Seoul National University") == "서울"
    assert c.region("seoul national university") == "서울"
    assert c.region("Pusan National University") == "부산·울산·경남"
    assert c.region("Chonnam National University Hwasun Hospital; X") == "광주·전라"
    assert c.region("Somewhere Else") == "기타"
    assert c.university_ko("Kyung Hee University") == "경희대학교"


def test_position():
    assert position("부교수") == "부교수"
    assert position("조교수(겸무)") == "조교수"
    assert position("Associate Professor") == "부교수"
    assert position("교수(대학장)") == "교수"
    assert position("") == ""
