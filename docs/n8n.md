# n8n 선택형 연결

기본 Windows 감시/예약 실행을 먼저 확인합니다. 아래 경로는 n8n을 이미 사용하는 연구실을 위한 선택 사항입니다. 제공 워크플로를 실제 n8n에 가져와 실행하는 검증은 현재 환경에서 수행하지 않았습니다.

## Python API 실행

프로그램 폴더에서 PowerShell을 열고 인증 토큰을 만든 뒤 API를 실행합니다. 이 토큰은 OpenAI API 키와 별개입니다.

```powershell
$TokenBytes = New-Object byte[] 32
$Generator = [Security.Cryptography.RandomNumberGenerator]::Create()
$Generator.GetBytes($TokenBytes)
$Generator.Dispose()
$env:RESEARCH_API_TOKEN = [Convert]::ToBase64String($TokenBytes)
$env:RESEARCH_API_TOKEN | Set-Clipboard
.\.venv\Scripts\python.exe -m research_automation --config config.json serve --host 127.0.0.1 --port 8765
```

24자 이상 토큰이 없으면 API 서버는 시작하지 않습니다. `/health`를 제외한 상태 조회와 실행 엔드포인트는 모두 Bearer 인증을 요구합니다. 파일 업로드나 임의 명령 실행 엔드포인트는 제공하지 않습니다.

| 메서드 | 경로 | 의미 |
|---|---|---|
| GET | /health | 서버 생존 확인 |
| GET | /status | 최근 작업 100건 |
| POST | /scan | 1회 스캔 |
| POST | /weekly | 현재 ISO 주 보고 |
| POST | /backup | 백업 |

동시에 다른 작업이 실행 중이면 409를 반환합니다. 스캔의 HTTP 200은 요청 자체가 처리됐다는 의미이며, 파일별 실패는 응답의 `counts.failed/blocked/rejected`를 확인합니다.

## 워크플로 가져오기

1. n8n의 Import from File에서 `workflows/n8n-research-automation.json`을 가져옵니다. 기본 비활성 상태입니다.
2. Header Auth credential을 만듭니다. Name은 `Authorization`, Value는 `Bearer ` 뒤에 복사한 토큰입니다. 각 POST 노드에 같은 credential을 지정합니다. 토큰은 워크플로 파일에 저장하지 않습니다. 복사 완료 후 클립보드를 비워도 됩니다.
3. n8n을 Windows에서 실행하면 POST 노드 URL의 호스트를 `127.0.0.1:8765`로 바꿉니다.
4. Docker Desktop의 n8n이면 기본 URL인 `host.docker.internal:8765`를 사용합니다. Python API를 `--host 0.0.0.0`으로 다시 시작하고 Windows 방화벽은 필요한 Docker/사설 네트워크 접근만 허용합니다. API를 인터넷 공개 주소로 노출하는 구성은 포함하지 않았습니다.
5. 각 노드를 수동 실행해 인증/경로/응답을 확인한 다음 워크플로를 활성화합니다. n8n timezone은 Asia/Seoul이며 기본 일정은 1분 스캔, 금요일 18시 주간 보고, 매일 19시 백업입니다.

API 서버를 켜둬야 요청이 실행됩니다. 재시작할 때 토큰을 새로 만들면 n8n credential도 갱신해야 합니다. 프로세스 환경변수에 고정 토큰을 제공하는 운영 방식도 가능합니다. 요청 제한 시간은 300초입니다. 매우 큰 Inbox는 수동으로 먼저 처리하거나 n8n HTTP timeout을 늘립니다. Python 내부 모델 피팅이나 개별 AI 요청에도 시간이 걸릴 수 있습니다.

Windows 예약 작업과 n8n을 동시에 활성화하면 잠금으로 데이터 중복은 막지만 실행이 불필요하게 겹칩니다. 예약은 한쪽을 선택하세요. n8n Cloud는 이 로컬 주소에 접근할 수 없으므로 그대로 연결되지 않습니다.
