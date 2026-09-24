import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from faculty_scraper_v2 import parse_photo_anchor  # noqa: E402

URL = "http://biomed.snu.ac.kr/research-faculty/faculty"


def _card(name, title, tags, idx):
    tag_html = "".join(f"<span class='tag'>{t}</span>" for t in tags)
    return (
        f"<li class='item'><a href='?mode=view&profidx={idx}'>"
        f"<img src='/webdata/faculty/fulltime/p{idx}.jpg' width='120' height='160'></a>"
        f"<div><strong>{name}</strong> <em>{title}</em>{tag_html}</div></li>"
    )


def test_card_page_with_field_tags():
    # Field tags come before the name in the DOM, the layout that used to
    # produce names like 분자세포 / 융합대사.
    people = [
        ("강건욱", "교수", ["분자세포", "융합대사"]),
        ("권용태", "교수", ["융합대사", "분자세포"]),
        ("김경수", "조교수(겸무)", ["오믹스-정보의학"]),
        ("김동현", "부교수", ["면역", "감염질환"]),
        ("김범준", "교수", ["감염질환", "면역"]),
        ("최무림", "교수", ["오믹스-정보의학"]),
    ]
    html = "<html><body><nav>소개 교수진 주소</nav><ul>" + "".join(
        _card(n, t, tags, i) for i, (n, t, tags) in enumerate(people)
    ) + "</ul><footer>주소 서울 종로구</footer></body></html>"
    rows = parse_photo_anchor(html, URL, "Seoul National University", "Biomedical Sciences", "SNU_BIOMED")
    assert [r["name"] for r in rows] == [n for n, _, _ in people]
    assert rows[0]["profile_url"].endswith("profidx=0")


def test_table_page_without_photos():
    html = """<table>
      <tr><th>교수명</th><th>직위</th><th>연구분야</th><th>E-mail</th></tr>
      <tr><td>이재원</td><td>교수</td><td>신경생화학</td><td>neuron@pusan.ac.kr</td></tr>
      <tr><td>김민수</td><td>부교수</td><td>약물학</td><td>mskim@pusan.ac.kr</td></tr>
      <tr><td>박지은</td><td>명예교수</td><td>약제학</td><td>jepark@pusan.ac.kr</td></tr>
    </table>"""
    rows = parse_photo_anchor(html, "https://pharm.pusan.ac.kr/faculty", "Pusan National University", "Pharmacy", "PNU")
    assert [(r["name"], r["email"]) for r in rows] == [
        ("이재원", "neuron@pusan.ac.kr"),
        ("김민수", "mskim@pusan.ac.kr"),
    ]


def test_english_card_page():
    html = "".join(
        f"<div class='prof'><img src='/img/{i}.jpg'><p>{t}</p><a href='/p/{i}'>view</a></div>"
        for i, t in enumerate([
            "Won-Suk Chung (정원석) Associate Professor Tel : 042-878-9815 Email : wonsuk.chung@kaist.ac.kr",
            "Jin Woo Kim (김진우) Professor Tel : 042-350-2641 Email : jinwoo@kaist.ac.kr",
            "Walton Jones (월튼 존스) Retired Professor Tel : Email : Lab :",
        ])
    )
    rows = parse_photo_anchor(html, "https://bio.kaist.ac.kr/faculty", "KAIST", "Biological Sciences", "KAIST_BIO")
    assert [(r["name_ko"], r["name_en"]) for r in rows] == [("정원석", "Won-Suk Chung"), ("김진우", "Jin Woo Kim")]


def test_enrich_from_profile_page_and_email():
    from faculty_scraper_v2 import enrich_from_profiles

    page = "http://biomed.snu.ac.kr/research-faculty/faculty"
    rows = [
        {"name_ko": "김경수", "name_en": "", "email": "", "source_page": page,
         "profile_url": page + "?mode=view&profidx=71"},
        {"name_ko": "윤여준", "name_en": "", "email": "yeojoonyoon@snu.ac.kr", "source_page": page,
         "profile_url": "https://lab.example.com"},
    ]
    pages = {rows[0]["profile_url"]: "<h2>김경수 조교수</h2><p>Kyung-Soo Kim</p><p>E-mail: kskim@snu.ac.kr</p>"}
    enrich_from_profiles(rows, fetch=lambda url: pages[url])
    assert (rows[0]["name_en"], rows[0]["email"], rows[0]["name_en_source"]) == ("Kyung-Soo Kim", "kskim@snu.ac.kr", "profile_page")
    assert (rows[1]["name_en"], rows[1]["name_en_source"]) == ("Yeojoon Yoon", "email")
