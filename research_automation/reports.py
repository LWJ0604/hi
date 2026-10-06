import hashlib
from contextlib import closing
import json
import os
from pathlib import Path
import tempfile
import zipfile
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .ai import interpret
from . import __version__, code_fingerprint
from .render import escape
from .store import Store, lock
from .util import atomic_text, digest, now, write_json
from .organization import csv_context


def weekly(cfg, on_date=None):
    with lock(cfg):
        zone = ZoneInfo(cfg.data["timezone"])
        target = date.fromisoformat(on_date) if on_date else now(cfg).date()
        monday = target - timedelta(days=target.weekday())
        start = datetime.combine(monday, time.min, zone)
        end = start + timedelta(days=7)
        store = Store(cfg)
        try:
            jobs = [job for job in store.completed() if start <= datetime.fromisoformat(job["completed_at"]).astimezone(zone) < end]
        finally:
            store.close()
        # Reanalysis of identical raw data is one measurement in the readout.
        latest = {}
        for job in jobs:
            latest[(job["source"], job["source_hash"])] = job
        summaries, missing = [], []
        for job in latest.values():
            try:
                value = json.loads(Path(job["result_path"]).read_text(encoding="utf-8"))
                summaries.append((job, value))
            except (OSError, ValueError):
                missing.append(job["id"])
        year, week, _ = monday.isocalendar()
        report_id = f"{year}-W{week:02d}"
        counts = {status: sum(s["qc"]["overall"] == status for _, s in summaries) for status in ("PASS", "WARN", "FAIL")}
        data = {"report_id": report_id, "generated_at": now(cfg).isoformat(), "timezone": cfg.data["timezone"], "start_inclusive": start.isoformat(), "end_exclusive": end.isoformat(), "cohort_basis": "분석 완료 시각; 실제 측정 시각은 아님. 측정 날짜는 별도 표시", "measurements": len(summaries), "qc_counts": counts, "missing_result_jobs": missing, "jobs": [{"job_id": job["id"], "source": job["source"], "source_hash": job["source_hash"], "note": Path(job["note_path"]).relative_to(cfg.paths["vault"]).with_suffix("").as_posix(), "qc": summary["qc"]["overall"], "groups": len(summary["groups"]), "ai_status": summary["interpretation"]["status"], "research_context": summary.get("research_context", {})} for job, summary in summaries]}
        axes = {summary["axis"] for _, summary in summaries}
        combined = {"groups": [{**group, "group_id": job["id"][:12] + "/" + group["group_id"], "research_context": {**{key: value for key, value in csv_context(summary.get("research_context", {})).items() if key != "source_relative_path"}, "metadata_review_required": summary.get("research_context", {}).get("metadata_review_required",bool(summary.get("research_context", {}).get("warnings")))}} for job, summary in summaries for group in summary["groups"]], "qc": {"overall": "FAIL" if counts["FAIL"] else "WARN" if counts["WARN"] else "PASS", "checks": [check for _, summary in summaries for check in summary["qc"]["checks"]]}, "axis": next(iter(axes)) if len(axes) == 1 else "mixed" if axes else cfg.data["analysis"]["x"], "model_caveat": "그룹별 경험적 기준선을 집계. 소자·측정 날짜·조명·바이어스를 구분하고, 다른 그룹끼리 AIC/BIC 비교 금지. 과거 주 대비 변화/인과는 이 입력에서 판단할 수 없음.", "source_filename": report_id, "report_context": {"period": report_id, "measurement_count": len(summaries), "qc_counts": counts, "cohort_basis": data["cohort_basis"]}}
        # No paid request for an empty week.
        cache_key = hashlib.sha256((json.dumps(combined, sort_keys=True) + cfg.fingerprint + __version__ + code_fingerprint()).encode()).hexdigest()
        cache = cfg.paths["state"] / "ai-cache" / ("weekly-" + cache_key + ".json")
        if summaries and cache.exists():
            data["interpretation"] = json.loads(cache.read_text(encoding="utf-8"))
        else:
            data["interpretation"] = interpret(combined, cfg) if summaries else {"status": "empty", "summary": "이 주에 분석 완료된 데이터가 없습니다.", "observations": [], "hypotheses": [], "next_steps": []}
            if data["interpretation"]["status"] == "completed":
                write_json(cache, data["interpretation"])
        path = cfg.paths["vault"] / "Weekly" / ("v" + __version__) / (report_id + "_" + now(cfg).strftime("%Y%m%d-%H%M%S-%f") + ".md")
        lines = ["---", "type: weekly-report", f"week: {report_id}", f"generated: {data['generated_at']}", "tags: [research, weekly, automated]", "---", f"# {report_id} 주간 연구 보고", "", "> 자동 생성 보고서. 연구자의 검토 및 다음 주 계획은 별도 노트에서 작성하세요.", "", f"- 기간: {monday} ~ {(end - timedelta(days=1)).date()} ({cfg.data['timezone']})", f"- 집계 기준: **{data['cohort_basis']}**. 동일 파일·동일 해시 재분석은 마지막 결과 1건만 집계.", f"- 결과: {len(summaries)}건; PASS {counts['PASS']}, WARN {counts['WARN']}, FAIL {counts['FAIL']}", "", "| 측정 날짜 | 소자 | 조건 | 측정파일 | QC | 그룹 수 | AI | 연구노트 |", "|---|---|---|---|---|---|---|---|"]
        for entry in data["jobs"]:
            context = entry["research_context"]
            lines.append(f"| {context.get('measurement_date') or '미확인'} | {escape(context.get('device_path') or '미확인')} | {escape(context.get('condition_label') or '미확인')} | {escape(entry['source'])} | {entry['qc']} | {entry['groups']} | {entry['ai_status']} | [[{entry['note']}]] |")
        if missing:
            lines += ["", f"집계에서 제외된 결과 파일 누락 {len(missing)}건. doctor/status로 복구를 확인하세요."]
        ai = data["interpretation"]
        lines += ["", "## 해석", "", f"AI 상태: `{ai['status']}`", "", ai["summary"]]
        for title, key in (("관측", "observations"), ("검증되지 않은 가설", "hypotheses"), ("다음 실험 제안", "next_steps")):
            lines += ["", f"### {title}", ""] + [f"- {value}" for value in ai[key]]
        lines += ["", "소자 유형·측정 조건을 확인하지 않은 모델 승률/비율을 물리적 결과로 해석하지 마세요."]
        atomic_text(path, "\n".join(lines) + "\n")
        output = cfg.paths["analysis"] / "weekly" / ("v" + __version__) / (path.stem + ".json")
        write_json(output, data)
        return {"report": str(path), "json": str(output), "measurements": len(summaries), "qc": counts, "missing_results": len(missing), "ai": ai["status"]}


def backup(cfg):
    with lock(cfg):
        timestamp = now(cfg).strftime("%Y%m%d-%H%M%S-%f")
        final = cfg.paths["backups"] / ("research-backup-" + timestamp + ".zip")
        manifest = {"created_at": now(cfg).isoformat(), "note": "보존된 입력 스냅샷·결과·Vault·SQLite·설정. inbox의 아직 처리하지 않은 파일과 .env/API 키는 포함하지 않음.", "files": []}
        with tempfile.TemporaryDirectory(dir=cfg.paths["state"]) as temporary:
            db_copy = Path(temporary) / "jobs.sqlite3"
            import sqlite3
            store = Store(cfg)
            try:
                with closing(sqlite3.connect(db_copy)) as target:
                    store.db.backup(target)
                    if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise RuntimeError("Backup database integrity check failed")
            finally:
                store.close()
            archive_path = Path(temporary) / "backup.zip"
            with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
                entries = [(cfg.path, "config.json"), (db_copy, "state/jobs.sqlite3")]
                for file in (cfg.paths["state"] / "ai-cache").glob("*.json"):
                    if not file.is_symlink():
                        entries.append((file, "state/ai-cache/" + file.name))
                # Vault may contain input data. Avoid adding inbox twice or
                # backing up a file while the measuring program is still writing it.
                for key in ("analysis", "vault", "logs"):
                    for file in cfg.paths[key].rglob("*"):
                        if not file.is_file() or file.is_symlink() or file.name.startswith(".working-"):
                            continue
                        if cfg.paths["inbox"] == file or cfg.paths["inbox"] in file.resolve().parents:
                            continue
                        if ".env" == file.name or any(part.startswith(".working-") for part in file.parts):
                            continue
                        entries.append((file, key + "/" + file.relative_to(cfg.paths[key]).as_posix()))
                for file, name in entries:
                    # Hash the exact archived bytes, including notes edited by the user.
                    content = file.read_bytes()
                    archive.writestr(name, content)
                    manifest["files"].append({"path": name, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()})
                archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            checksum = digest(archive_path)
            checksum_path = Path(temporary) / "backup.sha256"
            atomic_text(checksum_path, checksum + "  " + final.name + "\n")
            try:
                os.replace(archive_path, final)
                os.replace(checksum_path, str(final) + ".sha256")
            except OSError:
                final.unlink(missing_ok=True)
                Path(str(final) + ".sha256").unlink(missing_ok=True)
                raise
        return {"backup": str(final), "sha256": checksum, "files": len(manifest["files"])}
