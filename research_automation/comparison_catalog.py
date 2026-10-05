"""Local dark/light proposals with versioned evidence and portable vault links."""
import json
from pathlib import Path
import shutil
import pandas as pd
from . import __version__
from .comparison import photo_difference,compare_reasons
from .util import now,write_json,atomic_text


def publish(cfg,jobs,selected_sources=None):
    from collections import Counter
    exclusions=Counter();date_pending=0
    latest={}
    for job in sorted(jobs,key=lambda j:j['completed_at']):
        try:
            summary=json.loads(Path(job['result_path']).read_text(encoding='utf-8'))
            if summary.get('schema_version',0)<4:continue
            latest[summary['source_relative_path']]=(summary,Path(job['result_path']).parent)
        except (OSError,ValueError):continue
    entries=[e for e in latest.values() if selected_sources is None or e[0]["source_relative_path"] in selected_sources];pairs=[]
    from .note_presentation import conditions
    from .special_notes import photo_note
    for dark,ddir in entries:
        if dark['research_context']['illumination']!='dark':continue
        for light,ldir in entries:
            if light['research_context']['illumination']!='light':continue
            for gd in dark['groups']:
                for gl in light['groups']:
                    blocked=next((label for bad,label in (
                        (gd['axis']!=gl['axis'],'측정 축 불일치'),
                        (gd['conditions']!=gl['conditions'],'고정 Vg/Vds 불일치'),
                        (gd['direction']!=gl['direction'],'원래 sweep 방향 불일치'),
                        (gd['gate_block_id']!=gl['gate_block_id'],'원래 반복 블록 불일치')) if bad),None)
                    if blocked:exclusions[blocked]+=1;continue
                    reasons=compare_reasons(dark,gd,light,gl,photo=True)
                    dc,lc=dark['research_context'],light['research_context']
                    if dc.get('device_name') and lc.get('device_name') and dc['device_name']!=lc['device_name']:
                        exclusions['소자 이름 불일치 (추정 이름 포함 · 사용자가 재확인 가능)']+=1;continue
                    if any('원래 sweep' in r or '원래 gate step 범위' in r or '장비 원래 설정' in r for r in reasons):
                        exclusions['원래 sweep·gate step·장비 설정 불일치 (crop으로 해결 안 됨)']+=1;continue
                    if dc.get('measurement_date') and lc.get('measurement_date') and dc['measurement_date']!=lc['measurement_date'] and selected_sources is None:
                        date_pending+=1;continue
                    result={'metric_status':'unavailable','reasons':reasons,'points':[]}
                    if not reasons:
                        da=pd.read_csv(ddir/'curves.csv',float_precision='round_trip');la=pd.read_csv(ldir/'curves.csv',float_precision='round_trip')
                        da=da[da['group_id']==gd['group_id']].rename(columns={'x_v':gd['axis'],'id_a':'id'})
                        la=la[la['group_id']==gl['group_id']].rename(columns={'x_v':gl['axis'],'id_a':'id'})
                        result=photo_difference(dark,gd,da,light,gl,la)
                    pairs.append({'dark_job_id':dark['job_id'],'light_job_id':light['job_id'],'dark_group_id':gd['group_id'],'light_group_id':gl['group_id'],
                        'dark_note':dark['vault_note_relative_path'],'light_note':light['vault_note_relative_path'],
                        'presentation_conditions':'dark: '+conditions(dark,gd)+' / light: '+conditions(light,gl),
                        'measurement_date_dark':dc.get('measurement_date'),'measurement_date_light':lc.get('measurement_date'),
                        'cross_date_explicitly_selected':bool(selected_sources and dc.get('measurement_date')!=lc.get('measurement_date')),
                        'history_dark':dc.get('fields',{}).get('history',{}),'history_light':lc.get('fields',{}).get('history',{}),
                        'fixed_conditions_v':gd['conditions'],'original_sweep_dark':gd['original_sweep'],'original_sweep_light':gl['original_sweep'],**result})
    stamp=now(cfg).strftime('%Y%m%d-%H%M%S-%f');directory=cfg.paths['analysis']/'comparisons'/('v'+__version__)/stamp
    directory.mkdir(parents=True,exist_ok=False)
    write_json(directory/'comparison.json',{'version':__version__,'pairs':pairs,'automatic_averaging':False,'mechanism_inference':None,'excluded_by_reason':dict(exclusions),'cross_date_selection_pending':date_pending})
    rows=[]
    for pair in pairs:
        for point in pair['points']:rows.append({k:v for k,v in pair.items() if k not in ('points','reasons')}|point)
    pd.DataFrame(rows,columns=None if rows else ['signed_delta_id_a','delta_abs_id_a','current_unit','responsivity_a_per_w','evaluation_voltage_v']).to_csv(directory/'photoresponse.csv',index=False,encoding='utf-8-sig')
    assets=f'Attachments/v{__version__}/Comparisons/{stamp}';asset_dir=cfg.paths['vault']/assets;asset_dir.mkdir(parents=True,exist_ok=False)
    for path in directory.iterdir():shutil.copy2(path,asset_dir/path.name)
    note=cfg.paths['vault']/f'Experiments/v{__version__}/비교 검토_{stamp}.md'
    text=photo_note(pairs,assets,directory,dict(exclusions),date_pending)
    for path in directory.iterdir():
        if path.is_file() and not (asset_dir/path.name).exists():shutil.copy2(path,asset_dir/path.name)
    atomic_text(note,text)
    from .note_index import append_related
    append_related(cfg,note,'dark/light 비교 검토 · 후보와 제외 요약')
    return {'note':str(note),'pairs':len(pairs),'eligible':sum(p['metric_status']=='candidate' for p in pairs),'excluded_by_reason':dict(exclusions),'date_selection_pending':date_pending}
