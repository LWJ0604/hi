"""Explicit supplementary review; writes only a fresh analysis directory."""
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import shutil
import tempfile

from . import __version__,code_fingerprint
from .observation_analysis import analyze_file
from .observation_report import export_report
from .util import digest


def observe(cfg,sources,*,on_progress=None,stop_event=None):
    if not sources:raise ValueError('검토할 Inbox 상대 파일 경로를 선택하세요. 전체 파일 처리는 --all을 명시하세요.')
    inbox=cfg.paths['inbox'];selected=[]
    for relative in dict.fromkeys(sources):
        path=(inbox/relative).resolve()
        if inbox not in path.parents or path.is_symlink():raise ValueError('Inbox 안의 일반 측정 파일을 선택하세요.')
        if path.suffix.casefold() not in ('.csv','.xls','.xlsx'):raise ValueError('CSV/XLS/XLSX 측정 파일만 지원합니다.')
        selected.append((str(relative),path))
    parent=cfg.paths['analysis']/'observations'/('v'+__version__);parent.mkdir(parents=True,exist_ok=True)
    target=Path(tempfile.mkdtemp(prefix=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S-'),dir=parent))
    results=[]
    for relative,path in selected:
        if stop_event is not None and stop_event.is_set():break
        if on_progress:on_progress({'source':relative,'status':'processing','total_files':len(selected)})
        try:
            if not path.is_file():raise FileNotFoundError('선택 파일이 없습니다: '+relative)
            if path.stat().st_size>cfg.data['ingest']['max_bytes']:raise ValueError('설정된 파일 크기 한도를 초과했습니다: '+relative)
            fingerprint=digest(path);copy_dir=target/'inputs';copy_dir.mkdir(exist_ok=True)
            snapshot=copy_dir/(fingerprint[:16]+path.suffix.lower())
            if not snapshot.exists():shutil.copyfile(path,snapshot)
            if digest(snapshot)!=fingerprint or digest(path)!=fingerprint:raise ValueError('처리 중 원본이 변경되었습니다. 저장 완료 후 다시 검토하세요.')
            report=target/(f'{len(results)+1:03d}-'+fingerprint[:12])
            from .metadata_review import load_override
            override=load_override(cfg,relative,fingerprint)
            analysis,points=analyze_file(snapshot,cfg,{'fields':override.get('fields',{}),'relative_path':relative})
            analysis['code_sha256']=code_fingerprint()
            exported=export_report(analysis,points,report,path.name,{'relative_path':relative,'sha256':fingerprint})
            results.append({'source':relative,'status':'completed',**exported})
        except Exception as error:results.append({'source':relative,'status':'failed','error':type(error).__name__+': '+str(error)})
        if on_progress:on_progress(results[-1])
    listing=[]
    for r in results:
        if r['status']=='completed':listing.append('<li><a href="'+Path(r['html']).relative_to(target).as_posix()+'">'+html.escape(r['source'])+'</a> · '+str(r['branches'])+' branch · '+str(r['metrics'])+' 지표 기록</li>')
        else:listing.append('<li>'+html.escape(r['source']+' · '+r['error'])+'</li>')
    index=target/'index.html'
    index.write_text('<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>측정 관측 검토</title><style>body{font:16px/1.7 "Malgun Gothic",sans-serif;max-width:1000px;margin:32px auto;padding:20px}li{margin:12px}</style><h1>측정 관측 검토</h1><p>기존 노트·DB를 보존하고 새 분석 폴더에 생성했습니다. 사용자 단위·실제 날짜 확인을 위조하지 않았습니다. 같은 stress 조건끼리 비교하세요.</p><ul>'+''.join(listing)+'</ul></html>',encoding='utf-8')
    (target/'coverage.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    return {'output':str(target),'index':str(index),'files':results,'stopped':bool(stop_event and stop_event.is_set())}
