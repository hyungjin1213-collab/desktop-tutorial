# About Bio 교수 수집 파이프라인

## 한 번에 실행: `galaxy-full`

Actions → **Korea Bio Map Collector** → mode `galaxy-full`

```text
대학 목록 (data/universities_seed.csv, 의대·약대·바이오 학과가 있는 56개 대학)
  ↓ discover-departments   대학 홈페이지를 직접 탐색해 바이오/의약/약학 교수진 페이지 → data/faculty_sources.csv 자동 추가
  ↓ scrape-faculty-v2      교수 이름(한글) + 영문명(목록 → 상세 페이지 → 이메일) + 이메일
  ↓ match-faculty-identities-v2   ORCID → OpenAlex 신원 확정 (동명이인 구분)
  ↓ import-faculty-v2      verified / probable 교수를 professors_seed.csv에 추가 (ORCID 기준 중복 제거)
  ↓ all                    OpenAlex 공동논문 → 교수 간 선 → 3D 은하 → gh-pages 배포
```

- 신원 매칭은 한 번에 `IDENTITY_BATCH_LIMIT`(기본 800)명씩 처리한다. 교수가 더 많으면 `galaxy-full`을 다시 실행하면 이어서 처리한다.
- 학과 탐색은 **검색 API 없이** 각 대학 공식 홈페이지를 직접 탐색한다 (`src/site_crawler.py`).
  - `약학대학`·`의과대학`·`생명과학` 같은 링크를 먼저 따라가고, 그 안의 `교수진`·`교수소개` 링크를 찾는다.
  - 교수 이름 추출기로 실제 교수가 3명 이상 나오는 페이지만 수집 대상으로 인정한다.
  - 대학 도메인 밖, 경영·간호 등 비바이오 단과대, 공지/입학/명예교수 링크, PDF는 따라가지 않는다. robots.txt를 지킨다.
  - 한 번 실행에 `DISCOVERY_UNIVERSITY_LIMIT`(기본 20)개 대학, 대학당 최대 `CRAWL_PAGE_LIMIT`(기본 100) 페이지.
  - 탐색한 대학은 `data/discovery_log.csv`에 기록되어 다음 실행에서 건너뛴다 (`DISCOVERY_REFRESH=yes`로 재탐색, 또는 해당 행 삭제).
  - 자바스크립트 메뉴(`onclick="goPage(...)"`), iframe/frame, meta refresh 링크도 따라간다.
  - 홈페이지 메뉴를 못 읽어도 되도록 `pharm.`, `medicine.`, `bio.`, `life.` 같은 단과대학 서브도메인을 직접 시도한다.
  - 인증서 체인이 불완전한 대학 사이트는 (공개 페이지 읽기에 한해) 인증서 검증 없이 재시도한다.
  - 교수진 페이지를 찾으면 그 안의 교수별 상세 링크는 따라가지 않는다 (페이지 한도 절약).
  - 대학마다 로그에 `N pages fetched; M faculty-like pages checked; errors: …`가 찍히고 `discovery_log.csv`의 `note`에 남는다. 0건이면 이것으로 원인을 본다.
  - 0건이었던 대학은 다음 실행에서 새 대학을 먼저 탐색한 뒤 재시도한다.
  - SerpAPI 보조 검색은 기본으로 끈다 (`DISCOVERY_USE_SERPAPI=yes`로 켬). 429가 한 번 나면 그 실행에서는 더 쓰지 않는다.
- 잘못 들어간 수집 페이지는 `data/faculty_sources.csv`에서 `enabled`를 `no`로 바꾼다.
- 선택 GitHub Secrets: `OPENALEX_EMAIL`(요청 속도 향상, 권장), `OPENALEX_API_KEY`, `SCOPUS_API_KEY`/`SCOPUS_INSTTOKEN`, `ORCID_CLIENT_ID`/`ORCID_CLIENT_SECRET`(없어도 ORCID 공개 검색은 동작).

## 동명이인 구분 (신원 판정)

| 상태 | 조건 | DB 추가 |
|---|---|---|
| `verified` | ORCID 공개 이메일 = 교수 페이지 이메일, 또는 해당 기관에 그 이름의 ORCID가 하나뿐, 또는 여러 ORCID 중 OpenAlex(이름+기관+분야)가 정확히 하나를 고름 | O |
| `probable` | ORCID 없음. OpenAlex에서 해당 기관(현재/과거)의 같은 이름이 한 명이고 논문 주제가 주로 생명·보건 분야 | O (`IMPORT_IDENTITY_STATUSES`로 조정) |
| `manual_review` | 같은 기관 동명이인 구분 불가, 후보 없음, 비바이오 분야 | X |

ORCID가 확정되면 OpenAlex는 ORCID로 조회하므로 한 사람이 OpenAlex에 여러 프로필로 쪼개져 있어도 모두 모아
`openalex_id`에 `A1;A2` 형태로 저장하고, 공동연구 계산에 전부 사용한다.

## 공동연구 선 (협업 강도)

같이 쓴 논문 수가 아니라 **협업 강도**로 선을 긋는다 (`collaboration_weight` in `src/pipeline.py`).

- 논문 1편의 기여 = `1 / (저자 수 - 1)`: 3인 논문 0.5, 90인 다기관 임상 논문 0.011
- 두 교수가 모두 1저자/마지막 저자(연구실 대 연구실)면 x1.5
- 최근 2년 논문은 그대로, 그 이전은 8년마다 절반
- 강도 합이 `MIN_COLLAB_STRENGTH`(기본 0.5) 이상인 쌍만 선을 긋는다
  (최근 소규모 논문 1편, 5인 논문 2편, 10인 논문 약 5편 수준)
- `relationships_auto.csv`에 `collaboration_strength`, `first_year`, `last_year`가 남고,
  지도에서는 강도에 따라 선 밝기/굵기가 달라진다. 선에 마우스를 올리면 논문 수·최근 연도·강도가 보인다.

## 매일 자동 실행

`.github/workflows/korea-bio-map-daily.yml`이 매일 10:00 KST(01:00 UTC)에 `galaxy-full`을 시작한다.
GitHub 예약 실행은 기본 브랜치(`main`)의 워크플로만 돌리므로 **이 파일은 main에 있어야 한다.**
수집 워크플로는 `concurrency`로 동시에 한 번만 돈다.

## 공동연구 데이터 출처

- **OpenAlex** (기본, 무료): Crossref·PubMed·ORCID 통합.
- **Scopus** (선택): GitHub Secrets에 `SCOPUS_API_KEY`가 있으면 추가로 사용한다.
  - 저자 ID는 ORCID로 찾고, 없으면 영문명+소속으로 찾되 한 명일 때만 채택한다. 결과는 `data/scopus_author_cache.csv`에 저장해 다시 조회하지 않는다.
  - 같은 논문은 DOI로 합쳐서 한 번만 센다. 관계 `notes`에 `OpenAlex + Scopus` / `Scopus`처럼 출처가 남는다.
  - 논문의 전체 저자 목록(COMPLETE view)은 **기관 구독 권한**이 있어야 받을 수 있다. GitHub Actions는 학교 네트워크 밖이므로 `SCOPUS_INSTTOKEN`(기관 토큰)도 필요하다. 권한이 없으면 한 번 경고하고 OpenAlex만으로 계속 진행한다.
  - Scopus 할당량은 주 단위이므로 한 번 실행에 `SCOPUS_REQUEST_LIMIT`(기본 3000)건까지만 요청한다.
- Google Scholar·ResearchGate는 공식 API가 없고 자동 수집이 약관상 금지되어 사용하지 않는다.
- 저자 100명을 넘는 컨소시엄 논문은 공동연구로 치지 않는다 (`MAX_AUTHORS_PER_WORK`).

---

## (참고) 단계별 상세

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
