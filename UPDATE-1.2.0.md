# 1.2.0 — 소자·측정 날짜·조건별 Obsidian 저장

> 1.2.1에서는 파일명에 조명 표기가 없으면 dark가 기본값이며, 파일명 조명이 조건 폴더보다 우선합니다. 조명 규칙과 API 키 등록은 UPDATE-1.2.1.md를 보세요.

소자 폴더 이름을 고정 목록 없이 읽습니다. `drain-fold`, `center-fold`, `source-fold`, `sample-03`, 한글 이름 등 새 소자 이름이 늘어나도 코드나 설정을 수정할 필요가 없습니다. 기존 I–Vd/Id–Vg XLS 파서와 QC는 그대로 사용합니다.

## 기존 설치에 적용

1. `Start-Watch.cmd` 창에서 Ctrl+C를 누릅니다. 예약 실행 중이면 잠시 중지합니다.
2. 업데이트 ZIP **내용물**을 기존 `Setup.cmd`가 있는 프로그램 폴더에 덮어씁니다. config.json, DB, Vault는 ZIP에 포함되지 않아 기존 설정을 유지합니다.
3. `Start-Watch.cmd` 또는 예약 실행을 다시 시작합니다. 추가 Python 패키지가 필요하지 않습니다.

1.0.0/1.0.1/1.1.0 설치에 적용할 수 있는 누적 업데이트입니다. 아직 Keithley 형식 업데이트를 적용하지 않았다면 함께 포함된 `Apply-Keithley-Format.cmd`를 실행해 XLS/XLSX와 축 자동 선택을 설정하세요. 기존 config.json에는 새 organization 기본 설정이 실행 시 자동 보충됩니다.

코드가 바뀌면 원본을 새 분석 버전으로 다시 처리합니다. **AI가 켜져 있으면 추가 API 요청과 비용이 발생할 수 있습니다.** 이전 노트는 이력으로 남습니다. 기존 노트나 원본을 일괄 이동·삭제하지 않습니다. 원본을 다른 소자/날짜 폴더로 옮긴 경우 다음 스캔에서 새 경로로 분류하며 이전 결과는 보존합니다.

## 입력 폴더

사용자가 알려준 형식을 그대로 지원합니다.

```text
측정 데이터/
  drain-fold/
    2026-09-23/
      Id-Vg_Vd=2V_dark.xls
      Id-Vg_Vd=2V_light.xls
      Id-Vd_dark.xls
  center-fold/
    2026-09-24/
      IdVg_Vd=3V_dark.xls
  새 소자 이름/
    2026-09-24/
      Id-Vg_Vd=2V_dark.xls
```

`Id-Vg#1@2V dark_1.xls`처럼 기존 첨부 파일명도 지원합니다. 권장 파일명은 `Id-Vg_Vd=2V_dark.xls`, `Id-Vg_Vd=2V_light.xls`, `Id-Vd_dark.xls`입니다. 파일명의 숫자만으로 스윕 데이터를 새로 만들지는 않습니다.

재료·샘플 계층을 추가해도 됩니다.

```text
측정 데이터/ReS2/sample-03/center-fold/2026-09-23/Id-Vg_Vd=2V_dark.xls
```

이때 개별 소자 이름은 파일에 가장 가까운 `center-fold`, 재료 토큰은 `ReS2`, 소자 경로는 `ReS2/sample-03/center-fold`로 보존합니다. 알려지지 않은 재료도 상위 폴더명은 보존하지만 폴더명만으로 물성을 추측하지 않습니다. 소자 종류의 별도 정의가 필요하면 아래 path_rules로 지정합니다.

## 저장 결과

```text
Obsidian Vault/
  Experiments/
    자동 측정 목록.md
    drain-fold/2026-09-23/Id-Vg__dark__Vd=2V/<파일명>_<작업ID>.md
    center-fold/2026-09-24/Id-Vg__light__Vd=3V/<파일명>_<작업ID>.md
    새 소자 이름/2026-09-24/...
  Attachments/
    drain-fold/2026-09-23/Id-Vg__dark__Vd=2V/<작업ID>/...
  Weekly/
    2026-W41.md
```

파일마다 독립 노트가 만들어지고 CSV·JSON·그래프 연결은 Vault 상대 경로를 사용합니다. 같은 파일명이 다른 소자 폴더에 있어도 원본 상대 경로가 작업 ID에 포함되어 구분됩니다. 상위 소자 폴더 계층도 결과에 유지합니다.

폴더명으로 쓸 수 없는 Windows/Obsidian 특수문자는 저장 경로에서만 정리합니다. 원래 소자 이름과 원본 상대 경로는 노트와 result.json에 그대로 보존합니다. 긴 조건 이름은 경로에서만 짧게 표시하며 전체 조건과 모든 고정 전압은 노트/CSV/JSON에 보존합니다.

## 인식 우선순위와 확인 표시

- **소자 이름:** path_rules → 파일명의 `device_name=`/`device=`/`소자=` → 가장 가까운 소자 폴더. 소자 이름은 고정 목록이 아닙니다. `원본`, `raw`, 날짜, dark/light 등은 소자 이름에서 제외합니다. 여러 소자 폴더가 있으면 계층을 보존하고 확인 표시를 남깁니다.
- **측정 날짜:** path_rules → 파일명의 `measurement_date=`/`date=` → 가장 가까운 날짜 폴더 → 파일명 날짜 → Keithley Settings의 Last Executed. YYYY-MM-DD, YYYY.MM.DD, YYYYMMDD, YYYY년 M월 D일, YYYY/MM/DD 폴더를 지원합니다. Settings의 MM/DD/YYYY는 장비 원문 형식으로 읽고 시간대 미확인을 표시합니다.
- **측정 유형:** 실제 측정 컬럼과 Settings의 스윕 축으로 I–Vd/Id–Vg를 구분합니다. 파일명이 다르면 확인 표시를 남깁니다.
- **Id–Vg의 Vd:** 실제 데이터/Settings → 명시된 파일명 메타데이터 → `Id-Vg@2V` 또는 `Id-Vg_Vd=2V` 표기. 파일명에서 보충하면 실측 전압이 아니라 파일명에서 얻은 조건임을 컬럼 출처에 기록합니다. 실제값과 파일명 값이 다르면 실제값을 사용하며 확인 표시를 남깁니다.
- **조명:** path_rules → 파일명 `illumination=` → dark/light 조건 폴더 → 파일명의 dark/light/with light. `dark`/`light`만으로 광원 세기나 파장을 추측하지 않습니다.

측정 날짜 후보가 충돌하면 폴더 날짜를 우선 사용하고 장비 원문과 다른 후보를 모두 기록합니다. 날짜가 없으면 **측정일 미확인**으로 저장합니다. 처리 날짜·파일 수정 날짜를 측정 날짜로 대체하지 않습니다. 소자 이름이나 조명이 없으면 미확인/unknown을 명시합니다.

result.json의 `research_context.evidence`에 선택 후보와 출처를 저장합니다. 분류 확인 경고는 수치 QC의 PASS/WARN/FAIL과 별도입니다.

## 노트 속성과 CSV

자동 노트에는 `measurement_date`, `device_name`, `device_type`, `fold`, `measurement_type`, `illumination`, `condition_label`, `device_path`, `fixed_conditions_v`, `sweep_ranges_v`, `metadata_review_required`, `source_relative_path` 및 주요 출처 필드를 저장합니다. normalized.csv, curves.csv, fit_results.csv, metrics.csv에도 날짜·소자·조건 열을 넣습니다.

`Experiments/자동 측정 목록.md`에서 전체 최신 결과를 날짜·소자·조건별로 확인하고 해당 노트로 이동할 수 있습니다. 주간 보고에도 측정 날짜와 소자·조건을 표시합니다. 주간 집계 기간은 기존대로 **분석 완료 시각** 기준입니다.

AI 활성 시 요약 수치와 함께 소자 이름·종류·fold·측정 날짜·조명·조건 라벨이 해석 요청에 포함됩니다. 원본 경로와 원시 측정행은 보내지 않습니다. 소자 분류 이름만으로 물리 구조/메커니즘을 확정하지 않도록 해석 지침을 수정했습니다.

## 특수 폴더 구조 설정 (선택)

기본 구조에서는 설정이 필요 없습니다. 자동 인식과 다른 이름/종류를 지정해야 할 때 config.json에 아래 섹션을 추가하세요.

```json
"organization": {
  "path_rules": [
    "^(?P<device_type>[^/]+)/(?P<device_name>[^/]+)/(?P<measurement_date>\\d{4}-\\d{2}-\\d{2})/"
  ]
}
```

정규식은 Inbox 아래의 `/`로 정규화된 상대 경로에 적용합니다. 첫 번째로 맞는 규칙을 사용합니다. 허용 capture 이름은 `device_name`, `device_type`, `fold`, `measurement_date`, `condition`, `illumination`입니다. 기본값은 `"path_rules": []`입니다.

## 검증 범위

분류·날짜 충돌·임의 소자 이름·파일명 바이어스 보충·노트/첨부 링크·CSV 메타데이터·주간 보고와 기존 분석을 회귀 검증합니다. 첨부된 실제 XLS 3개를 예시 소자/날짜 폴더에 배치해 전체 수치 분석과 노트 생성을 확인합니다. 검증용 소자 배치는 실제 소자 종류를 확정한 것이 아닙니다. AI 검증은 Mock HTTP로 수행하고 실제 유료 요청은 하지 않습니다. Windows PC에 직접 설치하거나 PowerShell/예약 실행을 검증한 것은 아닙니다.
