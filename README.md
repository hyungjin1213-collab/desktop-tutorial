# About Bio

바이오 연구자의 **연구실 선택과 커리어 결정**을 돕는 데이터 기반 플랫폼입니다.

## 핵심 구조

**LAB → SKILL → JOB**

연구실의 공개 정보와 논문 데이터를 수집해 다음을 연결합니다.

- 연구실 / 교수 정보
- 연구 분야
- 핵심 실험 및 분석 기술
- 논문 생산성
- 관련 산업 분야
- 관련 직무와 커리어 경로

## v0.1 목표

교수명과 소속을 입력하면 공개 데이터를 기반으로 다음 정보를 수집합니다.

1. 교수 기본 정보
2. OpenAlex 기반 논문 목록
3. 최근 연구 주제
4. 주요 skill 키워드
5. CSV 형태의 정형 데이터

## 프로젝트 구조

```text
.
├── README.md
├── requirements.txt
├── .gitignore
├── data/
│   └── labs.csv
├── output/
│   └── .gitkeep
├── src/
│   ├── __init__.py
│   ├── config.py
│   ├── main.py
│   ├── collectors/
│   │   ├── __init__.py
│   │   └── openalex.py
│   └── analysis/
│       ├── __init__.py
│       └── skill_extractor.py
└── tests/
    └── __init__.py
```

## 데이터 원칙

- 확인 가능한 사실과 About Bio 자체 분석값을 분리합니다.
- 졸업기간, 급여, 졸업생 진로처럼 근거가 부족한 값은 임의로 추정하지 않습니다.
- 가능한 경우 source URL / source ID를 함께 저장합니다.
