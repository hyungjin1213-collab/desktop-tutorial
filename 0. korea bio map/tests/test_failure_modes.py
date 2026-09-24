"""Regressions from Actions run #22 (OpenAlex budget ran out mid-run)."""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import candidate_review  # noqa: E402
import faculty_identity_v2 as fi  # noqa: E402
import openalex_client  # noqa: E402
import pipeline  # noqa: E402
from openalex_client import OpenAlexClient, OpenAlexUnavailable  # noqa: E402
from test_faculty_identity_v2 import ENG, FakeOpenAlex, FakeORCID, _author, _orcid_rec  # noqa: E402


class Resp:
    def __init__(self, status, text="", headers=None):
        self.status_code, self.text, self.headers = status, text, headers or {}

    def json(self):
        return {"results": []}

    def raise_for_status(self):
        raise RuntimeError(self.status_code)


def test_openalex_daily_budget_raises_instead_of_empty(monkeypatch):
    c = OpenAlexClient()
    calls = []
    monkeypatch.setattr(c.session, "get", lambda *a, **k: calls.append(1) or Resp(429, "daily budget exceeded"))
    with pytest.raises(OpenAlexUnavailable):
        list(c.iter_works_by_author("A1"))
    assert len(calls) == 1  # no pointless retries on a daily limit


def test_openalex_rate_limit_retries_then_succeeds(monkeypatch):
    c = OpenAlexClient()
    seq = [Resp(429, "too many", {"Retry-After": "0"}), Resp(200)]
    monkeypatch.setattr(c.session, "get", lambda *a, **k: seq.pop(0))
    monkeypatch.setattr(openalex_client.time, "sleep", lambda s: None)
    assert c.authors_by_orcid("0000") == []


class DownOpenAlex(FakeOpenAlex):
    def authors_by_orcid(self, orcid):
        raise OpenAlexUnavailable("HTTP 429")

    def _get(self, path, params):
        raise OpenAlexUnavailable("HTTP 429")


def test_identity_batch_stops_and_keeps_unprocessed_for_next_run(tmp_path, monkeypatch):
    monkeypatch.setattr(fi, "OUTPUT_DIR", tmp_path)
    pd.DataFrame([{"source_id": "S", "name": "김경수", "name_ko": "김경수", "university": "Seoul National University"}]).to_csv(
        tmp_path / "faculty_directory_v2.csv", index=False)
    out = fi.resolve_faculty_identities_v2(DownOpenAlex([]), FakeORCID([_orcid_rec("0000-1", "Kyung-Soo", "Kim")]))
    assert out.empty  # nothing recorded as "no OpenAlex profile"


def test_orcid_of_same_name_engineer_is_rejected():
    orcid = FakeORCID([_orcid_rec("0000-0003-0105-6025", "Sunghyuk", "Park")])
    oa = FakeOpenAlex([], by_orcid={"0000-0003-0105-6025": [
        _author("A1", "Sunghyuk Park", "Seoul National University", topics=ENG)]})
    row = fi.resolve_person(oa, orcid, {"name": "박성혁", "name_ko": "박성혁", "university": "Seoul National University"})
    assert row["identity_status"] == "manual_review" and "same-name" in row["identity_reason"]


def test_pharmacy_chemist_is_bio_adjacent():
    chem = [{"count": 30, "domain": {"display_name": "Physical Sciences"}, "field": {"display_name": "Chemistry"},
             "subfield": {"display_name": "Organic Chemistry"}}]
    assert fi._bio_share(_author("A1", "x", "y", topics=chem)) == 1.0


def test_collect_does_not_write_empty_results_when_openalex_down(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "OUTPUT_DIR", tmp_path)

    class Down:
        def iter_works_by_authors(self, ids):
            raise OpenAlexUnavailable("HTTP 429")

    with pytest.raises(OpenAlexUnavailable):
        pipeline.collect_collaborations(Down(), pd.DataFrame([{"professor_id": "P1", "openalex_id": "A1"}]))
    assert not (tmp_path / "relationships_auto.csv").exists()


def test_seed_with_orcid_gets_openalex_id(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "DATA_DIR", tmp_path)
    monkeypatch.setattr(pipeline, "OUTPUT_DIR", tmp_path)
    pd.DataFrame([{"professor_id": "P1", "name_ko": "김경수", "orcid": "0000-1", "openalex_id": ""}]).to_csv(
        tmp_path / "professors_seed.csv", index=False)
    oa = FakeOpenAlex([], by_orcid={"0000-1": [_author("A7", "Kyung-Soo Kim", "SNU"), _author("A8", "K Kim", "SNU")]})
    assert pipeline.resolve_professors(oa).iloc[0].openalex_id == "A7;A8"


def test_candidate_review_with_no_candidates(tmp_path, monkeypatch):
    monkeypatch.setattr(candidate_review, "OUTPUT_DIR", tmp_path)
    pd.DataFrame(columns=["openalex_id", "display_name"]).to_csv(tmp_path / "collaborator_candidates.csv", index=False)
    assert candidate_review.classify_candidates(None, None).empty


def test_engineer_with_some_materials_papers_is_rejected():
    """Run #23: 박성혁 (pharmacy) matched an EE with a Materials Science side line."""
    topics = [
        {"count": 50, "domain": {"display_name": "Physical Sciences"}, "field": {"display_name": "Engineering"},
         "subfield": {"display_name": "Electrical and Electronic Engineering"}},
        {"count": 40, "domain": {"display_name": "Physical Sciences"}, "field": {"display_name": "Materials Science"},
         "subfield": {"display_name": "Electronic, Optical and Magnetic Materials"}},
        {"count": 30, "domain": {"display_name": "Life Sciences"}, "field": {"display_name": "Biochemistry"},
         "subfield": {"display_name": "Molecular Biology"}},
    ]
    orcid = FakeORCID([_orcid_rec("0000-0003-0105-6025", "Sunghyuk", "Park")])
    oa = FakeOpenAlex([], by_orcid={"0000-0003-0105-6025": [
        _author("A1", "Sunghyuk Park", "Seoul National University", topics=topics)]})
    row = fi.resolve_person(oa, orcid, {"name": "박성혁", "name_ko": "박성혁", "university": "Seoul National University"})
    assert row["identity_status"] == "manual_review"
