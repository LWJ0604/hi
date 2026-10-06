# 연구노트 출력 계약 2 — Windows 로컬 작업본

이 작업본은 기존 앱에 `fet-research-note-2` 출력을 추가합니다. 기존 측정 원본, 계산 결과, QC 문턱, 사용자 노트는 덮어쓰지 않습니다. 기존 결과는 새 버전 폴더와 선택 미리보기로 구별합니다.

## 실행

설치가 필요 없는 ZIP을 빈 폴더에 풀고 `Start-Local-QA.cmd`를 실행하세요. QA 입력은 `qa-runtime/data_inbox`, 결과는 `qa-runtime/analysis`, 새 노트와 그림은 `qa-runtime/vault`에 저장됩니다. 실행만으로 분석을 시작하지 않습니다. 파일을 복사한 뒤 GUI에서 입력을 선택하여 처리하세요.

기존 저장 결과는 GUI의 선택 노트 미리보기로 새 형식을 만들 수 있습니다. 이전 결과의 CSV/JSON과 Figure 2 PNG는 새 미리보기의 `prior_` 파일로도 보존하며, 원래 노트는 바꾸지 않습니다. 전체 과거 노트의 일괄 갱신은 필요하지 않습니다.

## 출력과 판단

- 연구 질문, 조건, 현재 판단과 최대 3개 수치를 먼저 표시합니다. 구조/조건 표는 값·추정/확인/충돌·출처를 함께 표시합니다.
- Figure 2 a–m 순서를 유지합니다. a는 실제 구조 이미지가 없으면 표, d는 실제 output, e는 직접 log-current 미분 SS, i는 signed G, j/k는 저장된 raw/local gm 및 서로 다른 정규화, m은 signed μFE 후보입니다.
- `figure2_manifest.json`은 생성/미생성/보류/실패를 구분하고 읽기 검증한 PNG의 hash·크기를 기록합니다. 존재하지 않거나 읽을 수 없는 PNG를 새 본문에 링크하지 않습니다.
- `research_report.json`은 직접 SS의 원본 세 점·미분 가중치, 원래 sweep/방향/블록, 극성별 원본 지원점, 독립적인 의존 조건을 기록합니다. Signed 전류 보간은 양쪽 bracket 전압·전류·원본 행/셀·가중치를 기록합니다. Transfer 극성 짝은 정확한 Vg 매칭만 지원합니다.
- RR은 `abs(I(+u))/abs(I(-u))` 방향을 고정합니다. 조건/history 또는 검출한계가 미확인이면 새 RR/ΔG/AG는 보류합니다. 음전류만 미검출이면 하한, 양전류만 미검출이면 보류합니다. 하한을 최대 RR로 순위화하지 않습니다.
- G+ = Id(+u)/u, G− = Id(−u)/(−u)는 부호를 보존합니다. 비대칭도만 ΔG = abs(G+)−abs(G−), AG = ΔG/(abs(G+)+abs(G−))를 사용합니다.
- 새 지표의 정규 계약은 `value`, `unit`, `availability`, `reason`, `extraction_method`, `bias_condition`, `provenance`입니다. `research_report.json`의 `metric_records`와 `research_metrics.csv`에 전체 새 지표를 모으며, 개별 `direct_metrics`, FET `points`/`extractions`, SS/극성별 `metrics`에도 보존합니다. `availability`는 available/candidate/held/unavailable이며 보류·추출 불가의 value는 null입니다. 계산 후보나 하한은 별도 필드에 남습니다. 출처에는 파일·sheet·행·셀·trace, 캐시된 원본값, header의 SI 환산 계수, configured scale, 평가 구간과 폭 환산을 기록합니다.
- 기존 `ln(10)|Id/gm|` SS와 새 직접 `log10|Id|` 미분 SS는 별도입니다. 자동 10–30% 구간, YFM 모델, μFE 선형 영역을 단위 확인만으로 승격하지 않습니다. μFE SI→cm²/(V s)는 ×10⁴이며 signed gm과 Vds를 사용합니다.
- TLM/Rc/nS/Rsh/μcon/Isat/DIBL 자료가 없으면 사유와 필수 입력을 표시합니다. Rs, V/I, 1/gds를 Rc로 명명하지 않습니다. QC PASS는 물리 모델 검증이 아닙니다.
- 전체 원본 근거, 이전 그림·CSV/JSON·QC·미확인 값은 접힌 감사 영역에 남습니다. 사용자 확인 날짜와 시간 미상은 메타데이터 상태를 그대로 표시합니다.
- 노트 frontmatter의 `metadata_status`, `metadata_review_required`, `measurement_date_status`, `measurement_time_status`는 저장된 상태를 그대로 사용합니다. 추정 날짜를 확인 상태로 바꾸지 않아 속성 검색에서도 검토 대상을 구분할 수 있습니다.

## 공유 근거 저장 · 스키마 호환

새 `fet_parameters.json`과 `research_report.json`의 디스크 schema_version/metric_contract_version은 3입니다. 반복 지표·원본점·sheet/trace 매핑·조건·방법·변환은 같은 폴더의 `metric_evidence.json`에 한 번 저장하며, `$ref: metric_evidence.json#/tables/종류/내용ID`로 연결합니다. 공유 테이블은 공통 필드와 열별 사전을 사용합니다. 값, JSON 타입, 누락 필드, 원본점 순서, 모든 추가 속성을 보존하고 내용 ID·모든 참조를 검사합니다. 단순 필드 생략이나 데이터 반올림은 하지 않습니다.

앱은 `research_automation.metric_store.read_metric_json(path)`로 참조를 풀어 기존 스키마 2의 전체 지표 딕셔너리를 읽습니다. 기존 스키마 1/2 JSON도 그대로 읽습니다. 새 지표를 해석한 뒤에는 value/unit/availability/reason/extraction_method/bias_condition/provenance와 원본 셀·변환 기록이 모두 유지됩니다. CSV의 필수 7필드도 남고 복합 필드는 같은 공유 테이블 참조를 사용합니다. `metric_ref`와 `evidence_document` 열로 전체 지표 및 원본 셀 근거를 찾습니다. JSON/CSV를 옮길 때 `metric_evidence.json`을 같은 폴더에 함께 옮기세요.

참조 검사: `runtime\python.exe -m research_automation.metric_store research_report.json`

기존 외부 도구용 확장 JSON: `runtime\python.exe -m research_automation.metric_store research_report.json --expand research_report-expanded.json`

확장 출력은 큰 파일이 될 수 있습니다. 명령은 기존 출력 파일을 덮어쓰지 않습니다. 공유 테이블 변경은 기존 ID를 유지하면서 추가하고, 근거 저장 후 참조 문서를 게시하므로 실패해도 기존 문서의 참조는 유지됩니다. 선택 미리보기는 이전 공유 테이블도 prior_metric_evidence.json으로 보존합니다.

기존의 큰 스키마 1/2 JSON·CSV를 선택 미리보기에 복사하는 경우 새 prior_ 사본도 같은 공유 근거로 무손실 정규화합니다. 원래 파일·노트·DB는 그대로이고 모든 필드·CSV 원문 셀·지원점은 해석 후 복원됩니다. 원본/정규화 사본 hash와 크기는 note_presentation.json의 legacy_copy_storage_normalization에 기록합니다. 이미 참조를 쓰는 스키마 3 prior_ 사본은 byte 그대로 보존합니다.

## 범위와 제한

Windows Tk의 실제 위젯/상태와 런처는 자동화 검증합니다. 실제 Obsidian 앱 화면과 Explorer 더블클릭 설치 검증은 별도입니다. 단순 PNG 디코딩과 사람이 그림을 열어 읽는 검증도 구분합니다. TLM 자동 피팅, cross-run 자동 조합, transfer 전류 보간, 독립 반복 수 확인은 이번 범위에서 구현하지 않습니다.

프로젝트 CI 지침은 `python -m unittest discover -s tests -v`입니다. 별도 lint/typecheck 명령은 설정되어 있지 않아 compileall과 Git 공백 검사를 보조적으로 사용합니다.
