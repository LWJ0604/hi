# 1.4.1: 음수 표시 수정과 저장 결과 점검

Windows 폰트에서 마이너스가 사각형으로 보이는 문제를 수정했습니다. Matplotlib의 Unicode minus(U+2212)를 일반 하이픈(U+002D)으로 표시합니다. x/y축·색상 막대에 적용하며 signed 측정값, RR, gm과 피팅 결과는 바꾸지 않습니다. 기존3 pt·무지개·축 단위·300 dpi 테마를 유지합니다.

## 이미 전체 분석을 마친 경우

1. GUI/감시를 닫고 업데이트 ZIP을 기존 프로그램 폴더에 복사합니다. 활성 config.json·원본·DB·분석 결과는 ZIP에 포함하지 않습니다.
2. `Start-GUI.cmd`를 실행합니다. 그래프 수정에는 **한 번 분석을 누를 필요가 없습니다**.
3. 완료 파일 선택 → **선택 그래프 갱신**. 기존 curves.csv와 저장 피팅을 사용해 `Attachments/v1.4.1/PlotRevisions/...`에 새 그림, `Experiments/v1.4.1/그래프 갱신/...`에 보기 노트를 만듭니다. 기존 노트/그림과 수치를 보존합니다.
4. 전체 그림을 갱신하려면 `Refresh-Plots.cmd`를 실행합니다. 출력량에 따라 시간이 걸릴 수 있습니다. 새 경로로 내보내며 원본을 다시 파싱하거나 피팅하지 않습니다.
5. GUI의 **전체 결과 점검** 또는 `Audit-Results.cmd`로 현재 입력/저장 결과를 점검합니다. 끝나면 `analysis/audits/v1.4.1/<시간>/`의 `report.md`, `audit.json`, `metrics.csv`, `result-audit.zip`을 확인하세요. GUI는 이 폴더를 엽니다.

## 점검 범위

현재 입력파일의 SHA와 완료 작업 대응, 원본과 저장 SHA 차이, 최신 완료 결과의 JSON/필수CSV/그림 존재, 노트 상대 링크, RR의 평가 전압/단위, 끝점 gm 잘못 인증 여부, 단위/메타데이터 확인 상태를 검사합니다. 파일 존재와 계산/확인 상태의 점검이며 모든 지표를 원본에서 독립 재계산하거나 PNG 픽셀/물리 조건을 인증하는 기능은 아닙니다.

점검 ZIP은 파일명·해시·요약 지표·확인 상태를 포함합니다. 원시 측정점, 원본 측정파일, 이미지, API 키, 활성 설정, DB는 넣지 않으며 외부로 자동 전송하지 않습니다. 실제 전체 결과를 검토받으려면 생성된 `result-audit.zip`을 이 대화에 첨부할 수 있습니다.

완료 기록이 모두 있어도 units_review_needed, metadata_review_needed가 남을 수 있습니다. 이는 ‘파일 추출 실패’와 다르며 V/A 단위·광 조건·전극·이력 등의 확인이 필요하다는 뜻입니다. 이번 환경에서는 Windows의 실제 전체 Vault에 접근하지 못했습니다. 이전 첨부3개 복사본만 직접 점검했습니다.

CLI:

```powershell
.\.venv\Scripts\python.exe -m research_automation --config config.json audit-results
.\.venv\Scripts\python.exe -m research_automation --config config.json refresh-plots
.\.venv\Scripts\python.exe -m research_automation --config config.json refresh-plots --source "drain-fold/2026-09-23/Id-Vd_dark.xls"
```

새로 수치 분석을 시작하면 기존1.4.0 결과와 별도의1.4.1 결과가 생깁니다. 화면 표시 수정만 필요한 경우 위의 그래프 갱신 기능을 사용하세요. 전체 설치·과학 분석 기준은 README.md와 docs/과학분석-v1.4.0.md를 참고하세요.
