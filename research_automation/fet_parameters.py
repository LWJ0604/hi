"""Additional FET observables, separate from immutable legacy metrics and QC.

G = Id/Vds is a secant conductance, not gds=dId/dVds. No offsets,
repeat averaging, contact correction, or automatic regime assumptions.
Optional extraction settings live separately from the legacy configuration.
"""
import json
import math
from pathlib import Path
import numpy as np
import pandas as pd
from .util import write_json

DEFINITIONS={
 'conductance':'G = signed Id / signed Vds (직류 할선 전도도; offset 차감 없음)',
 'resistance':'R = signed Vds / signed Id (직류 유효 저항; 접촉저항 아님)',
 'gds':'gds = dId/dVds (저장된 국소 미분; 할선 G와 다름)',
 'differential_resistance':'rd = 1/gds (부호 있는 미분 저항)',
 'gm':'gm = dId/dVg (저장된 raw 미분)',
 'gm_over_vds':'gm / signed Vds (A/V²)',
 'normalized_gm':'signed gm / max|raw gm| (개별 곡선 기준; 무차원)',
 'normalized_abs_gm':'|gm| / max|raw gm| (개별 곡선 기준; 무차원)',
 'leakage_current':'측정 signed Ig (누설 전류)',
 'leakage_ratio':'|Ig|/|Id| (Id=0에서는 정의하지 않음)',
 'mobility_linear':'signed μFE = L/(W Cox Vds) × gm; cm²/(V s), 2-terminal 유효 선형 이동도',
}


def settings_for(cfg, summary):
    path=cfg.paths['vault']/'ResearchAutomation'/'fet-extraction-settings.json'
    from .fet_methods import geometry_profiles,profile_name
    defaults=geometry_profiles().get(profile_name(summary.get('research_context',{}).get('device_name')),{}).copy()
    if not path.is_file():return defaults,None
    from .fet_settings import validate_devices
    data=validate_devices(json.loads(path.read_text(encoding='utf-8-sig')))
    device=summary.get('research_context',{}).get('device_name')
    defaults.update(data.get('devices',{}).get(device,{}))
    return defaults,path


def confirmed(item):
    return isinstance(item,dict) and item.get('status')=='confirmed' and bool(item.get('source')) and item.get('value') is not None


def export_fet(curves, summary, directory, cfg):
    settings,settings_path=settings_for(cfg,summary)
    records=[];extractions=[];coverage=[];method_arrays=[]
    def point(group,row,name,value,unit,formula,assumptions=None):
        if value is None or not math.isfinite(float(value)):return
        held=group.get('units_review_required',True)
        records.append({'group_id':group['group_id'],'parameter':name,'axis':group['axis'],
            'evaluation_voltage_v':float(row['x_v']),'fixed_voltages_v':group.get('conditions',{}),
            'gate_block_id':group.get('gate_block_id'),'direction':group.get('direction'),
            'value':None if held else float(value),'candidate_value_assuming_si':float(value) if held else None,
            'unit':unit,'metric_status':'unavailable' if held else 'candidate',
            'reason':'unconfirmed_voltage_or_current_units' if held else 'geometry_or_regime_assumption' if assumptions else 'derived_observable_not_certified',
            'definition':formula,'source_row':int(row['source_row']) if pd.notna(row.get('source_row')) else None,
            'source_x_cell':str(row.get('source_x_cell','')),'source_id_cell':str(row.get('source_id_cell','')),
            'source_sha256':summary.get('source_sha256'),'assumptions':assumptions or []})
    for group in summary.get('groups',[]):
        data=curves[curves['group_id']==group['group_id']].copy()
        good=data['x_v'].notna() & data['id_a'].notna()
        if 'metric_eligible' in data:good &= data['metric_eligible'].fillna(False).astype(bool)
        data=data[good]
        fixed=group.get('conditions',{}).get('vd')
        for _,row in data.iterrows():
            vd=float(row['x_v']) if group['axis']=='vd' else fixed
            current=float(row['id_a'])
            if isinstance(vd,(int,float)) and math.isfinite(vd) and vd!=0:
                point(group,row,'conductance',current/vd,'S',DEFINITIONS['conductance'])
            if isinstance(vd,(int,float)) and math.isfinite(vd) and current!=0:
                point(group,row,'resistance',vd/current,'Ω',DEFINITIONS['resistance'])
            for column,name,unit in [('did_dvd_a_per_v','gds','S'),('gm_a_per_v','gm','A/V'),
                    ('gm_over_vd_a_per_v2','gm_over_vds','A/V²'),('gm_signed_over_max_abs','normalized_gm','1'),
                    ('gm_abs_over_max_abs','normalized_abs_gm','1'),('ig_a','leakage_current','A')]:
                value=row.get(column)
                if value is not None and pd.notna(value):
                    point(group,row,name,value,unit,DEFINITIONS[name])
                    if name=='gds' and value!=0:point(group,row,'differential_resistance',1/value,'Ω',DEFINITIONS['differential_resistance'])
            if pd.notna(row.get('ig_a')) and current!=0:
                point(group,row,'leakage_ratio',abs(row['ig_a'])/abs(current),'1',DEFINITIONS['leakage_ratio'])
        transfer=group.get('transfer_metrics',{})
        for key,label in [('vth','문턱전압 Vth'),('ss','서브스레숄드 기울기 SS'),('mobility','전계효과 이동도'),('current_range_ratio','측정 구간 전류 비율')]:
            if group['axis']=='vg':
                m=transfer.get(key,{})
                coverage.append({'group_id':group['group_id'],'parameter':key,'label':label,
                    'legacy_metric_status':m.get('metric_status','unavailable'),'legacy_value':m.get('value'),
                    'legacy_reason':m.get('reason'),'existing_result_unchanged':True})
        if group['axis']=='vg':
            from .fet_methods import yfm_ss
            new_metrics,arrays=yfm_ss(group,data,settings)
            extractions.extend(new_metrics);method_arrays.extend(arrays)
            geometry=[settings.get(k,{}) for k in ('channel_length_m','channel_width_m','cox_f_per_m2')]
            regime=settings.get('linear_regime',{})
            ok=all(isinstance(item,dict) and item.get('status') in ('confirmed','assumed') and item.get('source') and isinstance(item.get('value'),(int,float)) and item['value']>0 for item in geometry)
            ok=ok and isinstance(fixed,(int,float)) and fixed!=0
            if ok:
                lo,hi=settings.get('mobility_window_v',[None,None])
                if not isinstance(lo,(int,float)) or not isinstance(hi,(int,float)) or lo>=hi:
                    lo,hi=(data['x_v'].min(),data['x_v'].max()) if len(data) else (None,None)
                    if lo is None:ok=False
            if ok:
                L,W,Cox=(g['value'] for g in geometry)
                for _,row in data[(data['x_v']>=lo)&(data['x_v']<=hi)].iterrows():
                    gm=row.get('gm_a_per_v')
                    if gm is not None and pd.notna(gm):point(group,row,'mobility_linear',L/(W*Cox*fixed)*gm*1e4,'cm²/(V s)',DEFINITIONS['mobility_linear'],
                        [*([] if confirmed(geometry[2]) else ['Cox·SiO₂ 유전율 가정']), *([] if confirmed(regime) and regime.get('value') is True else ['선형 동작 구간 미확인'])] )
            else:extractions.append({'group_id':group['group_id'],'parameter':'mobility_linear','value':None,'metric_status':'unavailable',
                                    'reason':'confirmed_geometry_cox_linear_regime_and_window_required'})
            _thresholds(group,data,settings,extractions)
        # These cannot be inferred from a single two-terminal sweep.
        for key,why in [('on_off_ratio','confirmed_on_off_operating_points_and_detection_limit_required'),
                        ('contact_resistance','TLM_or_four_probe_measurements_required'),
                        ('hysteresis_voltage','confirmed_forward_reverse_history_and_current_criterion_required'),
                        ('carrier_density','confirmed_capacitance_threshold_and_electrostatic_model_required'),
                        ('trap_density','confirmed_temperature_capacitance_and_subthreshold_model_required')]:
            if group['axis']=='vg' or key=='contact_resistance':
                extra=_on_off(group,data,settings) if key=='on_off_ratio' else None
                extra=extra or {'value':None,'metric_status':'unavailable','reason':why}
                extra.update({'group_id':group['group_id'],'parameter':key});extractions.append(extra)
    output={'schema_version':1,'scope':'additional FET observables; legacy calculations/QC/confirmation unchanged',
            'source_sha256':summary.get('source_sha256'),'legacy_job_id':summary.get('job_id'),
            'definitions':DEFINITIONS,'points':records,'extractions':extractions,'legacy_metric_coverage':coverage,
            'settings_source':str(settings_path) if settings_path else None,
            'settings':settings,'method_arrays':method_arrays,'contact_correction':False,'offset_subtraction':False,'repeat_averaging':False}
    write_json(Path(directory)/'fet_parameters.json',output)
    cols=['group_id','parameter','axis','evaluation_voltage_v','fixed_voltages_v','gate_block_id','direction','value',
          'candidate_value_assuming_si','unit','metric_status','reason','definition','source_row','source_x_cell','source_id_cell','source_sha256']
    frame=pd.DataFrame(records,columns=cols)
    if len(frame):frame['fixed_voltages_v']=frame['fixed_voltages_v'].map(lambda x:json.dumps(x,ensure_ascii=False))
    frame.to_csv(Path(directory)/'fet_parameters.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(extractions).to_csv(Path(directory)/'fet_summary.csv',index=False,encoding='utf-8-sig')
    return output


def _thresholds(group,data,settings,out):
    """Explicit user-selected constant-current Vth and SS window only; legacy fields untouched."""
    for key in ('vth','ss'):
        spec=settings.get(key,{})
        result={'group_id':group['group_id'],'parameter':key+'_additional','value':None,
                'metric_status':'unavailable','reason':'explicit_criterion_window_and_detection_limit_required'}
        out.append(result)
        if not spec or spec.get('status')!='confirmed' or not spec.get('source'):continue
        window=spec.get('window_v');limit=spec.get('detection_limit_a')
        if not isinstance(window,list) or len(window)!=2 or window[0]>=window[1] or not isinstance(limit,(int,float)) or limit<=0:continue
        d=data[(data['x_v']>=window[0])&(data['x_v']<=window[1])]
        # Do not bridge missing/excluded points or distinct acquisition segments.
        if len(d)<3 or not d.index.to_series().diff().dropna().eq(1).all():continue
        if 'segment_id' in d and d['segment_id'].nunique()!=1:continue
        x=d['x_v'].to_numpy();i=d['id_a'].to_numpy();mag=np.abs(i)
        if not np.isfinite(x).all() or not np.isfinite(i).all() or np.any(mag<=limit) or np.any(i[:-1]*i[1:]<=0):continue
        dx=np.diff(x)
        if not (np.all(dx>0) or np.all(dx<0)):continue
        if key=='vth':
            criterion=spec.get('current_a')
            if spec.get('method')!='constant_current' or not isinstance(criterion,(int,float)) or criterion<=limit:continue
            exact=np.where(mag==criterion)[0];crossings=np.where((mag[:-1]-criterion)*(mag[1:]-criterion)<0)[0]
            values=[(float(x[k]),[int(k)]) for k in exact]
            values += [(float(x[k]+(criterion-mag[k])/(mag[k+1]-mag[k])*(x[k+1]-x[k])),[int(k),int(k+1)]) for k in crossings]
            if len(values)!=1:
                result['metric_status']='ambiguous' if len(values)>1 else 'unavailable';result['reason']='multiple_crossings' if len(values)>1 else 'criterion_not_crossed';continue
            value,indices=values[0];unit='V';definition='Vth at explicitly confirmed |Id| criterion; linear interpolation between adjacent eligible points'
        else:
            if spec.get('method')!='log_current_linear_window':continue
            delta=np.diff(mag)
            if not (np.all(delta>0) or np.all(delta<0)):continue
            slope,intercept=np.polyfit(x,np.log10(mag),1)
            if slope==0 or not math.isfinite(slope):continue
            value=1000/abs(float(slope));indices=list(range(len(d)));unit='mV/dec'
            definition='SS = 1000/|slope of log10|Id| vs Vg| in explicitly confirmed window'
            result['fit_slope_dec_per_v']=float(slope);result['fit_intercept']=float(intercept)
        held=group.get('units_review_required',True)
        result.update({'value':None if held else value,'candidate_value_assuming_si':value if held else None,
            'metric_status':'unavailable' if held else 'candidate','reason':'unconfirmed_voltage_or_current_units' if held else 'explicit_method_candidate_not_certified',
            'unit':unit,'window_v':window,'definition':definition,'source_rows':[int(d.iloc[k]['source_row']) for k in indices] if 'source_row' in d else [],'settings':spec})


def _on_off(group,data,settings):
    spec=settings.get('on_off',{})
    if spec.get('status')!='confirmed' or not spec.get('source'):return None
    on,off=spec.get('on_vg_v'),spec.get('off_vg_v');limit=spec.get('detection_limit_a')
    if not isinstance(limit,(int,float)) or limit<=0:return None
    a=data[data['x_v']==on];b=data[data['x_v']==off]
    if len(a)!=1 or len(b)!=1:return None
    ia,ib=abs(float(a.iloc[0]['id_a'])),abs(float(b.iloc[0]['id_a']))
    if ia<=limit or ib<=limit:return None  # No fabricated finite off current or ratio.
    held=group.get('units_review_required',True);value=ia/ib
    return {'value':None if held else value,'candidate_value_assuming_si':value if held else None,
            'unit':'1','metric_status':'unavailable' if held else 'candidate',
            'reason':'unconfirmed_voltage_or_current_units' if held else 'selected_on_off_points_candidate_not_certified',
            'on_vg_v':on,'off_vg_v':off,'detection_limit_a':limit,'settings':spec}
