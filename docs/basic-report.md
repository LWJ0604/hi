# 원시 측정과 기초 파라미터 보고서

Windows ZIP을 새 폴더에 풀고 `Start-Local-QA.cmd`를 실행합니다. 기본 입력·출력은 패키지 안의 `qa-runtime` 폴더에 격리되어 있습니다. 실제 측정 폴더를 사용하려면 GUI에서 입력 폴더를 선택합니다. 보고서만 생성할 때도 Vault 경로를 기존 노트와 분리해 두는 것을 권장합니다.

GUI의 **파일 선택 → 기본 보고서**에서 입력 폴더 안의 CSV/XLS/XLSX를 고릅니다. 한 파일은 독립적으로 처리합니다. 두 파일을 선택하면 사용자가 지정한 잠정 연결입니다. 한 파일만 골라도 가장 가까운 `device.md`가 IdVd와 IdVg의 정확한 상대 파일명을 명시한 경우 두 파일을 연결합니다. 파일명 유사성이나 날짜만으로 다른 파일을 짝짓지 않습니다. 보고서는 항상 새 분석 폴더에 생성합니다. 기존 Obsidian 노트, 측정 원본과 `device.md` 아래의 사용자 메모는 수정하지 않습니다.

CLI에서 같은 기능을 실행합니다. 경로에 한글·공백이 있으면 따옴표를 사용합니다.

```powershell
runtime\python.exe -m research_automation --config qa-config.json report --source "원본\출력.xls"
runtime\python.exe -m research_automation --config qa-config.json report --source "원본\출력.xls" --source "원본\transfer.xls"
runtime\python.exe -m research_automation --config qa-config.json report --source "원본\출력.xls" --no-pair
```

기존 `scan`과 GUI의 한 번 분석·감시도 이 보고서를 생성합니다. 새 버전 결과와 노트만 추가하고 이전 파일을 보존합니다. 감시는 사용자가 시작해야 실행됩니다. 보고서에는 기초 수치·원시 그래프·모델과 잔차를 표시하며 상세 수치와 원본 셀은 CSV, 읽기/최적화 진단은 `diagnostics`에 분리합니다. 기존 `observe` 명령의 branch 검토와 기존 계산 파일도 유지됩니다.

기본 자동 처리에서는 기록 블록 전체를 한 번 그립니다. 이전 방식의 trace별 그림을 중복 생성하지 않아 큰 wide-sheet에서도 출력 파일 수를 줄입니다. 기존 수치 CSV/JSON은 보존하며 `benchmark.enabled: false`로 이전 보고서·그림 경로를 사용할 수 있습니다. 저장 결과의 `refresh-plots`와 명시적 `observe`도 상세 검토에 사용할 수 있습니다.

## 단위와 소자 정보

앱의 공용 기본 설정은 단위 미확인입니다. GUI의 **내 측정의 단위 없는 열은 전압 V / 전류 A로 확인**을 사용자가 선택하면 그 사용자 설정에 출처와 확인 시각을 저장하고 이전 설정을 사본으로 보존합니다. 확인을 선택하지 않아도 원시 그래프와 같은 전류열의 범위비를 표시하며 SI 가정임을 밝힙니다. 단위에 의존하는 RR·gm·모델 계수는 값 대신 보류 이유를 남깁니다. 파일 헤더에 nA/mA/mV 등 단위가 명시되면 파일 단위를 우선 환산하고 사용자 기본값과 충돌을 표시합니다. 단위 확인으로 검출한계·선형영역·측정일을 확인한 것으로 처리하지 않습니다.

`device.md`는 입력 폴더 또는 그 아래 소자/날짜 폴더에 둡니다. 상위 정보가 상속되며 가까운 파일의 값이 우선합니다. `metadata_root`가 없으면 입력 폴더까지만 탐색합니다. 입력 폴더가 `원본` 또는 `raw`이고 바로 상위에 `device.md`가 있으면 그 상위까지만 읽습니다. 상위에 다른 소자 이름을 덮어쓴 경우 기존 소자의 geometry를 이어 쓰지 않습니다.

아래 예시는 양식이며 실측 확인값을 뜻하지 않습니다. 직접 확인하지 않은 항목은 `value: null`, `verification: unconfirmed`로 둡니다. 전극쌍이 여러 개면 `active_electrode_pair` 또는 설정의 `benchmark.electrode_pair`로 계산 대상만 명시적으로 지정합니다.

```yaml
---
schema_version: 1
device_name: {value: null, source: null, verification: unconfirmed}
active_electrode_pair: null
structure:
  gate_dielectric:
    thickness: {value: null, unit: nm, source: null, verification: unconfirmed}
    relative_permittivity: {value: null, unit: dimensionless, source: null, verification: unconfirmed}
electrode_pairs:
  my_pair:
    L: {value: null, unit: um, source: null, verification: unconfirmed}
    W: {value: null, unit: um, source: null, verification: unconfirmed}
run_conditions:
  temperature: {value: null, unit: degC, source: null, verification: unconfirmed}
  IdVd:
    file: "원본/출력.xls"
    measurement_date: {value: null, source: null, verification: unconfirmed}
    illumination: {value: null, source: null, verification: unconfirmed}
  IdVg:
    file: "원본/transfer.xls"
    measurement_date: {value: null, source: null, verification: unconfirmed}
reference_inputs:
  mobility_cm2_Vs: {value: null, source: null, verification: not_provided}
---
사용자 메모를 여기에 남깁니다. 자동 분석은 이 파일을 덮어쓰지 않습니다.
```

YAML은 제한된 SafeLoader로 읽고 실행 객체·중복 키·순환 참조·지나친 크기·범위 밖 파일 연결을 거부합니다. 잘못된 메타데이터는 적용하지 않고 원시 데이터와 계산 가능한 결과를 유지합니다. 실제 날짜는 명시한 해당 파일에만 적용하며 장비 시각은 참고로 보존합니다.

하위 `device.md`에서 값·단위·출처·확인 상태 중 일부를 수정하면 그 필드는 **전체 교체**합니다. 예를 들어 상위에 확인된 `L: {value: 1.5, unit: um, source: ..., verification: user_confirmed}`가 있어도 하위의 `L: {value: 9}`는 단위 미확인·출처 없음·미확인 상태입니다. 이전 단위와 확인 근거를 새 값에 붙이지 않으며 이동도 계산을 보류합니다. 같은 단위여도 단위·출처·확인 상태를 새 레코드에 명시해야 합니다. 편집 자체를 사용자 확인으로 처리하지 않습니다. 수정하지 않은 W 등 다른 필드는 계속 상속됩니다.

단위 프로필과 전극 재료의 공통 확인 근거도 한 레코드로 교체합니다. 하위 조건에서 측정 `file`을 다시 선언하면 그 파일의 날짜·광 조건 등도 새 파일 조건으로 교체하며 이전 파일의 확인 정보를 가져오지 않습니다. 잘못된 목록·객체·숫자/문자열 타입은 필드별로 격리하고 경고를 표시합니다. 잘못된 전극쌍 선택을 설정의 다른 전극쌍으로 자동 대체하지 않습니다. 해당 조건에 의존하는 계산을 보류하고 원시 그래프와 독립적으로 계산 가능한 지표는 유지합니다.

## 계산 근거와 범위

RR은 원본에 정확히 존재하는 ±u 점의 `|I(+u)|/|I(−u)|`이며 평가 전압·원본 셀 주소를 CSV에 저장합니다. 분모가 0이거나 확인한 검출한계 아래면 값과 이유를 분리합니다. 전압의 실제 반전·정지·행 간격으로 기록 구간을 나누고 블록/방향/순서를 보존합니다. 범위를 자르거나 평균해 서로 다른 gate stress를 비교 가능하게 만들지 않습니다.

gm은 실제 전압 간격의 중앙차분과 국소 2차식의 2/4/8 V 창으로 비교합니다. 끝점과 불완전한 창은 보류합니다. 이동도 단위 참고값은 확인된 선택 전극쌍 L/W, 산화막/Cox와 Vd가 있을 때만 계산하며 입력 이동도와 구분합니다. 선형영역이 확인되지 않으면 물리적 이동도로 확정하지 않습니다.

비교식은 `j=Is(exp(u/a)-1)`과 `u=a ln(1+j/Is)+j Rs`입니다. 기본식과 직렬저항식의 offset은 0 고정이며 같은 구간·원본점을 사용합니다. 극성별 절댓값 근사와 양극성 단일 다이오드 참고식을 분리합니다. 전체 gate 계수/점별 잔차, 구간·offset 민감도, 대표 Rs 고정 프로파일을 CSV로 제공합니다. Rs/a/Is와 큰 유효 n, 강한 a–Rs 상관은 유효 모델 계수의 식별성 한계를 나타내며 접촉 장벽·고유 저항·전류 경로를 증명하지 않습니다.

수치 구현은 [SciPy Wright omega](https://docs.scipy.org/doc/scipy/reference/generated/scipy.special.wrightomega.html)와 [least_squares](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.least_squares.html)를 사용합니다. [ngspice 다이오드 문서](https://ngspice.sourceforge.io/docs/ngspice-manual.pdf)는 비교식의 배경 자료입니다.
