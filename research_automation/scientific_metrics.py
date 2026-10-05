"""Branch-local observable metrics with explicit support, units and limitations."""
import math
import numpy as np


def unavailable(reason,unit=None,**extra):
    return {'value':None,'unit':unit,'metric_status':'unavailable','reason':reason,**extra}


def rows(frame, indices):
    return [{'source_row':int(frame.iloc[i]['source_row']),
        'id_cell':frame.iloc[i].get('source_id_cell'),
        'x_cell':frame.iloc[i].get('source_x_cell'),
        'acquisition_order':int(frame.iloc[i].get('acquisition_order',i))} for i in indices]


def sample_at(frame,axis,target,column='id'):
    if column not in frame:return unavailable('column_not_measured','A',evaluation_voltage_v=float(target))
    x=frame[axis].to_numpy(dtype=float); y=frame[column].to_numpy(dtype=float)
    eligible=frame.get('metric_eligible',np.isfinite(y))
    eligible=np.asarray(eligible,dtype=bool)&np.isfinite(y)
    exact=np.flatnonzero(x==target)
    if len(exact):
        if not eligible[exact].all():return unavailable('excluded_exact_point','A',evaluation_voltage_v=float(target),source_points=rows(frame,exact))
        if len(set(y[exact]))>1:return {'value':None,'unit':'A','metric_status':'ambiguous','reason':'repeated_voltage_different_currents','evaluation_voltage_v':float(target),'candidate_currents_a':y[exact].tolist(),'source_points':rows(frame,exact)}
        return {'value':float(y[exact[0]]),'unit':'A','metric_status':'candidate','reason':'exact_measured_point','evaluation_voltage_v':float(target),'interpolated':False,'source_points':rows(frame,exact)}
    hits=[]
    for i in range(len(x)-1):
        if min(x[i:i+2])<target<max(x[i:i+2]):
            same_segment='segment_id' not in frame or frame.iloc[i]['segment_id']==frame.iloc[i+1]['segment_id']
            consecutive='acquisition_order' not in frame or frame.iloc[i+1]['acquisition_order']==frame.iloc[i]['acquisition_order']+1
            if same_segment and consecutive and eligible[i:i+2].all():hits.append(i)
    if len(hits)!=1:return unavailable('outside_coverage_or_gap_compliance_or_ambiguous','A',evaluation_voltage_v=float(target))
    i=hits[0]; value=y[i]+(y[i+1]-y[i])*(target-x[i])/(x[i+1]-x[i])
    return {'value':float(value),'unit':'A','metric_status':'candidate','reason':'adjacent_valid_interpolation','evaluation_voltage_v':float(target),'interpolated':True,'source_points':rows(frame,[i,i+1])}


def ratio_with_limit(numerator,denominator,limit):
    a,b=abs(numerator),abs(denominator)
    if limit is not None:
        if a<limit and b<limit:return unavailable('both_below_detection_limit','1')
        if b<limit:return {'value':None,'unit':'1','metric_status':'bound','bound_type':'lower','bound_value':a/limit,'reason':'denominator_below_detection_limit'}
        if a<limit:return {'value':None,'unit':'1','metric_status':'bound','bound_type':'upper','bound_value':limit/b,'reason':'numerator_below_detection_limit'}
    if b==0:return unavailable('zero_denominator_detection_limit_unknown','1')
    value=a/b
    if not math.isfinite(value):return unavailable('numerically_nonfinite_ratio','1')
    return {'value':value,'unit':'1','metric_status':'valid' if limit is not None else 'candidate','reason':'detected_at_both_polarities' if limit is not None else 'detection_limit_unknown'}


def rectification_series(frame,cfg):
    limit=cfg.data['science']['detection_limit_a'] if cfg.data['science']['detection_limit_evidence'] else None
    results=[]
    targets=sorted(set(cfg.data['science']['rr_voltages_v']+[cfg.data['analysis']['rr_voltage']]))
    for u in targets:
        pos,neg=sample_at(frame,'vd',u),sample_at(frame,'vd',-u)
        item={'evaluation_abs_vd_v':float(u),'vg_v':float(frame['vg'].iloc[0]) if 'vg' in frame else None,
            'positive_current':pos,'negative_current':neg,'detection_limit_a':limit,
            'definition':'abs(Id(+u))/abs(Id(-u)); RR<1 retained',
            'why':'극성별 전류 비대칭 관측','trust_when':'같은 스윕·블록, 두 극성의 유효점과 검출한계 확인'}
        if pos['value'] is None or neg['value'] is None:
            item.update(unavailable('polarity_samples_unavailable','1'))
            if pos['metric_status']=='ambiguous' or neg['metric_status']=='ambiguous':item['metric_status']='ambiguous'
        else:item.update(ratio_with_limit(pos['value'],neg['value'],limit))
        results.append(item)
    return results


def safe_derivative(frame,axis):
    """No deduplication. Duplicate/dwell coordinates invalidate local derivatives."""
    x=frame[axis].to_numpy(dtype=float); y=frame['id'].to_numpy(dtype=float)
    valid=np.asarray(frame.get('metric_eligible',np.ones(len(frame),dtype=bool)),dtype=bool).copy()
    duplicate=np.zeros(len(x),dtype=bool)
    if len(x)>1:
        equal=np.diff(x)==0; duplicate[:-1]|=equal; duplicate[1:]|=equal
    valid&=~duplicate
    cuts=[0]
    for i in range(1,len(x)):
        if not valid[i] or not valid[i-1] or ('segment_id' in frame and frame.iloc[i]['segment_id']!=frame.iloc[i-1]['segment_id']):cuts.append(i)
    cuts.append(len(x)); parts=[]; raw=np.full(len(x),np.nan)
    endpoint=np.zeros(len(x),dtype=bool)
    for start,end in zip(cuts[:-1],cuts[1:]):
        indices=np.arange(start,end)
        if len(indices)>=3 and valid[indices].all():
            raw[indices]=np.gradient(y[indices],x[indices],edge_order=2)
            endpoint[[indices[0],indices[-1]]]=True
            parts.append(indices)
    return raw,endpoint,parts,duplicate


def transfer_observables(frame,cfg):
    x=frame['vg'].to_numpy(dtype=float); y=frame['id'].to_numpy(dtype=float)
    raw,endpoints,parts,duplicate=safe_derivative(frame,'vg')
    arrays={'gm_a_per_v':raw,'gm_raw_endpoint':endpoints,'gm_duplicate_coordinate':duplicate}
    settings=[]; candidates=[]
    for width in cfg.data['science']['gm_windows_v']:
        derivative=np.full(len(frame),np.nan); counts=np.zeros(len(frame),dtype=int)
        interior=np.zeros(len(frame),dtype=bool)
        for indices in parts:
            for i in indices:
                window=indices[np.abs(x[indices]-x[i])<=width/2+1e-12]
                counts[i]=len(window)
                if len(window)<cfg.data['science']['gm_min_points']:continue
                dx=x[window]-x[i]; scale=max(np.max(np.abs(y[window])),np.finfo(float).tiny)
                coef=np.polynomial.polynomial.polyfit(dx,y[window]/scale,cfg.data['science']['gm_polynomial_order'])
                derivative[i]=coef[1]*scale
                interior[i]=min(x[indices])+width/2<=x[i]<=max(x[indices])-width/2
        key=f"gm_local_w{width:g}_a_per_v"
        arrays[key]=derivative; arrays[f"gm_local_w{width:g}_points"]=counts
        good=np.flatnonzero(interior & np.isfinite(derivative))
        peak=int(good[np.argmax(np.abs(derivative[good]))]) if len(good) else None
        if peak is not None:candidates.append((peak,float(derivative[peak])))
        settings.append({'width_v':width,'polynomial_order':cfg.data['science']['gm_polynomial_order'],
            'method':'local polynomial in actual Vg coordinates; valid for nonuniform steps',
            'min_points':cfg.data['science']['gm_min_points'], 'boundary':'one-sided local fit retained, excluded from internal peak',
            'internal_peak_vg_v':float(x[peak]) if peak is not None else None,
            'internal_peak_signed_gm_a_per_v':float(derivative[peak]) if peak is not None else None})
    good=np.flatnonzero(np.isfinite(raw))
    info={'status':'OK' if len(good) else 'SKIP','raw_method':'np.gradient signed Id versus actual signed Vg; no averaging',
        'smoothing_settings':settings,'original_range_v':[float(x.min()),float(x.max())],
        'vth':unavailable('constant_current_method_criterion_window_not_set','V'),
        'ss':unavailable('valid_monotone_subthreshold_window_and_detection_limit_required','V/dec'),
        'mobility':unavailable('confirmed_L_W_Cox_and_linear_regime_required','m^2/(V s)'),
        'caveat':'raw endpoint derivative maximum is not a certified internal peak; current range ratio is not device on/off ratio'}
    if len(good):
        signed_max=int(good[np.argmax(raw[good])]); peak=int(good[np.argmax(np.abs(raw[good]))])
        info.update({'gm_max_a_per_v':float(raw[signed_max]),'gm_min_a_per_v':float(np.min(raw[good])),
            'gm_peak_vg_v':float(x[signed_max]),
            'raw_peak_abs':{'value':float(abs(raw[peak])),'signed_gm_a_per_v':float(raw[peak]),'vg_v':float(x[peak]),
                'source_points':rows(frame,[peak]),'unit':'A/V','metric_status':'candidate',
                'endpoint':bool(endpoints[peak]),'reason':'raw_endpoint_maximum' if endpoints[peak] else 'raw_unsmoothed_maximum'}})
        norm=float(np.max(np.abs(raw[good])))
        arrays['gm_signed_over_max_abs']=raw/norm if norm>0 else np.full(len(raw),np.nan)
        arrays['gm_abs_over_max_abs']=np.abs(raw)/norm if norm>0 else np.full(len(raw),np.nan)
    else:info.update({'gm_max_a_per_v':None,'gm_min_a_per_v':None,'gm_peak_vg_v':None,'raw_peak_abs':unavailable('insufficient_valid_distinct_voltage_segments','A/V')})
    vd=float(frame['vd'].iloc[0]) if 'vd' in frame else None
    arrays['gm_over_vd_a_per_v2']=raw/vd if vd else np.full(len(raw),np.nan)
    info['gm_over_vd_status']='candidate' if vd else 'unavailable_zero_or_missing_vd'
    internal=unavailable('no_internal_smoothing_support','A/V')
    if len(candidates)>=2:
        positions=[x[i] for i,_ in candidates]; amplitudes=[abs(v) for _,v in candidates]
        spread=float(np.ptp(positions)); rel=float(np.ptp(amplitudes)/max(np.median(amplitudes),np.finfo(float).tiny))
        peak,value=candidates[len(candidates)//2]
        sign_cross=bool(np.any(y[:-1]*y[1:]<0))
        internal={'value':abs(value),'signed_gm_a_per_v':value,'vg_v':float(x[peak]),'unit':'A/V',
            'position_sensitivity_v':spread,'relative_amplitude_sensitivity':rel,
            'supported_windows':sum(s['internal_peak_vg_v'] is not None for s in settings),
            'unsupported_windows_v':[s['width_v'] for s in settings if s['internal_peak_vg_v'] is None],
            'metric_status':'ambiguous' if spread>cfg.data['science']['gm_peak_tolerance_v'] or rel>.5 or sign_cross else 'candidate',
            'reason':'window_or_sign_change_sensitive' if spread>cfg.data['science']['gm_peak_tolerance_v'] or rel>.5 or sign_cross else 'stable_across_configured_windows_noise_and_units_need_confirmation',
            'source_points':rows(frame,[peak])}
    info['internal_peak_abs']=internal
    absolute=np.abs(y); limit=cfg.data['science']['detection_limit_a'] if cfg.data['science']['detection_limit_evidence'] else None
    ratio=ratio_with_limit(float(absolute.max()),float(absolute.min()),limit)
    info.update({'current_max_abs_a':float(absolute.max()),'current_min_abs_a':float(absolute.min()),
        'current_range_ratio_abs':ratio['value'],'current_range_ratio':{**ratio,'evaluated_range_v':info['original_range_v'],'detection_limit_a':limit},
        'ratio_status':ratio['metric_status'],'method':info['raw_method']})
    extra_transfer_metrics(frame,info,cfg,vd,limit)
    return info,arrays


def extra_transfer_metrics(frame,info,cfg,vd,limit):
    options=cfg.data['science']; x=frame['vg'].to_numpy(); y=frame['id'].to_numpy()
    vth=options['vth']
    if vth and vth.get('method')=='constant_current' and vth.get('criterion_a',0)>0 and len(vth.get('window_v',[]))==2:
        criterion=vth['criterion_a']; lower,upper=vth['window_v']
        crossings=[]
        for i in range(len(x)-1):
            if x[i]!=x[i+1] and lower<=min(x[i:i+2]) and max(x[i:i+2])<=upper and (abs(y[i])-criterion)*(abs(y[i+1])-criterion)<=0 and abs(y[i])!=abs(y[i+1]):
                if frame.iloc[i].get('metric_eligible',True) and frame.iloc[i+1].get('metric_eligible',True):
                    crossings.append((float(x[i]+(criterion-abs(y[i]))*(x[i+1]-x[i])/(abs(y[i+1])-abs(y[i]))),i))
        distinct={v for v,_ in crossings}
        info['vth']={'value':next(iter(distinct)) if len(distinct)==1 else None,'unit':'V','method':'constant_current_abs_Id',
            'criterion_a':criterion,'window_v':[lower,upper],'metric_status':'candidate' if len(distinct)==1 and limit and criterion>limit else 'ambiguous' if len(distinct)>1 else 'unavailable',
            'reason':'unique_crossing' if len(distinct)==1 and limit and criterion>limit else 'multiple_crossings_or_detection_limit_unknown',
            'source_points':rows(frame,sorted({i for _,i in crossings}|{i+1 for _,i in crossings}))}
        if info['vth']['metric_status']=='unavailable':info['vth']['value']=None
    ss=options['ss']
    if ss and limit and len(ss.get('window_v',[]))==2:
        a,b=ss['window_v']; select=np.flatnonzero((x>=a)&(x<=b)&(np.abs(y)>limit)&np.asarray(frame.get('metric_eligible',True)))
        current_range=ss.get('current_range_a')
        if current_range:select=select[(np.abs(y[select])>=current_range[0])&(np.abs(y[select])<=current_range[1])]
        contiguous=len(select)>=max(5,cfg.data['analysis']['min_points']) and np.all(np.diff(select)==1) and np.all(np.diff(x[select])!=0) and len(set(np.sign(y[select])))==1
        if contiguous:
            difference=np.diff(np.abs(y[select])); monotone=np.all(difference>0) or np.all(difference<0)
            if monotone:
                log=np.log10(np.abs(y[select])); slope,offset=np.polyfit(x[select],log,1)
                residual=log-(slope*x[select]+offset)
                info['ss']={'value':float(1/abs(slope)) if slope else None,'unit':'V/dec','metric_status':'candidate','reason':'specified_monotone_window_above_detection_limit',
                    'window_v':[float(x[select].min()),float(x[select].max())],'current_range_a':[float(abs(y[select]).min()),float(abs(y[select]).max())],
                    'slope_dec_per_v':float(slope),'log_current_rmse_dec':float(np.sqrt(np.mean(residual**2))),'source_points':rows(frame,select)}
    geometry=options['mobility']
    peak=info['internal_peak_abs']
    if geometry and geometry.get('confirmed') is True and geometry.get('linear_regime_confirmed') is True and vd and peak.get('value') is not None and all(isinstance(geometry.get(k),(int,float)) and geometry[k]>0 for k in ('L_m','W_m','Cox_f_per_m2')):
        info['mobility']={'value':float(geometry['L_m']/geometry['W_m']/geometry['Cox_f_per_m2']*abs(peak['signed_gm_a_per_v']/vd)),
            'unit':'m^2/(V s)','name':'2-terminal apparent field-effect mobility','metric_status':'candidate' if peak['metric_status']=='candidate' else 'ambiguous',
            'reason':'geometry_and_linear_regime_confirmed_two_terminal_contact_effects_remain','geometry':geometry,'vd_v':vd,'gm_support':peak}


def output_observables(frame,cfg):
    raw,endpoints,parts,duplicates=safe_derivative(frame,'vd')
    derivative_frame=frame.copy(); derivative_frame['conductance']=raw
    items=[]
    for value in sorted(set([0.]+[v*s for v in cfg.data['science']['rr_voltages_v'] for s in (-1,1)])):
        current=sample_at(frame,'vd',value)
        derivative=sample_at(derivative_frame,'vd',value,'conductance'); derivative['unit']='A/V'
        items.append({'evaluation_vd_v':value,'vg_v':float(frame['vg'].iloc[0]) if 'vg' in frame else None,
            'signed_id':current,'signed_ig':sample_at(frame,'vd',value,'ig'),
            'i_over_v':{'value':current['value']/value,'unit':'A/V','metric_status':'candidate','reason':'signed_Id_over_Vd'} if value and current['value'] is not None else unavailable('zero_voltage_or_current_unavailable','A/V'),
            'differential_conductance':derivative})
    width=cfg.data['science']['zero_slope_window_v']
    zero=np.flatnonzero((np.abs(frame['vd'].to_numpy())<=width)&np.asarray(frame.get('metric_eligible',True)))
    resistance=unavailable('insufficient_zero_region_points','ohm',window_v=[-width,width])
    if len(zero)>=3 and frame.iloc[zero]['vd'].nunique()>=3:
        slope,offset=np.polyfit(frame.iloc[zero]['vd'],frame.iloc[zero]['id'],1)
        resistance={'value':float(1/slope) if slope else None,'unit':'ohm','metric_status':'candidate' if slope else 'unavailable',
            'reason':'inverse_local_zero_voltage_slope_not_contact_resistance','slope_a_per_v':float(slope),'window_v':[-width,width],
            'source_points':rows(frame,zero),'uncertainty':None,'uncertainty_reason':'no_independent_noise_model'}
    return items,resistance,raw
