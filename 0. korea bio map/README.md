# 0. Korea Bio Map

한국 바이오 교수/PI를 3D 네트워크로 보여주는 About Bio의 데이터 수집 모듈입니다.

## 핵심 원리

- 교수/PI = node
- 공동연구/학문 계보 = link
- score = relationship에서 계산되는 파생값
- 공동연구는 OpenAlex로 자동 수집
- 교수 여부와 advisor/student 관계는 사람 검증을 거침

## 평소에 하는 일

### 1) 교수 seed 추가
`data/professors_seed.csv`에 직접 확인한 교수만 추가합니다.

### 2) GitHub Actions 실행
Actions → **Korea Bio Map Collector** → **Run workflow**

일반 갱신은 mode를 `all`로 둡니다.

이 실행이 자동으로:
1. OpenAlex ID 매칭
2. 논문/공동저자 수집
3. seed 교수끼리 공동연구 관계 생성
4. 한국 소속 공동저자 후보 정리
5. score 계산
6. 3D 웹용 `network-data.js` 생성
7. gh-pages에 최신 지도 배포

까지 수행합니다.

## 후보 교수 검토

자동 수집 결과 중 사람이 볼 파일은:

`output/collaborator_candidates.csv`

입니다.

여기에는 기본적으로:
- 한국 소속 기록이 있고
- 현재 seed 교수들과 공동논문이 2편 이상인
- 우선 검토 후보

만 들어갑니다.

`output/collaborator_candidates_all.csv`에는 전체 공동저자 후보가 남습니다.

### 후보를 실제 교수 DB에 넣는 방법

`data/candidate_approvals.csv`에 승인할 사람을 추가합니다.

예:

```csv
openalex_id,approved,name_ko,name_en,university,department,primary_field,source_url
A1234567890,yes,홍길동,Gildong Hong,Seoul National University,의과대학,면역항암,https://...
```

그 다음 Actions에서 mode를 **promote-and-all**로 실행합니다.

그러면:
1. 승인된 후보에 새 P번호 자동 부여
2. `professors_seed.csv`에 추가
3. 전체 네트워크 재수집
4. 3D 지도 자동 갱신

이 됩니다.

## Academic lineage

지도교수/제자 교수 관계는 `data/relationships_manual.csv`에서 검증 후 넣습니다.

- `advisor_student`: A = 지도교수, B = 현재 교수/PI가 된 제자
- `postdoc_mentor`: A = mentor, B = 현재 교수/PI가 된 postdoc trainee

## 현재 score 규칙

`data/score_rules.csv` (관계마다 PI 쪽 / 제자 쪽 점수를 따로 준다)

| 관계 | PI (A) | 제자·포닥 (B) |
|---|---|---|
| 공동연구 (교수 1명당) | +1 | +1 |
| 지도교수 → 교수/PI가 된 제자 (`advisor_student`) | +10 | +1 |
| 포닥 멘토 → PI가 된 포닥 (`postdoc_mentor`) | +3 | +1 |

- 계보 관계는 `data/relationships_manual.csv`에서 `verified=yes`인 것만 점수에 반영된다.
- 가중치는 `score_rules.csv`에서 바꿀 수 있으며 원본 관계 데이터는 그대로 유지된다.

## 지도 표시

- 공동연구 선: 거의 보이지 않는 흐린 선. 별을 누르면(또는 마우스를 올리면) 그 교수의 공동연구 선만 밝게 강조된다.
- 지도교수 → 제자: 굵은 금색 선 + 화살표 + 흐르는 입자 (PI → 제자 방향).
- 포닥 멘토 → 포닥: 보라색 선 + 화살표 + 흐르는 입자.
- 계보로 이어진 교수들은 서로 가깝게 모이도록 배치된다.
- 오른쪽 위 **검색 · 순위** 탭: 이름(한글/영문)·대학·학과·분야 검색, 종합 점수 / 공동연구 수 / 교수 된 제자 수 순위와 대학 필터. 항목을 누르면 그 별로 이동한다. 모바일에서는 버튼으로 연다.
