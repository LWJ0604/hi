"""Evidence-oriented checks. Legacy thresholds remain advisory and never delete points."""
import numpy as np


def point_qc(frame, settings, cfg):
    options=cfg.data['science']
    result=frame.copy()
    flags=[[] for _ in range(len(frame))]
    statuses=[]
    def add(code,status,detail,indices=(),unit=None,value=None):
        rows=[int(frame.iloc[i]['source_row']) for i in indices]
        for i in indices:flags[i].append(code)
        statuses.append({'code':code,'status':status,'detail':detail,'unit':unit,'value':value,'source_rows':rows,
            'affected_metrics':['RR','conductance','gm','SS','Vth','mobility','rectifier_fit']})
    actual=np.flatnonzero(frame.get('compliance_flag',False)).tolist() if 'compliance_flag' in frame else []
    add('instrument_compliance_flag','candidate' if actual else 'evaluated' if 'compliance_flag_recorded' in frame and frame['compliance_flag_recorded'].all() else 'not_assessed','실제 장비 flag와 설정 한계 근접 추정은 별개; flag 미기록은 정상 확정이 아님',actual)
    proximity=np.zeros(len(frame),dtype=bool)
    for key,current in [('vd','id'),('vg','ig')]:
        limit=settings.get(key)
        if limit and limit>0 and current in frame:
            hits=np.flatnonzero(frame[current].abs().to_numpy()>=limit*options['compliance_proximity_ratio']).tolist()
            proximity[hits]=True
            add('compliance_proximity_'+current,'candidate' if hits else 'evaluated','설정 한계 근접 추정이며 실제 compliance 확정이 아님',hits,'A',limit)
    result['metric_eligible']=~(result.get('compliance_flag',False)|proximity)
    if 'ig' in frame:
        known=np.isfinite(frame['ig'].to_numpy())
        result['ig_over_id_abs']=np.where(known & (frame['id'].abs()>0),frame['ig'].abs()/frame['id'].abs(),np.nan)
        add('gate_leakage','evaluated' if known.all() else 'not_assessed','측정 Ig 절댓값 및 |Ig|/|Id|; 미측정은 null',unit='A',value=float(frame.loc[known,'ig'].abs().max()) if known.any() else None)
        if options['leakage_ratio_limit'] is not None:
            hits=np.flatnonzero(result['ig_over_id_abs'].to_numpy()>options['leakage_ratio_limit']).tolist()
            add('gate_leakage_ratio','candidate' if hits else 'evaluated','사용자 비율 기준; Id=0 제외',hits,'1',options['leakage_ratio_limit'])
    else:add('gate_leakage','not_assessed','Ig가 측정되지 않음; 0으로 대체하지 않음')
    x=frame['vd'].to_numpy() if 'vd' in frame else np.zeros(len(frame))
    if 'vd' in frame:
        zero=np.flatnonzero(np.abs(x)<=cfg.data['qc']['zero_voltage_tolerance_v'])
        values=frame.iloc[zero]['id'].to_numpy()
        add('zero_offset','evaluated' if len(zero) else 'not_assessed','영전압 원본 signed Id 평균; 자동 차감하지 않음',zero,'A',float(np.mean(values)) if len(values) else None)
        statuses[-1]['sample_std_a']=float(np.std(values,ddof=1)) if len(values)>1 else None
        statuses[-1]['uncertainty_status']='repeat_scatter_only' if len(values)>1 else 'unavailable_single_point'
    y=frame['id'].to_numpy()
    crossings=np.flatnonzero(y[:-1]*y[1:]<0)+1
    add('current_sign_change','candidate' if len(crossings) else 'evaluated','전류 부호 변화 보존; 물리 변화/offset 모두 검토 대상',crossings,'A')
    # A robust residual to a local voltage-aware slope detects candidates, never deletes steep slopes.
    axis='vg' if 'vg' in frame and frame['vg'].nunique()>1 and ('vd' not in frame or frame['vd'].nunique()==1) else 'vd'
    scores=np.full(len(frame),np.nan)
    if axis in frame and len(frame)>=5 and options['local_jump_sigma'] is not None:
        v=frame[axis].to_numpy(); errors=[]
        for i in range(1,len(frame)-1):
            if v[i+1]!=v[i-1]:errors.append((i,y[i]-np.interp(v[i],np.sort([v[i-1],v[i+1]]),[y[i-1],y[i+1]] if v[i-1]<v[i+1] else [y[i+1],y[i-1]])))
        if errors:
            residual=np.array([e for _,e in errors]); noise=1.4826*np.median(np.abs(residual-np.median(residual)))
            if noise>0:
                for i,e in errors:scores[i]=abs(e-np.median(residual))/noise
        hits=np.flatnonzero(scores>options['local_jump_sigma']).tolist()
        add('local_current_jump','candidate' if hits else 'evaluated','국소 전압 간격/선형 추세 잔차와 MAD; steep slope 자동 삭제 없음',hits,'robust sigma',options['local_jump_sigma'])
    else:add('local_current_jump','not_assessed','근거 있는 sigma 기준 미설정 또는 점 부족')
    limit=options['detection_limit_a'] if options['detection_limit_evidence'] else None
    add('detection_limit','evaluated' if limit else 'not_assessed','별도 baseline/사용자 근거만 사용; current_floor는 수치 보호 상수',unit='A',value=limit)
    result['point_flags']=[';'.join(f) for f in flags]
    result['local_jump_score']=scores
    return result, statuses
