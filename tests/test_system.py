from research_automation import __version__
import copy
from datetime import datetime
import hashlib
import json
import logging
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from fastapi.testclient import TestClient
import httpx
import numpy as np
import pandas as pd

from research_automation import __version__
from research_automation.ai import interpret
from research_automation.analysis import analyze, fit_models, qc_branch, split_sweeps
from research_automation.cli import demo
from research_automation.config import Config, DEFAULT
from research_automation.ingest import load_measurements
from research_automation.pipeline import retry_ai, scan
from research_automation.reports import backup, weekly
from research_automation.service import create_app
from research_automation.store import BusyError, Store, lock
from research_automation.util import parse_filename


class Base(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data = copy.deepcopy(DEFAULT)
        # This shared fixture checks the retained legacy pipeline and views.
        # Default basic-report behavior has its own acquisition/model tests.
        self.data['benchmark']['enabled']=False
        self.data["ingest"]["stable_seconds"] = .001
        self.data["ingest"]["retry_seconds"] = .001
        self.path = self.root / "config.json"
        self.cfg = self.configure()

    def tearDown(self):
        # Windows keeps active FileHandler files open; close only this test's logger.
        log = logging.getLogger("research-automation." + str(self.path.resolve()))
        for handler in list(log.handlers):
            handler.close()
            log.removeHandler(handler)
        self.temporary.cleanup()

    def configure(self):
        self.path.write_text(json.dumps(self.data), encoding="utf-8")
        cfg = Config(self.path)
        cfg.ensure_dirs()
        return cfg

    def sample(self, name="device=TEST_vg=0.csv", ig=True, offset=0):
        x = np.linspace(-1, 1, 21)
        data = {"DrainV (V)": x, "DrainI (nA)": (3e-9 * np.sinh(1.7 * x) + offset) * 1e9}
        if ig:
            data["GateI (A)"] = 1e-12
        path = self.cfg.paths["inbox"] / name
        pd.DataFrame(data).to_csv(path, index=False)
        return path


class NumericalTests(Base):
    def test_filename_metadata(self):
        self.assertEqual(parse_filename("device=TFET_vgs=5_vd=0.5.xlsx"), {"device": "TFET", "vgs": 5.0, "vd": .5})

    def test_sinh_parameters_at_nanoamp_scale(self):
        x = np.linspace(-2, 2, 81)
        y = 3e-9 * np.sinh(1.7 * x)
        fits, failures = fit_models(x, y, self.cfg)
        self.assertEqual(failures, [])
        self.assertEqual(fits[0]["model"], "sinh")
        self.assertAlmostEqual(fits[0]["parameters"]["i0_a"] / 3e-9, 1, places=5)
        self.assertAlmostEqual(fits[0]["parameters"]["alpha_per_v"], 1.7, places=5)
        self.assertTrue(np.isfinite(fits[0]["aic"]))

    def test_sweeps_share_only_turning_point(self):
        frame = pd.DataFrame({"vd": [-1, 0, 1, .5, 0, -1], "id": [0] * 6})
        branches = split_sweeps(frame, "vd")
        self.assertEqual([b[0] for b in branches], ["forward", "reverse"])
        self.assertEqual(branches[0][1]["vd"].tolist(), [-1, 0, 1])
        self.assertEqual(branches[1][1]["vd"].tolist(), [1, .5, 0, -1])

    def test_missing_gate_or_zero_is_skip(self):
        frame = pd.DataFrame({"vd": [.1, .2, .3], "id": [1e-9, 2e-9, 3e-9]})
        checks = {c["code"]: c["status"] for c in qc_branch(frame, self.cfg, "test")}
        self.assertEqual(checks["gate_leakage"], "SKIP")
        self.assertEqual(checks["zero_offset"], "SKIP")

    def test_nonfinite_gate_current_not_pass(self):
        frame = pd.DataFrame({"vd": [-1, 0, 1], "id": [1e-9] * 3, "ig": [1e-12, np.nan, 1e-12]})
        checks = qc_branch(frame, self.cfg, "test")
        self.assertEqual(checks[0]["status"], "SKIP")

    def test_conditions_and_hysteresis_separated(self):
        demo(self.cfg)
        path = next(self.cfg.paths["inbox"].glob("*.csv"))
        sheets, _ = load_measurements(path, self.cfg, {})
        summary, curves = analyze(sheets, self.cfg)
        self.assertEqual(len(summary["groups"]), 4)
        self.assertEqual({g["conditions"]["vg"] for g in summary["groups"]}, {0, 2})
        self.assertEqual(len([c for c in summary["qc"]["checks"] if c["code"] == "hysteresis" and c["status"] != "SKIP"]), 2)
        self.assertTrue(all(g["rectification"]["status"] == "OK" for g in summary["groups"]))

    def test_constant_voltage_insufficient(self):
        fits, failures = fit_models(np.zeros(10), np.ones(10) * 1e-9, self.cfg)
        self.assertEqual(fits, [])
        self.assertTrue(failures)

    def test_transfer_curve_grouped_by_drain_voltage(self):
        self.data["analysis"].update({"x": "vg", "group_by": ["vd"]})
        self.cfg = self.configure()
        frame = pd.DataFrame({"GateV (V)": np.linspace(-1, 1, 21), "DrainV (V)": .5, "DrainI (A)": np.linspace(-1e-9, 1e-9, 21)})
        path = self.cfg.paths["inbox"] / "transfer.csv"
        frame.to_csv(path, index=False)
        sheets, _ = load_measurements(path, self.cfg, {})
        summary, _ = analyze(sheets, self.cfg)
        self.assertEqual(summary["groups"][0]["conditions"], {"vd": .5})
        self.assertEqual(summary["groups"][0]["rectification"]["status"], "SKIP")


class IngestTests(Base):
    def test_windows_powershell_utf8_bom_config(self):
        self.path.write_text(json.dumps(self.data), encoding="utf-8-sig")
        self.assertEqual(Config(self.path).data["timezone"], "Asia/Seoul")

    def test_filename_vgs_used_for_fixed_gate(self):
        path = self.sample(name="device=TFET_vgs=2.csv")
        sheets, _ = load_measurements(path, self.cfg, parse_filename(path.name))
        self.assertEqual(sheets[0]["data"]["vg"].iloc[0], 2)

    def test_real_legacy_xls(self):
        fixture = Path(__file__).resolve().parents[1] / "examples" / "device=DEMO_vg=0_legacy.xls"
        sheets, _ = load_measurements(fixture, self.cfg, {})
        self.assertEqual(len(sheets), 1)
        self.assertEqual(len(sheets[0]["data"]), 21)
        self.assertAlmostEqual(sheets[0]["data"]["id"].iloc[-1], 3e-9 * np.sinh(1.7), places=16)

    def test_si_conversion(self):
        path = self.sample()
        sheets, _ = load_measurements(path, self.cfg, parse_filename(path.name))
        np.testing.assert_allclose(sheets[0]["data"]["id"], 3e-9 * np.sinh(1.7 * np.linspace(-1, 1, 21)), rtol=1e-10, atol=1e-20)
        self.assertEqual(sheets[0]["column_mapping"]["id"]["factor_to_si"], 1e-9)

    def test_excel_multisheet_and_metadata_header(self):
        path = self.cfg.paths["inbox"] / "multi.xlsx"
        frame = pd.read_csv(self.sample())
        with pd.ExcelWriter(path) as book:
            pd.DataFrame({"instrument": ["Keithley"]}).to_excel(book, sheet_name="Settings", index=False)
            frame.to_excel(book, sheet_name="Run1", index=False, startrow=2)
            frame.to_excel(book, sheet_name="Run2", index=False)
        sheets, ignored = load_measurements(path, self.cfg, {})
        self.assertEqual([s["name"] for s in sheets], ["Run1", "Run2"])
        self.assertEqual(ignored[0]["sheet"], "Settings")
        self.assertEqual(sheets[0]["data"]["source_row"].iloc[0], 4)

    def test_cp949_tab_csv_with_preamble(self):
        path = self.cfg.paths["inbox"] / "한글.csv"
        path.write_bytes(("측정 장비: Keithley\n" + "DrainV (mV)\tDrainI (uA)\n" + "100\t0.01\n200\t0.02\n").encode("cp949"))
        sheets, _ = load_measurements(path, self.cfg, {})
        self.assertAlmostEqual(sheets[0]["data"]["vd"].iloc[0], .1)
        self.assertAlmostEqual(sheets[0]["data"]["id"].iloc[0], 1e-8)

    def test_explicit_mapping(self):
        self.data["columns"]["mapping"] = {"vd": "CH1 [V]", "id": "CH2 [A]"}
        self.cfg = self.configure()
        path = self.cfg.paths["inbox"] / "mapped.csv"
        pd.DataFrame({"CH1 [V]": [-1, 0, 1], "CH2 [A]": [-1e-9, 0, 1e-9]}).to_csv(path, index=False)
        sheets, _ = load_measurements(path, self.cfg, {})
        self.assertEqual(sheets[0]["data"]["vd"].tolist(), [-1, 0, 1])

    def test_invalid_rows_fail_and_block_fit(self):
        path = self.sample()
        frame = pd.read_csv(path)
        frame.loc[:5, "DrainI (nA)"] = np.nan
        frame.to_csv(path, index=False)
        sheets, _ = load_measurements(path, self.cfg, {})
        summary, _ = analyze(sheets, self.cfg)
        self.assertEqual(summary["qc"]["overall"], "FAIL")
        self.assertTrue(all(not g["fits"] for g in summary["groups"]))

    def test_unknown_current_unit_rejected(self):
        path = self.cfg.paths["inbox"] / "wrong.csv"
        path.write_text("DrainV (V),DrainI (V)\n1,2\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "단위"):
            load_measurements(path, self.cfg, {})

    def test_nested_vault_inbox_allowed_and_generated_rejected(self):
        self.data["paths"]["inbox"] = "vault/측정 데이터"
        self.configure()
        self.data["paths"]["inbox"] = "vault/Attachments/input"
        with self.assertRaises(ValueError):
            self.configure()

    def test_unsafe_output_overlap_rejected(self):
        self.data["paths"]["analysis"] = "data_inbox/analysis"
        with self.assertRaises(ValueError):
            self.configure()


class PipelineTests(Base):
    def test_excel_only_ignores_analysis_csv_in_nested_folder(self):
        self.data["ingest"]["extensions"] = [".xlsx", ".xls"]
        self.cfg = self.configure()
        folder = self.cfg.paths["inbox"] / "vps 측정" / "원본"
        folder.mkdir(parents=True)
        (folder / "ReS2_IVG_parameters_center fold.csv").write_text("parameter,value\nalpha,1\n", encoding="utf-8")
        pd.DataFrame({"DrainV (V)": np.linspace(-1, 1, 21), "DrainI (A)": np.linspace(-1e-9, 1e-9, 21)}).to_excel(folder / "실측.XLSX", index=False)
        result = scan(self.cfg)
        self.assertEqual(result["counts"]["completed"], 1)
        self.assertEqual(result["counts"]["failed"], 0)
        self.assertEqual(len(result["files"]), 1)

    def test_exclude_glob_preserves_raw_csv(self):
        self.data["ingest"]["exclude_globs"] = ["*parameters*.csv"]
        self.cfg = self.configure()
        self.sample()
        folder = self.cfg.paths["inbox"] / "하위"
        folder.mkdir()
        (folder / "ReS2_IVD_PARAMETERS_drain fold.CSV").write_text("bad data", encoding="utf-8")
        result = scan(self.cfg)
        self.assertEqual(result["counts"]["completed"], 1)
        self.assertEqual(result["counts"]["failed"], 0)

    def test_previously_failed_analysis_csv_is_no_longer_retried(self):
        self.sample()
        (self.cfg.paths["inbox"] / "ReS2_IVG_parameters_center fold.csv").write_text("parameter,value\nalpha,1\n", encoding="utf-8")
        first = scan(self.cfg)
        self.assertEqual(first["counts"]["failed"], 1)
        self.data["ingest"]["exclude_globs"] = ["*parameters*.csv"]
        self.cfg = self.configure()
        second = scan(self.cfg)
        self.assertEqual(second["counts"]["unchanged"], 1)
        self.assertEqual(second["counts"]["failed"], 0)
        self.assertEqual(second["counts"]["deferred"], 0)
        store = Store(self.cfg)
        try:
            failed = [job for job in store.recent() if job["status"] == "failed"]
            self.assertEqual(len(failed), 1)
            self.assertEqual(failed[0]["attempts"], 1)
        finally:
            store.close()

    def test_selection_change_does_not_reprocess_completed_measurement(self):
        self.sample()
        scan(self.cfg)
        before = self.cfg.fingerprint
        self.data["ingest"]["exclude_globs"] = ["*parameters*.csv"]
        self.cfg = self.configure()
        self.assertEqual(before, self.cfg.fingerprint)
        self.assertEqual(scan(self.cfg)["counts"]["unchanged"], 1)

    def test_old_config_defaults_and_hash_preserved(self):
        self.data["ingest"].pop("extensions")
        self.data["ingest"].pop("exclude_globs")
        previous = hashlib.sha256(json.dumps(self.data, sort_keys=True).encode()).hexdigest()
        self.cfg = self.configure()
        self.assertEqual(self.cfg.fingerprint, previous)
        self.assertIn(".csv", self.cfg.data["ingest"]["extensions"])
        self.assertEqual(self.cfg.data["ingest"]["exclude_globs"], [])

    def test_invalid_extension_rejected(self):
        self.data["ingest"]["extensions"] = [".txt"]
        with self.assertRaisesRegex(ValueError, "extensions"):
            self.configure()

    def test_group_explosion_limit(self):
        self.data["analysis"]["max_groups"] = 1
        self.cfg = self.configure()
        demo(self.cfg)
        result = scan(self.cfg)
        self.assertEqual(result["counts"]["failed"], 1)
        self.assertIn("max_groups", result["files"][0]["error"])

    def test_interrupted_job_can_resume(self):
        self.sample()
        first = scan(self.cfg)
        job_id = first["files"][0]["job_id"]
        store = Store(self.cfg)
        store.db.execute("UPDATE jobs SET status='processing' WHERE id=?", (job_id,))
        store.db.commit()
        store.close()
        self.assertEqual(scan(self.cfg)["counts"]["completed"], 1)

    def test_weekly_caches_successful_interpretation(self):
        self.sample()
        scan(self.cfg)
        interpretation = {"status": "completed", "summary": "요약", "observations": [], "hypotheses": [], "next_steps": []}
        with patch("research_automation.reports.interpret", return_value=interpretation) as api:
            first = weekly(self.cfg)
            second = weekly(self.cfg)
        self.assertEqual(api.call_count, 1)
        self.assertNotEqual(first["report"], second["report"])
        self.assertTrue(Path(first["report"]).exists())
        self.assertTrue(Path(second["report"]).exists())

    def test_weekly_keeps_original_axes(self):
        self.sample()
        scan(self.cfg)
        self.data["analysis"].update({"x": "vg", "group_by": ["vd"]})
        self.cfg = self.configure()
        frame = pd.DataFrame({"GateV (V)": np.linspace(-1, 1, 21), "DrainV (V)": .5, "DrainI (A)": np.linspace(-1e-9, 1e-9, 21)})
        frame.to_csv(self.cfg.paths["inbox"] / "transfer.csv", index=False)
        scan(self.cfg)
        captured = []
        def interpretation(summary, cfg):
            captured.append(summary)
            return {"status": "disabled", "summary": "요약", "observations": [], "hypotheses": [], "next_steps": []}
        with patch("research_automation.reports.interpret", side_effect=interpretation):
            weekly(self.cfg)
        self.assertEqual(captured[0]["axis"], "mixed")
        self.assertEqual({group["axis"] for group in captured[0]["groups"]}, {"vd", "vg"})

    def test_end_to_end_duplicate_and_changed_content(self):
        source = self.sample(name="소자=TFET_vg=0.csv")
        original = source.read_bytes()
        result = scan(self.cfg)
        self.assertEqual(result["counts"]["completed"], 1)
        self.assertEqual(source.read_bytes(), original)
        note = Path(result["files"][0]["note"])
        self.assertIn("QC와 정량 사용 제한", note.read_text(encoding="utf-8"))
        images = list((self.cfg.paths["vault"] / "Attachments").rglob("*.png"))
        self.assertEqual(len([image for image in images if image.name.endswith("_fit.png")] ), 1)
        self.assertEqual(len([image for image in images if image.name.startswith("overview_")] ), 1)
        self.assertEqual(scan(self.cfg)["counts"]["unchanged"], 1)
        self.sample(name=source.name, offset=1e-10)
        self.assertEqual(scan(self.cfg)["counts"]["completed"], 1)
        self.assertEqual(len(list((self.cfg.paths["analysis"] / "runs" / ("v" + __version__)).iterdir())), 2)

    def test_saved_file_changes_are_deferred(self):
        source = self.sample()
        def change(_):
            with source.open("a") as stream:
                stream.write("\n")
        with patch("research_automation.pipeline.time.sleep", side_effect=change):
            result = scan(self.cfg)
        self.assertEqual(result["counts"]["deferred"], 1)
        self.assertEqual(result["counts"]["completed"], 0)

    def test_bad_file_does_not_stop_good_file_and_retry_limit(self):
        self.sample()
        bad = self.cfg.paths["inbox"] / "broken.xlsx"
        bad.write_text("not an excel workbook", encoding="utf-8")
        first = scan(self.cfg)
        self.assertEqual(first["counts"]["failed"], 1)
        self.assertEqual(first["counts"]["completed"], 1)
        with patch("research_automation.pipeline.now") as fake_now:
            fake_now.return_value = datetime.fromisoformat("2099-01-01T00:00:00+09:00")
            scan(self.cfg)
            fake_now.return_value = datetime.fromisoformat("2099-01-02T00:00:00+09:00")
            scan(self.cfg)
        self.assertEqual(scan(self.cfg)["counts"]["blocked"], 1)
        self.assertEqual(scan(self.cfg, retry_failed=True)["counts"]["failed"], 1)

    def test_exclusive_lock(self):
        with lock(self.cfg):
            with self.assertRaises(BusyError):
                scan(self.cfg)

    def test_oversize_and_excel_temporary_file(self):
        self.data["ingest"]["max_bytes"] = 10
        self.cfg = self.configure()
        self.sample()
        (self.cfg.paths["inbox"] / "~$locked.xlsx").write_text("excel lock", encoding="utf-8")
        result = scan(self.cfg)
        self.assertEqual(result["counts"]["rejected"], 1)
        self.assertEqual(len(result["files"]), 1)

    def test_missing_note_rebuilt(self):
        self.sample()
        result = scan(self.cfg)
        note = Path(result["files"][0]["note"])
        note.unlink()
        recovered=scan(self.cfg)
        self.assertEqual(recovered["counts"]["completed"], 1)
        self.assertTrue(Path(recovered["files"][0]["note"]).exists())
        self.assertNotEqual(recovered["files"][0]["note"],str(note))

    def test_weekly_deduplication_and_boundary(self):
        self.sample()
        scan(self.cfg)
        self.data["qc"]["current_jump_a"] = 1e-6
        self.cfg = self.configure()
        scan(self.cfg)
        store = Store(self.cfg)
        store.db.execute("UPDATE jobs SET completed_at='2026-01-05T00:00:00+09:00'")
        store.db.commit()
        store.close()
        result = weekly(self.cfg, "2026-01-05")
        self.assertEqual(result["measurements"], 1)
        self.assertEqual(weekly(self.cfg, "2026-01-04")["measurements"], 0)
        text = Path(result["report"]).read_text(encoding="utf-8")
        self.assertIn("실제 측정 시각은 아님", text)

    def test_backup_manifest_sqlite_and_secrets_excluded(self):
        self.sample()
        scan(self.cfg)
        (self.cfg.paths["vault"] / ".env").write_text("secret", encoding="utf-8")
        result = backup(self.cfg)
        with zipfile.ZipFile(result["backup"]) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            self.assertIn("state/jobs.sqlite3", archive.namelist())
            self.assertNotIn("vault/.env", archive.namelist())
            self.assertTrue(any(name.startswith("analysis/raw/") for name in archive.namelist()))
            for entry in manifest["files"]:
                self.assertEqual(hashlib.sha256(archive.read(entry["path"])).hexdigest(), entry["sha256"])


class AITests(Base):
    def summary(self):
        path = self.sample()
        sheets, _ = load_measurements(path, self.cfg, {})
        summary, _ = analyze(sheets, self.cfg)
        summary.update({"axis": "vd", "source_filename": "private-secret-file.csv"})
        return summary

    def enable(self):
        self.data["science"]["offline"] = False  # Mock HTTP only
        self.data["ai"]["enabled"] = True
        self.cfg = self.configure()

    def test_no_key_fallback(self):
        self.enable()
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            self.assertEqual(interpret(self.summary(), self.cfg)["status"], "missing_api_key")

    def test_responses_structured_output_and_privacy(self):
        self.enable()
        seen = []
        def transport(request):
            seen.append(json.loads(request.content))
            output = {"summary": "결과", "observations": ["관측"], "hypotheses": ["미검증 가설"], "next_steps": ["반복 측정"]}
            return httpx.Response(200, json={"status": "completed", "id": "response-test", "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(output)}]}]})
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key-never-output"}), httpx.Client(transport=httpx.MockTransport(transport)) as client:
            result = interpret(self.summary(), self.cfg, client)
        self.assertEqual(result["status"], "completed")
        self.assertFalse(seen[0]["store"])
        self.assertEqual(seen[0]["text"]["format"]["type"], "json_schema")
        self.assertNotIn("private-secret-file", seen[0]["input"])
        self.assertNotIn("source_row", seen[0]["input"])

    def test_invalid_ai_json_preserves_numerical_fallback(self):
        self.enable()
        response = {"status": "completed", "output": [{"content": [{"type": "output_text", "text": "not json"}]}]}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}), httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=response))) as client:
            self.assertEqual(interpret(self.summary(), self.cfg, client)["status"], "invalid_api_response")

    def test_rate_limit_retry(self):
        self.enable()
        calls = []
        def transport(request):
            calls.append(request)
            return httpx.Response(429)
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}), patch("research_automation.ai.time.sleep"), httpx.Client(transport=httpx.MockTransport(transport)) as client:
            value = interpret(self.summary(), self.cfg, client)
        self.assertEqual(value["status"], "api_error_429")
        self.assertEqual(len(calls), 3)

    def test_ai_retry_cannot_overwrite_researcher_note_or_refit(self):
        self.sample(); scan(self.cfg)
        store=Store(self.cfg); old=store.completed()[0];store.close()
        note=Path(old['note_path']);note.write_text(note.read_text(encoding="utf-8")+"\n연구자 수정 본문\n", encoding="utf-8")
        before=note.read_bytes(); result=Path(old['result_path']).read_bytes()
        with patch("research_automation.pipeline.interpret",side_effect=AssertionError("no API")),patch("research_automation.pipeline.analyze",side_effect=AssertionError("no refit")):
            with self.assertRaises(ValueError):retry_ai(self.cfg)
        self.assertEqual(note.read_bytes(),before);self.assertEqual(Path(old['result_path']).read_bytes(),result)


def retry_ai_without_request(cfg):
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}), patch("research_automation.pipeline.interpret", side_effect=AssertionError("must skip paid success")):
        return retry_ai(cfg)


class ServiceTests(Base):
    def test_api_authentication(self):
        with patch.dict(os.environ, {"RESEARCH_API_TOKEN": "a" * 32}):
            client = TestClient(create_app(self.cfg))
        self.assertEqual(client.get("/health").status_code, 200)
        self.assertEqual(client.get("/status").status_code, 401)
        self.assertEqual(client.post("/scan").status_code, 401)
        self.assertEqual(client.get("/status", headers={"Authorization": "Bearer " + "a" * 32}).status_code, 200)
        self.assertEqual(client.post("/scan", headers={"Authorization": "Bearer " + "a" * 32}).json()["counts"]["completed"], 0)

    def test_short_token_refused(self):
        with patch.dict(os.environ, {"RESEARCH_API_TOKEN": "weak"}):
            with self.assertRaises(ValueError):
                create_app(self.cfg)


if __name__ == "__main__":
    unittest.main()
