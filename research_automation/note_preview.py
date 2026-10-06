"""Selected notes from cached evidence. No scan, parse, enrichment, refit, or AI."""
import copy
import json
from pathlib import Path
import shutil
from . import __version__,code_fingerprint
from .result_review import read_jobs,latest_jobs,local_result
from .util import now,write_json,digest


def preview_notes(cfg, sources=None):
    import pandas as pd
    from .note_figures import evidence_figures,parameter_figures
    from .science_exports import note
    from .note_index import publish_index
    from .store import lock
    with lock(cfg):
        jobs=read_jobs(cfg);available=latest_jobs(jobs);chosen=[];seen=set()
        if sources is not None:
            absent=set(sources)-{j['source'] for j in available}
            if absent:raise ValueError('완료 저장 결과가 없는 선택 파일: '+', '.join(sorted(absent)))
        for job in available:
            if sources is not None and job['source'] not in sources:continue
            result=local_result(cfg,job)
            if not result:continue
            summary=json.loads(result.read_text(encoding='utf-8-sig'))
            axis=next(iter(summary.get('groups',[])),{}).get('axis')
            if sources is None and axis in seen:continue
            seen.add(axis);chosen.append((job,result,summary))
        if not chosen:raise ValueError('미리보기할 저장 결과가 없습니다.')
        stamp=now(cfg).strftime('%Y%m%d-%H%M%S-%f');records=[];outputs=[]
        for job,result,original in chosen:
            summary=copy.deepcopy(original)
            stage=cfg.paths['analysis']/'note-previews'/('v'+__version__)/stamp/job['id']
            stage.mkdir(parents=True,exist_ok=False)
            for path in result.parent.iterdir():
                if path.is_file():shutil.copy2(path,stage/path.name)
            curves=pd.read_csv(stage/'curves.csv',float_precision='round_trip')
            preserved={}
            for p in result.parent.iterdir():
                if p.is_file() and p.name.startswith('figure2_') and p.suffix=='.png':
                    shutil.copy2(p,stage/('prior_'+p.name))
                    preserved[p.name]='prior_'+p.name
                if p.is_file() and p.suffix in ('.csv','.json'):
                    name='prior_'+p.name if p.name.startswith('fet_') or p.name in ('research_report.json','research_metrics.csv','figure2_manifest.json','metric_evidence.json') else p.name
                    if name!=p.name:shutil.copy2(p,stage/name)
                    preserved[p.name]=name
            from .metric_store import compact_legacy_copies
            historical_storage=compact_legacy_copies(stage,preserved)
            from .fet_parameters import export_fet
            from .fet_figures import fet_figures
            report=export_fet(curves,summary,stage,cfg)
            figures=evidence_figures(curves,summary,stage)+parameter_figures(curves,summary,stage)+fet_figures(report,summary,stage)
            from .research_report import export_report
            from .research_panels import research_panels
            evidence=export_report(curves,summary,stage,cfg,report)
            new_figures,_=research_panels(curves,summary,stage,report,evidence)
            figures.extend(new_figures)
            # The copied result.json stays byte-identical, including prior figure list/version/paths.
            summary['figures']=figures+original.get('figures',[])
            assets=f'Attachments/v{__version__}/NotePreviews/{stamp}/{job["id"]}'
            rel=f'Experiments/v{__version__}/노트 미리보기/{stamp}/{job["id"]}.md'
            summary['vault_note_relative_path']=rel;summary['vault_assets_relative_path']=assets
            manifest={'presentation_version':__version__,'presentation_code_sha256':code_fingerprint(),
                      'numeric_analysis_version':original.get('version'),'source':job['source'],
                      'cached_result_sha256':digest(result),'cached_files_sha256':{p.name:digest(p) for p in result.parent.iterdir() if p.is_file() and p.suffix in ('.json','.csv')},
                      'preserved_cached_files':preserved,'legacy_copy_storage_normalization':historical_storage,
                      'new_extraction_files':['fet_parameters.json','fet_parameters.csv','fet_summary.csv','research_report.json','research_metrics.csv','metric_evidence.json','figure2_manifest.json'],
                      'original_note':original.get('vault_note_relative_path'),'note':rel,'figures':figures,
                      'representative_rule':'first acquisition block/direction, nearest fixed voltage to zero, source order tie-break',
                      'parser_rerun':False,'models_refit':False,'qc_changed':False,'metadata_changed':False,'api_calls':0}
            write_json(stage/'note_presentation.json',manifest)
            path=note(summary,stage,cfg)
            records.append((original,rel));outputs.append({'source':job['source'],'note':str(path),'assets':str(cfg.paths['vault']/assets),'manifest':str(stage/'note_presentation.json')})
        index=publish_index(cfg,records,jobs,preview=True)
        return {'files':outputs,'index':str(index),'refit':False,'qc_changed':False,'api_calls':0,
                'selection':'specified sources' if sources is not None else 'one saved representative per measurement type; not all historical notes'}


def preview_saved_photo(cfg, comparison_path):
    """Re-present already paired ΔId evidence without recomputing comparison metrics."""
    from .special_notes import photo_note
    from .note_presentation import conditions
    from .note_index import append_related
    original=Path(comparison_path).resolve()
    if not original.is_relative_to(cfg.paths['analysis'].resolve()):raise ValueError('Analysis 내부의 저장 비교 JSON을 선택하세요.')
    data=json.loads(original.read_text(encoding='utf-8-sig'));pairs=copy.deepcopy(data.get('pairs',[]))
    jobs={j['id']:j for j in read_jobs(cfg)}
    for pair in pairs:
        descriptions=[]
        for lighting in ('dark','light'):
            job=jobs.get(pair.get(lighting+'_job_id'))
            result=local_result(cfg,job) if job else None
            if result:
                summary=json.loads(result.read_text(encoding='utf-8-sig'))
                g=next((g for g in summary.get('groups',[]) if g['group_id']==pair.get(lighting+'_group_id')),None)
                if g:descriptions.append(lighting+': '+conditions(summary,g))
        if descriptions:pair['presentation_conditions']=' / '.join(descriptions)
    stamp=now(cfg).strftime('%Y%m%d-%H%M%S-%f')
    stage=cfg.paths['analysis']/'note-previews'/('v'+__version__)/'photo'/stamp
    stage.mkdir(parents=True,exist_ok=False)
    preserved={}
    for name in ('comparison.json','photoresponse.csv'):
        path=original.parent/name
        if path.is_file():shutil.copy2(path,stage/name);preserved[name]=digest(path)
    assets=f'Attachments/v{__version__}/PhotoPreviews/{stamp}'
    text=photo_note(pairs,assets,stage,data.get('excluded_by_reason',{}),data.get('cross_date_selection_pending',0))
    write_json(stage/'note_presentation.json',{'presentation_version':__version__,'copied_evidence_sha256':preserved,
        'paired_data_recomputed':False,'original_comparison':str(original),'legacy_metrics_changed':False,'api_calls':0})
    target=cfg.paths['vault']/assets;shutil.copytree(stage,target)
    path=cfg.paths['vault']/f'Experiments/v{__version__}/노트 미리보기/광 비교_{stamp}.md'
    from .util import atomic_text
    atomic_text(path,text);append_related(cfg,path,'저장된 dark/light 비교 노트 미리보기')
    return {'note':str(path),'assets':str(target),'paired_data_recomputed':False}
