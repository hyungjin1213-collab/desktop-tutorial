"""산학연병: which of industry / academia / research institute / hospital a professor belongs to.

From the professor's own affiliations on recent papers (already fetched for the
collaboration graph, no extra requests). OpenAlex gives every institution a
type: education -> 학, healthcare -> 병, company -> 산, facility / government /
nonprofit -> 연. A sector counts when it appears on at least MIN_SHARE of the
professor's recent papers (and on MIN_WORKS of them), so one visiting stint
does not move anyone. The page a person is listed on sets their home sector
(university faculty page -> 학, research institute -> 연; universities_seed.csv
org_type); a clinical professor at the university hospital is 학 + 병.

data/sector_overrides.csv (professor_id, sectors e.g. "학;산") always wins.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pandas as pd

SECTORS = ["학", "병", "연", "산"]
SECTOR_LABELS = {"학": "대학", "병": "병원", "연": "연구소", "산": "기업"}
# universities_seed.csv org_type -> home sector (where the person is listed)
ORG_TYPE_SECTOR = {"university": "학", "hospital": "병", "institute": "연", "company": "산"}
TYPE_TO_SECTOR = {
    "education": "학",
    "healthcare": "병",
    "company": "산",
    "facility": "연",
    "government": "연",
    "nonprofit": "연",
    "archive": "연",
}
# OpenAlex sometimes types a university hospital as "education"; the name is clearer.
HOSPITAL_WORDS = ("hospital", "medical center", "medical centre", "병원", "의료원")
RECENT_YEARS = 10
MIN_SHARE = 0.2
MIN_WORKS = 2
# Fallback before any papers are collected: departments that are clearly clinical.
CLINICAL_DEPARTMENT_WORDS = ("병원", "내과", "외과", "소아청소년과", "산부인과", "영상의학", "진단검사",
                             "마취", "정형외과", "피부과", "안과", "이비인후과", "정신건강의학", "임상")


def sector_of(institution: dict) -> str:
    name = str(institution.get("display_name", "")).casefold()
    if any(w in name for w in HOSPITAL_WORDS):
        return "병"
    return TYPE_TO_SECTOR.get(str(institution.get("type", "")).casefold(), "")


class SectorCollector:
    def __init__(self, now_year: int):
        self.now = now_year
        self.works: dict[str, int] = defaultdict(int)
        self.counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def add(self, professor_id: str, year: int, institutions: list[dict]) -> None:
        if year and self.now - year > RECENT_YEARS:
            return
        found = {sector_of(i) for i in institutions or [] if isinstance(i, dict)} - {""}
        if not found:
            return
        self.works[professor_id] += 1
        for sector in found:
            self.counts[professor_id][sector] += 1

    def to_frame(self) -> pd.DataFrame:
        rows = []
        for pid, n in self.works.items():
            shares = {s: self.counts[pid][s] / n for s in SECTORS}
            chosen = [s for s in SECTORS if shares[s] >= MIN_SHARE and self.counts[pid][s] >= MIN_WORKS]
            rows.append({"professor_id": pid, "works": n, **{s: round(shares[s], 3) for s in SECTORS},
                         "sectors": ";".join(chosen)})
        return pd.DataFrame(rows, columns=["professor_id", "works", *SECTORS, "sectors"])


def _read(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str).fillna("")


def _split(value: str) -> list[str]:
    parts = {p.strip() for p in str(value).replace(",", ";").split(";")}
    return [s for s in SECTORS if s in parts]


class SectorTable:
    """Sectors per professor: override > papers > department fallback."""

    def __init__(self, data_dir: Path, output_dir: Path):
        table = _read(output_dir / "professor_sectors.csv")
        self.from_papers = {r["professor_id"]: _split(r["sectors"]) for _, r in table.iterrows()} if not table.empty else {}
        overrides = _read(data_dir / "sector_overrides.csv")
        self.overrides = (
            {r["professor_id"].strip(): _split(r["sectors"]) for _, r in overrides.iterrows() if _split(r["sectors"])}
            if not overrides.empty else {}
        )

    def sectors(self, professor_id: str, home: str, department: str) -> list[str]:
        """home: the sector of the page the person is listed on (학 for a university)."""
        if professor_id in self.overrides:
            return self.overrides[professor_id]
        found = set(self.from_papers.get(professor_id, []))
        found.add(home or "학")
        if any(w in (department or "") for w in CLINICAL_DEPARTMENT_WORDS):
            found.add("병")
        return [s for s in SECTORS if s in found]
