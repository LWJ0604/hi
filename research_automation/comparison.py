"""Explicit comparability gates and continuous two-segment RR knees."""
import numpy as np

REQUIRED=('device_name','electrodes','polarity','sweep_delay_s','hold_s','pre_bias','history','environment')


def compare_reasons(first,ga,second,gb,photo=False):
    reasons=[]
    fa=first['research_context'].get('fields',{}); fb=second['research_context'].get('fields',{})
    for key in REQUIRED:
        a,b=fa.get(key,{}),fb.get(key,{})
        if a.get('status')!='confirmed' or b.get('status')!='confirmed':reasons.append(f'{key}: 미확인/추정/충돌 이력')
        elif a.get('value')!=b.get('value'):reasons.append(f'{key}: 확인값 불일치')
    for fields in (fa,fb):
        if fields.get('illumination',{}).get('status')!='confirmed':reasons.append('광 조건: 사용자 확인 전이거나 충돌')
    if not photo and first['research_context']['illumination']!=second['research_context']['illumination']:reasons.append('광 조건 불일치')
    if ga.get('units_review_required') or gb.get('units_review_required'):reasons.append('전압/전류 단위 미확인')
    if ga['axis']!=gb['axis']:reasons.append('측정 축 불일치')
    if ga['direction']!=gb['direction']:reasons.append('sweep 방향 불일치')
    for key in ('gate_block_id','branch_index'):
        if ga.get(key)!=gb.get(key):reasons.append(f'{key}: 반복 블록/방향 순서 불일치')
    a,b=ga.get('original_sweep',{}),gb.get('original_sweep',{})
    for key in ('start_v','end_v','min_v','max_v'):
        if a.get(key)!=b.get(key):reasons.append(f'원래 sweep {key} 불일치: crop으로 해결되지 않음')
    step=lambda p:sorted(set(round(abs(v),12) for v in p.get('steps_v',[]) if v))
    if step(a)!=step(b):reasons.append('원래 전압 step 불일치')
    for key in ('programmed_start_v','programmed_end_v','programmed_step_v'):
        if a.get(key)!=b.get(key):reasons.append(f'장비 원래 설정 {key} 불일치')
    if ga['axis']=='vd':
        gate_a=first['research_context'].get('fixed_conditions_v',{}).get('vg',[])
        gate_b=second['research_context'].get('fixed_conditions_v',{}).get('vg',[])
        if bool(gate_a)!=bool(gate_b) or (gate_a and (min(gate_a),max(gate_a))!=(min(gate_b),max(gate_b))):
            reasons.append('원래 gate step 범위 불일치: 동일 Vg 선택/crop으로 해결되지 않음')
    if photo and ga['conditions']!=gb['conditions']:reasons.append('고정 Vd/Vg 불일치')
    return sorted(set(reasons))


def knee_once(x,y,min_side):
    if len(x)<2*min_side:return {'metric_status':'unavailable','reason':'insufficient_points','knee_vg_v':None}
    linear=np.column_stack([np.ones(len(x)),x]);coef=np.linalg.lstsq(linear,y,rcond=None)[0]
    linear_rss=float(np.sum((y-linear@coef)**2)); candidates=[]
    for index in range(min_side-1,len(x)-min_side):
        knot=x[index]; design=np.column_stack([np.ones(len(x)),x-knot,np.maximum(x-knot,0)])
        parameters=np.linalg.lstsq(design,y,rcond=None)[0]; residual=y-design@parameters
        s1,s2=parameters[1],parameters[1]+parameters[2]
        candidates.append((float(np.sum(residual**2)),index,float(s1),float(s2)))
    rss,index,s1,s2=min(candidates)
    improvement=(linear_rss-rss)/max(linear_rss,np.finfo(float).tiny)
    scale=max(float(np.ptp(y)),np.finfo(float).tiny)
    if s1>=0 or abs(s2)>=abs(s1)*.6 or improvement<.15 or float(np.ptp(y))<1e-12:
        return {'metric_status':'no_knee','reason':'no_supported_decrease_then_flatter_transition','knee_vg_v':None,'slopes':[s1,s2],'improvement_fraction':improvement}
    residual_sigma=np.sqrt(rss/len(x))
    status='ambiguous' if residual_sigma/scale>.15 or s2 < s1 or index<min_side-1 or index>=len(x)-min_side else 'candidate'
    return {'metric_status':status,'reason':'continuous_two_segment_decrease_then_flatter','knee_vg_v':float(x[index]),
        'decreasing_slope':s1,'later_slope':s2,'left_points':index+1,'right_points':len(x)-index-1,
        'evaluated_range_v':[float(x.min()),float(x.max())],'rss':rss,'improvement_fraction':improvement}


def rr_knee(vg,rr,cfg):
    order=np.argsort(vg); x=np.asarray(vg,dtype=float)[order]; y=np.asarray(rr,dtype=float)[order]
    if len(set(x))!=len(x):return {'metric_status':'ambiguous','knee_vg_v':None,'reason':'repeated_Vg_not_averaged'}
    axis=cfg.data['science']['knee_axis']
    if axis=='log':
        if np.any(y<=0):return {'metric_status':'ambiguous','knee_vg_v':None,'reason':'nonpositive_RR_on_log_axis'}
        y=np.log(y)
    result=knee_once(x,y,cfg.data['science']['knee_min_side_points'])
    result.update({'rr_axis':axis,'slope_unit':'ln(RR)/V' if axis=='log' else 'RR/V','method':'continuous two-line regression; no forced argmin','unit':'V'})
    sensitivity=[]
    if len(x)>=2*cfg.data['science']['knee_min_side_points']+2:
        median=y.copy()
        for i in range(1,len(y)-1):median[i]=np.median(y[i-1:i+2])
        for label,xx,yy in [('trim_one_each_end',x[1:-1],y[1:-1]),('median_three_sensitivity_only',x,median)]:
            item=knee_once(xx,yy,cfg.data['science']['knee_min_side_points']);item['variant']=label;sensitivity.append(item)
        positions=[item['knee_vg_v'] for item in [result,*sensitivity] if item.get('knee_vg_v') is not None]
        if positions and (len(positions)!=len(sensitivity)+1 or np.ptp(positions)>2*np.median(np.diff(x))):
            if result['knee_vg_v'] is not None:result['metric_status']='ambiguous';result['reason']='range_or_smoothing_sensitive'
    result['sensitivity']=sensitivity
    return result


def within_file(summary,cfg):
    groups=summary['groups']; output={'rr_knees':[],'photo_comparisons':[]}
    for u in cfg.data['science']['rr_voltages_v']:
        blocks={g['gate_block_id'] for g in groups if g['axis']=='vd'}
        for block in sorted(blocks):
            for direction in ('forward','reverse'):
                selected=[g for g in groups if g['axis']=='vd' and g['gate_block_id']==block and g['direction']==direction]
                if not selected:continue
                reasons=[r for g in selected for r in compare_reasons(summary,selected[0],summary,g)]
                pairs=[]
                for g in selected:
                    metric=next((m for m in g.get('rr_series',[]) if m['evaluation_abs_vd_v']==u),None)
                    if metric and metric.get('value') is not None and metric['metric_status'] in ('valid','candidate') and metric['vg_v'] is not None:pairs.append((metric['vg_v'],metric['value']))
                    else:reasons.append('RR 점 부족/검출한계 bound/단위 미확인')
                item={'evaluation_abs_vd_v':u,'voltage_unit':'V','rr_unit':'1','gate_block_id':block,'direction':direction,'group_ids':[g['group_id'] for g in selected]}
                if reasons:item.update({'metric_status':'unavailable','reason':'conditions_not_comparable','reasons':sorted(set(reasons)),'knee_vg_v':None})
                else:item.update(rr_knee([p[0] for p in pairs],[p[1] for p in pairs],cfg))
                output['rr_knees'].append(item)
    return output


def photo_difference(dark,gd,df,light,gl,lf):
    reasons=compare_reasons(dark,gd,light,gl,photo=True)
    if dark['research_context']['illumination']!='dark' or light['research_context']['illumination']!='light':reasons.append('확인된 dark/light 쌍이 아님')
    if reasons:return {'metric_status':'unavailable','reasons':sorted(set(reasons)),'points':[]}
    from .scientific_metrics import sample_at
    axis='vd' if gd['axis']=='vd' else 'vg'
    points=[]; optical=light['research_context']['fields'].get('optical_power_w',{})
    power=optical.get('value') if optical.get('status')=='confirmed' else None
    for x in df[axis].to_numpy():
        a,b=sample_at(df,axis,float(x)),sample_at(lf,axis,float(x))
        if a['value'] is None or b['value'] is None:continue
        delta=b['value']-a['value']
        points.append({'evaluation_voltage_v':float(x),'axis':axis,'voltage_unit':'V','signed_delta_id_a':delta,
            'delta_abs_id_a':abs(b['value'])-abs(a['value']),'current_unit':'A',
            'responsivity_a_per_w':delta/power if power and power>0 else None,
            'responsivity_status':'candidate' if power and power>0 else 'unavailable_missing_optical_power',
            'source_points_dark':a['source_points'],'source_points_light':b['source_points']})
    return {'metric_status':'candidate','reasons':[],'points':points,'mechanism_inference':None}
