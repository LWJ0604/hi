"""GUI services. Workers communicate through a queue and never touch Tk."""
import copy
import json
import os
from pathlib import Path
import queue
import shutil
import sqlite3
from contextlib import closing
import threading
from urllib.parse import urlencode

from .config import Config, initialize
from .store import BusyError, lock
from .util import now, write_json


def ensure_config(path):
    path = Path(path).resolve()
    if not path.exists():
        template = path.parent / ("config.windows.json" if os.name == "nt" else "config.example.json")
        if template.exists():
            data = Config(template).data
            if os.name=="nt":
                home=Path(os.environ.get("USERPROFILE",Path.home()))
                onedrive=Path(os.environ.get("OneDrive",home/"OneDrive"))
                suggestions=[onedrive/"문서"/"Obsidian Vault",onedrive/"Documents"/"Obsidian Vault",home/"Documents"/"Obsidian Vault"]
                existing=next((p for p in suggestions if p.is_dir() and (p/"측정 데이터").is_dir()),None)
                if existing is not None:
                    data["paths"]["vault"]=str(existing);data["paths"]["inbox"]=str(existing/"측정 데이터")
            write_json(path, data)
        else:
            return initialize(path)
    return Config(path)


def save_settings(path, inbox, vault, ai_enabled, confirmed_va=None, electrode_pair=None):
    current = Config(path)
    data = copy.deepcopy(current.data)
    if not isinstance(ai_enabled, bool):
        raise ValueError("AI 설정은 켜기/끄기로 지정하세요.")
    changed = current.data["ai"]["enabled"] != ai_enabled
    for key, value in (("inbox", inbox), ("vault", vault)):
        if not str(value).strip():
            raise ValueError("측정 데이터와 Vault 폴더를 선택하세요.")
        candidate = (current.root / Path(str(value).strip()).expanduser()).resolve()
        if candidate != current.paths[key]:
            data["paths"][key] = str(candidate)
            changed = True
    data["ai"]["enabled"] = ai_enabled
    if confirmed_va is not None:
        if not isinstance(confirmed_va,bool):raise ValueError('단위 확인은 켜기/끄기로 지정하세요.')
        profile=data['measurement_profile']
        already_va=profile['confirmed'] and profile['voltage_unit']=='V' and profile['current_unit']=='A'
        if confirmed_va and not already_va:
            data['measurement_profile']={'voltage_unit':'V','current_unit':'A','confirmed':True,
                'source':'GUI에서 사용자 확인 '+now(current).isoformat()}
            changed=True
        elif not confirmed_va and already_va:
            data['measurement_profile']={'voltage_unit':None,'current_unit':None,'confirmed':False,'source':None}
            changed=True
    if electrode_pair is not None:
        if not isinstance(electrode_pair,str):raise ValueError('전극쌍은 device.md의 이름으로 지정하세요.')
        pair=electrode_pair.strip() or None
        if pair!=data['benchmark']['electrode_pair']:data['benchmark']['electrode_pair']=pair;changed=True
    if not changed:
        return current
    # Validate all paths/QC before touching the user's existing configuration.
    import tempfile
    descriptor, name = tempfile.mkstemp(prefix=".gui-config-", suffix=".json", dir=current.root)
    os.close(descriptor)
    draft = Path(name)
    try:
        write_json(draft, data)
        Config(draft)
        with lock(current):
            backup = current.path.with_name("config.before-gui-" + now(current).strftime("%Y%m%d-%H%M%S-%f") + ".json")
            shutil.copy2(current.path, backup)
            write_json(current.path, data)
    finally:
        draft.unlink(missing_ok=True)
    return Config(current.path)


def get_api_key():
    if os.name == "nt":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                value, _ = winreg.QueryValueEx(key, "OPENAI_API_KEY")
                if isinstance(value, str) and value.strip():
                    return value.strip()
        except OSError:
            pass
    return os.environ.get("OPENAI_API_KEY", "").strip()


def register_api_key(value):
    value = value.strip()
    if not value or any(ord(char) < 32 for char in value):
        raise ValueError("API 키를 입력하세요. 여러 줄 대신 키 하나를 붙여넣으세요.")
    if os.name != "nt":
        raise ValueError("영구 키 등록은 Windows에서 실행하세요. Linux 검증에서는 환경변수를 사용합니다.")
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
        winreg.SetValueEx(key, "OPENAI_API_KEY", 0, winreg.REG_SZ, value)
    os.environ["OPENAI_API_KEY"] = value
    # Existing GUI workers use the process value; new apps also receive the
    # Windows environment notification. Never put the key in a command line.
    import ctypes
    from ctypes import wintypes
    response = ctypes.c_size_t()
    try:
        send = ctypes.windll.user32.SendMessageTimeoutW
        send.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPCWSTR, wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
        send(0xFFFF, 0x001A, 0, "Environment", 0x0002, 1000, ctypes.byref(response))
    except (AttributeError, OSError):
        pass
    return {"registered": True}


def check_api_key(client=None):
    key = get_api_key()
    if not key:
        raise ValueError("먼저 API 키를 등록하세요.")
    import httpx
    owned = client is None
    client = client or httpx.Client(timeout=10)
    try:
        response = client.get("https://api.openai.com/v1/models", headers={"Authorization": "Bearer " + key})
        if response.status_code == 200:
            return "API 인증 성공. 실제 해석은 모델 권한과 API 잔액에 따라 달라집니다."
        if response.status_code in (401, 403):
            raise ValueError("API 인증 실패. 키와 프로젝트 권한을 확인하세요.")
        if response.status_code == 429:
            raise ValueError("API 요청 제한. 잠시 후 다시 확인하세요.")
        raise ValueError(f"API 연결 확인 실패 (HTTP {response.status_code}).")
    except (httpx.TimeoutException, httpx.NetworkError) as error:
        raise ValueError("OpenAI 연결 실패. 인터넷 연결을 확인하세요.") from error
    finally:
        if owned:
            client.close()


def safe_error(error):
    text = str(error)
    if isinstance(error,PermissionError):text+=' 폴더의 쓰기 권한과 다른 프로그램의 파일 사용 여부를 확인한 뒤 다시 실행하세요.'
    elif isinstance(error,FileNotFoundError):text+=' 입력 폴더와 파일 위치를 확인한 뒤 다시 선택하세요.'
    key = os.environ.get("OPENAI_API_KEY", "")
    return (text.replace(key, "[API 키 숨김]") if key else text)[:2000]


def job_row(job):
    row = {**job, "measurement_date": "—", "device_name": "—", "measurement_type": "—", "condition_label": "—", "qc": "—", "review_required": False}
    if job.get("result_path"):
        try:
            summary = json.loads(Path(job["result_path"]).read_text(encoding="utf-8"))
            context = summary.get("research_context", {})
            row.update({key: context.get(key) or "미확인" for key in ("measurement_date", "device_name", "measurement_type", "condition_label")})
            row["qc"] = summary["qc"]["overall"]
            from .result_evidence import evidence_items
            items = evidence_items(summary)
            shown = [f"{item['metric']}={item['support']['value']:.4g} {item['support'].get('unit') or ''}" +
                     (f" (u={item['support']['evaluation_abs_vd_v']} V)" if 'evaluation_abs_vd_v' in item['support'] else '')
                     for item in items if isinstance(item['support'].get('value'), (int, float))][:3]
            row['metric_summary'] = '핵심 지표 (최대 3개, 후보 포함): ' + (' · '.join(shown) if shown else '값 보류 또는 저장된 근거 없음')
            if summary.get('observation_headlines'):
                row['metric_summary']='관측 수치 (가정·한계 포함): '+' · '.join(summary['observation_headlines'][:3])+'\n모든 branch·원본 점: 선택 측정 수치 검토'
            row["review_required"] = context.get("metadata_status") != "confirmed" if "metadata_status" in context else bool(context.get("warnings"))
            detail = "\n".join(context.get("warnings", []))
            for key, label in (("measurement_date", "측정 날짜"), ("illumination", "조명"), ("device_name", "소자 이름"), ("device_type", "소자 종류"), ("source_folder_path", "상위 폴더 경로"), ("Settings/Last Executed", "장비 기록"), ("folder/", "폴더: ")):
                detail = detail.replace(key, label)
            if "metadata_status" in context:
                detail = "메타데이터: " + context["metadata_status"] + " (PASS/SKIP과 별개)\n" + detail
            row["details"] = detail
            row["qc_details"] = "\n".join(f"{check['code']} ({check.get('scope', '')}): {check['status']}" for check in summary["qc"]["checks"] if check["status"] in ("WARN", "FAIL"))[:5000]
            if summary.get('benchmark_report_format')=='basic-parameters-1':
                _basic_job_row(row,summary,Path(job['result_path']).parent)
        except (OSError, ValueError, KeyError):
            row["details"] = "결과 파일을 읽을 수 없습니다. 원본이 있으면 다시 분석하세요."
    return row


def _basic_job_row(row,summary,directory):
    """Use the same file-scoped evidence as the primary report in the GUI."""
    for i,item in enumerate(summary.get('benchmark_summary',[]),1):
        path=directory/'benchmark'/'diagnostics'/f'{i:02d}-source.json'
        if not path.is_file():continue
        evidence=json.loads(path.read_text(encoding='utf-8'))
        original=Path(evidence['source']).as_posix()
        if not original.endswith('/'+summary['source_relative_path'].replace('\\','/')):continue
        data=evidence['metadata']['data'];conditions=evidence['conditions']
        fields=evidence['metadata'].get('override',{}).get('fields',{})
        name=fields.get('device_name',data.get('device_name',{}))
        if isinstance(name,dict) and name.get('value'):row['device_name']=str(name['value'])
        measured=conditions.get('measurement_date',{})
        row['measurement_date']=str(measured.get('value') or '미확인') if isinstance(measured,dict) else '미확인'
        row['condition_label']=row['condition_label'].replace('__',' · ').replace('unknown','광 미확인')
        values=[]
        if item.get('RR_min') is not None:
            import csv
            with (directory/'benchmark'/'csv'/f'{i:02d}-RR.csv').open(encoding='utf-8-sig',newline='') as stream:
                voltages=list(dict.fromkeys(record['abs_Vd_V'] for record in csv.DictReader(stream)))
            values.append(f"RR {item['RR_min']:.3g}~{item['RR_max']:.3g} (|Vd|="+'/'.join(f'{float(v):g}' for v in voltages)+' V · 전체 기록 조건)')
        for metric in item.get('transfer_metrics',[]):
            if metric['current_range_ratio'] is not None:values.append(f"측정 범위 전류비 {metric['current_range_ratio']:.3g}")
            peak=next((p for p in metric['gm_peaks'] if p['width']==4),next(iter(metric['gm_peaks']),None))
            if peak:values.append(f"gm {peak['value_A_V']*1e9:.3g} nS (국소 {peak['width']:g} V 창 · Vg={peak['Vg_V']:g} V)")
        row['metric_summary']='사용 가능한 기초 수치: '+(' · '.join(values[:3]) if values else '단위 또는 계산 조건 확인 대기')+f"\n원시 {item['points']:,}점 · 전체 피팅 {item['fit_count']}개 · 선택 기본 보고서에서 그림과 원본 셀 확인"
        units=all(m.get('unit_status')=='confirmed' for record in evidence['records'] for k,m in record['column_mapping'].items() if k in ('vd','vg','id','ig'))
        row['review_required']=True
        row['next_check']='전압·전류 단위를 확인하세요.' if not units else '선택 파일의 실제 측정일을 확인하세요.' if row['measurement_date']=='미확인' else '연결된 파일의 물리적 배선을 확인하세요.' if len(summary['benchmark_summary'])>1 else '평가 전압의 원본점을 확인하세요.'
        from .benchmark_report import readable,num
        row['details']='조건 근거: device.md와 선택 파일 확인 이력 · 광 '+readable(conditions.get('illumination'))+'\n실제 시각 '+readable(conditions.get('measurement_time'))
        if conditions.get('sweep_delay_user_s') is not None or conditions.get('sweep_delay_settings_s') is not None:
            row['details']+='\nSweep delay: 사용자 '+num(conditions.get('sweep_delay_user_s'))+' s / 장비 '+num(conditions.get('sweep_delay_settings_s'))+' s · 차이가 있으면 불일치 유지'
        row['qc_details']='상세 점검·최적화 진단은 보고서의 분리 진단 자료에서 확인하세요.'
        return


def metadata_update_notice(result, source):
    """Describe actual update outcomes separately from an already-saved override."""
    files = result.get('files')
    outcomes = files if isinstance(files, list) else [{**result, 'source': source}]
    completed = [item for item in outcomes if item.get('status') == 'completed']
    unchanged = [item for item in outcomes if item.get('status') == 'unchanged']
    missing = [item for item in outcomes if item.get('status') not in ('completed', 'unchanged')]
    if not outcomes:
        missing = [{'source': source, 'status': 'unknown', 'reason': '처리 결과가 없습니다.'}]
    prefix = '확인 이력은 저장됐습니다. '
    if missing:
        labels = {'failed':'실패', 'rejected':'제외', 'deferred':'보류', 'blocked':'재시도 대기'}
        details = '; '.join(f"{item.get('source') or source}: {labels.get(item.get('status'), '갱신 미확인')} "
                            f"({item.get('reason') or item.get('error') or '사유 미기록'})" for item in missing)
        state = '부분 갱신' if completed or unchanged else '결과 갱신 실패/제외'
        return {'success': False, 'message': prefix + f'{state}: 새 결과 {len(completed)}개, 기존 결과 유지 {len(unchanged)}개. '
                + '갱신되지 않은 항목: ' + details + '. 원본 경로와 처리 제한을 확인한 뒤 선택 파일을 다시 분석하세요.'}
    if completed:
        return {'success': True, 'message': prefix + f'새 결과 {len(completed)}개를 갱신했습니다. 기존 결과 유지 {len(unchanged)}개.'}
    if unchanged:
        return {'success': True, 'message': prefix + '이미 처리된 동일 조건의 기존 결과를 유지합니다. 새 결과를 생성하지 않았습니다.'}
    return {'success': False, 'message': prefix + '결과 갱신을 확인할 수 없습니다. 선택 파일을 다시 분석하세요.'}


def load_jobs(cfg, limit=200):
    path = cfg.paths["state"] / "jobs.sqlite3"
    if not path.exists():
        return []
    # Opening the GUI must not initialize or mutate the pipeline database.
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)) as database:
        database.row_factory = sqlite3.Row
        jobs = [dict(row) for row in database.execute("SELECT * FROM jobs ORDER BY updated_at DESC LIMIT ?", (limit,))]
    return [job_row(job) for job in jobs]


def note_uri(path):
    path = Path(path).resolve()
    if not path.is_file() or path.suffix.lower() != ".md":
        raise ValueError("열 수 있는 연구노트가 없습니다.")
    return "obsidian://open?" + urlencode({"path": str(path)})


class JobController:
    def __init__(self, scan_function=None):
        self.events = queue.Queue()
        self.stop_event = threading.Event()
        self.thread = None
        self.scan_function = scan_function
        self.mode = None
        from .pipeline_logging import PipelineLogOwner
        self.log_owner = PipelineLogOwner()

    @property
    def busy(self):
        return self.thread is not None and self.thread.is_alive()

    def emit(self, event, **data):
        self.events.put({"event": event, **data})

    def start(self, mode, cfg=None, task=None):
        if self.busy:
            raise BusyError("현재 작업이 끝난 뒤 실행하세요.")
        if mode not in ("scan", "scan_retry", "watch", "weekly", "refresh", "task"):
            raise ValueError("지원하지 않는 GUI 작업입니다.")
        self.stop_event.clear()
        self.mode = mode
        self.thread = threading.Thread(target=self._work, args=(mode, cfg, task), daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def close_resources(self):
        if self.busy:
            raise BusyError('작업 완료 후 로그를 닫으세요.')
        self.log_owner.close()

    def _progress(self, cfg, outcome):
        self.emit("progress", outcome=outcome)
        if outcome["status"] in ("completed", "failed"):
            job = {"id": outcome["job_id"], "source": outcome["source"], "status": outcome["status"], "note_path": outcome.get("note"), "ai_status": outcome.get("ai"), "error": outcome.get("error"), "result_path": outcome.get("result_path") or (str(cfg.paths["analysis"] / "runs" / outcome["job_id"] / "result.json") if outcome["status"] == "completed" else None)}
            self.emit("row", row=job_row(job))

    def _work(self, mode, cfg, task):
        with self.log_owner.activate():
            self._execute(mode, cfg, task)

    def _execute(self, mode, cfg, task):
        try:
            if mode == "task":
                self.emit("task_result", result=task())
                return
            if mode == "refresh":
                self.emit("jobs", jobs=load_jobs(cfg))
                return
            api_key = get_api_key()
            if api_key:
                os.environ["OPENAI_API_KEY"] = api_key
            if mode == "weekly":
                from .reports import weekly
                self.emit("weekly", result=weekly(cfg))
                self.emit("jobs", jobs=load_jobs(cfg))
                return
            from .pipeline import scan
            scan_function = self.scan_function or scan
            waiting = False
            while not self.stop_event.is_set():
                try:
                    result = scan_function(cfg, retry_failed=mode == "scan_retry", on_progress=lambda outcome: self._progress(cfg, outcome), stop_event=self.stop_event)
                    self.emit("batch", result=result)
                    self.emit("jobs", jobs=load_jobs(cfg))
                    waiting = False
                except BusyError:
                    if not waiting:
                        self.emit("waiting", message="다른 분석 작업이 실행 중입니다. 종료 후 다시 시도합니다.")
                        waiting = True
                    if mode != "watch":
                        return
                if mode != "watch" or self.stop_event.wait(cfg.data["ingest"]["poll_seconds"]):
                    break
        except Exception as error:
            self.emit("error", message=safe_error(error))
        finally:
            self.emit("finished", mode=mode, stopped=self.stop_event.is_set())
