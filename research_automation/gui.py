"""Small, local Tk interface for the existing research pipeline."""
import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, ttk
import webbrowser

from . import __version__
from .gui_backend import JobController, check_api_key, ensure_config, get_api_key, note_uri, register_api_key, safe_error, save_settings


STATUS = {"completed": "완료", "processing": "분석 중", "failed": "실패", "blocked": "재시도 제한", "rejected": "제외", "deferred": "대기", "unchanged": "기존 결과"}
AI_STATUS = {"completed": "해석 완료", "disabled": "끔", "missing_api_key": "키 없음", "api_unreachable": "연결 실패"}


def open_path(path):
    path = Path(path)
    if not path.exists():
        raise ValueError("아직 생성되지 않은 파일 또는 폴더입니다.")
    if os.name == "nt":
        os.startfile(str(path))
    else:
        subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class ResearchApp:
    def __init__(self, root, config_path, controller=None):
        self.root = root
        self.config_path = Path(config_path).resolve()
        self.controller = controller or JobController()
        self.cfg = None
        self.rows = {}
        self.closing = False
        self.task_callback = None
        self.task_value = None
        self.task_received = False
        self.had_error = False
        self.progress_running = False
        self.refresh_notice = None
        self.controls = []
        self.settings_controls = []
        self.inbox = tk.StringVar()
        self.vault = tk.StringVar()
        self.ai_enabled = tk.BooleanVar(value=False)
        self.api_key = tk.StringVar()
        self.key_status = tk.StringVar()
        self.activity = tk.StringVar(value="준비 중")
        self.counts = tk.StringVar(value="아직 분석된 파일이 없습니다.")
        self._build()
        self._load_config()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(100, self._poll)
        if self.cfg:
            self._start("refresh")

    def _build(self):
        self.root.title(f"연구 자동화 · {__version__}")
        self.root.geometry("1160x850")
        self.root.minsize(980, 740)
        self.root.configure(bg="#f3f5f8")
        style = ttk.Style(self.root)
        style.theme_use("clam")
        family = "맑은 고딕" if os.name == "nt" else "Noto Sans CJK KR"
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
            tkfont.nametofont(name).configure(family=family, size=10)
        style.configure("TFrame", background="#f3f5f8")
        style.configure("TLabel", background="#f3f5f8", foreground="#24334a", font=(family, 10))
        style.configure("Title.TLabel", font=(family, 18, "bold"))
        style.configure("Muted.TLabel", foreground="#5e6c80", font=(family, 9))
        style.configure("TButton", padding=(10, 4), font=(family, 10))
        style.configure("Primary.TButton", background="#245ed5", foreground="white")
        style.map("Primary.TButton", background=[("disabled", "#c9d2df"), ("active", "#1747ac")], foreground=[("disabled", "#68788b")])
        style.configure("TCheckbutton", background="#f3f5f8", font=(family, 10))
        style.configure("TLabelframe", background="#f3f5f8", padding=(10, 4))
        style.configure("TLabelframe.Label", background="#f3f5f8", foreground="#24334a", font=(family, 10, "bold"))
        style.configure("Treeview", rowheight=29, font=(family, 9), background="white", fieldbackground="white")
        style.configure("Treeview.Heading", font=(family, 9, "bold"), padding=6)
        shell = ttk.Frame(self.root, padding=16)
        shell.grid(sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(5, weight=1)
        header = ttk.Frame(shell)
        header.grid(row=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="연구 자동화", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, text="측정파일 분석 · QC · Obsidian 연구노트", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(3, 0))
        ttk.Button(header, text="Vault 열기", command=lambda: self._open(self.vault.get())).grid(row=0, column=1)
        folders = ttk.LabelFrame(shell, text="저장 폴더")
        folders.grid(row=1, sticky="ew", pady=(0, 10))
        folders.columnconfigure(1, weight=1)
        for row, (label, variable) in enumerate((("측정 데이터", self.inbox), ("Obsidian Vault", self.vault))):
            ttk.Label(folders, text=label, width=15).grid(row=row, column=0, sticky="w", pady=2)
            entry = ttk.Entry(folders, textvariable=variable)
            entry.grid(row=row, column=1, sticky="ew", padx=10, pady=2, ipady=2)
            button = ttk.Button(folders, text="폴더 선택", command=lambda var=variable: self._choose(var))
            button.grid(row=row, column=2, pady=2)
            self.settings_controls += [entry, button]
        ttk.Label(folders, text="입력: 소자 이름 / 측정 날짜 / 파일.xls   ·   조명 표기가 없으면 dark 기본값 (미확인) · 파일명 추정과 사용자 확인을 구분", style="Muted.TLabel").grid(row=2, column=1, sticky="w", padx=10, pady=(4, 0))
        ai = ttk.LabelFrame(shell, text="AI 해석")
        ai.grid(row=2, sticky="ew", pady=(0, 10))
        ai.columnconfigure(1, weight=1)
        toggle = ttk.Checkbutton(ai, text="AI 사용", variable=self.ai_enabled)
        toggle.grid(row=0, column=0, sticky="w", padx=(0, 12))
        ttk.Label(ai, textvariable=self.key_status, style="Muted.TLabel").grid(row=0, column=1, sticky="w")
        key_entry = ttk.Entry(ai, textvariable=self.api_key, show="●")
        self.key_entry = key_entry
        key_entry.grid(row=1, column=1, sticky="ew", pady=(8, 0), ipady=3)
        ttk.Label(ai, text="새 API 키").grid(row=1, column=0, sticky="w", pady=(8, 0))
        key_button = ttk.Button(ai, text="키 등록", command=self._register_key)
        key_button.grid(row=1, column=2, padx=(10, 0), pady=(8, 0))
        check_button = ttk.Button(ai, text="연결 확인", command=self._check_connection)
        check_button.grid(row=1, column=3, padx=(8, 0), pady=(8, 0))
        ttk.Label(ai, text="AI 사용료는 ChatGPT 구독과 별도입니다. 설정을 바꾸면 기존 파일도 다시 분석할 수 있습니다.", style="Muted.TLabel").grid(row=2, column=0, columnspan=4, sticky="w", pady=(8, 0))
        self.settings_controls += [toggle, key_entry, key_button, check_button]
        actions = ttk.Frame(shell)
        actions.grid(row=3, sticky="ew", pady=(2, 10))
        action_specs = [("한 번 분석", lambda: self._save_then("scan"), "Primary.TButton"), ("감시 시작", lambda: self._save_then("watch"), "TButton"), ("설정 저장", lambda: self._save_then(None), "TButton"), ("실패 재시도", lambda: self._save_then("scan_retry"), "TButton"), ("주간 보고", lambda: self._save_then("weekly"), "TButton"), ("새로고침", self._refresh, "TButton")]
        for index, (text, command, button_style) in enumerate(action_specs):
            button = ttk.Button(actions, text=text, command=command, style=button_style)
            button.grid(row=0, column=index, padx=(0, 8))
            self.controls.append(button)
        self.stop_button = ttk.Button(actions, text="중지", command=self.stop)
        self.stop_button.grid(row=0, column=6)
        status = ttk.Frame(shell)
        status.grid(row=4, sticky="ew", pady=(0, 8))
        status.columnconfigure(0, weight=1)
        ttk.Label(status, textvariable=self.activity, wraplength=850).grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(status, mode="indeterminate", length=150)
        self.progress.grid(row=0, column=1, padx=(10, 0))
        ttk.Label(status, textvariable=self.counts, style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))
        table = ttk.Frame(shell)
        table.grid(row=5, sticky="nsew")
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        columns = ("date", "device", "type", "conditions", "status", "qc", "ai", "source")
        self.tree = ttk.Treeview(table, columns=columns, show="headings", selectmode="browse", height=10)
        headings = ("측정 날짜", "소자", "측정 유형", "측정 조건", "처리 상태", "QC", "AI", "원본 상대 경로")
        widths = (100, 120, 80, 205, 80, 55, 90, 270)
        for column, heading, width in zip(columns, headings, widths):
            self.tree.heading(column, text=heading)
            self.tree.column(column, width=width, minwidth=50, stretch=column in ("conditions", "source"))
        self.tree.grid(sticky="nsew")
        vertical = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.tag_configure("failed", foreground="#b42318")
        self.tree.tag_configure("warn", foreground="#986000")
        self.tree.bind("<<TreeviewSelect>>", self._select)
        self.tree.bind("<Double-1>", lambda event: self._open_note())
        results = ttk.Frame(shell)
        results.grid(row=6, sticky="ew", pady=(8, 8))
        ttk.Button(results, text="선택 노트 열기", command=self._open_note).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(results, text="선택 결과 폴더", command=self._open_result).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(results, text="전체 측정 목록", command=self._open_catalog).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(results, text="설정 파일", command=lambda: self._open(self.config_path)).grid(row=0, column=3)
        review = ttk.Button(results, text="메타데이터 검토", command=self._review_metadata)
        review.grid(row=0,column=4,padx=(8,0))
        self.controls.append(review)
        preview_button=ttk.Button(results,text='변경 미리보기',command=self._preview_changes)
        preview_button.grid(row=0,column=5,padx=(8,0));self.controls.append(preview_button)
        audit_button = ttk.Button(results, text='전체 결과 점검', command=self._audit_results)
        audit_button.grid(row=1, column=0, pady=(8,0), padx=(0,8));self.controls.append(audit_button)
        refresh_button = ttk.Button(results, text='선택 그래프 갱신', command=self._refresh_plots)
        refresh_button.grid(row=1, column=1, pady=(8,0), padx=(0,8));self.controls.append(refresh_button)
        note_button=ttk.Button(results,text='선택 노트 미리보기',command=self._preview_notes)
        note_button.grid(row=1,column=2,pady=(8,0),padx=(0,8));self.controls.append(note_button)
        fet_button=ttk.Button(results,text='FET 추출 조건',command=self._fet_settings)
        fet_button.grid(row=1,column=3,pady=(8,0));self.controls.append(fet_button)
        ttk.Button(results, text='RR / gm 계산 근거', command=self._show_evidence).grid(row=1, column=4, padx=(8,0), pady=(8,0))
        detail_frame = ttk.LabelFrame(shell, text="선택한 결과 · 조건·판단·다음 확인", padding=6)
        detail_frame.grid(row=7, sticky="ew")
        detail_frame.columnconfigure(0, weight=1)
        self.details = tk.Text(detail_frame, height=5, wrap="word", font=(family, 9), bg="white", relief="flat", state="disabled")
        self.details.grid(row=0, column=0, sticky="ew")
        detail_scroll = ttk.Scrollbar(detail_frame, command=self.details.yview)
        detail_scroll.grid(row=0, column=1, sticky="ns")
        self.details.configure(yscrollcommand=detail_scroll.set)
        ttk.Label(shell, text=f"{__version__}   ·   설정: {self.config_path.name}   ·   중지 시 현재 파일 저장을 마친 뒤 멈춥니다.", style="Muted.TLabel").grid(row=8, sticky="w", pady=(8, 0))

    def _load_config(self):
        try:
            self._use_config(ensure_config(self.config_path))
            self.activity.set("준비됨 · 자동으로 분석을 시작하지 않습니다.")
        except Exception as error:
            self.cfg = None
            self._notice("설정 읽기 실패: " + safe_error(error))
        self._update_controls()

    def _use_config(self, cfg):
        self.cfg = cfg
        self.inbox.set(str(cfg.paths["inbox"]))
        self.vault.set(str(cfg.paths["vault"]))
        self.ai_enabled.set(cfg.data["ai"]["enabled"])
        self._update_key_status()
        if cfg.data["science"]["offline"]:
            self.key_status.set("연구 검토 모드: 외부 API 호출 차단 · 규칙 기반 요약")

    def _update_key_status(self):
        self.key_status.set("API 키 등록됨 · 연결 확인을 눌러 인증을 확인하세요." if get_api_key() else "API 키 없음 · AI를 꺼도 분석·QC·노트 저장은 작동합니다.")

    def _choose(self, variable):
        path = filedialog.askdirectory(parent=self.root, initialdir=variable.get() if Path(variable.get()).is_dir() else str(self.config_path.parent), title="폴더 선택")
        if path:
            variable.set(path)

    def _notice(self, text):
        self.activity.set(text)

    def _task(self, task, callback):
        if self.controller.busy or self.task_callback or self.closing:
            return
        self.task_callback = callback
        self.task_received = False
        self.task_value = None
        self.had_error = False
        self.controller.start("task", task=task)
        self.activity.set("설정 확인 중…")
        self._update_controls()

    def _save_then(self, mode):
        if not self.cfg:
            self._notice("설정 파일을 확인한 뒤 새로고침을 누르세요.")
            return
        inbox, vault, enabled = self.inbox.get(), self.vault.get(), self.ai_enabled.get()
        if os.name=="nt" and mode in ("scan","watch","scan_retry") and (not Path(inbox).is_dir() or not Path(vault).is_dir()):
            self._notice("현재 PC의 실제 측정 폴더와 Vault를 선택하세요. 다른 사용자 폴더를 자동으로 생성하지 않습니다.");return
        config_path = self.config_path
        def saved(cfg):
            self._use_config(cfg)
            if mode:
                self._start(mode)
            else:
                self._notice("설정을 저장했습니다.")
        self._task(lambda: save_settings(config_path, inbox, vault, enabled), saved)

    def _register_key(self):
        value = self.api_key.get()
        if not value.strip():
            self._notice("새 API 키 입력란에 키를 붙여넣으세요.")
            return
        def saved(result):
            self.api_key.set("")
            self._update_key_status()
            self._notice("API 키를 등록했습니다. AI 사용을 선택하고 설정을 저장하세요.")
        self._task(lambda: register_api_key(value), saved)

    def _refresh(self):
        if self.controller.busy or self.task_callback:
            return
        self._load_config()
        if self.cfg:
            self._start("refresh")

    def _start(self, mode):
        if self.closing:
            return
        try:
            self.had_error = False
            self.controller.start(mode, self.cfg)
            self.activity.set({"scan": "폴더 분석 중…", "scan_retry": "실패 파일 재시도 중…", "watch": "폴더 감시 중…", "weekly": "주간 보고 생성 중…", "refresh": "최근 결과 읽는 중…"}[mode])
        except Exception as error:
            self._notice(safe_error(error))
        self._update_controls()

    def stop(self):
        self.controller.stop()
        self.activity.set("중지 요청됨 · 현재 파일의 저장을 마친 뒤 멈춥니다.")
        self._update_controls()

    def _update_controls(self):
        busy = self.controller.busy or self.task_callback is not None or self.closing
        for control in self.settings_controls:
            control.configure(state="disabled" if busy else "normal")
        for button in self.controls:
            button.configure(state="disabled" if busy else "normal")
        self.stop_button.configure(state="normal" if self.controller.busy and self.controller.mode in ("scan", "scan_retry", "watch") and not self.controller.stop_event.is_set() else "disabled")
        if busy and not self.progress_running:
            self.progress.start(15)
            self.progress_running = True
        elif not busy and self.progress_running:
            self.progress.stop()
            self.progress_running = False

    def _display_row(self, row, first=False):
        identifier = row["id"]
        self.rows[identifier] = row
        values = (row["measurement_date"], row["device_name"], row["measurement_type"], row["condition_label"], STATUS.get(row["status"], row["status"]), row["qc"], AI_STATUS.get(row.get("ai_status"), row.get("ai_status") or "—"), row["source"])
        tag = "failed" if row["status"] == "failed" or row["qc"] == "FAIL" else "warn" if row["qc"] == "WARN" or row["review_required"] else ""
        if self.tree.exists(identifier):
            self.tree.item(identifier, values=values, tags=(tag,))
        else:
            self.tree.insert("", 0 if first else "end", iid=identifier, values=values, tags=(tag,))

    def _display_jobs(self, jobs):
        selection = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        self.rows.clear()
        for row in jobs:
            self._display_row(row)
        if selection and self.tree.exists(selection[0]):
            self.tree.selection_set(selection[0])
        completed = sum(row["status"] == "completed" for row in jobs)
        warned = sum(row["qc"] == "WARN" for row in jobs)
        failed = sum(row["status"] == "failed" or row["qc"] == "FAIL" for row in jobs)
        review = sum(row["review_required"] for row in jobs)
        self.counts.set(f"최근 {len(jobs)}건 (최대 200건)   ·   완료 {completed}   ·   QC 경고 {warned}   ·   실패/QC FAIL {failed}   ·   분류 확인 {review}")

    def _selected(self):
        selection = self.tree.selection()
        return self.rows.get(selection[0]) if selection else None

    def _select(self, event=None):
        row = self._selected()
        if not row:
            return
        text = [f"조건: {row['measurement_date']} · {row['device_name']} · {row['condition_label']}",
                '현재 판단: QC는 데이터 점검 결과입니다. 연구 사용·비교에는 단위, 광 조건, 원래 sweep과 이력 확인이 필요합니다.',
                '다음 확인: 메타데이터 검토에서 보류/충돌 조건을 확인하세요.' if row['review_required'] else '다음 확인: RR / gm 계산 근거에서 평가 전압과 원본점을 확인하세요.',
                f"원본: {row['source']}", f"처리: {STATUS.get(row['status'], row['status'])} · QC: {row['qc']} · AI: {AI_STATUS.get(row.get('ai_status'), row.get('ai_status') or '—')}"]
        text.insert(2, row.get('metric_summary', '사용 가능한 지표: 완료 결과를 선택하세요.'))
        text += [str(row[key]) for key in ("error", "details", "qc_details") if row.get(key)]
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", "\n".join(text))
        self.details.configure(state="disabled")

    def _show_evidence(self):
        row = self._selected()
        if not row or row.get('status') != 'completed' or not row.get('result_path'):
            self._notice('계산 근거를 보려면 완료 결과를 선택하세요.'); return
        from .result_evidence import load_evidence, support_text
        try:
            items = load_evidence(row['result_path'])
        except (OSError, ValueError) as error:
            self._notice('결과 파일 경로를 확인한 뒤 선택 파일을 다시 분석하세요. ' + safe_error(error)); return
        if not items:
            self._notice('이 결과에는 RR / gm 근거가 없습니다. 이전 결과라면 원본을 보존하고 선택 파일만 다시 분석하세요.'); return
        dialog = tk.Toplevel(self.root); dialog.title('계산 근거 · 저장된 결과 읽기'); dialog.geometry('950x650')
        dialog.columnconfigure(1, weight=1); dialog.rowconfigure(0, weight=1)
        listing = tk.Listbox(dialog, width=35, exportselection=False)
        listing.grid(row=0, column=0, sticky='nsew', padx=8, pady=8)
        panel = ttk.Frame(dialog); panel.grid(row=0, column=1, sticky='nsew', padx=8, pady=8)
        text = tk.Text(panel, wrap='word'); scroll = ttk.Scrollbar(panel, command=text.yview)
        text.configure(yscrollcommand=scroll.set); scroll.pack(side='right', fill='y'); text.pack(fill='both', expand=True)
        for item in items:
            voltage = item['support'].get('evaluation_abs_vd_v')
            listing.insert('end', f"{item['group_id']} · {item['metric']}" + (f" · u={voltage} V" if voltage is not None else ''))
        def select(event=None):
            if not listing.curselection(): return
            text.configure(state='normal'); text.delete('1.0','end')
            text.insert('1.0', support_text(items[listing.curselection()[0]])); text.configure(state='disabled')
        listing.bind('<<ListboxSelect>>', select); listing.selection_set(0); select()

    def _open(self, path):
        try:
            if not str(path).strip():
                raise ValueError("먼저 폴더 또는 파일을 선택하세요.")
            open_path(path)
        except Exception as error:
            self._notice(safe_error(error))

    def _open_note(self):
        row = self._selected()
        try:
            if not row or not row.get("note_path"):
                raise ValueError("노트가 생성된 완료 파일을 선택하세요.")
            uri = note_uri(row["note_path"])
            if os.name == "nt":
                os.startfile(uri)
            else:
                webbrowser.open(uri)
        except Exception as error:
            self._notice(safe_error(error))

    def _open_result(self):
        row = self._selected()
        if not row or not row.get("result_path"):
            self._notice("분석 결과가 있는 완료 파일을 선택하세요.")
            return
        self._open(Path(row["result_path"]).parent)

    def _open_catalog(self):
        if not self.cfg:
            return
        from .science_exports import catalog_path
        path = catalog_path(self.cfg)
        try:
            uri = note_uri(path)
            if os.name == "nt":
                os.startfile(uri)
            else:
                webbrowser.open(uri)
        except Exception as error:
            self._notice(safe_error(error))

    def _check_connection(self):
        if self.cfg and self.cfg.data['science']['offline']:
            self._notice('연구 검토 모드에서는 외부 API 연결 확인을 실행하지 않습니다.')
            return
        self._task(check_api_key,lambda message:self._notice(message))

    def _preview_changes(self):
        if not self.cfg:return
        from .change_preview import preview
        cfg=self.cfg
        def display(result):
            dialog=tk.Toplevel(self.root);dialog.title('분석 변경 목록 · 읽기 전용');dialog.geometry('900x500')
            ttk.Label(dialog,text='기존 노트/결과는 보존합니다. 대표 파일은 CLI --source 또는 메타데이터 검토에서 선택 갱신하세요.').pack(pady=10)
            table=ttk.Treeview(dialog,columns=('action','preserved'),show='tree headings')
            table.heading('#0',text='원본 상대 경로');table.column('#0',width=500)
            table.heading('action',text='작업');table.heading('preserved',text='기존 결과 보존 수')
            table.pack(fill='both',expand=True)
            for item in result['files']:table.insert('','end',text=item['source_relative_path'],values=(item['action'],item['previous_notes_preserved']))
            def selected_scan():
                selected=table.selection()
                if not selected:self._notice('미리보기에서 대표 원본 하나를 선택하세요.');return
                relative=table.item(selected[0],'text')
                from .pipeline import scan
                def completed(output):
                    if dialog.winfo_exists():dialog.destroy()
                    self._notice('선택 원본의 새 버전 결과를 저장했습니다.');self._start('refresh')
                self._task(lambda:scan(cfg,sources=[relative]),completed)
            ttk.Button(dialog,text='선택 파일만 분석',command=selected_scan).pack(anchor='e',padx=10,pady=10)
        self._task(lambda:preview(cfg),display)

    def _audit_results(self):
        if not self.cfg:return
        from .result_review import audit_results
        cfg = self.cfg
        def done(result):
            self._notice(f"결과 점검 완료: 입력 {result['input_files']}개 / 완료 {result['covered_inputs']}개. 점검용 ZIP: {result['bundle']}")
            self._open(Path(result['bundle']).parent)
        self._task(lambda: audit_results(cfg), done)

    def _refresh_plots(self):
        row = self._selected()
        if not row or row.get('status') != 'completed':
            self._notice('그래프를 갱신할 완료 파일을 선택하세요.');return
        from .result_review import refresh_plots
        cfg, source = self.cfg, row['source']
        def done(result):
            if result['completed']:
                self._notice('수치 재분석 없이 그래프를 새 폴더에 저장했습니다. 기존 노트와 그림은 보존했습니다.')
                self._open(result['files'][0]['note'])
            else:self._notice('저장된 결과/curves.csv를 찾지 못해 그래프를 갱신하지 못했습니다.')
        self._task(lambda: refresh_plots(cfg, [source]), done)

    def _preview_notes(self):
        row=self._selected()
        if not row or row.get('status')!='completed':
            self._notice('새 형식으로 볼 완료 파일을 선택하세요.');return
        from .note_preview import preview_notes
        cfg,source=self.cfg,row['source']
        def done(result):
            self._notice('기존 노트·계산·QC를 보존하고 새 노트 미리보기와 파라미터 그림을 저장했습니다.')
            self._open_generated_note(result['files'][0]['note'])
        self._task(lambda:preview_notes(cfg,[source]),done)

    def _open_generated_note(self,path):
        try:
            uri=note_uri(path)
            if os.name=='nt':os.startfile(uri)
            else:webbrowser.open(uri)
        except Exception as error:self._notice(safe_error(error))

    def _fet_settings(self):
        row=self._selected()
        if not row or not row.get('result_path'):
            self._notice('FET 조건을 설정할 완료 파일을 선택하세요.');return
        from .fet_parameters import settings_for
        from .fet_settings import save_settings
        try:
            summary=json.loads(Path(row['result_path']).read_text(encoding='utf-8-sig'))
            settings,path=settings_for(self.cfg,summary)
            device=summary.get('research_context',{}).get('device_name')
            if not device:raise ValueError('소자 이름을 먼저 확인하세요.')
            data=json.loads(path.read_text(encoding='utf-8-sig')) if path else {'devices':{}}
            data['devices'][device]=settings
        except Exception as error:self._notice(safe_error(error));return
        dialog=tk.Toplevel(self.root);dialog.title('추가 FET 추출 조건 · 기존 계산/메타데이터 보존');dialog.geometry('920x700')
        ttk.Label(dialog,text='SI 치수: L/W/t는 m, Cox는 F/m². status와 source를 보존하세요.').pack(anchor='w',padx=12,pady=6)
        ttk.Label(dialog,text='yfm / ss_local의 window_v=[최소 V, 최대 V]로 평가 구간을 지정할 수 있습니다.').pack(anchor='w',padx=12)
        text=tk.Text(dialog,wrap='none');text.pack(fill='both',expand=True,padx=12,pady=8)
        text.insert('1.0',json.dumps(data,ensure_ascii=False,indent=2))
        ttk.Label(dialog,text='저장만으로 기존 결과를 변경하지 않습니다. ‘선택 노트 미리보기’로 새 추출·그림을 확인하세요.').pack(anchor='w',padx=12)
        def save():
            try:parsed=json.loads(text.get('1.0','end'));saved=save_settings(self.cfg,parsed)
            except Exception as error:self._notice(safe_error(error));return
            self._notice('추가 FET 조건을 저장했습니다. 기존 조건 파일은 사본으로 보존했습니다.');dialog.destroy()
        ttk.Button(dialog,text='추가 조건 저장',command=save).pack(anchor='e',padx=12,pady=10)

    def _review_metadata(self):
        row=self._selected()
        if not row or not row.get('result_path'):
            self._notice('검토할 완료 파일을 선택하세요.'); return
        from .metadata_review import UNITS, save_override
        try:summary=json.loads(Path(row['result_path']).read_text(encoding='utf-8'))
        except (OSError,ValueError) as error:self._notice(safe_error(error)); return
        dialog=tk.Toplevel(self.root); dialog.title('메타데이터 확인 · 원본 수정 없음'); dialog.geometry('980x720')
        tabs=ttk.Notebook(dialog); tabs.pack(fill='both',expand=True,padx=12,pady=12)
        metadata=ttk.Frame(tabs,padding=10); tabs.add(metadata,text='메타데이터 검토')
        table=ttk.Treeview(metadata,columns=('value','unit','status','source'),show='tree headings',height=13)
        table.heading('#0',text='필드'); table.column('#0',width=160)
        for key,label in [('value','현재 값'),('unit','단위'),('status','확인 상태'),('source','출처')]:
            table.heading(key,text=label); table.column(key,width=130)
        table.pack(fill='both',expand=True)
        fields=summary.get('research_context',{}).get('fields',{})
        for key in UNITS:
            item=fields.get(key,{})
            table.insert('', 'end',iid=key,text=key,values=(item.get('value') if item.get('value') is not None else 'unknown',UNITS[key] or '—',item.get('status','missing'),item.get('source','unavailable')))
        selected=tk.StringVar(value='illumination'); value=tk.StringVar(); reason=tk.StringVar()
        def select(event=None):
            selection=table.selection()
            if selection:
                selected.set(selection[0]); item=fields.get(selection[0],{})
                value.set(str(item.get('value')) if item.get('value') is not None else '')
                evidence.configure(state='normal'); evidence.delete('1.0','end')
                evidence.insert('1.0',json.dumps({'candidates':item.get('candidates',[]),'history':item.get('history',[])},ensure_ascii=False,indent=2)); evidence.configure(state='disabled')
        table.bind('<<TreeviewSelect>>',select)
        evidence=tk.Text(metadata,height=5,wrap='word',state='disabled'); evidence.pack(fill='x',pady=6)
        ttk.Label(metadata,text='선택 필드 확인값 (광 조건 dark/light/unknown; 날짜 YYYY-MM-DD; 단위 확인 true/false)').pack(anchor='w')
        ttk.Entry(metadata,textvariable=value).pack(fill='x')
        ttk.Label(metadata,text='확인 근거/수정 이유 · delay가 장비 기록과 다르면 충돌을 유지합니다.').pack(anchor='w',pady=(6,0))
        ttk.Entry(metadata,textvariable=reason).pack(fill='x')
        def save():
            field=selected.get(); text=value.get().strip()
            try:
                parsed=float(text) if field in ('sweep_delay_s','hold_s','optical_power_w') and text else (text.casefold()=='true' if field=='units_confirmed' and text.casefold() in ('true','false') else text or None)
            except ValueError:self._notice('숫자와 단위를 확인하세요.'); return
            why=reason.get().strip(); cfg=self.cfg; result_path=Path(row['result_path'])
            def task():
                from .review_recompute import metadata_recompute
                save_override(cfg,summary['source_relative_path'],summary['source_sha256'],{field:parsed},why)
                try:
                    return metadata_recompute(cfg,result_path,changed_fields=[field])
                except Exception as error:
                    raise ValueError('확인 이력은 저장됐지만 결과 갱신에 실패했습니다. 선택 파일을 다시 분석하세요. ' + safe_error(error)) from error
            def done(result):
                from .gui_backend import metadata_update_notice
                notice = metadata_update_notice(result, row['source'])
                self.refresh_notice = notice['message']
                self._notice(notice['message'])
                if notice['success'] and dialog.winfo_exists():dialog.destroy()
                self._start('refresh')
            self._task(task,done)
        ttk.Button(metadata,text='확인 저장 + 선택 결과 갱신',command=save).pack(anchor='e',pady=8)
        for title,key in [('관측 지표','groups'),('모델 비교','model_diagnostics')]:
            panel=ttk.Frame(tabs,padding=10); tabs.add(panel,text=title)
            if key=='groups':
                from .science_exports import metric_rows
                columns=('metric','value','unit','status','voltage','reason')
                labels=('지표','값/가정값','단위','상태','평가 |Vd| (V)','사유')
                items=metric_rows(summary) if summary.get('schema_version',0)>=4 else []
            else:
                columns=('metric','value','unit','status','voltage','reason')
                labels=('경험적/유효 모델','학습 RMSE / 보류 RMSE','단위','상태','피팅 |Vd| 구간 (V)','계수/사유')
                items=[]
                for group in summary['groups']:
                    for fit in group.get('fits',[]):items.append({'group_id':group['group_id'],'metric':fit['model'],'value':fit['rmse_a'],'unit':'A','metric_status':fit.get('model_status','converged'),'reason':'경험적 기준선; 물리 메커니즘 승자 아님'})
                    effective=group.get('rectifier_models',{})
                    if not effective.get('models'):items.append({'group_id':group['group_id'],'metric':'선택적 정류 모델','metric_status':'not_run','reason':effective.get('reason','not_enabled')})
                    for model in effective.get('models',[]):items.append({'group_id':group['group_id'],'metric':model['model'],'value':f"{model.get('current_rmse_a')} / {model.get('heldout_rmse_a')}",'unit':'A','metric_status':model['model_status'],'evaluation_abs_vd_v':str(effective.get('window_v')),'reason':json.dumps(model.get('parameters',{}),ensure_ascii=False)})
            view=ttk.Treeview(panel,columns=columns,show='tree headings');view.heading('#0',text='곡선');view.column('#0',width=70)
            for column,label in zip(columns,labels):view.heading(column,text=label);view.column(column,width=110 if column!='reason' else 220)
            view.pack(fill='both',expand=True)
            for item in items:
                primary=item.get('value');candidate=item.get('candidate_value_assuming_si')
                displayed=primary if primary is not None else ('보류; SI 가정 '+str(candidate) if candidate is not None else 'null')
                view.insert('','end',text=item['group_id'],values=(item['metric'],displayed,item.get('unit') or '—',item.get('metric_status'),item.get('evaluation_abs_vd_v') if item.get('evaluation_abs_vd_v') is not None else '—',item.get('reason')))
            ttk.Label(panel,text='세부 추출점·조건·계수 단위는 선택 결과 폴더의 observable_metrics.csv / model_diagnostics.csv에서 확인합니다.').pack(anchor='w',pady=8)
        table.selection_set('illumination'); select()

    def _finish_task(self):
        if self.controller.busy:
            self.root.after(25, self._finish_task)
            return
        callback, value, received = self.task_callback, self.task_value, self.task_received
        self.task_callback = None
        self.task_value = None
        self.task_received = False
        if callback and received and not self.closing:
            try:
                callback(value)
            except Exception as error:
                self._notice(safe_error(error))
        self._update_controls()

    def _poll(self):
        try:
            for _ in range(100):
                event = self.controller.events.get_nowait()
                kind = event["event"]
                if kind == "jobs":
                    self._display_jobs(event["jobs"])
                elif kind == "row":
                    self._display_row(event["row"], first=True)
                elif kind == "progress":
                    outcome = event["outcome"]
                    if not self.controller.stop_event.is_set():
                        self.activity.set(f"{STATUS.get(outcome['status'], outcome['status'])}: {outcome['source']}")
                elif kind == "batch":
                    counts = event["result"]["counts"]
                    prefix = "감시 중" if self.controller.mode == "watch" and not self.controller.stop_event.is_set() else "분석 결과"
                    self.activity.set(f"{prefix} · 신규 완료 {counts['completed']} · 실패 {counts['failed']} · 대기 {counts['deferred']} · 재시도 제한 {counts['blocked']} · 제외 {counts['rejected']}")
                elif kind == "weekly":
                    self.activity.set("주간 보고 저장 완료: " + Path(event["result"]["report"]).name)
                elif kind == "task_result":
                    self.task_value, self.task_received = event["result"], True
                elif kind in ("error", "waiting"):
                    self.had_error = True
                    self._notice(event["message"])
                elif kind == "finished":
                    if event["mode"] == "task":
                        self.root.after(25, self._finish_task)
                    elif event["stopped"] and not self.closing:
                        self.activity.set("중지 완료 · 저장된 결과는 유지됩니다.")
                    elif event["mode"] == "refresh" and not self.had_error:
                        self.activity.set(self.refresh_notice or "준비됨 · 한 번 분석하거나 감시를 시작하세요.")
                        self.refresh_notice = None
        except queue.Empty:
            pass
        if self.closing and not self.controller.busy:
            self._destroy()
            return
        self._update_controls()
        self.root.after(100, self._poll)

    def close(self):
        self.closing = True
        self.controller.stop()
        self.api_key.set("")
        if self.controller.busy:
            self.activity.set("종료 대기 · 현재 파일 저장을 마친 뒤 창을 닫습니다.")
            self._update_controls()
        else:
            self._destroy()

    def _destroy(self):
        self.controller.close_resources()
        # Cancel Python/Tk timers before deleting their callback commands.
        for timer in self.root.tk.call("after", "info"):
            self.root.tk.call("after", "cancel", timer)
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description="연구 자동화 GUI")
    parser.add_argument("--config", default=str(Path(__file__).resolve().parents[1] / "config.json"))
    parser.add_argument('--smoke-test', action='store_true', help='Open the GUI, record startup state, and close without analysis')
    args = parser.parse_args()
    root = tk.Tk()
    try:
        app = ResearchApp(root, args.config)
        if args.smoke_test:
            def check_startup():
                if app.controller.busy or app.task_callback:
                    root.after(100, check_startup)
                    return
                from .util import write_json
                import sys
                write_json(Path(args.config).resolve().parent/'gui-startup-smoke.json', {
                    'configured': app.cfg is not None, 'executable': sys.executable,
                    'config': str(app.config_path), 'tk_version': root.tk.call('info','patchlevel'),
                    'geometry': root.winfo_geometry(), 'automatic_analysis': False,
                    'message': app.activity.get()})
                app.close()
            root.after(200, check_startup)
        root.mainloop()
    except Exception as error:
        messagebox.showerror("연구 자동화", safe_error(error), parent=root)
        root.destroy()
        return 1
    return 0 if not args.smoke_test or app.cfg is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
