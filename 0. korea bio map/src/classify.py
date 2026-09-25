"""Broad research field, region and position for each professor (map filters).

- Field: OpenAlex subfield -> one of ~12 categories via data/field_categories.csv;
  if the subfield is missing or unmapped, department keywords decide; a row in
  data/field_overrides.csv (professor_id, category) always wins.
- Region: university -> region from data/universities_seed.csv, with keyword
  fallbacks for hospital / company affiliations.
- Position: 교수 / 부교수 / 조교수 from the faculty page title.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

OTHER = "기타"
UNKNOWN_REGION = "기타"

# Checked in order: the first matching keyword decides.
DEPARTMENT_KEYWORDS = [
    (("약학", "약대", "pharm", "제약"), "약학·신약"),
    (("신경", "뇌", "neuro"), "신경과학"),
    (("면역", "감염", "미생물", "immun"), "면역·감염"),
    (("종양", "암", "cancer", "onco"), "암·종양"),
    (("유전", "생물정보", "정보의학", "오믹스", "bioinfo", "genom"), "유전체·생물정보"),
    (("의공학", "바이오엔지니어링", "생체재료", "bioeng", "biomedical eng"), "의공학·바이오소재"),
    (("식품", "농", "산림", "원예", "식물", "동물", "수의", "축산", "생태", "환경"), "농생명·식품·생태"),
    (("보건", "역학", "public health"), "보건·역학"),
    (("생리", "대사", "영양"), "생리·대사"),
    (("의과대학", "의학과", "의학전문", "병원", "임상", "medicine", "medical"), "임상의학"),
    (("생명", "생화학", "분자", "세포", "바이오", "의과학", "의생명", "life", "bio"), "분자·세포생물"),
]

REGION_KEYWORDS = [
    (("seoul", "severance", "samsung", "asan", "yonsei", "korea university", "catholic university of korea"), "서울"),
    (("bundang", "gachon", "gil medical", "ajou", "inha", "incheon", "suwon", "ilsan", "cha university"), "경기·인천"),
    (("chonnam", "hwasun", "gwangju", "chonbuk", "jeonbuk", "wonkwang", "chosun"), "광주·전라"),
    (("pusan", "busan", "dong-a", "ulsan", "inje", "kosin", "gyeongsang", "changwon"), "부산·울산·경남"),
    (("kyungpook", "daegu", "keimyung", "yeungnam", "pohang", "postech", "dgist"), "대구·경북"),
    (("chungnam", "chungbuk", "daejeon", "kaist", "kongju", "soonchunhyang", "eulji", "cheonan"), "대전·충청"),
    (("kangwon", "hallym", "gangneung", "wonju", "chuncheon"), "강원"),
    (("jeju",), "제주"),
]


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str).fillna("")


class Classifier:
    def __init__(self, data_dir: Path):
        cats = _read_csv(data_dir / "field_categories.csv")
        self.by_subfield = (
            {r["openalex_subfield"].strip().casefold(): r["category"].strip() for _, r in cats.iterrows()}
            if not cats.empty else {}
        )
        overrides = _read_csv(data_dir / "field_overrides.csv")
        self.overrides = (
            {r["professor_id"].strip(): r["category"].strip() for _, r in overrides.iterrows() if r["category"].strip()}
            if not overrides.empty else {}
        )
        unis = _read_csv(data_dir / "universities_seed.csv")
        self.region_by_uni = (
            {r["university"].strip().casefold(): r.get("region", "").strip() for _, r in unis.iterrows()}
            if not unis.empty else {}
        )
        self.name_ko_by_uni = (
            {r["university"].strip().casefold(): r.get("name_ko", "").strip() for _, r in unis.iterrows()}
            if not unis.empty else {}
        )

    def category(self, professor_id: str, subfield: str, department: str) -> str:
        if professor_id in self.overrides:
            return self.overrides[professor_id]
        cat = self.by_subfield.get((subfield or "").strip().casefold())
        if cat:
            return cat
        dept = (department or "").casefold()
        for words, name in DEPARTMENT_KEYWORDS:
            if any(w.casefold() in dept for w in words):
                return name
        return OTHER

    def main_university(self, university: str) -> str:
        return (university or "").split(";")[0].strip()

    def region(self, university: str) -> str:
        main = self.main_university(university).casefold()
        if main in self.region_by_uni and self.region_by_uni[main]:
            return self.region_by_uni[main]
        for words, name in REGION_KEYWORDS:
            if any(w in main for w in words):
                return name
        return UNKNOWN_REGION

    def university_ko(self, university: str) -> str:
        return self.name_ko_by_uni.get(self.main_university(university).casefold(), "")


def position(title: str) -> str:
    """Normalise a faculty-page title to 교수 / 부교수 / 조교수 (or "")."""
    t = (title or "").casefold()
    if "부교수" in t or "associate" in t:
        return "부교수"
    if "조교수" in t or "assistant" in t:
        return "조교수"
    if "교수" in t or "professor" in t:
        return "교수"
    return ""
