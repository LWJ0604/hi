"""Explicit file selection and native-pipeline cache for the basic report."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import tempfile

from . import __version__,code_fingerprint
from .benchmark_report import export,write_diagnostic
from .device_metadata import context_for,declared_pair,fingerprint
from .util import digest


def select(cfg,sources,auto_pair=True):
    if not sources:raise ValueError('보고서를 만들 입력 파일을 선택하세요. Inbox 상대 경로를 지정합니다.')
    inbox=cfg.paths['inbox'].resolve();selected=[]
    for relative in dict.fromkeys(sources):
        candidate=inbox/relative;path=candidate.resolve()
        if inbox not in path.parents or candidate.is_symlink():raise ValueError('Inbox 안의 일반 측정 파일을 선택하세요.')
        if not path.is_file():raise FileNotFoundError('선택한 입력 파일이 없습니다: '+str(relative))
        if path.suffix.casefold() not in ('.csv','.xls','.xlsx'):raise ValueError('CSV/XLS/XLSX 측정 파일을 선택하세요.')
        selected.append(path)
    reason='사용자가 명시적으로 선택한 파일'
    if len(selected)==1 and auto_pair:
        pair=declared_pair(selected[0],context_for(selected[0],cfg))
        # Explicit metadata links still have to be inside the selected Inbox.
        if len(pair)==2 and all(inbox in path.parents for path in pair):
            selected=pair;reason='device.md에 명시된 IdVd/IdVg 파일'
    return selected,reason


def dependencies(cfg,source):
    paths,_=select(cfg,[Path(source).relative_to(cfg.paths['inbox']).as_posix()])
    from .metadata_review import fingerprint as override_fingerprint
    return [{'source':p.relative_to(cfg.paths['inbox']).as_posix(),'sha256':digest(p),
        'device_sha256':fingerprint(context_for(p,cfg)),
        'override_sha256':override_fingerprint(cfg,p.relative_to(cfg.paths['inbox']).as_posix(),digest(p))} for p in paths]


def generate(cfg,sources,*,auto_pair=True,cached=False,on_progress=None,stop_event=None):
    paths,reason=select(cfg,sources,auto_pair)
    key=hashlib.sha256(json.dumps({'dependencies':dependencies(cfg,paths[0]) if auto_pair else [
        {'source':str(p),'sha256':digest(p),'device_sha256':fingerprint(context_for(p,cfg))} for p in paths],
        'selection':[str(p) for p in paths],'config':cfg.fingerprint,'code':code_fingerprint()},sort_keys=True).encode()).hexdigest()
    parent=cfg.paths['analysis']/'benchmarks'/('v'+__version__);parent.mkdir(parents=True,exist_ok=True)
    receipt=parent/(key+'.json')
    if cached and receipt.is_file():
        try:
            result=json.loads(receipt.read_text(encoding='utf-8'));folder=Path(result['output'])
            if folder.parent==parent and all(digest(folder/name)==sha for name,sha in result['artifact_sha256'].items()):return result
        except (OSError,KeyError,ValueError):pass
    target=Path(tempfile.mkdtemp(prefix=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S-'),dir=parent))
    try:
        result=export(paths,cfg,target,pair_reason=reason,on_progress=on_progress,stop_event=stop_event)
        result.update(output=str(target),index=result['html'],stopped=bool(stop_event and stop_event.is_set()))
        result['artifact_sha256']={p.relative_to(target).as_posix():digest(p) for p in target.rglob('*') if p.is_file()}
        if cached and not result['stopped']:write_diagnostic(receipt,result)
        return result
    except Exception as error:
        write_diagnostic(target/'diagnostics'/'failure.json',{'error':type(error).__name__+': '+str(error),'sources':[str(p) for p in paths]})
        raise
