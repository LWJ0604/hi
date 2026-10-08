# 날짜 폴더와 Excel 광 조건

1.9.1부터 명시한 연결 쌍뿐 아니라 입력 폴더의 모든 Excel 파일에 적용합니다. 원본 파일·device.md·기존 노트는 수정하지 않고 새 결과에 값과 근거를 기록합니다.

## 측정일

원본 분류 폴더 이름의 유효한 전체 날짜를 사용합니다. `YYYY-MM-DD`, `YYYY.M.D`, `YYYY_M_D`와 `YYYY/MM/DD` 폴더 계층을 지원하며 결과는 `YYYY-MM-DD`입니다. 월·일만 있는 이름, 잘못된 날짜, 파일명에 적힌 날짜, 장비 시각, 파일 수정 시각은 측정일을 채우지 않습니다.

여러 날짜 폴더가 중첩되면 파일에 가장 가까운 유효한 분류 날짜를 사용하고 후보를 보존합니다. `원본`, `raw`, `original`에 들어가기 전까지의 분류만 읽습니다. `분석`, `analysis`, `runs`, `benchmarks`, `observations`, `Experiments`, `Attachments`, `Weekly`도 경계입니다. 이 경계 아래의 날짜는 처리일 또는 내보낸 파일의 날짜일 수 있어 사용하지 않습니다. 입력 폴더 자체가 원본 폴더면 바로 상위 날짜 이름을 사용할 수 있지만, device.md 탐색 범위를 늘리지는 않습니다.

예: `소자 A/2026-09-23/원본/2026-10-08/data.xlsx`의 측정일은 `2026-09-23`입니다. `소자 A/2026-09-09/2026-09-23/data.xlsx`는 `2026-09-23`입니다. `2026-10-08_demo`처럼 날짜 외 문자가 붙은 폴더는 날짜로 인정하지 않습니다. 실제 측정 시각이 없으면 계속 미확인입니다.

## 광 조건

`.xls`와 `.xlsx`의 파일명에서 확장자를 제외하고 대소문자와 관계없이 `light`를 찾습니다. 포함되면 light, 없으면 dark입니다. `with light`, `withlight`, `LIGHT`, `dark_withlight`는 light입니다. `data.xlsx`, `with dark.xls`는 dark입니다. 상위 폴더의 light/dark는 판단에 사용하지 않습니다. CSV는 이 Excel 규칙의 대상이 아니며 기존 메타데이터 검토 흐름을 유지합니다.

## 명시값과 자동 입력의 우선순위

해당 원본 경로와 SHA256에 연결된 유효한 사용자 override → 정확히 해당 파일에 연결된 유효한 device.md 값 → 이름 규칙 순서입니다. 다른 파일의 날짜·광 조건을 복사하지 않습니다. null, unknown, unconfirmed 문자열이나 잘못된 날짜는 이름 규칙을 막지 않습니다. 반면 구체적인 날짜/light/dark가 명시되어 있고 확인 상태만 unconfirmed인 경우 그 값과 미확인 상태를 보존합니다.

명시값과 이름 규칙이 다르면 명시값을 유지하고 후보 및 확인 안내를 새 보고서에 함께 보여 줍니다. 자동 입력은 `source: folder_name/filename`, `verification: naming_rule`, `status: inferred`이며 사람의 확인 이력을 생성하지 않습니다. 사람의 확인 출처·상태·기존 override 이력은 유지합니다. 이름 규칙으로 온도, 단위, delay, 배선, 치수, 유전율, 광파워를 확인하지 않습니다.

## 설정

`config.json`의 다음 설정을 사용합니다. 기존 설정 파일에 항목이 없으면 읽는 동안 기본값을 적용하며 파일을 자동 수정하지 않습니다.

```json
"organization": {
  "path_rules": [],
  "naming_rules": {
    "date_from_folder": true,
    "excel_light_from_filename": true
  }
}
```

false로 바꾸면 해당 자동 규칙을 끕니다. 폴더명과 Excel 규칙은 여기서 정한 기본 규칙이며 path_rules로 Excel 광 조건을 다시 추정하지 않습니다. 설정을 바꾼 뒤 프로그램을 다시 시작하고 필요한 파일만 선택하여 처리하세요. 과거 노트 전체를 자동 갱신하지 않습니다. QC, RR 방향, gm 계산 및 비교 조건 문턱은 이 변경으로 바뀌지 않습니다.
