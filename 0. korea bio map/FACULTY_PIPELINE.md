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
