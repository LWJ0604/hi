"""Candidate Y-function and SS extraction from stored eligible transfer points.

These are new, explicitly labelled estimates. They never replace legacy Vth/SS,
unit confirmation, or QC. Automatic windows are exploratory, not certified
linear-regime or subthreshold regions.
"""
import math
import numpy as np
import pandas as pd


def geometry_profiles():
    source='사용자 제공: 2026-10-05 대화 · L/W/절연막 값'
    def f(value,unit):return {'value':value,'unit':unit,'status':'confirmed','source':source}
    return {
        'drainfold':{'channel_length_m':f(1.5e-6,'m'),'channel_width_m':f(400e-9,'m'),
                     'oxide_thickness_m':f(90e-9,'m'),'dielectric':f('SiO2','1'),
                     'relative_permittivity':{'value':3.9,'unit':'1','status':'assumed',
                         'source':'SiO₂의 통상적 상대유전율 3.9 가정 · 사용자/시편 확인 전'},
                     'cox_f_per_m2':{'value':8.8541878128e-12*3.9/90e-9,'unit':'F/m²','status':'assumed',
                         'source':'Cox = ε0 εr/t; εr=3.9 가정; 두께 90 nm 사용자 제공'}},
        'centerfold':{'channel_length_m':f(2e-6,'m'),'channel_width_m':f(400e-9,'m'),
                      'oxide_thickness_m':f(90e-9,'m'),'dielectric':f('SiO2','1'),
                      'relative_permittivity':{'value':3.9,'unit':'1','status':'assumed','source':'SiO₂ 통상 상대유전율 가정'},
                      'cox_f_per_m2':{'value':8.8541878128e-12*3.9/90e-9,'unit':'F/m²','status':'assumed','source':'εr=3.9 가정 · SiO₂ 90 nm 사용자 확인'}},
    }


def profile_name(device):return ''.join(c for c in (device or '').casefold() if c.isalnum())


def yfm_ss(group,data,settings):
    out=[];arrays=[]
    held=group.get('units_review_required',True)
    def item(parameter,value,unit,definition,window,extra):
        # Candidates require researcher review even after units are confirmed.
        return {'group_id':group['group_id'],'parameter':parameter,'value':None if held else value,
                'candidate_value_assuming_si':value if held else None,'unit':unit,
                'metric_status':'unavailable' if held else 'candidate',
                'reason':'unconfirmed_voltage_or_current_units' if held else 'exploratory_window_regime_and_detection_limit_unconfirmed',
                'definition':definition,'window_v':window,'conditions_v':group.get('conditions',{}),
                'selection_rule':'user window if specified; otherwise fixed current-fraction rule and first longest contiguous segment',
                'requires_review':['선형 동작/아임계 동작 구간','검출한계','미분 잡음과 폭 민감도'],**extra}
    def unavailable(name,why):
        out.append({'group_id':group['group_id'],'parameter':name,'value':None,'metric_status':'unavailable','reason':why})
    if data.empty or 'gm_a_per_v' not in data:
        for name in ('vth_yfm','ss_min','ss_average'):unavailable(name,'eligible_transfer_points_and_gm_required')
        return out,arrays
    vd=group.get('conditions',{}).get('vd')
    # Use a stored derivative; do not change its width or recompute legacy gm.
    spec=settings.get('yfm',{})
    width=float(spec.get('gm_window_v',4))
    column=f'gm_local_w{width:g}_a_per_v'
    if column not in data or not data[column].notna().any():column='gm_a_per_v'
    gm=data[column].to_numpy(dtype=float);x=data['x_v'].to_numpy(dtype=float);i=data['id_a'].to_numpy(dtype=float)
    finite=np.isfinite(gm)&np.isfinite(x)&np.isfinite(i)&(gm!=0)&(i!=0)
    if 'gm_raw_endpoint' in data:finite &= ~data['gm_raw_endpoint'].fillna(True).to_numpy(dtype=bool)
    if 'gm_duplicate_coordinate' in data:finite &= ~data['gm_duplicate_coordinate'].fillna(True).to_numpy(dtype=bool)
    mag=np.abs(i)
    if column!='gm_a_per_v':finite &= (x>=np.min(x)+width/2)&(x<=np.max(x)-width/2)
    y=np.full(len(data),np.nan);y[finite]=mag[finite]/np.sqrt(np.abs(gm[finite]))
    # Longest run only; no bridges across excluded points or acquisition segments.
    def run(mask,min_points=8):
        runs=[];current=[];indices=data.index.to_numpy()
        seg=data['segment_id'].to_numpy() if 'segment_id' in data else np.zeros(len(data))
        for k,keep in enumerate(mask):
            if current and (not keep or indices[k]!=indices[current[-1]]+1 or seg[k]!=seg[current[-1]]):
                runs.append(current);current=[]
            if keep:current.append(k)
        if current:runs.append(current)
        choices=[r for r in runs if len(r)>=min_points and (np.all(np.diff(x[r])>0) or np.all(np.diff(x[r])<0)) and
                 (np.all(gm[r]>0) or np.all(gm[r]<0)) and (np.all(i[r]>0) or np.all(i[r]<0))]
        return max(choices,key=len) if choices else []
    ymax=mag[finite].max() if finite.any() else 0
    ymin=mag[finite].min() if finite.any() else 0
    ywindow=spec.get('window_v')
    mask=finite.copy()
    if isinstance(ywindow,list) and len(ywindow)==2:mask &= (x>=ywindow[0])&(x<=ywindow[1])
    else:mask &= (mag>=ymin+.2*(ymax-ymin))&(mag<=ymin+.8*(ymax-ymin))
    chosen=run(mask,int(spec.get('min_points',8)))
    slope=intercept=None;vth=None;prediction=np.full(len(data),np.nan)
    if chosen and isinstance(vd,(int,float)) and vd!=0:
        slope,intercept=np.polyfit(x[chosen],y[chosen],1)
        if slope!=0 and math.isfinite(slope):
            zero=float(-intercept/slope);vth=zero-float(vd)/2;pred=slope*x[chosen]+intercept
            rss=float(np.sum((y[chosen]-pred)**2));tss=float(np.sum((y[chosen]-np.mean(y[chosen]))**2))
            r2=float(1-rss/tss) if tss>0 else None
            over=np.abs(x[chosen]-vth);ratio=float(abs(vd)/over.min()) if over.min()>0 else None
            prediction[chosen]=pred
            window=[float(min(x[chosen])),float(max(x[chosen]))]
            out.append(item('vth_yfm',vth,'V','Y = |Id|/sqrt(|gm|); Y zero intercept = -intercept/slope; Vth,YFM = Y zero intercept - signed Vds/2 (gradual-channel linear model)',window,
                {'y_zero_intercept_v':zero,'drain_bias_correction_v':float(vd)/2,'low_vds_approximation_v':zero,'slope_sqrt_a_v_per_v':float(slope),'intercept_sqrt_a_v':float(intercept),'r_squared':r2,
                 'fit_rmse_sqrt_a_v':math.sqrt(rss/len(chosen)),'gm_source_column':column,
                 'linear_regime_max_abs_vds_over_overdrive':ratio,
                 'linear_regime_confirmed':False,'automatic_window':not bool(ywindow),
                 'automatic_window_rule':'20–80% of measured |Id| span; longest contiguous eligible run; no best-R² search',
                 'polarity_treatment':'magnitudes for Y; signed Vg preserved; rising/falling response retained',
                 'source_rows':[int(data.iloc[k]['source_row']) for k in chosen] if 'source_row' in data else []}))
        else:unavailable('vth_yfm','zero_or_nonfinite_y_slope')
    else:unavailable('vth_yfm','nonzero_vds_and_contiguous_y_window_required')
    # SS is an exploratory local slope in an explicitly reported low-current window.
    ss_spec=settings.get('ss_local',{});sswindow=ss_spec.get('window_v')
    ssmask=finite.copy()
    if isinstance(sswindow,list) and len(sswindow)==2:ssmask &= (x>=sswindow[0])&(x<=sswindow[1])
    else:ssmask &= (mag>=.1*ymax)&(mag<=.3*ymax)
    ss_indices=run(ssmask,int(ss_spec.get('min_points',5)))
    ss=np.full(len(data),np.nan)
    # d log10|I| / dV = gm/(I ln10), so local SS = ln10 |I/gm| ×1000 mV/dec.
    ss[finite]=1000*np.log(10)*np.abs(i[finite]/gm[finite])
    if ss_indices:
        window=[float(min(x[ss_indices])),float(max(x[ss_indices]))]
        values=ss[ss_indices];minimum=ss_indices[int(np.argmin(values))]
        common={'gm_source_column':column,'n':len(ss_indices),'log_current_span_dec':float(np.ptp(np.log10(mag[ss_indices]))),
                'subthreshold_region_confirmed':False,'detection_limit_confirmed':False,
                'automatic_window':not bool(sswindow),'automatic_window_rule':'10–30% of max measured |Id|; first longest contiguous eligible run',
                'source_rows':[int(data.iloc[k]['source_row']) for k in ss_indices] if 'source_row' in data else [],
                'signed_slope_dec_per_v_at_min':float(gm[minimum]/(i[minimum]*np.log(10)))}
        for name,value in [('ss_min',float(np.min(values))),('ss_average',float(np.mean(values)))]:
            out.append(item(name,value,'mV/dec','SSlocal = 1000 ln(10) |Id/gm|; minimum or arithmetic mean over same stated window',window,
                            {**common,'peak_vg_v':float(x[minimum]) if name=='ss_min' else None}))
    else:
        for name in ('ss_min','ss_average'):unavailable(name,'contiguous_low_current_window_required')
    for k in range(len(data)):
        if finite[k]:arrays.append({'group_id':group['group_id'],'evaluation_voltage_v':float(x[k]),
                                   'y_function_sqrt_a_v':float(y[k]),'y_fit_sqrt_a_v':float(prediction[k]) if np.isfinite(prediction[k]) else None,
                                   'y_fit_used':k in chosen,'ss_local_mv_per_dec':float(ss[k]),'ss_summary_used':k in ss_indices,
                                   'metric_status':'unavailable' if held else 'candidate','units_review_required':held,'gm_source_column':column,
                                   'source_row':int(data.iloc[k]['source_row']) if 'source_row' in data else None})
    return out,arrays
