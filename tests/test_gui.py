import os
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch

from test_system import Base
from research_automation.gui_backend import JobController

try:
    import tkinter as tk
    from research_automation.gui import ResearchApp
    HAS_TK = bool(os.environ.get("DISPLAY") or os.name == "nt")
except ImportError:
    HAS_TK = False


@unittest.skipUnless(HAS_TK, "GUI smoke requires a display and Tcl/Tk")
class GuiTests(Base):
    def setUp(self):
        super().setUp()
        self.root_window = tk.Tk()
        self.callback_errors = []
        self.root_window.report_callback_exception = lambda kind, error, traceback: self.callback_errors.append(error)
        self.app = ResearchApp(self.root_window, self.path)
        self.wait_idle()

    def tearDown(self):
        self.app.controller.stop()
        if self.app.controller.thread:
            self.app.controller.thread.join(timeout=90)
        try:
            self.app._destroy()
        except tk.TclError:
            pass
        # Tcl interpreters must be finalized on the thread that created them,
        # before another test's analysis worker may trigger cyclic collection.
        self.app = None
        self.root_window = None
        import gc
        gc.collect()
        super().tearDown()

    def pump(self, seconds=.15):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.root_window.update()
            time.sleep(.005)
        self.assertEqual(self.callback_errors, [])

    def wait_idle(self):
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            self.pump(.05)
            if not self.app.controller.busy and self.app.task_callback is None and self.app.controller.events.empty():
                return
        self.fail("GUI worker did not finish")

    def test_launch_does_not_analyze_or_show_registered_secret(self):
        self.assertFalse((self.cfg.paths["state"] / "jobs.sqlite3").exists())
        self.assertTrue(self.app.key_entry.cget("show"))
        self.assertEqual(self.app.api_key.get(), "")

    def test_evidence_panel_reads_selected_result_and_preserves_files(self):
        self.sample(); self.app._save_then('scan'); self.wait_idle()
        selected = self.app.tree.get_children()[0]
        self.app.tree.selection_set(selected); self.app._select()
        row=self.app.rows[selected]
        result=Path(row['result_path']); note=Path(row['note_path'])
        before=(result.read_bytes(), note.read_bytes())
        self.app._show_evidence(); self.pump()
        windows=[w for w in self.root_window.winfo_children() if isinstance(w,tk.Toplevel)]
        self.assertEqual(len(windows),1)
        listing=next(w for w in windows[0].winfo_children() if isinstance(w,tk.Listbox))
        self.assertGreater(listing.size(),0)
        self.assertIn('다음 확인',self.app.details.get('1.0','end'))
        windows[0].destroy()
        self.assertEqual((result.read_bytes(),note.read_bytes()),before)

    def test_settings_are_saved_using_gui_controls(self):
        self.app.ai_enabled.set(True)
        self.app._save_then(None)
        self.wait_idle()
        from research_automation.config import Config
        self.assertTrue(Config(self.path).data["ai"]["enabled"])
        self.assertEqual(self.app.activity.get(), "설정을 저장했습니다.")

    def test_audit_and_cached_plot_refresh_buttons_use_worker_and_keep_old_note(self):
        self.sample(); self.app._save_then('scan'); self.wait_idle()
        selected = self.app.tree.get_children()[0]
        self.app.tree.selection_set(selected); self.app._select()
        note = Path(self.app.rows[selected]['note_path']); before = note.read_bytes()
        with patch.object(self.app, '_open') as opened:
            self.app._audit_results(); self.wait_idle()
            audit_folder = Path(opened.call_args.args[0])
            self.assertTrue((audit_folder/'result-audit.zip').is_file())
            self.app._refresh_plots(); self.wait_idle()
            self.assertIn('그래프 갱신', str(opened.call_args.args[0]))
        self.assertEqual(note.read_bytes(), before)

    def test_scan_updates_table_and_selection_details(self):
        self.sample()
        self.app._save_then("scan")
        self.wait_idle()
        children = self.app.tree.get_children()
        self.assertEqual(len(children), 1)
        self.app.tree.selection_set(children[0])
        self.app._select()
        self.assertIn("TEST", self.app.tree.item(children[0], "values"))
        self.assertIn("PASS", self.app.details.get("1.0", "end"))
        row = self.app.rows[children[0]]
        self.assertTrue(Path(row["note_path"]).exists())
        with patch("research_automation.gui.webbrowser.open") as browser:
            if os.name != "nt":
                self.app._open_note()
                self.assertTrue(browser.call_args.args[0].startswith("obsidian://open?"))

    def test_close_waits_for_current_worker_without_freezing_ui(self):
        entered = threading.Event()
        release = threading.Event()
        self.app.controller = JobController()
        self.app._task(lambda: (entered.set(), release.wait(5)), lambda value: None)
        self.assertTrue(entered.wait(2))
        self.app.close()
        self.pump(.2)
        self.assertTrue(self.root_window.winfo_exists())
        self.assertTrue(self.app.controller.stop_event.is_set())
        release.set()
        deadline = time.monotonic() + 5
        while self.app.controller.busy and time.monotonic() < deadline:
            self.root_window.update()
            time.sleep(.01)

    def test_metadata_review_has_three_tabs_and_offline_connection_is_blocked(self):
        self.sample();self.app._save_then('scan');self.wait_idle()
        child=self.app.tree.get_children()[0];self.app.tree.selection_set(child)
        self.app._review_metadata();self.pump()
        windows=[w for w in self.root_window.winfo_children() if isinstance(w,tk.Toplevel)]
        self.assertEqual(len(windows),1)
        from tkinter import ttk
        tabs=next(w for w in windows[0].winfo_children() if isinstance(w,ttk.Notebook))
        self.assertEqual([tabs.tab(item,'text') for item in tabs.tabs()],['메타데이터 검토','관측 지표','모델 비교'])
        windows[0].destroy()
        with patch('research_automation.gui.check_api_key',side_effect=AssertionError('HTTP forbidden')):
            self.app._check_connection()
        self.assertIn('실행하지 않습니다',self.app.activity.get())


    def test_note_preview_and_fet_settings_controls_preserve_prior_note(self):
        self.sample();self.app._save_then('scan');self.wait_idle()
        selected=self.app.tree.get_children()[0];self.app.tree.selection_set(selected);self.app._select()
        original=Path(self.app.rows[selected]['note_path']);before=original.read_bytes()
        with patch.object(self.app,'_open_generated_note') as opened:
            self.app._preview_notes();self.wait_idle()
            path=Path(opened.call_args.args[0]);self.assertIn('노트 미리보기',str(path));self.assertTrue(path.is_file())
        self.assertEqual(original.read_bytes(),before)
        self.app._fet_settings();self.pump()
        dialogs=[widget for widget in self.root_window.winfo_children() if isinstance(widget,tk.Toplevel)]
        self.assertTrue(any('FET 추출 조건' in dialog.title() for dialog in dialogs))
        for dialog in dialogs:dialog.destroy()

    def test_metadata_rejected_update_reports_saved_override_without_success(self):
        import copy, hashlib, json
        from research_automation.config import Config
        from research_automation.result_review import read_jobs
        from research_automation.review_recompute import metadata_recompute
        from tkinter import ttk
        source=self.sample(); self.app._save_then('scan'); self.wait_idle()
        selected=self.app.tree.get_children()[0]; self.app.tree.selection_set(selected)
        row=self.app.rows[selected]; old_result=Path(row['result_path']).read_bytes()
        old_note=Path(row['note_path']).read_bytes(); old_jobs=read_jobs(self.app.cfg)
        source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
        data=copy.deepcopy(self.app.cfg.data); data['ingest']['max_bytes']=1
        self.path.write_text(json.dumps(data),encoding='utf-8'); self.app._use_config(Config(self.path))
        self.app._review_metadata(); self.pump()
        dialog=next(w for w in self.root_window.winfo_children() if isinstance(w,tk.Toplevel))
        tabs=next(w for w in dialog.winfo_children() if isinstance(w,ttk.Notebook))
        panel=dialog.nametowidget(tabs.tabs()[0])
        entries=[w for w in panel.winfo_children() if isinstance(w,ttk.Entry)]
        entries[0].delete(0,'end'); entries[0].insert(0,'light')
        entries[1].insert(0,'synthetic QA confirmation only')
        button=next(w for w in panel.winfo_children() if isinstance(w,ttk.Button))
        actual=[]
        def record(*args,**kwargs):
            result=metadata_recompute(*args,**kwargs); actual.append(result); return result
        with patch('research_automation.review_recompute.metadata_recompute',side_effect=record):
            button.invoke(); self.wait_idle()
        self.assertEqual(actual[0]['counts']['completed'],0)
        self.assertEqual(actual[0]['counts']['rejected'],1)
        self.assertIn('결과 갱신 실패/제외',self.app.activity.get())
        self.assertIn('max_bytes',self.app.activity.get()); self.assertIn(row['source'],self.app.activity.get())
        self.assertIn('확인 이력은 저장',self.app.activity.get())
        self.assertTrue(dialog.winfo_exists()); dialog.destroy()
        self.assertEqual(len(read_jobs(self.app.cfg)),len(old_jobs))
        self.assertEqual(Path(row['result_path']).read_bytes(),old_result)
        self.assertEqual(Path(row['note_path']).read_bytes(),old_note)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),source_hash)
        self.assertTrue((self.app.cfg.paths['vault']/'ResearchAutomation'/'metadata-overrides.json').is_file())

    def test_close_reopen_releases_owned_log_and_db_without_closing_other_handler(self):
        import logging
        from research_automation.reports import backup
        source=self.sample(); self.app._save_then('scan'); self.wait_idle()
        owned=[handler for log,handler in self.app.controller.log_owner.handlers]
        self.assertTrue(owned)
        unrelated=logging.getLogger('unrelated-test-app')
        foreign=logging.FileHandler(self.root/'foreign.log',encoding='utf-8'); unrelated.addHandler(foreign)
        try:
            self.app.close()
            self.assertTrue(all(handler.stream is None for handler in owned))
            self.assertIsNotNone(foreign.stream)
            log=self.cfg.paths['logs']/'pipeline.log'; moved=log.with_suffix('.moved')
            log.rename(moved); moved.rename(log)
            db=self.cfg.paths['state']/'jobs.sqlite3'; moved_db=db.with_suffix('.moved')
            db.rename(moved_db); moved_db.rename(db)
            self.root_window=tk.Tk(); self.app=ResearchApp(self.root_window,self.path); self.wait_idle()
            self.app._save_then('scan'); self.wait_idle()
            result=backup(self.app.cfg); self.assertTrue(Path(result['backup']).is_file())
            self.app.close(); log.rename(moved); moved.rename(log)
            db.rename(moved_db); moved_db.rename(db)
            self.assertIsNotNone(foreign.stream)
        finally:
            unrelated.removeHandler(foreign); foreign.close()


if __name__ == "__main__":
    unittest.main()
