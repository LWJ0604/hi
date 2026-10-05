# 1.1.0 — 첨부 Keithley I–Vd / Id–Vg 형식 대응

사용자가 첨부한 실제 세 `.xls` 파일을 확인하고 파서·분석·그래프·연구노트를 수정했습니다. 1.0.0 또는 1.0.1 설치에 바로 적용할 수 있는 누적 업데이트입니다. 추가 Python 패키지는 필요하지 않습니다.

## 적용 방법

1. 감시 창에서 Ctrl+C를 누릅니다. 예약 스캔이 실행 중이면 잠시 중지합니다.
2. 업데이트 ZIP의 **내용물**을 기존 `Setup.cmd`가 있는 프로그램 폴더에 풀고 같은 이름의 코드 파일을 덮어씁니다. ZIP은 기존 config.json/Vault/SQLite를 포함하지 않습니다.
3. `Apply-Keithley-Format.cmd`를 실행합니다. config.json을 날짜가 붙은 파일로 먼저 백업하고, 입력 확장자를 XLS/XLSX로, 분석 축 선택을 자동으로 설정합니다. Vault 경로·QC·AI 설정은 유지합니다.
4. `Start-Watch.cmd` 또는 기존 예약 실행을 다시 시작합니다.

코드와 분석 설정이 바뀌므로 기존 측정파일도 새로운 분석 버전으로 처리됩니다. AI가 켜져 있으면 새 API 해석 요청도 발생합니다. 이전 결과와 노트는 이력으로 남습니다. 첨부 데이터 검증에서는 AI를 끄고 수치 파이프라인만 실행했습니다.

## 실제 확인한 입력

| 파일 | 실제 형식 | 해석 |
|---|---|---|
| I-V#1@-1 to 20_dark.xls | Data 81행 × 132열, 44개 번호별 3열 묶음 | I–Vd; Vd −2~2 V; Vg −1~20 V가 2회 기록됨 |
| I-V#1@1 with light.xls | Data 41행 × 246열, 82개 번호별 3열 묶음 | I–Vd; Vd −2~2 V; Vg −20~20 V가 2회 기록됨 |
| Id-Vg#1@2V dark_1.xls | Data 161행 × 5열 | Id–Vg; Vg −40~40 V; Settings의 고정 Vd=2 V |

세 파일은 실제 구형 Excel BIFF/OLE 형식이며 xlsx로 변환하지 않아도 됩니다. `Data`, `Calc`, `Settings` 시트가 있습니다.

## 변경 내용

- `DrainI(1)`, `DrainV(1)`, `GateV(1)`의 괄호 숫자는 단위가 아닌 **trace 번호**로 읽습니다. 같은 번호끼리 묶어 long-format 측정표로 변환합니다.
- 같은 Vg 값이 반복되더라도 trace를 각각 보존합니다. 첨부 I–Vd 곡선은 모두 Vd 정방향이므로 두 반복을 연결해 가짜 역스윕/히스테리시스를 만들지 않습니다.
- `Settings`의 `Forcing Function`으로 스윕 축을 우선 결정합니다. `Voltage Sweep`인 단자가 Drain이면 Vd, Gate이면 Vg입니다. 설정이 없으면 변하는 전압 컬럼으로 판단하고, 모호하면 기본 설정 축을 사용하며 확인 메시지를 남깁니다.
- Id–Vg의 없는 DrainV 컬럼은 `Voltage Bias` / `Start/Level`의 **설정값 2 V**로 보충하고 출처를 기록합니다. 파일명의 `@2V`를 추측해 쓰지 않습니다. 이는 측정된 전압이 아닌 프로그램된 고정 바이어스입니다.
- `Calc`와 `Settings`는 측정 데이터로 피팅하지 않습니다. 장비 계산값 `GM`, `GM2`의 `#REF` 때문에 필수 측정행을 제외하지 않습니다. 시트 텍스트/수식은 실행하지 않습니다.
- Excel의 숫자 셀을 불필요하게 문자열로 변환하지 않아 원래 숫자 정밀도를 유지합니다. 단위 없는 Keithley 전압/전류는 기존 설정에 따라 V/A로 가정하고 노트에 표시합니다.
- 원본 행 번호, 원본 시트, trace 번호, Vg/Vd 조건을 CSV/JSON에 보존합니다.
- XLS 리더의 OLE 구조 경고는 JSON 출력과 분리해 결과에 기록합니다. 실제 첨부파일의 측정값은 전부 읽혔습니다.

## 유형별 분석

**I–Vd:** trace별 linear/sinh 경험 모델 비교, 잔차·RMSE·AIC·BIC, ±1 V의 `abs(I(+V))/abs(I(−V))`, 예시 QC. Ig가 없는 첨부 I–Vd 파일은 게이트 누설 검사가 SKIP입니다. 두 경험 모델만으로 전도 메커니즘을 확정하지 않습니다.

**Id–Vg:** Vd 조건별 전달곡선, linear 경험적 기준선, 유효한 Id/Vg의 비평활 수치 미분 gm, 측정 구간의 최대/최소 |Id| 비율, 측정된 Ig 누설 검사. Id–Vg에 대칭 sinh 모델이나 I–Vd RR을 적용하지 않습니다. gm은 잡음 영향을 받고 최대값이 경계점에서 나올 수 있습니다. 문턱전압/SS/이동도는 추출 조건 없이 계산하지 않습니다.

Settings의 compliance에 대한 전류 근접 여부도 확인합니다. 근접 경고는 실제 장비의 compliance 상태 플래그를 읽었다는 의미는 아닙니다.

## 추가 산출물

- `overview_vd.png` / `overview_vg.png`: 파일의 전체 곡선
- `gNNNN_fit.png`: 독립 곡선별 데이터·경험 모델·잔차
- `gNNNN_transfer.png`: Id–Vg의 |Id| 로그 그래프, gm, |Ig|
- `metrics.csv`: trace별 RR/전달 지표
- `curves.csv`: 예측값과 함께 axis/trace, Id–Vg의 gm 및 측정된 Ig
- Obsidian 노트: Settings 바이어스 출처, 조명 조건의 파일명 출처, 측정 유형별 지표

주간 보고는 Vd/Vg가 섞여도 각 그룹의 실제 축을 보존합니다. 집계 기준은 기존처럼 분석 완료 시각입니다. Settings의 Last Executed는 시간대가 확인되지 않은 원문으로 기록합니다.

## 설정

기존 설정에 없으면 아래 기본값을 자동 보충합니다.

```json
"auto_detect_axis": true,
"transfer_models": ["linear"]
```

두 필드는 `analysis` 안에 들어갑니다. 직접 축을 지정하려면 auto_detect_axis를 false로 바꾸고 x/group_by를 맞추세요. I–Vd의 모델 목록은 기존 analysis.models를 따르며 Id–Vg는 transfer_models를 사용합니다. transfer_models를 빈 목록으로 두면 Id–Vg 기준선 피팅을 생략하고 수치 지표만 계산합니다.

입력 확장자/제외 패턴 기능은 그대로 유지합니다. CSV 실측도 사용할 경우 extensions에 .csv를 넣고 `exclude_globs: ["*parameters*.csv"]` 등으로 분석용 파일을 구분할 수 있습니다.

실제 첨부파일 3개로 전체 분석·노트·주간 보고를 검증했습니다. 수치 알고리즘은 회귀 테스트로 검증했으며, Windows에서 PowerShell/예약 작업을 직접 실행하는 검증은 이 클라우드 환경에서 수행하지 못했습니다.
