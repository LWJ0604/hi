"""Additional note-format-2 evidence. Legacy calculations and QC are untouched.

Every new scalar is paired with dependencies and its original rows. Neither a
confirmed unit nor a successful export certifies a model or a detection floor.
"""
import math
from pathlib import Path
import numpy as np
import pandas as pd
from .scientific_metrics import safe_derivative, sample_at


def finite(value):
    return isinstance(value,(int,float,np.number)) and not isinstance(value,bool) and math.isfinite(float(value))


def signed_mobility(gm,vd,L,W,cox):
    if not all(finite(v) for v in (gm,vd,L,W,cox)) or vd==0 or min(L,W,cox)<=0:return None
    return float(L*gm/(W*cox*vd)*1e4)


def direct_ss(data,validated_floor=None,return_support=False):
    """Actual-spacing derivative of log10|Id|, without gap/sign bridges."""
    frame=data.rename(columns={'x_v':'vg','id_a':'id'}).copy()
    values=frame['id'].to_numpy(dtype=float)
    eligible=np.asarray(frame.get('metric_eligible',np.ones(len(frame),bool)),dtype=bool)&np.isfinite(values)&(values!=0)
    if finite(validated_floor) and validated_floor>0:eligible &= np.abs(values)>=validated_floor
    segment=frame.get('segment_id',pd.Series(0,index=frame.index)).to_numpy()
    cuts=np.zeros(len(frame),dtype=int)
    for k in range(1,len(frame)):
        cuts[k]=cuts[k-1]+int(segment[k]!=segment[k-1] or values[k]*values[k-1]<=0)
    frame['segment_id']=cuts
    frame['metric_eligible']=eligible
    frame['id']=np.log10(np.where(eligible,np.abs(values),np.nan))
    slope,endpoints,parts,_=safe_derivative(frame,'vg')
    support={}
    for part in parts:
        for index,k in enumerate(part):
            support[int(k)]=[int(v) for v in (part[:3] if index==0 else part[-3:] if index==len(part)-1 else part[index-1:index+2])]
    ss=np.full(len(frame),np.nan)
    valid=np.isfinite(slope)&(slope!=0)
    ss[valid]=1000/np.abs(slope[valid])
    return (ss,slope,endpoints,support) if return_support else (ss,slope,endpoints)


def polarity_metrics(positive,negative,u,limit,units_confirmed,history_confirmed):
    """No epsilon, invented floor, inf, or lower-bound ranking."""
    result={'rr':None,'rr_lower_bound':None,'g_positive_s':None,'g_negative_s':None,
            'delta_g_s':None,'a_g':None,'metric_status':'held','reason':'paired_signed_currents_required',
            'evaluation_abs_vds_v':u,'detection_limit_a':limit,
            'definition':'RR=abs(Id(+u))/abs(Id(-u)); G+=Id(+u)/u; G-=Id(-u)/(-u); deltaG=abs(G+)-abs(G-); AG=deltaG/(abs(G+)+abs(G-))',
            'units':{'rr':'1','rr_lower_bound':'1','g_positive_s':'S','g_negative_s':'S','delta_g_s':'S','a_g':'1'}}
    if not all(finite(v) for v in (positive,negative,u)) or u<=0:return result
    if not units_confirmed:result['reason']='voltage_current_units_unconfirmed';return result
    if not history_confirmed:result['reason']='conditions_or_history_unconfirmed';return result
    if not finite(limit) or limit<=0:result['reason']='validated_detection_floor_required';return result
    a,b=abs(positive),abs(negative)
    if a<limit and b<limit:result['reason']='both_polarities_below_floor';return result
    if a<limit:result['reason']='positive_current_below_floor_upper_bound_not_implemented';return result
    if b<limit:
        result.update(rr_lower_bound=float(a/limit),metric_status='bound',reason='negative_current_below_floor')
        return result
    gp,gn=positive/u,negative/(-u);den=abs(gp)+abs(gn)
    delta=abs(gp)-abs(gn)
    result.update(rr=float(a/b),g_positive_s=float(gp),g_negative_s=float(gn),delta_g_s=float(delta),
                  a_g=float(delta/den) if den else None,metric_status='candidate',reason='detected_pair_model_interpretation_not_certified')
    return result


def _strict_sample(data,axis,target):
    frame=data.rename(columns={'x_v':axis,'id_a':'id'})
    if int((frame[axis]==target).sum())>1:
        return {'value':None,'metric_status':'ambiguous','reason':'duplicate_coordinates_not_averaged','source_points':[]}
    return sample_at(frame,axis,target)


def export_report(curves,summary,directory,cfg,additional):
    settings=additional.get('settings',{});science=cfg.data['science']
    floor=science['detection_limit_a'] if science['detection_limit_evidence'] else None
    records=[];pairs=[];groups=[]
    def source(group,row):
        return {'source_sha256':summary.get('source_sha256'),'source_relative_path':summary.get('source_relative_path'),
                'group_id':group['group_id'],'source_row':int(row['source_row']) if pd.notna(row.get('source_row')) else None,
                'source_x_cell':str(row.get('source_x_cell','')),'source_id_cell':str(row.get('source_id_cell','')),
                'source_sheet':group.get('sheet'),'trace_id':group.get('trace_id'),
                'gate_block_id':group.get('gate_block_id'),'direction':group.get('direction'),
                'original_sweep':group.get('original_sweep',{}),'fixed_bias_v':group.get('conditions',{})}
    for g in summary.get('groups',[]):
        data=curves[curves['group_id']==g['group_id']].copy()
        held=g.get('units_review_required',True)
        group={'group_id':g['group_id'],'axis':g['axis'],'direction':g.get('direction'),'gate_block_id':g.get('gate_block_id'),
               'conditions_v':g.get('conditions',{}),'original_sweep':g.get('original_sweep',{}),'n':len(data),
               'units_confirmed':not held,'normalization':'signed gm / max(abs(raw gm)); absolute gm / same maximum',
               'raw_derivative':'np.gradient edge_order=2, actual spacing; one-sided endpoints; no averaging',
               'local_derivatives':g.get('transfer_metrics',{}).get('smoothing_settings',[])}
        groups.append(group)
        if data.empty:continue
        width=settings.get('channel_width_m',{})
        W=width.get('value') if width.get('status')=='confirmed' and width.get('source') else None
        if finite(W) and W>0:
            for _,row in data.iterrows():
                for column,parameter,unit in [('id_a','id_over_width','A/μm'),('gm_a_per_v','gm_over_width','A/(V μm)')]:
                    v=row.get(column)
                    if not finite(v) or (parameter=='gm_over_width' and g['axis']!='vg'):continue
                    result=float(v/(W*1e6))
                    records.append({**source(g,row),'parameter':parameter,'value':None if held else result,
                                    'candidate_value_assuming_si':result if held else None,'unit':unit,
                                    'metric_status':'held' if held else 'candidate','evaluation_voltage_v':float(row['x_v']),
                                    'formula':column+' / confirmed W in micrometres','width_source':width,
                                    'reason':'unconfirmed_voltage_or_current_units' if held else 'width_normalized_observable_geometry_uncertainty_not_certified',
                                    'input_value_si':float(v),'input_column':column,'width_m':float(W),'width_um':float(W*1e6),
                                    'dependencies':{'units_confirmed':not held,'width_confirmed':True,'geometry_uncertainty_recorded':'uncertainty' in width}})
        if g['axis']=='vg':
            ss,slope,end,derivative_support=direct_ss(data,floor,return_support=True)
            mag=np.abs(data['id_a'].to_numpy(dtype=float));maximum=np.nanmax(mag)
            ss_spec=settings.get('ss_local',{});window=ss_spec.get('window_v')
            chosen=((data['x_v']>=window[0])&(data['x_v']<=window[1])).to_numpy() if window else (mag>=.1*maximum)&(mag<=.3*maximum)
            if finite(floor) and floor>0:chosen &= mag>=floor
            # A displayed summary never crosses gaps, reversals, excluded points or a sign change.
            valid=np.isfinite(ss)&~end&chosen
            runs=[];run=[]
            for k in range(len(data)):
                consecutive=bool(run) and data.index[k]==data.index[run[-1]]+1
                same=not run or (data.iloc[k].get('segment_id')==data.iloc[run[-1]].get('segment_id') and data.iloc[k]['id_a']*data.iloc[run[-1]]['id_a']>0)
                if run and (not valid[k] or not consecutive or not same):runs.append(run);run=[]
                if valid[k]:run.append(k)
            if run:runs.append(run)
            runs=[r for r in runs if len(r)>=3 and (np.all(np.diff(mag[r])>0) or np.all(np.diff(mag[r])<0))]
            selected=max(runs,key=len) if runs else []
            status='held' if held or not floor else 'candidate'
            dependencies={'units_confirmed':not held,'floor_confirmed':bool(floor),'subthreshold_region_confirmed':False,
                          'temperature_confirmed':False,'window_explicit':bool(window)}
            for k,(_,row) in enumerate(data.iterrows()):
                below_floor=bool(finite(floor) and abs(row['id_a'])<floor)
                if not finite(ss[k]):continue
                support_indices=derivative_support[k]
                support=[];target=float(row['x_v'])
                for q in support_indices:
                    point=data.iloc[q];others=[float(data.iloc[j]['x_v']) for j in support_indices if j!=q];xq=float(point['x_v'])
                    weight=(2*target-sum(others))/((xq-others[0])*(xq-others[1]))
                    support.append({**source(g,point),'voltage_v':xq,'signed_current_a':float(point['id_a']),
                                    'log10_abs_current':float(np.log10(abs(point['id_a']))),'derivative_weight_per_v':float(weight)})
                records.append({**source(g,row),'parameter':'ss_direct','value':None if held or below_floor or not floor else float(ss[k]),
                    'candidate_value_exploratory':float(ss[k]) if not held and not floor else None,
                    'candidate_value_assuming_si':float(ss[k]) if held else None,'unit':'mV/dec','metric_status':'held' if below_floor else status,
                    'formula':'1000/abs(d(log10(abs(Id)))/dVg); actual-spacing derivative',
                    'dependencies':dependencies,'signed_slope_dec_per_v':float(slope[k]),'endpoint':bool(end[k]),
                    'signed_current_a':float(row['id_a']),'evaluation_voltage_v':float(row['x_v']),
                    'summary_selected':k in selected,'below_floor':below_floor,'derivative_support':support,
                    'reason':'below_detection_floor' if below_floor else 'direct_log_derivative_exploratory_region_not_certified'})
            group['ss_summary']={'value_min':float(np.min(ss[selected])) if selected and not held and floor else None,
                'value_average':float(np.mean(ss[selected])) if selected and not held and floor else None,
                'exploratory_min':float(np.min(ss[selected])) if selected and not held and not floor else None,
                'exploratory_average':float(np.mean(ss[selected])) if selected and not held and not floor else None,
                'candidate_min_assuming_si':float(np.min(ss[selected])) if selected and held else None,
                'candidate_average_assuming_si':float(np.mean(ss[selected])) if selected and held else None,
                'metric_status':status if selected else 'unavailable','reason':'region_floor_temperature_need_review' if selected else 'no_contiguous_monotone_window',
                'window_v':[float(data.iloc[selected]['x_v'].min()),float(data.iloc[selected]['x_v'].max())] if selected else None,
                'n':len(selected),'span_decades':float(np.ptp(np.log10(mag[selected]))) if selected else None,
                'weighting':'arithmetic mean of selected derivative samples','automatic_rule':None if window else '10–30% of measured max |Id|; first longest contiguous monotone run',
                'source_rows':[int(data.iloc[k]['source_row']) for k in selected] if 'source_row' in data else [],'dependencies':dependencies}
    from .comparison import compare_reasons
    transfer=[g for g in summary.get('groups',[]) if g['axis']=='vg' and finite(g.get('conditions',{}).get('vd'))]
    for gp in transfer:
        u=gp['conditions']['vd']
        if u<=0:continue
        matches=[g for g in transfer if g['conditions']['vd']==-u and g.get('gate_block_id')==gp.get('gate_block_id') and g.get('direction')==gp.get('direction') and g.get('branch_index')==gp.get('branch_index')]
        if len(matches)!=1:continue
        gn=matches[0];reasons=compare_reasons(summary,gp,summary,gn)
        pos=curves[curves['group_id']==gp['group_id']];neg=curves[curves['group_id']==gn['group_id']]
        # Exact matching Vg only in this release. No independent sweeps silently aligned.
        for x in pos['x_v']:
            a,b=_strict_sample(pos,'vg',x),_strict_sample(neg,'vg',x)
            if b.get('interpolated'):b={'value':None,'reason':'exact_matching_Vg_required','source_points':[]}
            m=polarity_metrics(a['value'],b['value'],u,floor,not gp.get('units_review_required',True) and not gn.get('units_review_required',True),not reasons)
            pairs.append({**m,'vg_v':float(x),'positive_group':gp['group_id'],'negative_group':gn['group_id'],
                          'source_positive':a,'source_negative':b,'comparison_reasons':reasons,'pair_method':'exact Vg, exact signed Vds, same acquisition block/order; no extrapolation'})
    for g in summary.get('groups',[]):
        if g['axis']!='vd':continue
        data=curves[curves['group_id']==g['group_id']];reasons=compare_reasons(summary,g,summary,g)
        for u in sorted(set(science['rr_voltages_v'])):
            a,b=_strict_sample(data,'vd',u),_strict_sample(data,'vd',-u)
            m=polarity_metrics(a['value'],b['value'],u,floor,not g.get('units_review_required',True),not reasons)
            pairs.append({**m,'vg_v':g.get('conditions',{}).get('vg'),'positive_group':g['group_id'],'negative_group':g['group_id'],
                          'source_positive':a,'source_negative':b,'comparison_reasons':reasons,'pair_method':'same output branch; signed-current adjacent interpolation only; no RR interpolation'})
    output={'report_format':'fet-research-note-2','schema_version':2,'groups':groups,'direct_metrics':records,'polarity_pairs':pairs,
            'primary_evaluation_abs_vds_v':cfg.data['analysis']['rr_voltage'],
            'settings':settings,'source_sha256':summary.get('source_sha256'),'detection_floor':{'value_a':floor,'evidence':science['detection_limit_evidence']},
            'legacy_values_unchanged':True,'repeat_averaging':False,'contact_correction':False,
            'ranked_rr':[], # Bounds and held pairs are never ranked as measured maxima.
            'unavailable':{'TLM':'같은 geometry·이력·낮은 bias의 여러 채널 길이와 TLM 저항 배열 필요',
                           'Rc':'TLM/4-probe 접촉 분리 측정 필요; Rs와 V/I는 Rc가 아님',
                           'nS':'확인된 용량·문턱전압·정전기 모델 필요',
                           'mu_con':'접촉 분리 Rsh와 검증된 양의 nS 필요',
                           'DIBL':'비교 가능한 여러 Vds와 동일한 Vth 정의 필요',
                           'Isat':'검증된 포화 plateau와 평가 bias 필요'}}
    from .metric_contract import complete_report_contract,export_contract_csv
    complete_report_contract(output,additional,summary,cfg,directory,curves)
    from .metric_store import write_metric_json
    stored,store=write_metric_json(Path(directory)/'research_report.json',output)
    export_contract_csv(stored,store,directory)
    return output
