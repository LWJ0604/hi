# 1.2.1 — 표기 없는 파일의 dark 기본값과 API 키 등록

파일명에 dark/light 표기가 없으면 dark로 저장합니다. 조명 출처는 `default/unmarked_filename_dark`로 남겨 실제로 dark라고 쓴 파일과 구분합니다. 명시된 파일명은 기본값과 조건 폴더보다 우선하며 충돌 후보는 확인 표시로 남깁니다. 기존 organization.path_rules의 명시적 사용자 지정은 유지됩니다.

## 적용

감시를 Ctrl+C로 중지한 뒤 ZIP 내용물을 기존 Setup.cmd가 있는 폴더에 덮어쓰고 Start-Watch.cmd를 다시 실행합니다. 기존 config.json/DB/Vault는 덮어쓰지 않습니다. 1.0.0~1.2.0에 적용 가능한 누적 업데이트이며 추가 Python 패키지가 필요하지 않습니다. 코드 업데이트로 기존 파일도 새 분석 버전으로 처리되고 AI가 켜져 있으면 추가 API 비용이 발생할 수 있습니다. 이전 결과는 보존합니다.

## API 키 등록

1. https://platform.openai.com/api-keys 에서 OpenAI API 계정의 키를 만듭니다. API 사용은 ChatGPT 구독과 별도로 청구되며 API 계정의 결제/잔액도 확인하세요.
2. 프로그램 폴더의 `Register-API-Key.cmd`를 실행합니다.
3. 키를 붙여넣고 Enter를 누릅니다. 입력한 키는 화면에 보이지 않습니다.
4. config.json의 ai.enabled를 true로 설정한 뒤 감시 창을 다시 시작합니다.

등록 도구는 현재 Windows 사용자의 OPENAI_API_KEY 환경변수에 저장합니다. 키를 config.json이나 연구노트에 저장하지 않고 실제 API 요청도 하지 않습니다. Windows에서 직접 실행하는 검증은 이 클라우드에서 수행하지 못했습니다.

등록 도구 대신 CMD에서 아래 명령을 실행할 수도 있습니다. 예시 문자열을 실제 키로 바꾸세요.

```cmd
setx OPENAI_API_KEY "여기에_실제_API_키"
```

새 CMD 창에서 아래 명령으로 등록 여부만 확인할 수 있습니다. 키 값은 표시하지 않습니다.

```cmd
if defined OPENAI_API_KEY (echo API key registered) else (echo API key missing)
```

기존 실행 중인 Python 감시는 종료 후 다시 실행해야 새 환경변수를 사용합니다. 함께 포함된 run-job.ps1은 User 환경변수를 읽습니다. 키 등록만으로 AI가 활성화되지는 않으며 config.json에서 ai.enabled를 true로 설정해야 합니다.

회귀 테스트 75개 통과. 첨부된 실제 Id–Vg XLS의 파일명에서 조명 표기를 제거한 시험 입력을 dark로 분석·저장했고 161개 측정행의 원본 숫자를 보존했습니다. 유료 API 호출은 하지 않았습니다. 자세한 증거는 verification-v1.2.1.json 및 test-results-v1.2.1.txt에 있습니다.
