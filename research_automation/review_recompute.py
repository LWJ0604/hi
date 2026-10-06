"""Re-publish only a selected reviewed source; reuse unchanged scientific values."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

import pandas as pd

from . import __version__,code_fingerprint
from .metadata_review import build_context,fingerprint
from .organization import csv_context
from .render import experiment_note,plots,vault_locations,measurement_catalog
from .science_exports import enrich_context,export_metrics
from .store import Store,lock
from .util import digest,now,write_json


def metadata_recompute(cfg,result_path,changed_fields):
    prior=json.loads(Path(result_path).read_text(encoding='utf-8'))
    source=cfg.paths['inbox']/prior['source_relative_path']
    if not source.is_file():raise ValueError('현재 PC의 Inbox에 선택 원본을 찾지 못했습니다. 경로를 확인하세요. 다른 PC의 절대 스냅샷 경로는 사용하지 않습니다.')
    if digest(source)!=prior['source_sha256']:raise ValueError('원본 내용이 바뀌었습니다. 선택 원본을 새로 분석하세요.')
    snapshot_path=Path(result_path).parent/'config_snapshot.json'
    saved=json.loads(snapshot_path.read_text(encoding='utf-8-sig')) if snapshot_path.exists() else {}
    same_science=all(saved.get(k)==cfg.data[k] for k in ('analysis','columns','ingest','qc','science'))
    if prior.get('schema_version',0)<4 or prior.get('code_sha256')!=code_fingerprint() or not same_science:
        from .pipeline import scan
        return scan(cfg,sources=[prior['source_relative_path']])
    relative=prior['source_relative_path']; source_hash=prior['source_sha256']
    identity=f'{relative}\n{source_hash}\n{cfg.fingerprint}\n{__version__}\n{code_fingerprint()}\n{fingerprint(cfg,relative,source_hash)}'
    job=hashlib.sha256(identity.encode()).hexdigest()
    with lock(cfg):
        store=Store(cfg)
        stage=Path(tempfile.mkdtemp(prefix='.review-',dir=cfg.paths['analysis']))
        try:
            previous=store.get(job)
            if previous and previous['status']=='completed' and Path(previous['result_path']).is_file():return {'status':'unchanged','job_id':job}
            store.begin(job,relative,source_hash,cfg.fingerprint,now(cfg).isoformat())
            summary=copy.deepcopy(prior); summary['job_id']=job;summary['created_at']=now(cfg).isoformat()
            summary['research_context']=build_context(relative,summary['metadata'],summary['instrument_settings'],summary,cfg,source_hash)
            summary['illumination']={'value':summary['research_context']['illumination'],'source':summary['research_context']['illumination_source']}
            summary['recalculation']={'changed_fields':changed_fields,'reused_from_job_id':prior['job_id'],
                'reused_numeric_analysis':True,'recomputed':['metadata','metric_confirmation_status','comparison_eligibility','rule_summary','note_locations'],
                'parser_rerun':False,'models_refit':False}
            enrich_context(summary,cfg)
            for path in Path(result_path).parent.iterdir():
                if path.is_file():shutil.copy2(path,stage/path.name)
            for filename in ('normalized.csv','curves.csv','metrics.csv','fit_results.csv'):
                frame=pd.read_csv(stage/filename,float_precision='round_trip')
                for key,value in csv_context(summary['research_context']).items():frame[key]=value
                if filename=='metrics.csv':
                    ratios={g['group_id']:g['rectification'].get('ratio_abs_i_positive_over_negative') for g in summary['groups']}
                    frame['rr_abs_positive_over_negative']=frame['group_id'].map(ratios)
                frame.to_csv(stage/filename,index=False,encoding='utf-8-sig')
            summary['source_locations']['processed_at']=summary['created_at']
            summary['vault_note_relative_path'],summary['vault_assets_relative_path']=vault_locations(summary)
            counter=0
            while (cfg.paths['vault']/summary['vault_note_relative_path']).exists() or (cfg.paths['vault']/summary['vault_assets_relative_path']).exists():
                counter+=1;note,assets=vault_locations(summary)
                summary['vault_note_relative_path']=note[:-3]+f'_preserved-r{counter}.md';summary['vault_assets_relative_path']=assets+f'_preserved-r{counter}'
            if set(changed_fields)&{'device_name','illumination','units_confirmed'}:
                curves=pd.read_csv(stage/'curves.csv',float_precision='round_trip')
                summary['figures']=plots(curves,summary,stage)
            export_metrics(summary,stage)
            # Rebuild dependency-labelled supplemental evidence after any review.
            # This does not refit legacy models or confirm independent conditions.
            curves=pd.read_csv(stage/'curves.csv',float_precision='round_trip')
            from .fet_parameters import export_fet
            from .research_report import export_report
            from .research_panels import research_panels
            additional=export_fet(curves,summary,stage,cfg)
            report=export_report(curves,summary,stage,cfg,additional)
            new_figures,_=research_panels(curves,summary,stage,additional,report)
            summary['figures']=list(dict.fromkeys([*summary.get('figures',[]),*new_figures]))
            summary['report_format']='fet-template-report-1'
            write_json(stage/'result.json',summary);write_json(stage/'config_snapshot.json',cfg.data)
            final=cfg.paths['analysis']/'runs'/('v'+__version__)/job
            suffix=0
            while final.exists():suffix+=1;final=final.with_name(job+f'_preserved-r{suffix}')
            if digest(source)!=source_hash:raise ValueError('검토 갱신 중 원본이 변경되었습니다. 새로 분석하세요.')
            final.parent.mkdir(parents=True,exist_ok=True);os.replace(stage,final)
            note=experiment_note(summary,final,cfg)
            store.finish(job,now(cfg).isoformat(),final/'result.json',note,'disabled')
            measurement_catalog(cfg,store.completed())
            from .comparison_catalog import publish
            publish(cfg,store.completed())
            return {'status':'completed','job_id':job,'note':str(note),'result_path':str(final/'result.json'),'recalculation':summary['recalculation']}
        except Exception as error:
            store.fail(job,now(cfg).isoformat(),f"{type(error).__name__}: {error}")
            raise
        finally:
            if stage.exists():shutil.rmtree(stage)
            store.close()
