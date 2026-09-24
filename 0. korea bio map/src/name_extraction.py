"""Professor name extraction and Korean-name romanization helpers.

Faculty pages mix person names with field tags (분자세포, 면역), menu words
(소개, 주소) and titles (부교수). A 2-4 syllable Hangul regex alone cannot
tell them apart, so a name is accepted only when:

1. it starts with a known Korean surname,
2. it is not a known non-name word, and
3. it sits in a person-like position: next to a title (``권용태 교수``,
   ``교수 이재원``) or at the start of the card text.

English names are validated against the romanized surname of the Korean
name, so ``Seoul National`` is never taken as the English name of 서지훈.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Compound surnames first so 남궁민 is split as 남궁 + 민.
COMPOUND_SURNAMES = {
    "남궁": ["Namgung", "Namkung"],
    "황보": ["Hwangbo"],
    "선우": ["Sunwoo", "Seonwoo"],
    "제갈": ["Jegal"],
    "독고": ["Dokgo"],
    "사공": ["Sagong"],
}

SURNAME_ROMANIZATIONS = {
    "김": ["Kim", "Gim"],
    "이": ["Lee", "Yi", "Rhee", "Rhie", "Ri", "I"],
    "박": ["Park", "Pak", "Bak"],
    "최": ["Choi", "Choe", "Chey"],
    "정": ["Jung", "Jeong", "Chung", "Cheong", "Joung"],
    "강": ["Kang", "Gang"],
    "조": ["Cho", "Jo", "Joh", "Choh"],
    "윤": ["Yoon", "Yun"],
    "장": ["Jang", "Chang"],
    "임": ["Lim", "Im", "Yim", "Rim"],
    "림": ["Lim", "Rim"],
    "한": ["Han"],
    "오": ["Oh", "O"],
    "서": ["Seo", "Suh", "Seoh"],
    "신": ["Shin", "Sin"],
    "권": ["Kwon", "Gwon"],
    "황": ["Hwang"],
    "안": ["Ahn", "An"],
    "송": ["Song"],
    "류": ["Ryu", "Yoo", "Yu", "Rhyu", "Ryoo", "Lyu"],
    "유": ["Yoo", "Yu", "Ryu", "You"],
    "홍": ["Hong"],
    "전": ["Jeon", "Jun", "Chun", "Chon", "Jon"],
    "고": ["Ko", "Go", "Koh"],
    "문": ["Moon", "Mun"],
    "양": ["Yang"],
    "손": ["Son", "Sohn"],
    "배": ["Bae", "Pae"],
    "백": ["Baek", "Paik", "Paek", "Baik", "Back"],
    "허": ["Heo", "Huh", "Hur"],
    "남": ["Nam"],
    "심": ["Shim", "Sim"],
    "노": ["Noh", "Roh", "No", "Ro"],
    "하": ["Ha"],
    "곽": ["Kwak", "Gwak"],
    "성": ["Sung", "Seong"],
    "차": ["Cha"],
    "주": ["Joo", "Ju", "Chu", "Choo"],
    "우": ["Woo", "U"],
    "구": ["Koo", "Ku", "Gu", "Goo"],
    "민": ["Min"],
    "진": ["Jin", "Chin"],
    "나": ["Na", "Ra"],
    "라": ["Ra", "La"],
    "지": ["Ji", "Chi"],
    "엄": ["Eom", "Um", "Uhm"],
    "채": ["Chae"],
    "원": ["Won"],
    "천": ["Cheon", "Chun", "Chon"],
    "방": ["Bang"],
    "공": ["Kong", "Gong"],
    "현": ["Hyun", "Hyeon"],
    "함": ["Ham"],
    "변": ["Byun", "Byeon", "Pyun"],
    "염": ["Yeom", "Yum", "Youm"],
    "여": ["Yeo", "Yuh", "Yeu"],
    "추": ["Choo", "Chu"],
    "도": ["Do", "Doh", "Toh"],
    "소": ["So"],
    "석": ["Seok", "Suk"],
    "선": ["Sun", "Seon"],
    "설": ["Seol", "Sul"],
    "마": ["Ma"],
    "길": ["Gil", "Kil"],
    "연": ["Yeon", "Youn", "Yun"],
    "위": ["Wi", "Wee"],
    "표": ["Pyo"],
    "명": ["Myung", "Myeong"],
    "기": ["Ki", "Gi"],
    "반": ["Ban"],
    "왕": ["Wang"],
    "금": ["Keum", "Geum", "Kum"],
    "옥": ["Ok"],
    "육": ["Yuk", "Yook"],
    "인": ["In"],
    "맹": ["Maeng"],
    "제": ["Je"],
    "모": ["Mo"],
    "탁": ["Tak"],
    "국": ["Kook", "Guk", "Kuk"],
    "은": ["Eun"],
    "편": ["Pyun", "Pyeon"],
    "용": ["Yong"],
    "예": ["Ye"],
    "경": ["Kyung", "Gyeong"],
    "봉": ["Bong"],
    "사": ["Sa"],
    "부": ["Boo", "Bu"],
    "피": ["Pi", "Pee"],
    "빈": ["Bin"],
    "태": ["Tae"],
    "어": ["Eo"],
    "견": ["Kyun", "Gyeon"],
    "계": ["Kye", "Gye"],
    "두": ["Doo", "Du"],
    "탄": ["Tan"],
    "호": ["Ho"],
    "범": ["Bum", "Beom"],
    "시": ["Si", "Shi"],
    "형": ["Hyung", "Hyeong"],
    "승": ["Seung"],
    "상": ["Sang"],
    "갈": ["Gal", "Kal"],
    "가": ["Ka", "Ga"],
    "간": ["Kan", "Gan"],
    "감": ["Kam", "Gam"],
    "음": ["Eum"],
    "판": ["Pan"],
    "평": ["Pyung", "Pyeong"],
    "화": ["Hwa"],
    "당": ["Dang"],
    "대": ["Dae"],
    "동": ["Dong"],
    "묵": ["Muk"],
    "빙": ["Bing"],
    "야": ["Ya"],
    "요": ["Yo"],
    "운": ["Woon", "Un"],
    "즙": ["Jeup"],
    "초": ["Cho"],
    "춘": ["Chun"],
    "쾌": ["Kwae"],
    "흥": ["Heung"],
}
SURNAMES_BY_LENGTH = sorted(
    list(COMPOUND_SURNAMES) + list(SURNAME_ROMANIZATIONS), key=len, reverse=True,
)
ALL_ROMANIZATIONS = {**SURNAME_ROMANIZATIONS, **COMPOUND_SURNAMES}

# Words that look like 2-4 syllable Hangul names but are page furniture,
# titles or research-field tags. Every entry below was seen as a "name" in
# earlier scraper output or starts with a common surname character.
NON_NAME_WORDS = {
    # titles / roles
    "교수", "정교수", "부교수", "조교수", "명예교수", "석좌교수", "겸임교수", "겸직교수",
    "초빙교수", "연구교수", "기금교수", "임상교수", "강의교수", "주임교수", "교수진",
    "교수명", "교수소개", "교수님", "전임교수", "학장", "부학장", "학과장", "원장", "센터장",
    "주임", "석좌", "전임", "겸무", "겸직", "특임", "산학", "기금", "임상", "명예", "초빙", "겸임",
    "연구원", "구성원", "직원", "조교", "행정실", "사무실", "대학원생", "박사후", "연구소",
    # menu / layout
    "소개", "인사말", "학장소개", "학과소개", "대학소개", "주소", "연락처", "전화", "전화번호",
    "이메일", "메일", "홈페이지", "사이트", "상세보기", "더보기", "전체", "목록", "검색",
    "공지", "공지사항", "뉴스", "소식", "커뮤니티", "게시판", "자료실", "오시는길", "찾아오시는길", "도서관", "교수팀", "조직도", "연혁",
    "관악", "연건", "학력", "경력", "석학", "지도", "방문", "대우", "특임",
    "연구", "연구실", "연구분야", "교육", "입학", "학부", "대학원", "전공", "세부전공", "소속",
    "소속교실", "직위", "직책", "학위", "위치", "사진", "이름", "성명", "근무지", "기타",
    "인하소식", "인하알림", "행사", "세미나", "강의", "강의자료", "서식", "로그인", "사이트맵",
    "정보", "이전", "다음", "처음", "마지막", "닫기", "메뉴", "바로가기", "본문", "하단",
    # departments / fields
    "의과학과", "의학과", "약학과", "생명과학", "생명공학", "바이오", "바이오엔지니어링",
    "의공학", "약리학", "생리학", "생화학", "병리학", "해부학", "미생물학", "면역", "면역학",
    "분자세포", "융합대사", "감염질환", "오믹스", "정보의학", "신경과학", "유전학", "종양학",
    "약제학", "임상약학", "예방약학", "독성학", "천연물", "의약화학", "분자생물학", "세포생물학",
    "구조생물학", "생물정보", "생물정보학", "화학", "물리", "수학", "공학", "의학", "약학",
    "간호학", "치의학", "한의학", "수의학", "식품", "영양", "환경", "재료", "기계", "전자",
    "화학생물공학부", "첨단융합학부", "물공학부", "생명과학부", "생명과학과", "생명공학과",
    "신경", "생리", "대사", "유전체", "단백질", "항체", "세포", "분자", "조직", "발생",
    "진화", "생태", "식물", "동물", "미생물", "바이러스", "암", "종양", "면역항암",
}

TITLE_WORDS = [
    "명예교수", "석좌교수", "겸임교수", "겸직교수", "초빙교수", "연구교수", "기금교수",
    "임상교수", "강의교수", "정교수", "부교수", "조교수", "교수",
]
EXCLUDED_TITLES = {"명예교수", "겸임교수", "초빙교수", "연구교수", "강의교수", "기금교수"}
EN_TITLE_RE = re.compile(
    r"(?:Distinguished\s+|Full\s+|Associate\s+|Assistant\s+|Adjunct\s+|Visiting\s+|"
    r"Research\s+|Emeritus\s+|Clinical\s+)?Professor",
    re.I,
)

HANGUL_NAME = r"[가-힣]{2,4}"
# News items, paper lists and board posts mention professors but are not
# faculty cards.
NON_CARD_RE = re.compile(
    r"교수팀|연구팀|\[(?:학술지)?논문\]|\[학술발표\]|\b20\d\d[.-]\d\d[.-]\d\d\b|\b\d\d-\d\d-\d\d\s*$"
)
EN_WORD = r"[A-Z][a-z]+(?:-[A-Za-z][a-z]*)?"
EN_NAME_PATTERNS = [
    # "Lee, Seunghee" / "Jeong, Gi Uk" / "Ki, Chang Seok"
    re.compile(rf"\b(?P<last>{EN_WORD}),\s*(?P<first>{EN_WORD}(?:\s+{EN_WORD})?)"),
    # "Seongjun Park" / "Won-Suk Chung" / "Sang Taek Jung"
    re.compile(rf"\b(?P<first>{EN_WORD}(?:\s+{EN_WORD})?)\s+(?P<last>{EN_WORD})\b"),
    # Korean order: "Lee Ki Young"
    re.compile(rf"\b(?P<last>{EN_WORD})\s+(?P<first>{EN_WORD}(?:\s+{EN_WORD})?)\b"),
]
EN_NOISE = {
    "professor", "assistant", "associate", "full", "adjunct", "visiting", "research",
    "emeritus", "clinical", "distinguished", "tel", "email", "fax", "office", "major",
    "contact", "lab", "laboratory", "university", "college", "school", "department",
    "seoul", "national", "institute", "science", "technology", "medicine", "medical",
    "pharmacy", "korea", "korean", "ph", "phd", "md", "dr", "more", "information",
    "homepage", "site", "profile", "view", "the", "of", "and", "center",
}


@dataclass
class PersonName:
    name_ko: str = ""
    name_en: str = ""
    title: str = ""
    confidence: str = "low"
    reason: str = ""

    @property
    def display(self) -> str:
        return self.name_ko or self.name_en

    @property
    def ok(self) -> bool:
        return bool(self.display)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def split_korean_name(name: str) -> tuple[str, str]:
    for surname in SURNAMES_BY_LENGTH:
        if name.startswith(surname) and len(name) > len(surname):
            return surname, name[len(surname):]
    return "", name


def is_korean_person_name(token: str) -> bool:
    token = _clean(token)
    if not re.fullmatch(HANGUL_NAME, token) or token in NON_NAME_WORDS:
        return False
    if any(token.endswith(t) for t in ("교수", "학과", "학부", "대학", "센터", "교실", "전공")):
        return False
    surname, given = split_korean_name(token)
    return bool(surname) and 1 <= len(given) <= 2


# ---------------------------------------------------------------- romanization
_INITIALS = ["g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "", "j", "jj", "ch", "k", "t", "p", "h"]
_VOWELS = ["a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa", "wae", "oe", "yo",
           "u", "wo", "we", "wi", "yu", "eu", "ui", "i"]
_FINALS = ["", "k", "k", "k", "n", "n", "n", "t", "l", "k", "m", "l", "l", "l", "p", "l",
           "m", "p", "p", "t", "t", "ng", "t", "t", "k", "t", "p", "t"]


def romanize_syllable(ch: str) -> str:
    code = ord(ch) - 0xAC00
    if not 0 <= code < 11172:
        return ch
    initial, rest = divmod(code, 588)
    vowel, final = divmod(rest, 28)
    return _INITIALS[initial] + _VOWELS[vowel] + _FINALS[final]


def romanize_given_name(given: str) -> str:
    """Revised Romanization, syllable by syllable, e.g. 경수 -> Gyeongsu."""
    return "".join(romanize_syllable(c) for c in given).capitalize()


def surname_romanizations(name_ko: str) -> list[str]:
    surname, _ = split_korean_name(name_ko)
    return ALL_ROMANIZATIONS.get(surname, [])


def english_query_variants(name_ko: str) -> list[str]:
    """Search strings for OpenAlex when the page has no English name."""
    surname, given = split_korean_name(name_ko)
    if not surname or not given:
        return []
    romans = ALL_ROMANIZATIONS.get(surname, [])[:1]
    parts = [romanize_syllable(c).capitalize() for c in given]
    return [f"{'-'.join(parts)} {r}" for r in romans] + [f"{''.join(parts).capitalize()} {r}" for r in romans]


def phonetic_key(text: str) -> str:
    """Collapse common Korean-romanization spelling differences.

    Kyung/Gyeong, Joon/Jun, Seok/Suk, Hyun/Hyeon all map to the same key.
    """
    s = re.sub(r"[^a-z]", "", (text or "").casefold())
    for a, b in [("weo", "wo"), ("eo", "u"), ("oo", "u"), ("ou", "u"), ("ee", "i"),
                 ("ui", "i"), ("ea", "a"), ("wu", "u"), ("wo", "w"),
                 ("sh", "s"), ("ch", "j"), ("k", "g"), ("p", "b"),
                 ("t", "d"), ("r", "l"), ("yu", "u"), ("y", "")]:
        s = s.replace(a, b)
    s = re.sub(r"(.)\1+", r"\1", s)
    return s.replace("e", "")


def english_matches_korean(name_en: str, name_ko: str) -> bool:
    """True when an English name is a plausible romanization of name_ko."""
    surname, given = split_korean_name(name_ko)
    if not surname:
        return False
    tokens = [t for t in re.split(r"[\s,.]+", name_en or "") if t]
    romans = {r.casefold() for r in ALL_ROMANIZATIONS.get(surname, [])}
    for i, tok in enumerate(tokens):
        if tok.casefold() in romans:
            rest = "".join(tokens[:i] + tokens[i + 1:])
            if not rest:
                continue
            return phonetic_key(rest) == phonetic_key(romanize_given_name(given))
    return False


# ------------------------------------------------------------------ extraction
def _title_in(text: str) -> str:
    for t in TITLE_WORDS:
        if t in text:
            return t
    m = EN_TITLE_RE.search(text)
    return m.group(0) if m else ""


def _korean_candidates(text: str) -> list[tuple[str, str, int]]:
    """(name, reason, score) for each Hangul token in a person-like position."""
    out: list[tuple[str, str, int]] = []
    title_alt = "|".join(TITLE_WORDS)
    # 1) name before a title: "권용태 교수", "김경수 조교수(겸무)". A separator
    #    is required so compounds (지도교수, 임상조교수) are not split.
    # The title must end the word, so 교수학습센터 / 교수팀 do not count.
    for m in re.finditer(rf"(?<![가-힣])({HANGUL_NAME})(?:\s*\([^)]{{0,40}}\)\s*|\s+)(?:{title_alt})(?![가-힣])", text):
        out.append((m.group(1), "name before title", 3))
    # 2) title then name: "교수 이재원 (Jaewon Lee)", "조교수 (OO전공 전임) 성정열"
    for m in re.finditer(rf"(?<![가-힣])(?:{title_alt})\s*(?:\([^)]{{0,40}}\))?\s+({HANGUL_NAME})(?=\s|\(|$)", text):
        out.append((m.group(1), "title before name", 2))
    # 3) first token of the card: "김경임 상세보기 소속 약학과 ..."
    m = re.match(rf"\s*({HANGUL_NAME})(?=[\s(]|$)", text)
    if m:
        out.append((m.group(1), "first token", 2))
    # 4) labelled field: "성명 홍길동", "이름: 홍길동"
    for m in re.finditer(rf"(?:성명|이름|교수명)\s*[:：]?\s*({HANGUL_NAME})(?=\s|\(|$)", text):
        out.append((m.group(1), "labelled", 3))
    return out


def _english_candidates(text: str) -> list[str]:
    found: list[str] = []
    for pat in EN_NAME_PATTERNS:
        for m in pat.finditer(text):
            first, last = m.group("first"), m.group("last")
            words = f"{first} {last}".split()
            if any(w.casefold() in EN_NOISE for w in words):
                continue
            found.append(f"{first} {last}")
    return list(dict.fromkeys(found))


def _english_only(text: str) -> tuple[str, str]:
    """For English pages: 'Jeong, Gi Uk Assistant Professor' -> 'Gi Uk Jeong'."""
    m = re.search(rf"\b({EN_WORD}),\s*({EN_WORD}(?:\s+{EN_WORD})?)\s+(?={EN_TITLE_RE.pattern})", text)
    if m and not {w.casefold() for w in (m.group(1) + " " + m.group(2)).split()} & EN_NOISE:
        return f"{m.group(2)} {m.group(1)}", "Last, First before title"
    m = re.match(rf"\s*({EN_WORD}(?:\s+{EN_WORD}){{1,2}})\s*(?:\(([가-힣]{{2,4}})\))?", text)
    if m:
        words = m.group(1).split()
        # Stop at the first noise word ("Seunghee Professor Lee" -> keep nothing).
        if not {w.casefold() for w in words} & EN_NOISE:
            return m.group(1), "leading English name"
    return "", ""


def extract_person(text: str, frequent_tokens: set[str] | None = None) -> PersonName:
    """Extract a professor's name from one card's text.

    frequent_tokens: Hangul tokens that repeat across many cards on the same
    page (field tags, menu words). They are never accepted as names.
    """
    text = _clean(text)
    frequent_tokens = frequent_tokens or set()
    title = _title_in(text)
    if NON_CARD_RE.search(text):
        return PersonName(title=title, reason="news/paper/board item")

    scored: dict[str, tuple[int, str]] = {}
    for name, reason, score in _korean_candidates(text):
        if not is_korean_person_name(name) or name in frequent_tokens:
            continue
        prev = scored.get(name, (0, ""))
        scored[name] = (prev[0] + score, prev[1] or reason)

    name_ko = ""
    reason = ""
    if scored:
        name_ko, (score, reason) = max(scored.items(), key=lambda kv: kv[1][0])

    name_en = ""
    if name_ko:
        for cand in _english_candidates(text):
            if english_matches_korean(cand, name_ko) or _surname_matches(cand, name_ko):
                name_en = _to_given_family(cand, name_ko)
                break
    else:
        name_en, reason = _english_only(text)
        # "Won-Suk Chung (정원석)" gives us the Korean name too.
        m = re.search(r"\(([가-힣]{2,4})\)", text[:80])
        if name_en and m and is_korean_person_name(m.group(1)):
            name_ko = m.group(1)

    if not (name_ko or name_en):
        return PersonName(title=title, reason="no person-like name")

    confidence = "low"
    if title and (reason in {"name before title", "title before name", "labelled"} or name_en):
        confidence = "high"
    elif title or name_en:
        confidence = "medium"
    return PersonName(name_ko, name_en, title, confidence, reason)


def _surname_matches(name_en: str, name_ko: str) -> bool:
    romans = {r.casefold() for r in surname_romanizations(name_ko)}
    toks = [t.casefold() for t in re.split(r"[\s,]+", name_en) if t]
    return bool(toks) and (toks[0] in romans or toks[-1] in romans) and len(toks) >= 2


def _to_given_family(name_en: str, name_ko: str) -> str:
    """Normalise to 'Given Family' order, the order OpenAlex uses."""
    romans = {r.casefold() for r in surname_romanizations(name_ko)}
    toks = [t for t in re.split(r"[\s,]+", name_en) if t]
    if toks and toks[0].casefold() in romans and toks[-1].casefold() not in romans:
        toks = toks[1:] + toks[:1]
    return " ".join(toks)


def frequent_hangul_tokens(card_texts: list[str], min_cards: int = 3) -> set[str]:
    """Hangul tokens present in at least min_cards cards (tags, menu words).

    A real professor's name appears in one card; a field tag such as
    분자세포 shows up in many.
    """
    counts: dict[str, int] = {}
    for text in card_texts:
        for tok in set(re.findall(HANGUL_NAME, text or "")):
            counts[tok] = counts.get(tok, 0) + 1
    limit = max(min_cards, 3)
    return {t for t, c in counts.items() if c >= limit}
