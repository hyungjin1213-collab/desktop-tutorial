import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sectors import SectorCollector, SectorTable, sector_of  # noqa: E402

UNI = {"display_name": "Seoul National University", "type": "education"}
HOSP = {"display_name": "Seoul National University Hospital", "type": "education"}
KIST = {"display_name": "Korea Institute of Science and Technology", "type": "facility"}
CO = {"display_name": "Samsung Biologics (South Korea)", "type": "company"}


def test_institution_types_map_to_sectors():
    assert sector_of(UNI) == "학" and sector_of(HOSP) == "병"
    assert sector_of(KIST) == "연" and sector_of(CO) == "산"


def test_sector_needs_share_and_two_papers():
    c = SectorCollector(now_year=2026)
    for _ in range(6):
        c.add("A", 2024, [UNI, HOSP])     # clinical professor: 학 + 병
    c.add("A", 2024, [UNI, CO])            # one industry paper: not 산
    c.add("A", 2005, [KIST])               # too old
    row = c.to_frame().set_index("professor_id").loc["A"]
    assert row["sectors"] == "학;병"


def test_table_override_and_fallbacks(tmp_path):
    out, data = tmp_path / "out", tmp_path / "data"
    out.mkdir(); data.mkdir()
    pd.DataFrame([{"professor_id": "A", "sectors": "연"}]).to_csv(out / "professor_sectors.csv", index=False)
    pd.DataFrame([{"professor_id": "B", "sectors": "학;산"}]).to_csv(data / "sector_overrides.csv", index=False)
    t = SectorTable(data, out)
    assert t.sectors("A", "학", "") == ["학", "연"]            # faculty page -> 학, papers -> 연
    assert t.sectors("B", "학", "") == ["학", "산"]            # override wins
    assert t.sectors("C", "학", "내과학교실") == ["학", "병"]  # clinical department fallback
    assert t.sectors("D", "연", "") == ["연"]                  # listed on a research institute page
