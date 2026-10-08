# 연구 자동화 1.9.0

Keithley 측정 파일을 읽어 반복 그래프, 기본 파라미터, 계산 근거와 Obsidian 연구노트를 만드는 Windows용 로컬 앱입니다. **측정 조건 확인 → 원시 데이터와 결과 읽기 → 비교 가능한 조건 선택** 순서로 사용합니다. Python 3.12, Tk GUI, pandas·NumPy·SciPy·Matplotlib을 사용합니다.

[기본 보고서와 상세 메타데이터 양식](docs/basic-report.md) · [1.9 변경점](UPDATE-1.9.0.md) · [branch별 관측 검토](UPDATE-1.8.0.md) · [CI 결과](https://github.com/LWJ0604/hi/actions)

이 README는 `main`의 **1.9.0 소스** 기준입니다. 2026-10-08 확인 시 공개 릴리스에는 **1.6.0**만 등록되어 있습니다. [Releases](https://github.com/LWJ0604/hi/releases)의 실제 첨부 버전을 확인하세요. GitHub의 **Code → Download ZIP**은 소스이며 Python 런타임이 포함된 휴대용 패키지와 다릅니다.

## Windows에서 처음 실행하기

현재 1.9.0은 소스로 설치할 수 있습니다.

1. **Python 3.12 64비트와 Tcl/Tk**를 설치합니다. 설치할 때 Tcl/Tk 옵션을 포함하세요.
2. 이 저장소의 소스 ZIP을 내려받아 Vault와 측정 폴더 밖의 새 프로그램 폴더에 풉니다.
3. `Setup.cmd`를 실행합니다. 의존성 설치에는 인터넷이 필요하며 기존 `config.json`은 보존합니다.
4. `Start-GUI.cmd`를 실행합니다. 현재 PC의 **측정 데이터** 폴더와 **Obsidian Vault**를 선택하고 **설정 저장**을 누릅니다. 처음 점검할 때는 작업용 데이터 사본과 별도 QA Vault를 사용하세요. OneDrive 파일은 로컬에서 읽을 수 있어야 합니다.
5. **파일 선택 → 기본 보고서**에서 대표 파일 하나를 선택합니다. 원시 그래프, 조건과 보류 이유를 확인한 뒤 다음 파일로 진행하세요. 처음부터 **한 번 분석**으로 전체 입력을 처리할 필요는 없습니다.

| 실행 방법 | 설정과 기본 저장 위치 | 사용할 때 |
| --- | --- | --- |
| 소스의 `Setup.cmd` → `Start-GUI.cmd` | `config.json`; 이 PC에서 선택한 경로 | 소스 설치·업데이트 |
| 휴대용 패키지의 `Start-Local-QA.cmd` | `qa-config.json`; 패키지 안의 `qa-runtime` | Python/Tcl/Tk가 포함된 패키지로 격리 점검 |

`Start-Local-QA.cmd`는 패키지 빌드 시 생성하는 런처로 저장소 소스 ZIP에는 없습니다. Local QA도 같은 앱이며 **입력 폴더나 Vault를 바꾸면 새 경로를 사용**하므로 격리가 계속 유지되는지 확인하세요. GUI 시작만으로 분석·감시·예약 작업을 시작하지 않습니다.

## 선택한 결과 읽기와 자동 처리

- **파일 선택 → 기본 보고서**: 입력 폴더 안의 파일을 선택해 새 HTML/Markdown 보고서를 만듭니다. 원본 파일, 기존 노트와 `device.md`의 메모는 수정하지 않습니다. 두 파일을 직접 선택한 연결도 배선·날짜·이력이 확인되기 전에는 잠정 검토입니다.
- **변경 미리보기 → 선택 파일만 분석**: 처리 대상과 새 버전 저장 위치를 확인하고 작업 기록·새 노트까지 생성합니다. **선택 기본 보고서**와 **선택 노트 열기**로 다시 확인할 수 있습니다.
- **메타데이터 검토**: 값·출처·추정/확인/충돌 상태를 확인합니다. 사용자 확인값과 이유는 원본 대신 별도 override 이력에 저장합니다. 먼저 실제 날짜나 단위처럼 필요한 조건 한 가지를 확인하세요.
- **선택 측정 수치 검토**, 계산 근거 패널의 **모든 지표와 원본 점 보기**: branch별 수치, 사용한 점·평가 전압·구간·제외 사유를 확인합니다. `observe`의 탐색 관측과 기본 보고서의 계산 기준은 구별됩니다.
- **한 번 분석 / 감시 시작 / 중지 / 실패 재시도**: 선택 검토 후 전체 운영에 사용합니다. 감시는 직접 시작해야 동작하며, 중지는 현재 처리 단계 사이에 반영합니다. 실패한 경로·누락 파일·권한을 바로잡은 뒤 재시도하세요. GUI 감시와 예약 Scan을 동시에 운영하지 마세요.

보고서는 **RR 대 Vg와 대응 극성 전류 → 조건 → 원시 Id–Vd/Id–Vg와 gm → 모델 중첩·잔차** 순서로 구성합니다. 반복 gate와 획득 블록을 보존하고 대표 그림으로 묶어 보여 주며, 전체 수치와 원본 셀은 CSV로 연결합니다. 기본 보고서는 중복 trace 그림 생성을 줄였고, `observe`와 명시적인 그래프 갱신으로 상세 검토할 수 있습니다.

## 입력 폴더와 `device.md`

**CSV, BIFF XLS, XLSX**를 지원합니다. Keithley의 가로 `DrainI(1)…` 열, 반복 전류 헤더와 Settings의 축·고정 전압을 읽습니다. 측정 Id/Ig와 장비 계산 GM 열, 끝의 빈 패딩과 중간 결측을 구별합니다. 원시 부호·행/열/셀 주소·블록·방향·획득 순서를 남깁니다. CSV가 섞인 폴더에서는 `Use-Excel-Only.cmd` 또는 `ingest.exclude_globs`로 분석 산출물의 재입력을 제외할 수 있습니다.

다음은 일반적인 **양식 예시**입니다. 값이나 확인 기록을 뜻하지 않습니다. GUI의 입력 폴더를 `측정 데이터`로 선택하면 그 안의 소자·날짜 폴더에서 정보를 상속할 수 있습니다.

```text
측정 데이터/                         GUI에서 선택한 입력 범위
  device.md                          여러 측정에 적용할 공통 정보(선택)
  sample-a/
    device.md                        소자 정보(선택)
    2026-01-15/
      device.md                      이 조건의 정확한 파일 연결과 실제 날짜
      원본/
        IdVd_dark.xlsx
        IdVg_dark.xlsx
```

가장 작은 연결 양식은 날짜/조건 폴더의 `device.md`에 다음처럼 저장합니다. UTF-8 Markdown의 YAML front matter 아래에 자유롭게 메모를 남길 수 있습니다.

```yaml
---
schema_version: 1
device_name: {value: null, source: null, verification: unconfirmed}
active_electrode_pair: null
run_conditions:
  IdVd:
    file: "원본/IdVd_dark.xlsx"
    measurement_date: {value: null, source: null, verification: unconfirmed}
    illumination: {value: null, source: null, verification: unconfirmed}
  IdVg:
    file: "원본/IdVg_dark.xlsx"
    measurement_date: {value: null, source: null, verification: unconfirmed}
    illumination: {value: null, source: null, verification: unconfirmed}
---
확인할 조건과 사용자 메모를 여기에 적습니다. 자동 분석은 이 파일을 덮어쓰지 않습니다.
```

직접 확인하지 않은 값은 `null`과 `unconfirmed`로 둡니다. 확인한 값만 출처와 함께 기록하고 해당 필드에 `verification: user_confirmed`를 지정하세요. 전극쌍의 L/W, gate dielectric, 온도·단위·참고 이동도 양식은 [상세 안내](docs/basic-report.md)에 있습니다. `device.md`를 만들었다는 사실 자체는 사용자 확인이 아닙니다.

**상속과 탐색 경계:** 입력 폴더부터 원본에 가까운 `device.md`까지 읽으며 가까운 값이 우선합니다. 입력 폴더가 `원본` 또는 `raw`이고 바로 상위에 `device.md`가 있으면 그 상위까지 읽습니다. 더 넓은 상속이 필요하면 입력 폴더를 공통 상위로 선택하거나 `benchmark.metadata_root`를 지정합니다. 명시한 root는 입력 폴더를 포함해야 하며 파일 선택과 연결 대상은 여전히 GUI의 입력 폴더 안에 있어야 합니다. 파일 연결은 해당 `device.md` 기준의 상대 경로이고 `..`, 절대 경로와 범위 밖 연결은 허용하지 않습니다.

하위 파일에서 값·단위·출처·확인 상태 중 일부를 바꾸면 그 **필드 전체를 교체**합니다. 새 값에 상위 단위나 확인 이력을 붙이지 않습니다. 파일 연결을 다시 선언하면 그 파일의 날짜·광 조건도 다시 지정해야 합니다. 수정하지 않은 다른 필드는 상속됩니다. 소자 이름이 달라지면 이전 소자의 geometry를 계속 사용하지 않습니다. 잘못된 타입·YAML은 경고와 함께 격리하고 의존하는 계산을 보류합니다.

**현재 연결 제한:** 하나의 병합된 `run_conditions`는 **IdVd 한 파일 + IdVg 한 파일**만 명시할 수 있습니다. 날짜/광 조건/전극쌍별로 다른 연결이 필요하면 별도 조건 폴더의 `device.md`에 정확히 지정하거나 파일을 직접 선택하세요. 파일명 유사성이나 같은 날짜만으로 짝을 찾지 않으며, 나머지 파일·조건을 자동으로 연결하거나 비교하지 않습니다. Scan/감시는 다른 입력 파일도 개별 처리하지만 모든 조건 조합을 자동 해석하는 기능은 아닙니다.

## 단위·실제 날짜·광 조건 확인

**공용 기본값은 단위 미확인**입니다. 모든 사용자의 자료를 V/A로 확정하지 않으며 확인 없이도 원시 데이터를 검토할 수 있습니다.

- 파일 헤더에 V/mV, A/mA/nA 등의 단위가 명시되면 해당 단위를 우선 환산합니다. 단위 없는 열의 SI 가정은 확인된 단위와 구별합니다.
- 자신의 **단위 없는 전압/전류 열이 실제로 V/A임을 확인한 경우에만** GUI의 **내 측정의 단위 없는 열은 전압 V / 전류 A로 확인**을 선택하고 저장하세요. 이 선택은 사용자 설정에 출처·시각을 기록하고 이전 설정 사본을 남깁니다. V/A 확인은 필수 시작 조건이 아닙니다.
- 다른 단위라면 V/A 확인을 선택하지 말고 파일의 명시 단위 또는 `device.md`의 확인된 `run_conditions.units`를 사용하세요. 이 프로필은 전압 V/mV/uV, 전류 A/mA/uA/nA/pA를 지원합니다. 충돌은 따로 표시합니다.
- 기본 보고서의 평가 전압·전류 단위가 미확인이면 RR·gm·모델 계수 등 의존 계산을 `null`과 사유로 보류합니다. 원시 그림과 독립적으로 가능한 관측은 유지합니다. 단위 확인은 검출한계·선형영역·측정일 확인을 대신하지 않습니다.

**실제 측정일은 사용자가 확인한 정보가 기준**이며 `measurement_date`는 명시한 해당 파일에만 적용합니다. Keithley의 날짜·시각은 참고 정보로 분리합니다. 실제 시간이 없으면 만들어 넣지 않으며 장비 delay와 사용자 기록의 불일치는 그대로 남깁니다.

`withlight`, `with light`, `with_light`, `light`는 light, `dark`는 dark로 파싱합니다. 무표기의 dark 기본값·파일명 추정은 **미확인**이며 사람이 확인한 광 조건과 구별합니다. 광파워가 없으면 responsivity를 확정하지 않습니다.

## 계산의 의미와 제한

| 결과 | 읽는 기준 |
| --- | --- |
| RR 대 Vg와 I(+u)/I(−u) | `RR = abs(I(+u)) / abs(I(−u))` 방향 고정. 평가 전압 필수. 기본 보고서는 같은 trace에 정확히 존재하는 ±u 원본점을 사용하며 0 분모·확인된 검출한계 미만은 값과 사유를 분리. 검출한계가 없으면 분모 신뢰도는 미평가. |
| Id–Vg와 gm | 실제 전압 간격의 중앙차분과 국소 2차식 창을 비교. 기본 보고서의 gm 창 기본값은 2/4/8 V이며 끝점·불완전 창은 보류. 창 폭과 적용 구간을 함께 검토. |
| 이동도 참고값 | 선택한 전극쌍 L/W, gate dielectric/Cox와 Vd 등 필요한 입력에 의존. 입력 이동도와 계산 참고값을 분리하며 선형영역이 확인되지 않으면 물리 이동도로 확정하지 않음. |
| Shockley / Shockley+Rs | 같은 구간·원본점으로 참고 피팅하고 극성별 절댓값 근사와 양극성 단일 다이오드식을 분리. 잔차, 구간·offset 민감도, 계수 상관과 Rs 고정 프로파일로 안정성을 검토. 프로파일을 신뢰구간으로 자동 변환하지 않음. |

비교식은 `j = Is(exp(u/a) − 1)`과 `u = a ln(1 + j/Is) + j Rs`입니다. Rs·a·Is와 기존 모델의 j0는 **유효 모델 계수**이며 고유 접촉저항·장벽·전류 경로의 증명이 아닙니다. 기본 피팅 범위와 gm 창은 기록된 분석 설정으로 보편적인 물리 문턱이 아닙니다.

원래 gate sweep ±20 V와 ±40 V는 서로 다른 stress 조건입니다. Crop·평균으로 비교 가능하게 만들지 않습니다. 방향·블록·delay/hold·전극·광 조건·사전 이력이 다르거나 미확인인 결과는 직접 비교하지 않습니다. Vth/SS 등 미확인 지표는 `null`과 이유를 남깁니다.

`parse_status`, `data_qc`, `metadata_status`, `metric_status`, `model_status`는 별개입니다. **QC PASS는 연구 사용 가능·메타데이터 확인 완료를 뜻하지 않으며 SKIP은 통과가 아닙니다.** 기존 QC 문턱은 유지합니다. Ig가 없거나 근거 있는 검출한계·잡음 검사가 없으면 `not_assessed`입니다. [기존 과학 분석 설정](docs/과학분석-v1.4.0.md)도 참고하세요.

## 결과와 진단의 저장 위치

`analysis`, `vault` 등은 설정한 경로의 이름입니다. CLI `report`와 GUI 기본 보고서는 새 폴더를 만들며, Scan의 기본 보고서는 해당 작업 폴더 안에 생성합니다.

```text
analysis/benchmarks/v1.9.0/<새 폴더>/         선택 파일의 기본 보고서
analysis/runs/v1.9.0/<job>/benchmark/         Scan/감시의 기본 보고서
  report.html, report.md                     읽는 보고서
  images/                                   PNG/SVG 그래프
  csv/                                      RR·극성 전류·gm·피팅·잔차·원본 셀
  inputs/, metadata/                        선택 원본과 사용한 device.md 사본
  diagnostics/                              읽기·조건·최적화·보류·실패 진단
analysis/observations/v1.9.0/                observe의 branch별 상세 검토
vault/Experiments/v1.9.0/                    새 버전 연구노트
vault/Attachments/v1.9.0/                    새 버전 노트의 그림·수치 자료
vault/ResearchAutomation/metadata-overrides.json  확인값·이유·변경 이력
state/jobs.sqlite3                          작업 기록
logs/pipeline.log                           실행/오류 로그
```

기존 수치 CSV/JSON과 이전 버전 결과·사용자 메모는 보존합니다. 코드·설정·원본·연결 파일·메타데이터·override 변경은 작업 식별자/캐시에 반영합니다. **진단 자료에는 원본 사본·경로·메모가 포함될 수 있으므로 공개 저장소에 올리지 마세요.** `benchmark.enabled: false`는 기존 보고서 경로를 유지하려는 운영 옵션이며 기본값은 `true`입니다.

## CLI와 백업

소스 설치의 프로그램 폴더에서 실행합니다. `--source`는 선택한 입력 폴더 기준의 상대 경로이며 한글·공백 경로는 따옴표로 감쌉니다. `--config`는 서브명령 앞에 둡니다.

```powershell
.\.venv\Scripts\python.exe -m research_automation --config config.json preview --source "sample-a/2026-01-15/원본/IdVd_dark.xlsx"
.\.venv\Scripts\python.exe -m research_automation --config config.json report --source "sample-a/2026-01-15/원본/IdVd_dark.xlsx"
.\.venv\Scripts\python.exe -m research_automation --config config.json report --source "sample-a/2026-01-15/원본/IdVd_dark.xlsx" --no-pair
.\.venv\Scripts\python.exe -m research_automation --config config.json doctor
.\.venv\Scripts\python.exe -m research_automation --config config.json backup
```

두 파일을 직접 연결하려면 `--source`를 반복해서 지정합니다.

`report --no-pair`는 `device.md` 연결 없이 선택 파일만 처리합니다. `observe --source ...`는 branch별 상세 검토, `scan --source ...`는 선택 파일의 자동 처리입니다. `scan`, `watch`, `weekly`, `status`, `backup`과 [n8n 연동](docs/n8n.md)은 유지합니다. 백업 ZIP의 체크섬·DB 무결성은 `scripts/verify-backup.py`로 확인할 수 있습니다.

`Register-Schedules.cmd`는 사용자가 직접 실행할 때만 예약을 등록합니다. 기본 `science.offline: true`에서는 외부 AI 요청과 연결 확인을 차단합니다. AI 옵션이나 키만 켠다고 외부 전송하지 않으며, 과거 노트의 AI 일괄 재작성은 비활성화되어 있습니다.

## 기존 설치 업데이트와 검증

실행 중인 GUI·감시를 종료하고 **기존 config·원본·Vault·DB를 별도로 보관한 뒤 새 프로그램 폴더에 설치**하세요. `Setup.cmd`는 기존 설정을 덮어쓰지 않습니다. 설정을 새 폴더로 옮기면 상대 경로의 기준도 바뀌므로 입력·Vault뿐 아니라 analysis/state/backups 경로도 확인하세요. [변경 미리보기와 보존 안내](UPDATE-1.9.0.md)를 확인하고 대표 파일부터 처리한 뒤 감시를 재시작하세요. 앱 업데이트가 전체 과거 노트를 일괄 갱신하는 승인은 아닙니다.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

2026-10-08 사용자 업로드 커밋 [`889d4f9`](https://github.com/LWJ0604/hi/commit/889d4f97c057a49e7d5221743a4453051a47a3be)의 [Windows·Ubuntu CI](https://github.com/LWJ0604/hi/actions/runs/37709011754)는 **각각 266개 테스트를 통과**했습니다. 로컬 Windows에서도 266개 전체 테스트, 공개용 패키지의 45개 회귀와 런처를 확인했습니다. 실제 Tk의 파일 선택·중복 실행 방지·누락 파일 재시도·결과 열기·백업과 Chrome 보고서 화면을 검증했습니다. **다른 PC 설치, 실제 Obsidian 화면과 작업 스케줄러는 미검증**입니다. 최신 커밋의 결과는 [Actions](https://github.com/LWJ0604/hi/actions)에서 확인하세요.
