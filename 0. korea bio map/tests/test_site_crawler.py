import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import department_discovery as dd  # noqa: E402
from site_crawler import SiteCrawler, department_label, link_score  # noqa: E402


def _cards(*people):
    return "".join(
        f"<div class='prof'><img src='/p/{i}.jpg' width='100' height='120'><strong>{n}</strong> <span>{t}</span>"
        f" <a href='/view?id={i}'>상세보기</a> {n.lower()}@snu.ac.kr</div>"
        for i, (n, t) in enumerate(people)
    )


PEOPLE = [("강건욱", "교수"), ("권성원", "교수"), ("구자현", "부교수"), ("김찬혁", "조교수")]

SITE = {
    "https://www.snu.ac.kr/robots.txt": "User-agent: *\nDisallow: /private",
    "https://www.snu.ac.kr/": """<title>서울대학교</title>
        <a href="/colleges">대학·대학원</a> <a href="/admission">입학</a> <a href="/notice">공지사항</a>
        <a href="/private/faculty">의과대학 교수진</a> <a href="https://other.ac.kr/faculty">약학대학 교수진</a>""",
    "https://www.snu.ac.kr/colleges": """<title>대학·대학원</title>
        <a href="https://pharm.snu.ac.kr/">약학대학</a> <a href="https://cba.snu.ac.kr/">경영대학</a>
        <a href="https://nursing.snu.ac.kr/">간호대학</a>""",
    "https://pharm.snu.ac.kr/": """<title>서울대학교 약학대학</title>
        <a href="/faculty">교수진</a> <a href="/emeritus">명예교수</a> <a href="/notice">공지사항</a>
        <a href="/brochure.pdf">교수진 안내 PDF</a>""",
    "https://pharm.snu.ac.kr/faculty": "<title>교수진 | 약학대학</title>" + _cards(*PEOPLE),
    "https://pharm.snu.ac.kr/emeritus": "<title>명예교수</title>" + _cards(*PEOPLE),
    "https://cba.snu.ac.kr/": '<title>경영대학</title><a href="/faculty">교수진</a>',
    "https://cba.snu.ac.kr/faculty": "<title>교수진</title>" + _cards(*PEOPLE),
    "https://www.snu.ac.kr/private/faculty": "<title>교수진</title>" + _cards(*PEOPLE),
}


class FakeWeb:
    def __init__(self, site):
        self.site, self.requested = site, []

    def __call__(self, url):
        self.requested.append(url)
        if url not in self.site:
            raise RuntimeError("404")
        return self.site[url]


def _crawler(web, **kw):
    return SiteCrawler(web, dd._count_faculty, delay=0, **kw)


def test_finds_pharmacy_faculty_page_only():
    web = FakeWeb(SITE)
    pages = _crawler(web).crawl("snu.ac.kr", ["https://www.snu.ac.kr/"])
    assert [p.url for p in pages] == ["https://pharm.snu.ac.kr/faculty"]
    assert pages[0].faculty_count == 4
    assert department_label(pages[0], "서울대학교") == "약학대학"
    # never fetched: non-bio colleges, menus, PDFs, other domains, robots-disallowed paths
    for url in ["https://cba.snu.ac.kr/faculty", "https://nursing.snu.ac.kr/", "https://www.snu.ac.kr/notice",
                "https://pharm.snu.ac.kr/brochure.pdf", "https://other.ac.kr/faculty",
                "https://www.snu.ac.kr/private/faculty", "https://pharm.snu.ac.kr/emeritus"]:
        assert url not in web.requested, url


def test_page_limit_is_respected():
    web = FakeWeb(SITE)
    _crawler(web, page_limit=2).crawl("snu.ac.kr", ["https://www.snu.ac.kr/"])
    assert len([u for u in web.requested if not u.endswith("robots.txt")]) == 2


def test_faculty_titled_page_without_people_is_ignored():
    site = dict(SITE)
    site["https://pharm.snu.ac.kr/faculty"] = "<title>교수진</title><p>준비중입니다</p>"
    assert _crawler(FakeWeb(site)).crawl("snu.ac.kr", ["https://www.snu.ac.kr/"]) == []


def test_link_scores():
    assert link_score("약학대학", "https://pharm.x.ac.kr/", False)[0] > link_score("대학·대학원", "https://x.ac.kr/c", False)[0]
    assert link_score("교수진", "https://x.ac.kr/f", True)[0] > link_score("약학대학", "https://pharm.x.ac.kr/", False)[0]
    assert link_score("공지사항", "https://pharm.x.ac.kr/n", True)[0] == 0
    assert link_score("경영대학", "https://biz.x.ac.kr/", False)[0] == 0 or not link_score("경영대학", "https://biz.x.ac.kr/", False)[1]


def test_discovery_uses_crawler_and_logs_universities(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(dd, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(dd, "OUTPUT_DIR", tmp_path / "out")
    monkeypatch.setattr(dd, "SERPAPI_KEY", "")
    pd.DataFrame([{"university": "Seoul National University", "name_ko": "서울대학교", "official_domain": "snu.ac.kr"}]).to_csv(
        tmp_path / "data" / "universities_seed.csv", index=False)
    pd.DataFrame([{"source_id": "SNU_PHARM", "university": "Seoul National University", "department": "College of Pharmacy",
                   "faculty_url": "https://pharm.snu.ac.kr/faculty/", "parser": "photo_anchor", "enabled": "yes", "notes": ""}]
                 ).to_csv(tmp_path / "data" / "faculty_sources.csv", index=False)
    site = dict(SITE)
    site["https://pharm.snu.ac.kr/"] += '<a href="/bio-faculty">생명약학 교수소개</a>'
    site["https://pharm.snu.ac.kr/bio-faculty"] = "<title>생명약학 교수소개</title>" + _cards(*PEOPLE[:3])
    crawler = _crawler(FakeWeb(site))

    out = dd.discover_departments(crawler=crawler)
    assert dict(zip(out.department_url, out.accepted)) == {
        "https://pharm.snu.ac.kr/faculty": "known", "https://pharm.snu.ac.kr/bio-faculty": "yes"}
    sources = pd.read_csv(tmp_path / "data" / "faculty_sources.csv", dtype=str)
    assert list(sources.faculty_url)[-1] == "https://pharm.snu.ac.kr/bio-faculty"
    log = pd.read_csv(tmp_path / "data" / "discovery_log.csv", dtype=str)
    assert list(log.university) == ["Seoul National University"]
    # second run: already explored, nothing fetched
    crawler2 = _crawler(FakeWeb(site))
    dd.discover_departments(crawler=crawler2)
    assert crawler2.fetch.requested == []
