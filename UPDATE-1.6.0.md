# v1.6.0 업데이트

Windows 백업/파일 핸들 오류를 수정하고, 선택한 결과에서 조건과 계산 근거를 쉽게 확인하도록 개선했습니다. 연구노트 형식 2와 반복 근거 저장 schema 3을 추가합니다. 기존 과학 계산의 QC 문턱과 원본·연구자 메모를 보존합니다.

## 시작

1. 실행 중인 앱/감시를 종료합니다.
2. Release의 Windows ZIP을 **새롭고 짧은 폴더**(예: `C:\ResearchQA`)에 풉니다. 구버전 프로그램·설정·결과를 덮어쓰지 마세요.
3. `Start-Local-QA.cmd`를 실행합니다. Python 3.12·Tcl/Tk·의존성이 포함되어 Setup.cmd 없이 실행합니다. qa-runtime의 별도 입력/분석/Vault/DB를 기본으로 사용합니다.
4. 대표 파일을 복사해서 선택 분석하거나 기존 결과를 검토합니다. 측정 조건/출처를 먼저 확인하고 **RR / gm 계산 근거**와 선택 노트 미리보기를 엽니다. 자동 감시는 직접 시작한 경우에만 실행됩니다.
5. 기존 데이터 경로를 연결하려면 GUI에서 경로를 확인하고 변경 미리보기로 출력 위치를 검토하세요. 신규 산출물은 v1.6.0 아래에 저장하며 과거 노트 전체 갱신은 필요 없습니다.

## 지표와 호환성

RR은 `abs(I(+u))/abs(I(-u))`이며 평가 전압·방향·획득 이력이 필수입니다. 낮은 분모는 검출한계 상태입니다. gm 끝점/평활 폭/단위를 구별하고 이동도는 signed gm과 Vds를 사용한 후보입니다. ±20 V와 ±40 V의 원래 stress 조건은 crop 후에도 자동 비교하지 않습니다. QC PASS는 연구 검토 완료가 아닙니다. 단위·광 조건·날짜·시간·delay는 임의 확정하지 않습니다.

각 지표의 value/unit/availability/reason/extraction_method/bias_condition/provenance와 원본 셀을 보존합니다. 반복 근거는 metric_evidence.json 한 곳에 저장합니다. JSON/CSV를 이동할 때 이 파일을 **같은 폴더에 함께 이동**하세요. schema 1/2를 계속 읽으며 schema 3은 `research_automation.metric_store.read_metric_json`으로 원래 논리 구조를 복원합니다. 일반 JSON 포인터 도구가 압축 테이블을 직접 해석하지는 못합니다.

```bat
runtime\python.exe -m research_automation.metric_store research_report.json
runtime\python.exe -m research_automation.metric_store research_report.json --expand research_report-expanded.json
```

확장 파일은 커질 수 있으며 기존 파일을 덮어쓰지 않습니다. 작업용 사본 두 개의 JSON과 근거 그래프 합계는 95% 이상 감소했고 전체 필드·자료형·순서·CSV 셀·원본 셀 참조의 동일성을 검사했습니다. 측정 데이터와 로컬 QA 결과는 공개하지 않습니다.

## 검증과 한계

Windows 전체 184개 회귀, 깨끗한 패키지의 42개 집중 회귀, 실제 Tk 위젯/작업 스레드/CMD 런처를 검증했습니다. 버전 갱신 후 전체 테스트를 다시 실행합니다. 정확한 릴리스 커밋의 Windows/Ubuntu 결과는 [Actions](https://github.com/LWJ0604/hi/actions)에서 확인하세요.

깊은 경로는 Windows MAX_PATH 제한이 남아 있습니다. **짧은 폴더를 사용하세요.** GUI 픽셀 스크린샷·실제 Obsidian·Explorer 더블클릭·작업 스케줄러·외부 AI·계측기 제어는 미검증입니다. TLM 자동 피팅, cross-run 자동 차감, 전체 인터랙티브 편집기는 이번 범위에 포함하지 않습니다. [세부 검증](LOCAL-WINDOWS-REVIEW.md), [노트 형식](RESEARCH-NOTE-V2-LOCAL.md)
