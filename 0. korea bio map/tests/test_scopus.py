import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pipeline  # noqa: E402
from scopus_client import ScopusClient  # noqa: E402


class FakeResponse:
    def __init__(self, status, payload=None):
        self.status_code = status
        self.payload = payload or {}

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self, handler):
        self.headers = {}
        self.handler = handler
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append((url, params))
        return self.handler(url, params)


def _client(handler):
    c = ScopusClient(api_key="k", insttoken="t")
    c.session = FakeSession(handler)
    return c


def _author_entry(aid, given, surname):
    return {"dc:identifier": f"AUTHOR_ID:{aid}", "preferred-name": {"given-name": given, "surname": surname}}


def test_author_id_by_orcid():
    c = _client(lambda url, p: FakeResponse(200, {"search-results": {"entry": [_author_entry("111", "Kyung-Soo", "Kim")]}}))
    assert c.find_author_id(orcid="0000-0001-0000-0001") == ("111", "Scopus author by ORCID")
    assert c.session.calls[0][1]["query"] == "ORCID(0000-0001-0000-0001)"


def test_name_search_requires_single_romanization_match():
    entries = [_author_entry("1", "Kyung-Soo", "Kim"), _author_entry("2", "Kyungsoo", "Kim")]
    c = _client(lambda url, p: FakeResponse(200, {"search-results": {"entry": entries}}))
    sid, reason = c.find_author_id(name_ko="김경수", name_en="Kyung-Soo Kim", affiliation="Seoul National University")
    assert sid == "" and reason.startswith("ambiguous")


def test_no_entitlement_disables_scopus_once():
    c = _client(lambda url, p: FakeResponse(401))
    try:
        c.find_author_id(orcid="0000-0001-0000-0001")
    except Exception as exc:
        assert type(exc).__name__ == "ScopusUnavailable"
    assert not c.enabled and "SCOPUS_INSTTOKEN" in c.disabled_reason


class FakeOpenAlex:
    def iter_works_by_author(self, author_id):
        works = {
            "A1": [{"id": "https://openalex.org/W1", "doi": "https://doi.org/10.1/abc", "display_name": "p1",
                    "authorships": [{"author": {"id": "A1"}}, {"author": {"id": "B1"}}]}],
        }
        return iter(works.get(author_id, []))


class FakeScopus:
    enabled = True

    def iter_documents(self, sid):
        docs = {
            # same paper as W1 (DOI match) + one Scopus-only paper with P3
            "S1": [{"id": "SCOPUS_ID:9", "doi": "10.1/abc", "author_ids": ["S1", "S2"]},
                   {"id": "SCOPUS_ID:10", "doi": "10.1/xyz", "author_ids": ["S1", "S3"]}],
        }
        return iter(docs.get(sid, []))


def test_openalex_and_scopus_merged_by_doi(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "OUTPUT_DIR", tmp_path)
    professors = pd.DataFrame([
        {"professor_id": "P1", "openalex_id": "A1", "scopus_id": "S1"},
        {"professor_id": "P2", "openalex_id": "B1", "scopus_id": "S2"},
        {"professor_id": "P3", "openalex_id": "", "scopus_id": "S3"},
    ])
    auto, _ = pipeline.collect_collaborations(FakeOpenAlex(), professors, FakeScopus())
    got = {(r.professor_a_id, r.professor_b_id): (r.collaboration_paper_count, r.notes) for r in auto.itertuples()}
    assert got[("P1", "P2")][0] == 1 and got[("P1", "P2")][1].startswith("OpenAlex + Scopus")
    assert got[("P1", "P3")] == (1, "Scopus coauthorship between confirmed professors")


def test_scopus_ids_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "DATA_DIR", tmp_path)

    class S:
        enabled = True
        calls = 0

        def find_author_id(self, *a):
            S.calls += 1
            return "S1", "Scopus author by ORCID"

    profs = pd.DataFrame([{"professor_id": "P1", "orcid": "0000", "name_ko": "", "name_en": "", "university": "", "scopus_id": ""}])
    assert pipeline.resolve_scopus_ids(S(), profs).iloc[0].scopus_id == "S1"
    assert pipeline.resolve_scopus_ids(S(), profs).iloc[0].scopus_id == "S1"
    assert S.calls == 1
