# Korea Bio Map Web Prototype

현재 seed 교수 5명의 실제 자동수집 결과를 사용한 3D-force-graph 예시입니다.

## 로컬 실행

브라우저에서 파일을 직접 여는 것보다 간단한 로컬 서버 사용을 권장합니다.

```bash
cd "0. korea bio map/web"
python -m http.server 8000
```

그다음 http://localhost:8000 접속.

## 다음 단계

- network_nodes.csv / network_links.csv를 자동으로 network-data.js로 변환
- 교수 검색
- 클릭 시 이웃만 강조
- advisor_student / postdoc_mentor 색상 분리
- score에 따른 노드 크기 조절
