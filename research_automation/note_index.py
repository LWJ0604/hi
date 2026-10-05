"""Immutable indexes and append-only root navigation."""
from collections import defaultdict
from pathlib import Path
import json
from . import __version__
from .note_presentation import cell, conditions, usability, next_action, representative
from .util import atomic_text, now, digest


def root_navigation(cfg, index):
    root=cfg.paths['vault']/'Experiments';root.mkdir(parents=True,exist_ok=True)
    shortcut=root/'최신 연구 결과.md'
    # Append even when a researcher has edited this file. Nothing is replaced.
    old=shortcut.read_bytes().decode('utf-8') if shortcut.exists() else '# 최신 연구 결과\n\n아래 기록 중 가장 최근 추가된 링크를 여세요. 이전 결과는 보존됩니다.\n'
    relative=index.relative_to(cfg.paths['vault']).as_posix()
    if relative not in old:
        block=f'\n## {now(cfg).isoformat()} · 최신 연결\n\n[[{relative}|v{__version__} 최신 결과 인덱스]]\n\n이전 결과: '
        prior=sorted(p for p in root.glob('v*') if p.is_dir() and p.name!='v'+__version__)
        block+=' · '.join(f'[[{p.relative_to(cfg.paths["vault"]).as_posix()}/자동 측정 목록|{p.name} 이전 결과]]' for p in prior if (p/'자동 측정 목록.md').is_file()) or '이전 버전 폴더를 그대로 보존했습니다.'
        atomic_text(shortcut,old+block+'\n')
    # Existing root indexes are augmented, including arbitrary researcher text.
    for name in ('index.md','Index.md','자동 측정 목록.md'):
        path=root/name
        if path.is_file():
            old=path.read_bytes().decode('utf-8')
            if relative not in old:atomic_text(path,old+f'\n\n[[{relative}|v{__version__} 최신 결과 인덱스]]\n')
    return shortcut


def publish_index(cfg, records, jobs=(), preview=False):
    """records: (unchanged summary, vault-relative new note path)."""
    accumulated={}
    preview_root=cfg.paths['vault']/'Attachments'/('v'+__version__)/'NotePreviews'
    for manifest_path in sorted(preview_root.glob('*/*/note_presentation.json')):
        try:
            manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
            summary=json.loads((manifest_path.parent/'result.json').read_text(encoding='utf-8'))
            note_path=(cfg.paths['vault']/manifest['note']).resolve()
            if note_path.is_relative_to(cfg.paths['vault'].resolve()) and note_path.is_file():
                accumulated[summary['source_relative_path']]=(summary,manifest['note'])
        except (OSError,ValueError,KeyError):continue
    for summary,note in records:accumulated[summary['source_relative_path']]=(summary,note)
    records=list(accumulated.values())
    versions=defaultdict(set)
    for job in jobs:
        try:
            s=json.loads(Path(job['result_path']).read_text(encoding='utf-8-sig'))
            versions[s.get('version','미확인')].add(s['source_relative_path'])
        except (OSError,ValueError,KeyError,TypeError):continue
    all_sources=set().union(*versions.values()) if versions else set()
    rendered={s.get('source_relative_path') for s,_ in records}
    from .pipeline import candidates
    input_paths=list(candidates(cfg));completed_hashes={(j.get('source'),j.get('source_hash')) for j in jobs if j.get('status')=='completed'}
    missing=[];current_sources={p.relative_to(cfg.paths['inbox']).as_posix() for p in input_paths}
    for path in input_paths:
        source=path.relative_to(cfg.paths['inbox']).as_posix()
        try:
            if (source,digest(path)) not in completed_hashes:missing.append(source)
        except OSError:missing.append(source)
    saved_missing=all_sources-rendered
    lines=['# 자동 측정 목록 · '+('노트 미리보기' if preview else '최신 출력'),'',
           f'새 형식 {len(rendered)}개 파일 · 이 인덱스는 기존 분석 결과의 확인 상태를 보존합니다.',
           f'현재 입력 {len(input_paths)}개 중 현재 파일 내용에 대응하는 완료 기록 {len(input_paths)-len(missing)}개 · 미처리/변경/읽기 확인 필요 {len(missing)}개.',
           f'과거 버전 포함 저장 완료 파일 {len(all_sources)}개 · 이 인덱스에 포함하지 않은 저장 결과 {len(saved_missing)}개.',
           '이 숫자는 파일 처리 범위이며 단위·조건 확인 또는 연구자 검토 완료를 뜻하지 않습니다. 과거 결과 수보다 최신 수가 적으면 전체 재처리 완료로 표시하지 않습니다.','',
           '| 소자 | 측정 날짜 | 종류 | 주요 조건 | 사용 가능 상태 | 다음 확인 | 노트 |','|---|---|---|---|---|---|---|']
    for s,note in sorted(records,key=lambda r:(r[0].get('research_context',{}).get('measurement_date') or '',r[0].get('source_relative_path','')),reverse=True):
        c=s.get('research_context',{});g=representative(s)
        from .note_presentation import field
        values=[field(s,'device_name'),field(s,'measurement_date'),'Id–Vd' if (g or {}).get('axis')=='vd' else 'Id–Vg' if g else '파일 읽기 실패',
                conditions(s),' · '.join(usability(s)),next_action(s)]
        lines.append('| '+' | '.join(cell(v) for v in values)+f' | [[{note}|열기]] |')
    from .result_review import read_jobs
    latest_jobs={j['source']:j for j in read_jobs(cfg)}
    for source,job in latest_jobs.items():
        if source not in current_sources or job.get('status')!='failed':continue
        failures=sorted((cfg.paths['vault']/'Experiments'/('v'+__version__)/'읽기 실패').glob(job['id']+'_*.md'))
        if failures:
            link=failures[-1].relative_to(cfg.paths['vault']).as_posix()
            lines.append('| 미확인 | 미확인 | 파일 읽기 실패 | 조건 미확인 | 파일 읽기 실패 | 원본 측정 열·첫 측정행 확인 | [['+link+'|'+cell(source)+']] |')
    lines+=['','> [!info]- 이전 결과와 처리 범위', '>']
    for version,sources in sorted(versions.items()):lines.append(f'> - v{version}: 저장 완료 {len(sources)}개 파일 · 이전 결과 유지')
    for source in missing:lines.append('> - 현재 내용의 완료 결과 없음: '+cell(source))
    for source in sorted(saved_missing):lines.append('> - 이 인덱스에 포함하지 않은 저장 결과: '+cell(source))
    root=cfg.paths['vault']/'Experiments'/('v'+__version__)
    path=root/('자동 측정 목록_'+now(cfg).strftime('%Y%m%d-%H%M%S-%f')+'.md')
    atomic_text(path,'\n'.join(lines)+'\n');root_navigation(cfg,path)
    return path


def append_related(cfg,note,label):
    from .science_exports import catalog_path
    path=catalog_path(cfg)
    if path.is_file():
        text=path.read_bytes().decode('utf-8');relative=Path(note).relative_to(cfg.paths['vault']).as_posix()
        if relative not in text:atomic_text(path,text+f'\n\n[[{relative}|{label}]]\n')
