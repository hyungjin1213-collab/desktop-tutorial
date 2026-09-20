# 1. Lab

About Bio의 연구실/교수 데이터 수집 모듈입니다.

## 현재 목표

교수명과 소속을 입력하면 공개 학술 데이터를 기반으로 연구자 후보를 찾고,
향후 LAB → SKILL → JOB 연결에 사용할 정형 데이터를 만듭니다.

## 구조

```text
1.lab/
├── README.md
├── requirements.txt
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
