"""Programmatic Tk layout/state QA, using only synthetic isolated data.

Run from the project folder with its Python. No screenshot or pixel QA is claimed.
"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import time
import tkinter as tk

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from research_automation.config import DEFAULT, Config
from research_automation.gui import ResearchApp
from research_automation.pipeline import scan
from research_automation.reports import backup
import numpy as np
import pandas as pd

root=Path('qa-layout').resolve(); root.mkdir(exist_ok=True)
config=root/'config.json'
config.write_text(json.dumps(copy.deepcopy(DEFAULT)),encoding='utf-8')
cfg=Config(config); cfg.ensure_dirs()
source=cfg.paths['inbox']/'한글 공백 소자'/'2026-09-23'/'Id-Vd_dark.csv'
source.parent.mkdir(parents=True,exist_ok=True)
x=np.linspace(-2,2,41)
pd.DataFrame({'DrainV (V)':x,'DrainI (A)':3e-9*np.sinh(x),'GateI (A)':1e-12,'GateV (V)':0}).to_csv(source,index=False)
source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
result=scan(cfg); saved=result['files'][0]
before={key:hashlib.sha256(Path(saved[key]).read_bytes()).hexdigest() for key in ('note','result_path')}
window=tk.Tk(); app=ResearchApp(window,config)
errors=[]; window.report_callback_exception=lambda kind,error,trace:errors.append(str(error))
def idle():
    limit=time.monotonic()+30
    while time.monotonic()<limit:
        window.update(); time.sleep(.01)
        if not app.controller.busy and not app.task_callback and app.controller.events.empty(): return
    raise RuntimeError('GUI timeout')
idle(); selected=app.tree.get_children()[0]; app.tree.selection_set(selected); app._select()
window.update_idletasks()
def widgets(widget):
    output=[]
    for child in widget.winfo_children():
        record={'class':child.winfo_class(),'x':child.winfo_rootx(),'y':child.winfo_rooty(),'width':child.winfo_width(),'height':child.winfo_height()}
        try: record['text']=child.cget('text')
        except tk.TclError: pass
        output.append(record); output.extend(widgets(child))
    return output
report={'platform':sys.platform,'python':sys.version,'pixel_screen_verified':False,'main_widgets':widgets(window),'selected_details':app.details.get('1.0','end')}
app._show_evidence(); window.update(); report['evidence_widgets']=widgets(window)
assert not errors,errors
assert any(record.get('text')=='RR / gm 계산 근거' for record in report['main_widgets'])
assert len([w for w in window.winfo_children() if isinstance(w,tk.Toplevel)])==1
for dialog in [w for w in window.winfo_children() if isinstance(w,tk.Toplevel)]: dialog.destroy()
app._destroy()
report['backup']=backup(cfg)
assert hashlib.sha256(source.read_bytes()).hexdigest()==source_hash
assert all(hashlib.sha256(Path(saved[key]).read_bytes()).hexdigest()==digest for key,digest in before.items())
report['synthetic_source_and_cached_note_preserved']=True
(root/'gui-evidence.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('GUI widget/layout QA and backup passed; evidence:',root/'gui-evidence.json')
