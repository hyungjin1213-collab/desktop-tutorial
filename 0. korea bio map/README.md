# 0. Korea Bio Map

한국 바이오 연구자를 **3D 네트워크/은하 지도**로 보여주기 위한 데이터 수집 파이프라인입니다.

핵심 원칙은 단순합니다.

- Professor = node
- Relationship = link
- Score = relationship에서 계산되는 파생값
- 공동연구 관계는 OpenAlex로 최대한 자동화
- 지도교수/제자 교수 관계는 근거가 있는 경우 수동 검증

## 왜 이렇게 나누나?

OpenAlex는 논문과 공동저자를 자동으로 수집하기에 좋지만,
"이 사람이 현재 교수/PI인가", "누구의 박사 제자인가"까지 항상 정확하게 알려주지는 않습니다.

그래서 이 모듈은 **자동 수집 + 사람 검증**을 기본 설계로 합니다.

## 폴더

```text
0. korea bio map/
├── README.md
├── requirements.txt
├── data/
│   ├── professors_seed.csv
│   ├── relationships_manual.csv
│   └── score_rules.csv
├── output/
│   └── .gitkeep
└── src/
    ├── config.py
    ├── openalex_client.py
    ├── pipeline.py
    └── main.py
```

## 1. 교수 입력

`data/professors_seed.csv`에 확인된 교수만 넣습니다.

```csv
professor_id,name_ko,name_en,university,department,primary_field,openalex_id,source_url
P0001,홍길동,Gildong Hong,서울대학교,생명과학부,면역항암,,https://...
```

`openalex_id`를 비워두면 이름 + 소속으로 후보를 찾습니다.
자동 매칭은 편의를 위한 것이므로 결과는 반드시 한 번 확인하는 것을 권장합니다.

## 2. 실행

```bash
cd "0. korea bio map"
pip install -r requirements.txt
python src/main.py all
```

단계별 실행도 가능합니다.

```bash
python src/main.py resolve
python src/main.py collect
python src/main.py build
```

## 3. 자동 생성 결과

`output/`에 다음 파일이 생성됩니다.

- `professors_enriched.csv`: OpenAlex ID가 보강된 교수 DB
- `collaborator_candidates.csv`: seed에 아직 없는 공동저자 후보
- `relationships_auto.csv`: seed 교수끼리 확인된 공동연구 관계
- `relationships.csv`: 자동 공동연구 + 수동 genealogy를 합친 관계 DB
- `network_nodes.csv`: 3d-force-graph node용
- `network_links.csv`: 3d-force-graph link용

## 4. 지도교수/제자 교수 입력

`data/relationships_manual.csv`에 수동으로 넣습니다.

```csv
relationship_id,professor_a_id,professor_b_id,relationship_type,evidence_url,verified,notes
R0001,P0001,P0007,advisor_student,https://...,yes,A가 지도교수 B가 제자 교수
```

방향 규칙:

- `collaboration`: 방향 없음
- `advisor_student`: A = 지도교수, B = 현재 교수/PI가 된 제자
- `postdoc_mentor`: A = mentor, B = 현재 교수/PI가 된 postdoc trainee

## 5. Score

기본값은 `data/score_rules.csv`에서 바꿀 수 있습니다.

- 공동연구 교수 1명: +1
- 교수/PI가 된 제자 1명: +5
- PI가 된 postdoc trainee 1명: +3

점수는 원본으로 입력하지 않습니다.
항상 관계 DB에서 다시 계산합니다.

## 주의

공동저자 후보가 자동으로 "교수"라는 뜻은 아닙니다.
`collaborator_candidates.csv`는 사람이 검토한 뒤 교수 DB에 승격시키는 후보 목록입니다.
