# 합성 측정 예제

여기의 파일은 파이프라인 검증을 위해 만든 데이터입니다. 실제 실험 결과가 아닙니다.

| 파일 | 검증용 구성 |
|---|---|
| device=DEMO_measurement=synthetic.csv | 메타데이터 2행, nA 단위, Vg=0/2 V, 각 정·역스윕 |
| device=DEMO_multisheet.xlsx | 메타데이터 시트 1개와 측정 시트 2개, 첫 측정 헤더는 3행 |
| device=DEMO_vg=0_legacy.xls | 실제 구형 Excel BIFF 형식, 21점의 sinh 곡선 |

`demo/vault`에서 연구노트와 주간 보고의 실제 생성 결과를 확인할 수 있습니다. Windows 설치 스크립트의 `-RunDemo`는 이 폴더와 별개인 `demo-runtime`에서 실행되므로 실측 Vault에 샘플을 섞지 않습니다.
