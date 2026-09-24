import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from name_extraction import (  # noqa: E402
    english_matches_korean,
    english_query_variants,
    extract_person,
    frequent_hangul_tokens,
    is_korean_person_name,
)

# (card raw_text from earlier scraper output, expected name_ko, expected name_en)
CASES = [
    ("강건욱 교수 강건욱 사이트로 이동 전공 약물학 주소 20-326 연락처 880-7851/880-7855 이메일 kwkang@snu.ac.kr 상세보기", "강건욱", ""),
    ("권용태 교수 융합대사 분자세포", "권용태", ""),
    ("김경수 조교수(겸무) 오믹스-정보의학", "김경수", ""),
    ("김동현 부교수 면역 감염질환", "김동현", ""),
    ("박성준 첨단융합학부 / 의과대학 의과학과 교수 박성준 사이트로 이동 Seongjun Park 전공 바이오전자", "박성준", "Seongjun Park"),
    ("정상택 서울대학교 화학생물공학부 부교수 정상택 사이트로 이동 Sang Taek Jung 전공 항체 및 단백질공학", "정상택", "Sang Taek Jung"),
    ("한주리(Jooli Han) 한주리 사이트로 이동 의과대학 의학과 의공학교실 조교수 전공 바이오기계", "한주리", "Jooli Han"),
    ("교수 이재원 (Jaewon Lee) 상세보기 직책 교수 전화번호 +82-51-510-2805 전공 신경생화학", "이재원", "Jaewon Lee"),
    ("김경임 상세보기 소속 약학과 직위 교수 학위 약학박사(Seoul National University) 연구분야 임상약학", "김경임", ""),
    ("이기영 조교수 more + 영 문 명 Lee Ki Young 소 속 의과대학 보 직 전 화 번 호", "이기영", "Ki Young Lee"),
    ("이원재 조교수 Won Jae Lee wjlee81@catholic.ac.kr 근무지 성의교정 전공 생명과학", "이원재", "Won Jae Lee"),
    ("기창석 교수 기창석 사이트로 이동 Ki, Chang Seok 전공 연질생체고분자 재료", "기창석", "Chang Seok Ki"),
    ("김병식 (Byoung Sik Kim, Ph.D.) 교수", "김병식", "Byoung Sik Kim"),
    ("Won-Suk Chung (정원석) Associate Professor Tel : 042-878-9815 Email : wonsuk.chung@kaist.ac.kr", "정원석", "Won-Suk Chung"),
    ("Jeong, Gi Uk Assistant Professor +82-31-299-6131 giuk@skku.edu", "", "Gi Uk Jeong"),
    ("Kang, Tong Mook Professor +82-31-299-6102 tongmkang@skku.edu", "", "Tong Mook Kang"),
    ("장민정 교수(제약의료규제과학 의대-약대 협동과정 주임교수) mjchang@yonsei.ac.kr", "장민정", ""),
]

NOT_PEOPLE = [
    "바이오엔지니어링 소개 소개 주임교수 인사말 사무실 주소 및 연락처",
    "교수명 직위 최종출신학교 학위명 연구분야 E-mail",
    "커뮤니티 공지사항 교수칼럼 포럼 강의자료실 세미나 서식 행사/소식",
    "YONSEI, The truth will make you free 학장소개 학장인사말 학장단 역대학장",
]


@pytest.mark.parametrize("text,name_ko,name_en", CASES)
def test_extracts_real_cards(text, name_ko, name_en):
    p = extract_person(text)
    assert p.name_ko == name_ko
    if name_en:
        assert p.name_en == name_en


@pytest.mark.parametrize("text", NOT_PEOPLE)
def test_rejects_non_person_cards(text):
    assert not extract_person(text).name_ko


@pytest.mark.parametrize("word", ["분자세포", "융합대사", "면역", "주소", "소개", "전공", "구성원", "부교수", "의과학과", "물공학부", "학장소개"])
def test_field_and_menu_words_are_not_names(word):
    assert not is_korean_person_name(word)


def test_frequent_tags_are_excluded():
    cards = ["권용태 교수 융합대사 분자세포", "강건욱 교수 분자세포 융합대사", "최무림 교수 분자세포", "김범준 교수 감염질환 면역"]
    freq = frequent_hangul_tokens(cards)
    assert "분자세포" in freq and "권용태" not in freq


@pytest.mark.parametrize("en,ko", [
    ("Kyung-Soo Kim", "김경수"), ("Kyungsoo Kim", "김경수"), ("Gyeongsu Kim", "김경수"),
    ("Seongjun Park", "박성준"), ("Sung Joon Park", "박성준"), ("Jaewon Lee", "이재원"),
    ("Sang Taek Jung", "정상택"), ("Won-Suk Chung", "정원석"), ("Yong-Tae Kwon", "권용태"),
    ("Jin Woo Kim", "김진우"), ("Min-Hee Lee", "이민희"), ("Jae-Weon Park", "박재원"),
    ("Hyuk Choi", "최혁"), ("Young-Joon Yoon", "윤영준"), ("Eun Ji Oh", "오은지"),
])
def test_romanization_matching(en, ko):
    assert english_matches_korean(en, ko)


@pytest.mark.parametrize("en,ko", [("Jaewon Lee", "김재원"), ("Minho Park", "박성준")])
def test_romanization_mismatch(en, ko):
    assert not english_matches_korean(en, ko)


def test_query_variants():
    assert english_query_variants("김경수") == ["Kyung-Soo Kim", "Gyeong-Su Kim"]
    assert english_query_variants("박영호") == ["Young-Ho Park", "Yeong-Ho Park"]
    assert english_query_variants("윤여준", "Yoon") == ["Yeo-Jun Yoon"]
    assert english_query_variants("진영원", "Chin")[0] == "Young-Won Chin"


@pytest.mark.parametrize("text,name_ko,name_en", [
    ("조교수 (그린바이오과학전공 전임) 성정열 상세보기 영문이름 Jung Yeol Sung 직급 조교수", "성정열", "Jung Yeol Sung"),
    ("교수 (그린바이오과학전공 전임) 조성근 상세보기 영문이름 Seong-Keun Cho 직급 교수", "조성근", "Seong-Keun Cho"),
    ("Oh, Won Keun Professor Oh, Won Keun 사이트로 이동 Major Pharmacognosy", "", "Won Keun Oh"),
])
def test_more_layouts(text, name_ko, name_en):
    p = extract_person(text)
    assert (p.name_ko, p.name_en) == (name_ko, name_en)


@pytest.mark.parametrize("text", [
    "교육지원 도서관 교수학습센터 학습관리시스템 IT교육센터",
    "박상효 교수팀, 3차원 공간 정밀 이해 AI 기술 개발… ECCV 2026서 발표",
    "연구실 지도교수 위치 연락처 홈페이지",
    "구성원 관악 연건 교수 바이오전자 바이오정보학",
    "Univ. of California, Irvine, Biomedical Engineering, 방문교수 (2009-2010)",
    "학력 및 경력 2016~2017 서울대학교병원 임상조교수",
    "소개 인사말 역대학장 연혁 조직도 교수 및 학생 현황",
])
def test_rejects_news_and_menus(text):
    assert not extract_person(text).name_ko


from name_extraction import english_name_from_email, given_name_initials, surname_from_email  # noqa: E402


@pytest.mark.parametrize("ko,email,en", [
    ("윤여준", "yeojoonyoon@snu.ac.kr", "Yeojoon Yoon"),
    ("김찬혁", "kimchanhyuk@snu.ac.kr", "Chanhyuk Kim"),
    ("노민수", "minsoonoh@snu.ac.kr", "Minsoo Noh"),
    ("이인균", "ingyunlee@snu.ac.kr", "Ingyun Lee"),
    ("진영원", "ywchin@snu.ac.kr", ""),
    ("이병훈", "lee@snu.ac.kr", ""),
])
def test_english_name_from_email(ko, email, en):
    assert english_name_from_email(ko, email) == en


def test_surname_from_email():
    assert surname_from_email("진영원", "ywchin@snu.ac.kr") == "Chin"
    assert surname_from_email("심상희", "sanghee_shim@snu.ac.kr") == "Shim"


def test_given_name_initials():
    assert set(given_name_initials("김경수")) == {"K", "G"}
    assert set(given_name_initials("박영호")) == {"Y"}
    assert set(given_name_initials("이정원")) == {"J", "C"}
