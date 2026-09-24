import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import department_discovery as dd  # noqa: E402

# Titles taken from the earlier department_candidates.csv
ACCEPT = [
    ("교수진 목록 - 바이오엔지니어링전공 - 서울대학교", "https://bioeng.snu.ac.kr/교수진-목록/"),
    ("교수진 > 약학과 > 학과소개 | 중앙대학교 대학원", "https://gradu.cau.ac.kr/x"),
    ("Faculty - 서울대학교 약학대학", "https://snupharm.snu.ac.kr/faculty"),
    ("전임교수 - 생명정보공학과 - 고려대학교", "https://biotechnology.korea.ac.kr/faculty/8650/subview.do"),
]
REJECT = [
    ("KAIST 생명과학과 > 겸임·초빙 교수 - 카이스트", "https://bio.kaist.ac.kr/x"),
    ("현직교수 | 간호대학 | 중앙대학교", "https://nursing.cau.ac.kr/x"),
    ("교수진 | 경영학부", "https://biz.cau.ac.kr/x"),
    ("전임교수 - 유성구 - 인문사회과학부 - 카이스트", "https://humanities.kaist.ac.kr/x"),
    ("공지사항 - 생명과학과", "https://bio.snu.ac.kr/notice"),
]


def test_bio_page_filter():
    for title, url in ACCEPT:
        assert dd.is_bio_faculty_page(title, url), title
    for title, url in REJECT:
        assert not dd.is_bio_faculty_page(title, url), title


def test_other_universities_domains_rejected():
    assert dd._is_official("https://bioeng.snu.ac.kr/x", "snu.ac.kr")
    assert not dd._is_official("https://biotechnology.korea.ac.kr/x", "snu.ac.kr")
    assert not dd._is_official("https://bms.seoultech.ac.kr/x", "snu.ac.kr")


def test_discovery_appends_sources_once(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(dd, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(dd, "OUTPUT_DIR", tmp_path / "out")
    pd.DataFrame([
        {"university": "Seoul National University", "name_ko": "서울대학교", "official_domain": "snu.ac.kr"},
        {"university": "Yonsei University", "name_ko": "연세대학교", "official_domain": "yonsei.ac.kr"},
    ]).to_csv(tmp_path / "data" / "universities_seed.csv", index=False)
    pd.DataFrame([{"source_id": "YONSEI_PHARM", "university": "Yonsei University", "department": "Pharmacy",
                   "faculty_url": "https://pharmacy.yonsei.ac.kr/p", "parser": "photo_anchor",
                   "enabled": "yes", "notes": ""}]).to_csv(tmp_path / "data" / "faculty_sources.csv", index=False)

    results = [
        {"title": "교수진 목록 - 바이오엔지니어링전공 - 서울대학교", "link": "https://bioeng.snu.ac.kr/faculty/"},
        {"title": "전임교수 - 생명정보공학과 - 고려대학교", "link": "https://biotechnology.korea.ac.kr/f"},
    ]
    calls = []

    def fake_search(q):
        calls.append(q)
        return results

    dd.discover_departments(search=fake_search)
    sources = pd.read_csv(tmp_path / "data" / "faculty_sources.csv", dtype=str)
    assert list(sources.faculty_url) == ["https://pharmacy.yonsei.ac.kr/p", "https://bioeng.snu.ac.kr/faculty/"]
    assert sources.iloc[1].department == "바이오엔지니어링전공"
    # Yonsei already has sources: not searched again.
    assert all("snu.ac.kr" in q for q in calls)
