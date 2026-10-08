import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time

from . import __version__
from .config import Config, initialize
from .pipeline import retry_ai, scan
from .reports import backup, weekly
from .store import BusyError, Store


def output(value):
    print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def doctor(cfg):
    cfg.ensure_dirs()
    issues = []
    path_info = {}
    for name, path in cfg.paths.items():
        try:
            import tempfile
            with tempfile.TemporaryFile(dir=path):
                pass
            path_info[name] = {"path": str(path), "writable": True}
        except OSError:
            path_info[name] = {"path": str(path), "writable": False}
            issues.append(f"{name}: 쓰기 권한 확인 필요")
    if cfg.data["ai"]["enabled"] and not os.getenv("OPENAI_API_KEY"):
        issues.append("AI 활성화됨; OPENAI_API_KEY 없음 (수치 요약으로 계속 진행)")
    if os.name != "nt":
        issues.append("현재 검증 환경은 Windows가 아님; PowerShell/Task Scheduler는 Windows에서 확인 필요")
    packages = {}
    for package in ("pandas", "numpy", "scipy", "matplotlib", "openpyxl", "xlrd", "httpx", "fastapi", "uvicorn"):
        try:
            packages[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            packages[package] = "MISSING"
            issues.append(f"{package}: 설치 필요")
    store = Store(cfg)
    try:
        missing = [job["id"] for job in store.completed() if not Path(job["result_path"]).exists() or not Path(job["note_path"]).exists()]
    finally:
        store.close()
    if missing:
        issues.append(f"완료 작업의 출력 누락 {len(missing)}건; 원본이 inbox에 있으면 scan으로 재생성")
    return {"version": __version__, "python": sys.version.split()[0], "config": str(cfg.path), "axis": cfg.data["analysis"]["x"], "paths": path_info, "input_extensions": cfg.data["ingest"]["extensions"], "exclude_globs": cfg.data["ingest"]["exclude_globs"], "ai_enabled": cfg.data["ai"]["enabled"], "api_key_present": bool(os.getenv("OPENAI_API_KEY")), "packages": packages, "issues": issues, "missing_output_jobs": missing}


def demo(cfg):
    """Explicit command only: never mix synthetic files into a real Inbox at install."""
    import numpy as np
    import pandas as pd
    from .util import atomic_text
    x = np.linspace(-1, 1, 41)
    points = []
    for vg in (0.0, 2.0):
        for direction in ("forward", "reverse"):
            voltage = x if direction == "forward" else x[::-1][1:]
            for v in voltage:
                current = (1 + vg / 2) * 2e-8 * np.sinh(2 * v) + (2e-10 if direction == "reverse" else 0)
                points.append({"DrainV (V)": v, "GateV (V)": vg, "DrainI (nA)": current * 1e9, "GateI (nA)": .01})
    frame = pd.DataFrame(points)
    cfg.ensure_dirs()
    path = cfg.paths["inbox"] / "device=DEMO_measurement=synthetic.csv"
    if path.exists():
        raise FileExistsError("샘플 파일이 이미 있습니다.")
    atomic_text(path, "# SYNTHETIC DEMO ONLY\n# No real measurement or material claim\n" + frame.to_csv(index=False))
    return {"sample": str(path), "synthetic": True, "rows": len(frame)}


def main():
    parser = argparse.ArgumentParser(description="Keithley → QC/피팅 → AI(선택) → Obsidian 연구 자동화")
    parser.add_argument("--config", default="config.json", help="설정 파일 경로 (서브명령 앞에 지정)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="기본 설정과 로컬 폴더 생성")
    commands.add_parser("doctor", help="경로·패키지·출력·API 키 유무 확인")
    observe_cmd=commands.add_parser('observe',help='선택 측정의 모든 branch·수치·계산 근거를 새 폴더에 검토; 기존 노트/DB 보존')
    observe_cmd.add_argument('--source',action='append',help='Inbox 상대 경로; 반복 지정 가능')
    observe_cmd.add_argument('--all',action='store_true',help='Inbox 전체를 명시적으로 선택')
    report_cmd=commands.add_parser('report',help='선택 파일의 기본 파라미터·원시 그래프·모델과 잔차 보고서를 새 폴더에 생성')
    report_cmd.add_argument('--source',action='append',required=True,help='Inbox 상대 경로; 두 파일을 반복 지정하면 명시적 연결')
    report_cmd.add_argument('--no-pair',action='store_true',help='device.md의 연결을 사용하지 않고 선택 파일만 출력')
    scan_cmd = commands.add_parser("scan", help="신규/변경 파일 1회 처리")
    scan_cmd.add_argument("--retry-failed", action="store_true")
    scan_cmd.add_argument("--source",action="append",help="선택 원본의 Inbox 상대 경로; 반복 지정 가능")
    preview_cmd=commands.add_parser("preview",help="읽기 전용 변경 목록; 기존 노트 보존 확인")
    preview_cmd.add_argument("--source",action="append")
    commands.add_parser('audit-results', help='저장 결과 전체 점검 및 로컬 점검용 ZIP 생성; 기존 파일 수정 없음')
    refresh_cmd = commands.add_parser('refresh-plots', help='저장 수치를 재사용해 새 그래프만 내보내기')
    refresh_cmd.add_argument('--source', action='append', help='Inbox 상대 경로; 생략하면 최신 완료 결과 전체')
    notes_cmd = commands.add_parser("preview-notes", help="저장 결과로 새 노트 미리보기; 기본 종류별 1개, 재분석 없음")
    notes_cmd.add_argument("--source", action="append", help="선택 파일 Inbox 상대 경로; 반복 지정 가능")
    photo_cmd=commands.add_parser('preview-photo', help='명시적으로 선택한 dark/light 파일의 새 비교 노트; 기존 비교 보존')
    photo_cmd.add_argument('--dark',required=True,help='dark 원본 Inbox 상대경로')
    photo_cmd.add_argument('--light',required=True,help='light 원본 Inbox 상대경로; 다른 날짜는 이 선택으로만 검토')
    commands.add_parser("watch", help="폴더 주기 감시 (Ctrl+C 중단)")
    weekly_cmd = commands.add_parser("weekly", help="지정 날짜가 속한 ISO 주 집계")
    weekly_cmd.add_argument("--date", help="YYYY-MM-DD; 기본 오늘")
    commands.add_parser("backup", help="원본 스냅샷·결과·Vault·DB ZIP 백업")
    commands.add_parser("retry-ai", help="수치 분석 완료/AI 실패 작업의 AI 단계만 재시도")
    commands.add_parser("demo", help="설정의 inbox에 합성 예제 생성; 실측 폴더에 실행하지 마세요")
    status_cmd = commands.add_parser("status", help="작업 상태 조회")
    status_cmd.add_argument("--limit", type=int, default=30)
    serve_cmd = commands.add_parser("serve", help="선택형 n8n용 인증 HTTP API")
    serve_cmd.add_argument("--host", default="127.0.0.1")
    serve_cmd.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    try:
        if args.command == "init":
            cfg = initialize(args.config)
            output({"config": str(cfg.path), "created": True})
            return 0
        cfg = Config(args.config)
        if args.command=='report':
            from .benchmark_batch import generate
            from .store import lock
            with lock(cfg):result=generate(cfg,args.source,auto_pair=not args.no_pair)
            output(result);return 0
        if args.command=="preview":
            from .change_preview import preview
            output(preview(cfg,args.source));return 0
        if args.command == 'audit-results':
            from .result_review import audit_results
            output(audit_results(cfg));return 0
        if args.command == 'preview-photo':
            from .result_review import read_jobs,latest_jobs
            from .comparison_catalog import publish
            jobs=latest_jobs(read_jobs(cfg));sources=[args.dark,args.light]
            if not all(any(j['source']==s for j in jobs) for s in sources):raise ValueError('선택한 두 파일의 완료 저장 결과가 필요합니다.')
            output(publish(cfg,jobs,selected_sources=sources));return 0
        if args.command == "preview-notes":
            from .note_preview import preview_notes
            output(preview_notes(cfg, args.source));return 0
        if args.command == 'refresh-plots':
            from .result_review import refresh_plots
            output(refresh_plots(cfg, args.source));return 0
        if os.name=="nt" and args.command in ("scan","watch","doctor") and any(not cfg.paths[k].is_dir() for k in ("inbox","vault")):
            raise ValueError("현재 PC의 Inbox/Vault 경로를 찾지 못했습니다. GUI에서 실제 폴더를 선택하세요.")
        if args.command=='observe':
            from .observation_batch import observe
            from .pipeline import candidates
            if args.all and args.source:raise ValueError('--all과 --source 중 하나를 선택하세요.')
            sources=[p.relative_to(cfg.paths['inbox']).as_posix() for p in candidates(cfg)] if args.all else args.source
            result=observe(cfg,sources);output(result)
            return 1 if any(r['status']=='failed' for r in result['files']) else 0
        cfg.ensure_dirs()
        if args.command == "doctor":
            output(doctor(cfg))
        elif args.command == "demo":
            output(demo(cfg))
        elif args.command == "scan":
            result = scan(cfg, args.retry_failed,sources=args.source)
            output(result)
            return 1 if any(result["counts"][state] for state in ("failed", "blocked", "rejected")) else 0
        elif args.command == "watch":
            output({"watching": str(cfg.paths["inbox"]), "poll_seconds": cfg.data["ingest"]["poll_seconds"]})
            while True:
                try:
                    result = scan(cfg)
                    if any(result["counts"][state] for state in ("completed", "failed", "blocked", "rejected")):
                        output(result)
                except BusyError:
                    pass
                time.sleep(cfg.data["ingest"]["poll_seconds"])
        elif args.command == "weekly":
            output(weekly(cfg, args.date))
        elif args.command == "backup":
            output(backup(cfg))
        elif args.command == "retry-ai":
            output(retry_ai(cfg))
        elif args.command == "status":
            store = Store(cfg)
            try:
                output(store.recent(max(1, min(args.limit, 1000))))
            finally:
                store.close()
        elif args.command == "serve":
            import uvicorn
            from .service import create_app
            uvicorn.run(create_app(cfg), host=args.host, port=args.port)
        return 0
    except KeyboardInterrupt:
        output({"stopped": True})
        return 0
    except BusyError as error:
        output({"status": "busy", "message": str(error)})
        return 0
    except Exception as error:
        output({"status": "error", "type": type(error).__name__, "message": str(error)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
