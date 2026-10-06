import hashlib
import fnmatch
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
from datetime import datetime

import pandas as pd

from . import __version__, code_fingerprint
from .ai import interpret
from .analysis import analyze
from .ingest import load_measurements
from .organization import csv_context
from .metadata_review import build_context, fingerprint as override_fingerprint
from .science_exports import enrich_context, export_metrics, catalog_path
from .render import experiment_note, measurement_catalog, plots, vault_locations
from .store import Store, lock
from .util import digest, filename_hints, now, parse_filename, slug, write_json

from .pipeline_logging import logger


def candidates(cfg):
    root = cfg.paths["inbox"]
    extensions = {ext.lower() for ext in cfg.data["ingest"]["extensions"]}
    patterns = [pattern.replace("\\", "/").casefold() for pattern in cfg.data["ingest"]["exclude_globs"]]
    files = root.rglob("*") if cfg.data["ingest"]["recursive"] else root.glob("*")
    selected = []
    for path in files:
        if not path.is_file() or path.is_symlink() or path.suffix.lower() not in extensions or path.name.startswith(("~$", ".")) or root not in path.resolve().parents:
            continue
        relative = path.relative_to(root).as_posix().casefold()
        name = path.name.casefold()
        if any(fnmatch.fnmatchcase(relative, pattern) or fnmatch.fnmatchcase(name, pattern) for pattern in patterns):
            continue
        selected.append(path)
    return sorted(selected)


def stamp(path):
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def process_one(source, source_hash, job_id, cfg, store, log):
    relative = source.relative_to(cfg.paths["inbox"]).as_posix()
    timestamp = now(cfg).isoformat()
    store.begin(job_id, relative, source_hash, cfg.fingerprint, timestamp)
    stage = Path(tempfile.mkdtemp(prefix=f".working-{job_id[:12]}-", dir=cfg.paths["analysis"]))
    phase = "snapshot"
    try:
        raw_dir = cfg.paths["analysis"] / "raw" / job_id
        raw_dir.mkdir(parents=True, exist_ok=True)
        snapshot = raw_dir / (slug(source.stem) + source.suffix.lower())
        copied = stage / ("input" + source.suffix.lower())
        before = stamp(source)
        shutil.copy2(source, copied)
        if before != stamp(source) or digest(copied) != source_hash or digest(source) != source_hash:
            raise ValueError("파일 내용이 처리 도중 변경됨; 안정화 후 재시도 필요")
        if snapshot.exists() and digest(snapshot) == source_hash:
            copied.unlink()
        else:
            os.replace(copied, snapshot)
        metadata = parse_filename(source.name)
        metadata["_filename_hints"] = filename_hints(source.name)
        phase = "parse"
        sheets, ignored = load_measurements(snapshot, cfg, metadata)
        phase = "analysis"
        summary, curves = analyze(sheets, cfg)
        instrument = next((sheet["instrument_settings"] for sheet in sheets if "instrument_settings" in sheet), {})
        context = build_context(relative, metadata, instrument, summary, cfg, source_hash)
        summary.update({"schema_version": 4, "job_id": job_id, "version": __version__, "code_sha256": code_fingerprint(), "created_at": timestamp, "source_filename": source.name, "source_relative_path": relative, "source_sha256": source_hash, "config_sha256": cfg.fingerprint, "metadata": metadata, "research_context": context, "illumination": {"value": context["illumination"], "source": context["illumination_source"]}, "instrument_settings": instrument, "sheets": [{key: value for key, value in sheet.items() if key not in ("data", "points", "instrument_settings")} for sheet in sheets], "ignored_sheets": ignored, "raw_snapshot": str(snapshot)})
        summary["source_locations"] = {"original_relative_to_inbox": relative, "snapshot_relative_to_analysis": snapshot.relative_to(cfg.paths["analysis"]).as_posix(), "analysis_copy": "parsed_points.csv", "local_original_exists": source.exists(), "file_mtime_record_only": datetime.fromtimestamp(source.stat().st_mtime).isoformat(), "processed_at": timestamp}
        enrich_context(summary, cfg)
        summary["vault_note_relative_path"], summary["vault_assets_relative_path"] = vault_locations(summary)
        revision = 0
        while (cfg.paths["vault"] / summary["vault_note_relative_path"]).exists() or (cfg.paths["vault"] / summary["vault_assets_relative_path"]).exists():
            revision += 1
            base_note, base_assets = vault_locations(summary)
            summary["vault_note_relative_path"] = base_note[:-3] + f"_preserved-r{revision}.md"
            summary["vault_assets_relative_path"] = base_assets + f"_preserved-r{revision}"
        pd.concat([sheet.get("points",sheet["data"]) for sheet in sheets],ignore_index=True).to_csv(stage / "parsed_points.csv",index=False,encoding="utf-8-sig")
        csv_metadata = csv_context(context)
        pd.concat([sheet["data"] for sheet in sheets], ignore_index=True).assign(**csv_metadata).to_csv(stage / "normalized.csv", index=False, encoding="utf-8-sig")
        curves.assign(**csv_metadata).to_csv(stage / "curves.csv", index=False, encoding="utf-8-sig")
        fit_rows = []
        for group in summary["groups"]:
            for fit in group["fits"]:
                fit_rows.append({"group_id": group["group_id"], "axis": group["axis"], "trace_id": group["trace_id"], "sheet": group["sheet"], "direction": group["direction"], "conditions": json.dumps(group["conditions"]), **{key: fit[key] for key in ("model", "n", "k", "rmse_a", "aic", "bic", "rss_a2")}, "parameters": json.dumps(fit["parameters"]), "parameter_units":json.dumps({"slope_a_per_v":"A/V","offset_a":"A","i0_a":"A","alpha_per_v":"1/V"}), "voltage_unit":"V", "current_unit":"A", "parameter_std": json.dumps(fit["parameter_std"]), "warnings": json.dumps(fit["warnings"], ensure_ascii=False)})
        pd.DataFrame(fit_rows, columns=["group_id", "axis", "trace_id", "sheet", "direction", "conditions", "model", "n", "k", "rmse_a", "aic", "bic", "rss_a2", "parameters", "parameter_std", "warnings", "parameter_units", "voltage_unit", "current_unit"]).assign(**csv_metadata).to_csv(stage / "fit_results.csv", index=False, encoding="utf-8-sig")
        metrics = [{"group_id": group["group_id"], "axis": group["axis"], "trace_id": group["trace_id"], "conditions": json.dumps(group["conditions"]), "direction": group["direction"], "n": group["n"], "rr_status": group["rectification"]["status"], "rr_abs_positive_over_negative": group["rectification"].get("ratio_abs_i_positive_over_negative"), "rr_evaluation_abs_vd_v": group["rectification"]["voltage_v"], "rr_unit": "1", "current_unit": "A", "gm_unit": "A/V", "transfer_status": group["transfer_metrics"]["status"], **{key: group["transfer_metrics"].get(key) for key in ("gm_max_a_per_v", "gm_min_a_per_v", "gm_peak_vg_v", "current_range_ratio_abs")}} for group in summary["groups"]]
        pd.DataFrame(metrics).assign(**csv_metadata).to_csv(stage / "metrics.csv", index=False, encoding="utf-8-sig")
        export_metrics(summary, stage)
        summary["figures"] = plots(curves, summary, stage)
        from .fet_parameters import export_fet
        from .fet_figures import fet_figures
        additional=export_fet(curves,summary,stage,cfg)
        summary['figures'].extend(fet_figures(additional,summary,stage))
        from .research_report import export_report
        from .research_panels import research_panels
        report=export_report(curves,summary,stage,cfg,additional)
        new_figures,_=research_panels(curves,summary,stage,additional,report)
        summary['figures'].extend(new_figures)
        summary['report_format']='fet-template-report-1'
        phase = "publication"
        cache = cfg.paths["state"] / "ai-cache" / (job_id + ".json")
        if cache.exists():
            summary["interpretation"] = json.loads(cache.read_text(encoding="utf-8"))
        else:
            summary["interpretation"] = interpret(summary, cfg)
            # Cache a successful paid response before publishing notes.
            if summary["interpretation"]["status"] == "completed":
                write_json(cache, summary["interpretation"])
        write_json(stage / "result.json", summary)
        write_json(stage / "config_snapshot.json", cfg.data)
        final = cfg.paths["analysis"] / "runs" / ("v" + __version__) / job_id
        final.parent.mkdir(parents=True, exist_ok=True)
        # Preserve every earlier output, even recovery of the same job.
        if final.exists():
            counter = 1
            while final.with_name(job_id + f"_preserved-r{counter}").exists():
                counter += 1
            final = final.with_name(job_id + f"_preserved-r{counter}")
        os.replace(stage, final)
        note = experiment_note(summary, final, cfg)
        store.finish(job_id, now(cfg).isoformat(), final / "result.json", note, summary["interpretation"]["status"])
        log.info("completed job=%s source=%s qc=%s ai=%s", job_id[:16], relative, summary["qc"]["overall"], summary["interpretation"]["status"])
        return {"job_id": job_id, "source": relative, "status": "completed", "qc": summary["qc"]["overall"], "ai": summary["interpretation"]["status"], "note": str(note), "result_path": str(final / "result.json")}
    except Exception as error:
        # API response/error bodies and environment variables are never logged.
        message = f"{type(error).__name__}: {error}"
        store.fail(job_id, now(cfg).isoformat(), message)
        failure_dir = cfg.paths['analysis'] / 'failures' / ('v' + __version__)
        failure_dir.mkdir(parents=True, exist_ok=True)
        failure_path = failure_dir / (job_id + '_' + str(time.time_ns()) + '.json')
        write_json(failure_path, {'job_id':job_id,'version':__version__,'code_sha256':code_fingerprint(),
            'source_relative_path':relative,'source_sha256':source_hash,'config_sha256':cfg.fingerprint,
            'processed_at':timestamp,'failed_phase':phase,'error':message,
            'parse_status':'failed' if phase=='parse' else 'not_run' if phase=='snapshot' else 'parsed',
            'data_qc_status':'not_run' if phase in ('parse','snapshot') else 'incomplete',
            'metadata_status':'not_reviewed','metric_status':'unavailable','model_status':'not_run' if phase in ('parse','snapshot') else 'incomplete'})
        if phase=='parse':
            try:
                from .special_notes import failure_note
                failure_note(failure_path,cfg)
            except Exception as note_error:
                log.warning('failure note export: %s',type(note_error).__name__)
        log.error("failed job=%s source=%s error=%s", job_id[:16], relative, message)
        return {"job_id": job_id, "source": relative, "status": "failed", "error": message, "diagnostic_path": str(failure_path)}
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def scan(cfg, retry_failed=False, *, on_progress=None, stop_event=None, sources=None):
    with lock(cfg):
        log = logger(cfg)
        store = Store(cfg)
        try:
            if retry_failed:
                store.reset_failed()
            files = candidates(cfg)
            if sources is not None:
                allowed = {str(value).replace("\\", "/") for value in sources}
                files = [file for file in files if file.relative_to(cfg.paths["inbox"]).as_posix() in allowed]
            observed = {}
            outcomes = []
            for source in files:
                try:
                    observed[source] = stamp(source)
                except OSError:
                    outcomes.append({"source": str(source), "status": "deferred", "reason": "파일 접근 불가"})
            # A batch shares one wait; poll includes moved/renamed files on next scan.
            if observed:
                if stop_event is None:
                    time.sleep(cfg.data["ingest"]["stable_seconds"])
                else:
                    stop_event.wait(cfg.data["ingest"]["stable_seconds"])
            for source, initial in observed.items():
                if stop_event is not None and stop_event.is_set():
                    break
                relative = source.relative_to(cfg.paths["inbox"]).as_posix()
                try:
                    if stamp(source) != initial:
                        outcomes.append({"source": relative, "status": "deferred", "reason": "저장 중"})
                        continue
                    if initial[0] > cfg.data["ingest"]["max_bytes"]:
                        outcomes.append({"source": relative, "status": "rejected", "reason": "max_bytes 초과"})
                        continue
                    source_hash = digest(source)
                    identity = f"{relative}\n{source_hash}\n{cfg.fingerprint}\n{__version__}\n{code_fingerprint()}\n{override_fingerprint(cfg, relative, source_hash)}"
                    job_id = hashlib.sha256(identity.encode()).hexdigest()
                    previous = store.get(job_id)
                    if previous and previous["status"] == "completed" and Path(previous["result_path"]).exists() and Path(previous["note_path"]).exists():
                        outcomes.append({"source": relative, "job_id": job_id, "status": "unchanged"})
                        continue
                    if previous and previous["status"] != "completed":
                        if previous["attempts"] >= cfg.data["ingest"]["max_attempts"]:
                            outcomes.append({"source": relative, "status": "blocked", "reason": "최대 재시도 초과; scan --retry-failed 사용"})
                            continue
                        if previous["status"] == "failed" and (now(cfg) - datetime.fromisoformat(previous["updated_at"])).total_seconds() < cfg.data["ingest"]["retry_seconds"] and not retry_failed:
                            outcomes.append({"source": relative, "status": "deferred", "reason": "재시도 대기"})
                            continue
                    if on_progress is not None:
                        on_progress({"source": relative, "job_id": job_id, "status": "processing", "total_files": len(observed)})
                    outcome = process_one(source, source_hash, job_id, cfg, store, log)
                    outcomes.append(outcome)
                    if on_progress is not None:
                        on_progress(outcome)
                except (OSError, ValueError) as error:
                    outcomes.append({"source": relative, "status": "deferred", "reason": str(error)})
                    log.warning("deferred source=%s reason=%s", relative, type(error).__name__)
            if any(outcome["status"] in ("completed","failed") for outcome in outcomes) or not catalog_path(cfg).exists():
                measurement_catalog(cfg, store.completed())
                from .comparison_catalog import publish
                publish(cfg,store.completed())
            result = {"counts": {status: sum(o["status"] == status for o in outcomes) for status in ("completed", "unchanged", "failed", "deferred", "blocked", "rejected")}, "files": outcomes}
            if stop_event is not None and stop_event.is_set():
                result["stopped"] = True
            return result
        finally:
            store.close()


def retry_ai(cfg):
    raise ValueError("기존 결과/노트의 AI 재작성은 비활성화했습니다. 이 연구 검토 버전은 새 버전 결과와 규칙 기반 요약을 사용합니다.")
