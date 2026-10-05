import copy
import json
import os
from pathlib import Path
import queue
import threading
import unittest
from unittest.mock import patch

import httpx

from test_system import Base
from research_automation.config import Config
from research_automation.gui_backend import JobController, check_api_key, ensure_config, get_api_key, load_jobs, note_uri, safe_error, save_settings
from research_automation.pipeline import scan
from research_automation.store import BusyError, lock


class SettingsTests(Base):
    def test_preserves_other_settings_and_saves_backup(self):
        self.data["qc"]["gate_leakage_a"] = 7e-8
        self.data["organization"]["path_rules"] = [r"^(?P<device_name>[^/]+)/"]
        self.cfg = self.configure()
        original = self.path.read_bytes()
        updated = save_settings(self.path, self.root / "new input", self.root / "new vault", True)
        self.assertTrue(updated.data["ai"]["enabled"])
        self.assertEqual(updated.data["qc"]["gate_leakage_a"], 7e-8)
        self.assertEqual(updated.data["organization"], self.data["organization"])
        self.assertEqual(next(self.root.glob("config.before-gui-*.json")).read_bytes(), original)
        self.assertEqual(updated.paths["inbox"], self.root / "new input")

    def test_unchanged_save_does_not_reprocess_or_rewrite(self):
        original = self.path.read_bytes()
        updated = save_settings(self.path, self.cfg.paths["inbox"], self.cfg.paths["vault"], False)
        self.assertEqual(updated.fingerprint, self.cfg.fingerprint)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertFalse(list(self.root.glob("config.before-gui-*")))

    def test_invalid_paths_preserve_config(self):
        original = self.path.read_bytes()
        with self.assertRaises(ValueError):
            save_settings(self.path, self.root / "vault" / "Attachments", self.cfg.paths["vault"], False)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertFalse(list(self.root.glob(".gui-config-*")))

    def test_saving_while_pipeline_busy_is_rejected(self):
        original = self.path.read_bytes()
        with lock(self.cfg), self.assertRaises(BusyError):
            save_settings(self.path, self.cfg.paths["inbox"], self.cfg.paths["vault"], True)
        self.assertEqual(self.path.read_bytes(), original)

    def test_gui_reads_status_without_creating_database(self):
        for path in self.cfg.paths["state"].iterdir():
            path.unlink()
        self.assertEqual(load_jobs(self.cfg), [])
        self.assertFalse((self.cfg.paths["state"] / "jobs.sqlite3").exists())

    def test_missing_config_uses_template(self):
        target = self.root / "new-config.json"
        (self.root / "config.example.json").write_text(json.dumps(self.data))
        cfg = ensure_config(target)
        self.assertEqual(cfg.data["qc"], self.data["qc"])
        self.assertFalse(cfg.data["ai"]["enabled"])

    def test_note_uri_handles_korean_spaces_and_hash(self):
        note = self.root / "연구 노트 #1.md"
        note.write_text("test")
        uri = note_uri(note)
        from urllib.parse import parse_qs, urlparse
        self.assertEqual(parse_qs(urlparse(uri).query)["path"], [str(note)])
        with self.assertRaises(ValueError):
            note_uri(self.root / "missing.md")


class ControllerTests(Base):
    def events(self, controller):
        controller.thread.join(timeout=15)
        self.assertFalse(controller.busy)
        output = []
        while True:
            try:
                output.append(controller.events.get_nowait())
            except queue.Empty:
                return output

    def test_scan_emits_result_context_from_real_pipeline(self):
        self.sample()
        controller = JobController()
        controller.start("scan", self.cfg)
        events = self.events(controller)
        rows = [event["row"] for event in events if event["event"] == "row"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["device_name"], "TEST")
        self.assertEqual(rows[0]["qc"], "PASS")
        self.assertEqual(rows[0]["condition_label"], "I-Vd__unknown__Vg=0V")
        self.assertTrue(Path(rows[0]["note_path"]).exists())
        self.assertEqual(events[-1]["event"], "finished")

    def test_second_job_cannot_start_while_busy(self):
        entered = threading.Event()
        finish = threading.Event()
        controller = JobController()
        controller.start("task", task=lambda: (entered.set(), finish.wait(5)))
        self.assertTrue(entered.wait(2))
        with self.assertRaises(BusyError):
            controller.start("refresh", self.cfg)
        finish.set()
        self.events(controller)

    def test_watch_wait_is_interruptible(self):
        scanned = threading.Event()
        def one_scan(*args, **kwargs):
            scanned.set()
            return {"counts": {}, "files": []}
        controller = JobController(scan_function=one_scan)
        controller.start("watch", self.cfg)
        self.assertTrue(scanned.wait(5))
        controller.stop()
        events = self.events(controller)
        self.assertTrue(events[-1]["stopped"])

    def test_worker_error_is_reported_without_secret(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-private-key"}):
            controller = JobController()
            controller.start("task", task=lambda: (_ for _ in ()).throw(ValueError("bad test-private-key")))
            events = self.events(controller)
        error = next(event["message"] for event in events if event["event"] == "error")
        self.assertNotIn("test-private-key", error)

    def test_cancellation_finishes_current_file_before_stopping(self):
        self.sample(name="a_vg=0.csv")
        self.sample(name="b_vg=0.csv")
        stop = threading.Event()
        progress = []
        def notify(outcome):
            progress.append(outcome)
            if outcome["status"] == "processing":
                stop.set()
        result = scan(self.cfg, on_progress=notify, stop_event=stop)
        self.assertEqual(result["counts"]["completed"], 1)
        self.assertTrue(result["stopped"])
        self.assertEqual([value["status"] for value in progress], ["processing", "completed"])
        self.assertTrue(Path(result["files"][0]["note"]).exists())

    def test_cancellation_during_stability_wait_skips_files(self):
        self.sample()
        stop = threading.Event()
        stop.set()
        result = scan(self.cfg, stop_event=stop)
        self.assertTrue(result["stopped"])
        self.assertEqual(result["files"], [])


class KeyTests(unittest.TestCase):
    def test_key_check_authenticates_without_sending_measurements(self):
        seen = []
        def response(request):
            seen.append(request)
            return httpx.Response(200, json={"data": []})
        with patch("research_automation.gui_backend.get_api_key", return_value="test-secret"), httpx.Client(transport=httpx.MockTransport(response)) as client:
            result = check_api_key(client)
        self.assertIn("인증 성공", result)
        self.assertEqual(seen[0].method, "GET")
        self.assertEqual(seen[0].url.path, "/v1/models")
        self.assertEqual(seen[0].content, b"")

    def test_auth_failure_does_not_show_raw_response_or_key(self):
        with patch("research_automation.gui_backend.get_api_key", return_value="test-secret"), httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(401, text="raw body test-secret"))) as client:
            with self.assertRaises(ValueError) as raised:
                check_api_key(client)
        self.assertNotIn("test-secret", str(raised.exception))
        self.assertNotIn("raw body", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
