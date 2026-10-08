# v1.8.0 — 모든 branch의 관측 수치 검토 (로컬)

기존 계산식과 QC 문턱을 보존하면서 별도의 관측 추출과 보고서를 추가했습니다. 이전 버전 결과와 사용자 노트를 덮어쓰지 않습니다.

GUI에서 작업 목록의 파일을 선택하고 **선택 측정 수치 검토**를 누르세요. 모든 gate/branch의 핵심 수치와 signed 원본 곡선, 평가 전압별 RR, 창 폭별 gm을 브라우저에서 엽니다. 계산 근거 패널에서 branch를 바꾼 뒤 **모든 지표와 원본 점 보기**를 눌러 지표를 선택할 수 있습니다.

CLI는 `runtime\python.exe -m research_automation --config qa-config.json observe --source "한글 폴더/파일.xls"`입니다. 여러 파일은 `--source`를 반복하고, Inbox 전체 검토는 명시적으로 `--all`을 사용합니다. 기존 Vault·노트·DB를 수정하지 않고 `analysis/observations/v1.8.0/` 아래 새 폴더에 결과를 생성합니다. 최초 분석(scan)도 별도 `observations/report.html`을 생성합니다.

Id–Vd: 고정 방향 RR/log RR/비대칭/odd-even 전류, 평가 전압의 signed Id·secant G·gds, offset을 포함한 G0와 창 폭 민감도, 비선형 잔차. Id–Vg: branch별 최대/최소 전류와 위치, 고정 gate쌍의 비/차, signed gm peak·위치·폭·창 민감도, 동일 acquisition의 forward/reverse 비교, operational Vcc와 탐색 역 log 기울기. 측정 Ig와 누설 비도 별도로 표시합니다.

단위 없는 열은 SI 가정값을 보존합니다. 같은 Id 채널의 비는 탐색 관측으로 제공하며, 검출한계가 없으면 분모 신뢰도는 미평가입니다. 0 분모는 null이고 epsilon으로 큰 수치를 만들지 않습니다. 보간은 같은 segment의 인접 원본 점 사이에서만 수행하며 외삽·중복 전압 평균·stress crop을 하지 않습니다. 물리 VT·검증된 SS·μ·고유 Rc·장벽 높이는 필요한 모델과 조건이 없으면 null+이유로 남습니다.

출력은 `report.html`, `report.md`, `metrics.csv`, `observation_points.csv`, `observations.json`, branch별 계산 근거 HTML입니다. 날짜는 사용자 정보가 기준이고 Keithley 시각은 참고입니다. 메타데이터 확인 이력을 새로 위조하지 않습니다. 창 폭/최소 점 수는 기록된 engineering 기본값이며 보편적 물리 문턱이 아닙니다.

보고·비교 원칙: [Cheng et al. (2022)](https://arxiv.org/pdf/2203.16759). Gate 의존 접촉저항에 따른 해석 제한: [Bennett et al. (2025)](https://poplab.stanford.edu/pdfs/Bennett-TransistorsGateDependentRc-npj2d25.pdf).
