# About Bio

바이오 연구자의 **연구실 선택, 학계 네트워크, 커리어 결정**을 돕는 데이터 기반 프로젝트입니다.

## Modules

```text
About Bio
├── 0. korea bio map/
│   └── 한국 바이오 교수/PI의 공동연구·학문 계보 네트워크
└── 1.lab/
    └── 연구실/교수/연구 분야/skill 데이터
```

### 0. Korea Bio Map

교수를 node, 교수 간 관계를 link로 저장합니다.

- OpenAlex 기반 공동연구 관계 자동 수집
- 지도교수 → 제자 교수 관계 수동 검증
- 관계 종류별 색상
- 관계 DB에서 Academic Network Score 자동 계산
- 향후 3d-force-graph 기반 3D 연구자 은하에 연결

### 1. Lab

기존 About Bio의 LAB → SKILL → JOB 데이터 수집 모듈입니다.

## 데이터 원칙

- 확인 가능한 사실과 About Bio 자체 분석값을 분리합니다.
- 지도교수/제자, 교수 여부처럼 OpenAlex만으로 확정하기 어려운 정보는 자동 확정하지 않습니다.
- 가능한 경우 source URL / source ID를 함께 저장합니다.
- Score는 직접 입력하지 않고 관계 데이터에서 계산합니다.
