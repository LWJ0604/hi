import hmac
import os

from fastapi import Depends, FastAPI, Header, HTTPException

from .pipeline import scan
from .reports import backup, weekly
from .store import BusyError, Store


def create_app(cfg):
    token = os.getenv("RESEARCH_API_TOKEN", "")
    if len(token) < 24:
        raise ValueError("serve는 24자 이상의 RESEARCH_API_TOKEN이 필요합니다.")
    app = FastAPI(title="Local Research Automation", docs_url=None, redoc_url=None, openapi_url=None)

    def authorize(authorization: str = Header(default="")):
        if not hmac.compare_digest(authorization.encode(), ("Bearer " + token).encode()):
            raise HTTPException(status_code=401, detail="인증 필요")

    def operation(function):
        try:
            return function(cfg)
        except BusyError:
            raise HTTPException(status_code=409, detail="다른 작업 실행 중; 다음 주기에 재시도")

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/status", dependencies=[Depends(authorize)])
    def status():
        store = Store(cfg)
        try:
            return store.recent(100)
        finally:
            store.close()

    @app.post("/scan", dependencies=[Depends(authorize)])
    def run_scan():
        return operation(scan)

    @app.post("/weekly", dependencies=[Depends(authorize)])
    def run_weekly():
        return operation(weekly)

    @app.post("/backup", dependencies=[Depends(authorize)])
    def run_backup():
        return operation(backup)

    return app
