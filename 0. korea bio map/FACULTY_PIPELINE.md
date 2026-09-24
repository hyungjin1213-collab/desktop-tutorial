# About Bio 교수 수집 파이프라인

## 목표

공동저자에서 교수 후보를 추정하는 대신, 공식 대학/학과 홈페이지를 교수의 출발점으로 사용한다.

```text
대학 목록
  ↓
의대 / 약대 / 생명 / 바이오 계열 교수 페이지 탐색
  ↓
공식 교수진 페이지에서 교수 명단 수집
  ↓
ORCID 매칭
  ↓
OpenAlex 저자 ID 매칭
  ↓
신원 신뢰도 분류
  ↓
확정 교수 DB
  ↓
공동논문 / 공동연구 네트워크
  ↓
3D 은하
```

## Step 1. 학과/교수 페이지 찾기

GitHub Actions mode:

`discover-departments`

결과:

`output/department_candidates.csv`

현재 필터 원칙:
- page_title에 교수진 / 교수소개 / 교수 / faculty가 있어야 함
- 보직교수 / 겸임교수 페이지 제외
- 공식 대학 도메인 우선
- 의대 / 약대 / 생명과학 / 생명공학 / 바이오 / 의생명 계열 중심

## Step 2. 교수 정보 수집

GitHub Actions mode:

`scrape-faculty`

결과:

`output/faculty_directory.csv`

주요 컬럼:
- name
- title
- university
- department
- email
- profile_url
- source_page

제외 대상:
- 겸임교수
- 보직교수 페이지
- 초빙교수
- 명예교수
- adjunct / visiting / emeritus
- 학생 / 포닥 / 연구원

## 교수 이름 추출 규칙 (v2, `src/name_extraction.py`)

`scrape-faculty-v2`는 카드 텍스트에서 이름을 다음 조건을 모두 만족할 때만 채택한다.

- 한국 성씨로 시작하는 2~4글자 한글 (`남궁`, `황보` 등 복성 포함)
- 분야 태그 / 메뉴 / 직위 단어가 아님 (`분자세포`, `면역`, `주소`, `소개`, `부교수` …)
- 사람 이름 위치에 있음: `권용태 교수`, `교수 이재원`, `성명: 홍길동`, 또는 카드 첫 단어
- 같은 페이지의 카드 3개 이상에 반복되는 단어가 아님 (분야 태그는 반복되고 이름은 반복되지 않음)
- 뉴스/논문/게시판 항목이 아님 (`교수팀`, `[논문]`, 날짜 등)

영문명은 한글 성씨의 로마자 표기와 맞을 때만 채택하고 `Given Family` 순서로 저장한다
(`Ki, Chang Seok` → `Chang Seok Ki`). 결과 CSV에는 `name_ko`, `name_en`, `name_reason` 컬럼이 추가된다.

사진 카드가 3개 미만인 페이지는 표(`tr`) / 목록(`li`, `dl`) 행도 같이 검사한다.

테스트:

```bash
pip install -r requirements.txt pytest
python -m pytest tests
```

## Step 3. ORCID + OpenAlex 신원 매칭

GitHub Actions mode:

`match-faculty-identities`

결과:

`output/faculty_identity.csv`

주요 컬럼:
- orcid
- orcid_url
- orcid_match_score
- openalex_id
- openalex_name
- openalex_affiliation
- identity_confidence
- identity_status
- identity_reason

판정:
- `high / verified`: 공식 교수 페이지 + ORCID + OpenAlex ORCID 일치
- `medium / probable`: 공식 교수 페이지 + 이름/소속 기반 OpenAlex 일치
- `low / manual_review`: 자동 신원 확정 실패

ORCID Public API credentials가 GitHub Secrets에 있으면 공식 API를 우선 사용한다.
없으면 기존 SERPAPI_KEY로 `orcid.org` 검색을 사용한다.

선택적 GitHub Secrets:
- ORCID_CLIENT_ID
- ORCID_CLIENT_SECRET

### v2 매칭 (`match-faculty-identities-v2`)

OpenAlex 저자명은 영문이므로 한글 이름으로 검색하지 않는다.

- 페이지에 영문명이 있으면 그 이름으로, 없으면 로마자 변환(`김경수` → `Gyeong-Su Kim`, `Gyeongsu Kim`)으로 검색
- 이름 비교는 표기 차이를 흡수 (Kyung/Gyeong, Joon/Jun, Lee/Yi/Rhee, Woo/U …)
- 기관은 현재 소속 + 과거 소속 모두 확인, `KAIST`/`POSTECH`/`UNIST`/`GIST`/`DGIST` 약어 처리
- 같은 학교에 동명이인이 여러 명이면 자동 확정하지 않고 `manual_review` (`ambiguous: …`)

## Step 4. 교수 DB로 가져오기

GitHub Actions mode:

`import-faculty`

현재는 OpenAlex ID가 안정적으로 매칭된 교수만 professors_seed.csv에 추가한다.

네트워크까지 한 번에 다시 만들려면:

`import-faculty-and-all`

## 자주 쓰게 될 순서

처음 학교/학과를 확장할 때:

1. discover-departments
2. scrape-faculty
3. match-faculty-identities
4. faculty_identity.csv 확인
5. import-faculty-and-all

학과 목록이 이미 괜찮다면:

1. scrape-faculty
2. match-faculty-identities
3. import-faculty-and-all

## 한 번에 수집 + 신원매칭

`faculty-full`

이 모드는:
- 학과 탐색
- 교수 수집
- ORCID/OpenAlex 신원 매칭

까지 실행한다. 처음에는 각 단계 결과를 확인하기 위해 개별 실행을 권장한다.
