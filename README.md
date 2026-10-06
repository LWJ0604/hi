# 연구 자동화 1.7.0

**휴대용 실행:** [GitHub 릴리스](https://github.com/LWJ0604/hi/releases)의 **research-automation-windows-v1.7.0.zip**을 짧은 로컬 경로에 풀고 **Start-Local-QA.cmd**를 실행하세요. Python/Tcl/Tk가 포함됩니다. 기본 입력·분석·Vault·DB는 패키지 내부 `qa-runtime`의 격리된 폴더입니다. 자동 감시는 직접 시작하기 전에는 동작하지 않습니다. [실행·업데이트 안내](UPDATE-1.7.0.md)

**1.7.0:** 실제 Template Creator Jinja·스키마를 새 노트와 비교 보고서에 연결했습니다. 값·상태·근거를 보존하고 과거 노트를 덮어쓰지 않습니다. [실행 안내](UPDATE-1.7.0.md), [연결 계약](docs/TEMPLATE-BRIDGE-LOCAL.md)

**1.6.0:** Windows SQLite 백업과 로그 정리를 수정했습니다. 선택 결과의 조건·핵심 수치·다음 확인과 RR/gm 계산 근거를 먼저 보여줍니다. 연구노트 형식 2, Figure 2 패널, 모든 지표의 단위·상태·출처를 제공합니다. 반복 계산 근거는 손실 없이 공용 테이블에 저장하는 디스크 schema 3으로 정규화합니다. 기존 schema 1/2와 연구자 메모·이전 결과는 보존합니다. [노트·저장 형식](RESEARCH-NOTE-V2-LOCAL.md), [Windows 검증 범위](LOCAL-WINDOWS-REVIEW.md)

**이전 1.5.0:** 보존형 선택 노트 미리보기와 추가 FET 후보를 도입했습니다. [이전 업데이트 안내](UPDATE-1.5.0.md)

**이전 1.4.1:** Windows의 음수 부호 깨짐을 수정했습니다. 이미 분석을 마쳤다면 GUI의 **선택 그래프 갱신** 또는 `Refresh-Plots.cmd`로 수치 재분석 없이 새 그림을 내보내세요. **전체 결과 점검** 또는 `Audit-Results.cmd`는 로컬 점검 보고와 `result-audit.zip`을 만듭니다. 기존 결과/노트는 보존합니다. [수정·점검 안내](UPDATE-1.4.1.md)와 [1.4.1 검증](docs/검증결과-v1.4.1.md)을 참고하세요.

기존 1.3.1 GUI와 Keithley → Python 분석 → Obsidian 흐름을 유지하면서, 메타데이터 확인과 비교 가능한 지표 추출을 추가했습니다. **기존 설치는 [UPDATE-1.6.0.md](UPDATE-1.6.0.md)**를 따르세요. 실제 테스트와 한계는 [검증 보고](docs/검증결과-v1.4.0.md), 계산 기준은 [과학 분석 설정](docs/과학분석-v1.4.0.md)에 있습니다.

`withlight`, `with light`, `with_light`, `light`는 입사광 **light**입니다. `dark`는 dark, 표기가 없으면 **dark 기본값(미확인)**, 출처가 다르면 **conflict**입니다. 기본값·파일명 추정은 사용자 확인과 구별합니다.

원본 파일은 수정·이동하지 않고 SHA-256을 기록합니다. 새 노트와 산출물은 `Experiments/v1.7.0`, `Attachments/v1.7.0` 아래에 저장합니다. 기존 노트의 연구자 본문과 과거 결과를 덮어쓰지 않습니다. 외부 AI 호출은 `science.offline: true`로 차단하며 자동 요약은 규칙 기반입니다.

## Windows 사용

포터블 릴리스는 Python 설치나 Setup.cmd 없이 **Start-Local-QA.cmd**로 실행합니다. 아래 Setup 절차는 소스 설치에 해당합니다.

1. Python 3.12 64비트와 Tcl/Tk를 설치합니다. 이번 검증은 Python 3.12에서 했습니다. 3.14에서는 현재 고정된 의존성의 호환성을 별도로 확인해야 합니다.
2. 프로그램 ZIP을 Vault 밖의 폴더에 풀고 `Setup.cmd`를 실행합니다. 설치는 패키지를 받기 위해 인터넷이 필요합니다. 합성 예제는 실측 Inbox에 자동 생성하지 않습니다.
3. `Start-GUI.cmd` → 현재 PC의 **측정 데이터 폴더**와 **Vault** 선택 → 설정 저장. 집·연구실 경로는 각각 선택하며 코드에 사용자명을 넣지 않습니다. OneDrive 파일은 로컬에서 읽을 수 있는 상태여야 합니다.
4. **변경 미리보기**에서 처리 대상·새 버전 위치·기존 노트 보존을 확인합니다. 파일을 선택하고 **선택 파일만 분석**으로 대표 파일부터 실행하세요.
5. 완료 파일을 선택하고 **메타데이터 검토**에서 실제 날짜, 광 조건, 소자, 전극, delay, hold, 이력과 단위를 검토합니다. 값과 확인 이유를 저장하면 원본 대신 별도 override가 기록됩니다. 다른 파일은 재계산하지 않습니다.
6. **관측 지표 / 모델 비교** 탭과 **선택 노트 열기**로 값·단위·상태·보류 이유를 확인합니다. 조건이 확인된 뒤 필요에 따라 한 번 분석 또는 감시를 사용합니다.

입력 구조는 `측정 데이터/<자유로운 소자 이름>/<YYYY-MM-DD>/<파일.xls 또는 xlsx>`입니다. `drain-fold`, `center fold`, 새 샘플 이름을 모두 지원합니다. 파일명은 `Id-Vd_dark.xls`, `Id-Vg@2V_withlight.xls` 같은 표기를 권장합니다. 장비 Settings의 축·고정 전압을 우선 읽고 파일명은 보조 근거로 기록합니다.

`Setup.cmd`는 기존 `config.json`을 보존합니다. 새 설치의 상대 경로 템플릿은 예시입니다. GUI에서 실제 폴더를 선택해야 합니다. 다른 Python 실행 파일을 지정할 때는 다음과 같이 실행합니다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1 -Python "C:\Python312\python.exe"
```

## 파서와 지표

- BIFF XLS, XLSX, CSV를 지원합니다. 가로 `DrainI(1)…` trace, 반복 `DrainI` 헤더와 위쪽 Vds 조건 행을 각각 개별 곡선으로 읽습니다. 파일 끝의 연속 빈칸/`--` 패딩과 실제 측정 중간 결측을 구별합니다.
- `Id`, `Ig`의 부호, 획득 순서, 원본 행·열·셀을 유지합니다. GM/GM2 계산 열은 측정 전류와 구별해 제외합니다. 왕복 방향·gate reset·결측을 분리하고 dwell 점을 평균하거나 제거하지 않습니다.
- 단위 없는 컬럼은 V/A 가정으로 읽되 새 지표를 보류합니다. GUI `units_confirmed`는 내보낸 데이터의 전압 V·전류 A를 실제 확인한 경우에만 true로 저장하세요. 잘못된 단위는 `columns.scales`를 수정하고 선택 파일을 재분석해야 합니다.
- RR은 `abs(Id(+u))/abs(Id(-u))`; 0.2를 5로 바꾸지 않습니다. 기본 u는 0.5, 1, 1.5, 2 V입니다. 각 결과에 평가 전압·방향·블록·전류·원본점·보간 여부가 있습니다. 결측/compliance를 건너뛰거나 외삽하지 않습니다.
- gm은 signed raw 미분과 비균일 간격을 지원하는 국소 다항식 미분을 함께 제공합니다. 끝점 최대와 내부 peak 후보를 분리합니다. 검출한계·단위·조건이 미확인인 후보는 인증된 값이 아닙니다.
- Vth/SS/이동도는 명시적 방법·구간·검출한계·geometry 조건이 있을 때만 계산합니다. 측정 구간 전류 비율을 on/off ratio라고 부르지 않습니다. 영전압 기울기 역수는 유효 미분저항입니다.
- ±20 V와 ±40 V 원래 sweep, 방향, 반복 블록, delay/hold/pre-bias/전극/이력이 다르거나 미확인인 데이터는 자동 비교하지 않습니다. 광파워가 없으면 responsivity는 null입니다.
- 선택적 정류 모델은 기본 꺼짐입니다. 선형/sinh는 경험적 기준선이며 물리 메커니즘의 자동 승자를 정하지 않습니다.

## QC와 확인 상태

`parse_status`, `data_qc`, `metadata_status`, `metric_status`, `model_status`를 따로 기록합니다. **PASS는 메타데이터 확인 완료가 아니며 SKIP은 통과가 아닙니다.** 측정되지 않은 Ig, 근거 없는 검출한계와 잡음 검사는 `not_assessed`입니다.

기존 `qc`의 50/100 nA 문턱은 호환을 위한 legacy 경고로 남습니다. 새 `science` 설정에는 국소 변화·Ig/Id 비율·근거 있는 검출한계·compliance 근접·gm 창·모델 범위를 지정합니다. 기본값의 근거와 조정 위치는 [계산 기준](docs/과학분석-v1.4.0.md)을 참고하세요. 곡선이 가파르거나 평탄하다는 이유로 원본점을 자동 삭제하지 않습니다.

## 저장 구조

```text
analysis/raw/<job>/                          원본 보관 사본
analysis/runs/v1.6.0/<job>/                   새 분석 결과
analysis/failures/v1.6.0/<job>_<time>.json     실패 단계와 미계산 상태
analysis/comparisons/v1.6.0/<time>/           비교 후보/가능 여부
vault/Experiments/v1.7.0/<소자>/<날짜>/<조건>/  새 연구노트
vault/Attachments/v1.7.0/<소자>/<날짜>/<조건>/  그래프·CSV·JSON
vault/ResearchAutomation/metadata-overrides.json  확인값·이유·수정 이력
vault/Weekly/v1.6.0/                         새 주간 보고
state/jobs.sqlite3                          작업 기록
logs/pipeline.log                           실행/오류 로그
```

`parsed_points.csv`는 패딩·중간 결측까지 포함한 추적용 사본입니다. `normalized.csv`는 유효 측정, `curves.csv`는 signed gm·전도도·정규화·점별 적합성, `observable_metrics.csv`는 단위·평가 전압·상태·근거, `rectifier_parameters.csv`/`model_diagnostics.csv`는 선택 모델 결과, `result.json`은 전체 구조와 출처입니다.

노트와 그림은 Vault 상대 링크를 사용합니다. 원본은 Inbox 상대 경로, 스냅샷은 Analysis 상대 경로로 구별합니다. 새 버전이나 복구 때 이름이 충돌하면 `preserved-rN`을 붙여 보존합니다. 같은 경로·내용·설정·코드·override를 재실행하면 unchanged가 됩니다. 코드 업데이트 뒤 감시 프로세스를 재시작하세요.

## CLI와 기존 운영 기능

프로그램 폴더에서 다음을 실행할 수 있습니다. Windows에서는 `.venv\Scripts\python.exe`를 사용하세요.

```powershell
.\.venv\Scripts\python.exe -m research_automation --config config.json preview
.\.venv\Scripts\python.exe -m research_automation --config config.json scan --source "drain-fold/2026-09-23/Id-Vd_dark.xls"
.\.venv\Scripts\python.exe -m research_automation --config config.json doctor
```

`scan`, `watch`, `weekly`, `backup`, `status`는 기존 흐름을 유지합니다. `Use-Excel-Only.cmd`로 분석용 CSV를 제외하거나 `ingest.exclude_globs`에 `*parameters*.csv`를 지정할 수 있습니다. `Register-Schedules.cmd`는 이 PC에서 사용자가 실행할 때 Scan(1분), Weekly(금요일 18시), Backup(매일 19시) 예약을 등록합니다. GUI 감시와 예약 Scan을 동시에 운영하지 마세요. 예약 해제는 `scripts/unregister-tasks.ps1`입니다. n8n 연동은 [별도 안내](docs/n8n.md), 백업 검증은 `scripts/verify-backup.py`를 참고하세요.

기존 AI 켜기·끄기/키 등록 UI는 유지하지만 이번 버전 기본 `science.offline: true`에서는 API 연결 확인도 호출하지 않습니다. 키를 등록하거나 `ai.enabled`만 켜도 외부 전송이 되지 않습니다. 과거 노트를 덮어쓰는 `retry-ai`는 차단합니다. 이번 작업에서는 실제 외부 AI 요청·업로드·예약 등록·계측기 제어를 실행하지 않았습니다.

## 검증

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Windows/Python 3.12에서 최종 기능 변경까지 184개 테스트를 통과했습니다. 버전 갱신 후 같은 전체 회귀를 다시 실행합니다. 실제 Tk 위젯·레이아웃·작업 스레드와 CMD 런처를 자동 검증했으며, 픽셀 스크린샷·실제 Obsidian·Explorer 더블클릭 설치·작업 스케줄러는 검증하지 않았습니다. 정확한 릴리스 커밋의 Windows/Ubuntu 결과는 [Actions](https://github.com/LWJ0604/hi/actions)에서 확인하세요.


## v1.6.0 노트 미리보기와 추가 FET 지표

기존 결과를 보존하면서 **선택 노트 미리보기**로 새 읽기 형식을 확인할 수 있습니다. G(Vg), gm/Vds, 정규화 gm, RR, YFM Vth 후보, SS min/average와 해당 그림을 제공합니다. **FET 추출 조건**에서 geometry·평가 구간·가정 출처를 확인합니다. 설치·보존·후보 지표의 조건은 [UPDATE-1.5.0.md](UPDATE-1.5.0.md)를 참고하세요.
