"""Versioned research exports alongside the existing pipeline and file layout."""
import json
from pathlib import Path
import shutil

from . import __version__
from .util import atomic_text


def catalog_path(cfg):
    root=cfg.paths['vault']/'Experiments'/('v'+__version__)
    candidates=list(root.glob('자동 측정 목록*.md'))
    return max(candidates,key=lambda p:p.stat().st_mtime_ns) if candidates else root/'자동 측정 목록.md'


def enrich_context(summary,cfg):
    context=summary['research_context']; fields=context['fields']
    units_confirmed=fields['units_confirmed']['value'] is True and fields['units_confirmed']['status']=='confirmed'
    for group in summary['groups']:
        group['metadata_status']=context['metadata_status']
        unit_hold=group['unit_status']!='confirmed' and not units_confirmed
        group['units_review_required']=unit_hold
        metrics=[*group.get('rr_series',[])]
        for entry in group.get('output_observables',[]):
            metrics.extend(entry[k] for k in ('signed_id','signed_ig','i_over_v','differential_conductance'))
        if group.get('effective_differential_resistance'):metrics.append(group['effective_differential_resistance'])
        transfer=group['transfer_metrics']
        metrics.extend(transfer[k] for k in ('raw_peak_abs','internal_peak_abs','vth','ss','mobility','current_range_ratio') if k in transfer)
        for metric in metrics:
            if not unit_hold and 'candidate_value_assuming_si' in metric:
                metric['value']=metric.pop('candidate_value_assuming_si')
                metric['metric_status']=metric.pop('pre_unit_hold_status','candidate')
                metric['reason']=metric.pop('pre_unit_hold_reason','units_confirmed_by_user')
            if not unit_hold and 'candidate_bound_assuming_si' in metric:
                metric['bound_value']=metric.pop('candidate_bound_assuming_si');metric['metric_status']='bound'
            if unit_hold and metric.get('bound_value') is not None:
                metric['candidate_bound_assuming_si']=metric['bound_value'];metric['bound_value']=None;metric['metric_status']='unavailable';metric['reason']='unconfirmed_units_for_bound'
            if unit_hold and metric.get('value') is not None:
                metric['pre_unit_hold_status']=metric['metric_status']; metric['pre_unit_hold_reason']=metric.get('reason')
                metric['candidate_value_assuming_si']=metric['value']; metric['value']=None
                metric['metric_status']='unavailable'; metric['reason']='unconfirmed_voltage_or_current_units'
        if not unit_hold and 'candidate_ratio_assuming_si' in group['rectification']:
            rr=group['rectification']; rr['ratio_abs_i_positive_over_negative']=rr.pop('candidate_ratio_assuming_si')
            rr['status']='OK' if rr['ratio_abs_i_positive_over_negative'] is not None else 'SKIP'
            rr['metric_status']='candidate'
        if group.get('rectifier_models',{}).get('models'):
            group['rectifier_models']['unit_status']='unconfirmed; numerical coefficients assume SI' if unit_hold else 'confirmed'
        if unit_hold:
            rr=group['rectification']
            rr.setdefault('candidate_ratio_assuming_si',rr.get('ratio_abs_i_positive_over_negative'))
            rr['ratio_abs_i_positive_over_negative']=None; rr['status']='SKIP'; rr['metric_status']='unavailable'; rr['reason']='unconfirmed_units'
            if group.get('rectifier_models',{}).get('models'):
                group['rectifier_models']['unit_status']='unconfirmed; numerical coefficients assume SI'
        group['metric_status']='unavailable' if unit_hold else 'candidate'
    from .comparison import within_file
    summary['comparisons']=within_file(summary,cfg)
    summary['statuses']={'parse_status':{'status':'parsed_with_gaps' if any(s['invalid_rows'] for s in summary['sheets']) else 'parsed',
        'sheets':[s.get('parse_status',{}) for s in summary['sheets']], 'ignored_sheets':summary['ignored_sheets']},
        'data_qc':{'legacy_status':summary['qc']['overall'],'meaning':'legacy thresholds are advisory; SKIP is not PASS',
            'checks':[check for group in summary['groups'] for check in group.get('data_qc',[])]},
        'metadata_status':context['metadata_status'],
        'metric_status':{g['group_id']:g['metric_status'] for g in summary['groups']},
        'model_status':{g['group_id']:g['model_status'] for g in summary['groups']}}


def metric_rows(summary):
    output=[]
    for group in summary['groups']:
        base={'group_id':group['group_id'],'axis':group['axis'],'vg_v':group['conditions'].get('vg'),
            'fixed_vd_v':group['conditions'].get('vd'),'voltage_unit':'V','current_unit':'A',
            'gate_block_id':group['gate_block_id'],'branch_id':group['branch_id'],'direction':group['direction'],
            'original_sweep':json.dumps(group['original_sweep']), 'metadata_status':group['metadata_status'],
            'source_relative_path':summary['source_relative_path'],'source_sha256':summary['source_sha256']}
        def append(name,metric,voltage=None):
            output.append({**base,'metric':name,'value':metric.get('value'),'unit':metric.get('unit'),
                'metric_status':metric.get('metric_status','unavailable'),'reason':metric.get('reason'),
                'evaluation_abs_vd_v':voltage,'evaluation_vd_v':metric.get('evaluation_voltage_v'),
                'bound_type':metric.get('bound_type'),'bound_value':metric.get('bound_value'),
                'candidate_value_assuming_si':metric.get('candidate_value_assuming_si'),
                'support_json':json.dumps(metric,ensure_ascii=False,allow_nan=False)})
        for rr in group.get('rr_series',[]):append('rectification_ratio',rr,rr['evaluation_abs_vd_v'])
        for item in group.get('output_observables',[]):
            for key in ('signed_id','signed_ig','i_over_v','differential_conductance'):append(key,item[key],abs(item['evaluation_vd_v']))
        if group.get('effective_differential_resistance'):append('effective_differential_resistance',group['effective_differential_resistance'])
        transfer=group['transfer_metrics']
        for key in ('raw_peak_abs','internal_peak_abs','vth','ss','mobility','current_range_ratio'):
            if key in transfer:append(key,transfer[key])
    return output


def export_metrics(summary,directory):
    import pandas as pd
    pd.DataFrame(metric_rows(summary)).to_csv(directory/'observable_metrics.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame([{'group_id':g['group_id'],'status':g['model_status'],'parameter_units':json.dumps({'slope_a_per_v':'A/V','offset_a':'A','i0_a':'A','alpha_per_v':'1/V'}),
        'models_json':json.dumps(g.get('rectifier_models',{}),ensure_ascii=False,allow_nan=False)} for g in summary['groups']]).to_csv(directory/'model_diagnostics.csv',index=False,encoding='utf-8-sig')
    parameters=[]
    for group in summary['groups']:
        for model in group.get('rectifier_models',{}).get('models',[]):
            for polarity,values in model.get('parameters',{}).items():
                for key,value in values.items():
                    parameters.append({'group_id':group['group_id'],'model':model['model'],'polarity':polarity,
                        'parameter':key,'value':value,'unit':model['parameter_units'][key],
                        'model_status':model['model_status'],'fixed_vg_v':group['conditions'].get('vg'),
                        'units_status':'unconfirmed_SI_assumption' if group['units_review_required'] else 'confirmed',
                        'fit_range_abs_vd_v':json.dumps(group['rectifier_models']['window_v']),
                        'voltage_unit':'V','current_unit':'A','current_rmse_a':model['current_rmse_a'],
                        'heldout_rmse_a':model['heldout_rmse_a'],'source_rows':json.dumps(model['source_rows'])})
    pd.DataFrame(parameters,columns=None if parameters else ['group_id','model','parameter','value','unit','model_status','fit_range_abs_vd_v']).to_csv(directory/'rectifier_parameters.csv',index=False,encoding='utf-8-sig')


def note(summary,directory,cfg):
    from .note_presentation import render_note, representative
    relative,assets=summary['vault_note_relative_path'],summary['vault_assets_relative_path']
    destination=cfg.paths['vault']/relative
    if destination.exists():raise FileExistsError('기존 연구노트는 덮어쓰지 않습니다.')
    asset_dir=cfg.paths['vault']/assets
    asset_dir.mkdir(parents=True,exist_ok=False)
    for path in directory.iterdir():
        if path.is_file():shutil.copy2(path,asset_dir/path.name)
    g=representative(summary)
    name='note_representative.png' if (directory/'note_representative.png').is_file() else None
    if not name and g:
        candidate=g['group_id']+('_transfer.png' if g['axis']=='vg' else '_fit.png')
        if (directory/candidate).is_file():name=candidate
    atomic_text(destination,render_note(summary,assets,directory,name))
    return destination
