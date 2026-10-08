"""Branch-local observations with dependency-specific numerical availability.

This supplements the legacy metrics without changing their formulas or QC.
Unknown SI units retain raw/assumed values, never human confirmations. Engineering
windows are recorded explicitly; no contact/barrier/mechanism certification.
"""
import math
import numpy as np

METHOD_VERSION='branch-observations-1.0'
POLICY={'rr_abs_voltages':[0.1,0.5,1.0,1.5,2.0], 'g0_half_windows':[0.025,0.05,0.1],
        'g0_min_unique':5,'gds_widths':[0.2,0.4,0.8],'gds_min_unique':7,
        'gm_widths':[1.0,2.0,4.0],'gm_min_unique':5,'gate_pairs':[[-20,20],[-40,40]],
        'ss_min_decades':1.0,'ss_min_unique':5}

MEANINGS={
 'signed_current':('부호를 보존한 전류','양·음은 장비의 전류 방향입니다. 전류 절댓값이나 메커니즘으로 바꾸지 않습니다.'),
 'rr':('동일 gate·branch에서 +전압/−전압 전류 크기의 비','RR<1도 그대로 유지합니다. 저분모·누설·변하는 Vgd 때문에 단독으로 전도 경로를 증명하지 않습니다.'),
 'log10_rr':('RR의 자릿수와 극성 방향','0보다 크면 +전압 쪽 전류 크기가 크고, 작으면 −전압 쪽이 큽니다.'),
 'asymmetry':('두 극성 전류 크기의 정규화 차이','−1부터 +1의 관측 지표이며 장벽 높이나 경로 비율이 아닙니다.'),
 'odd_current':('전압 반전에 따라 반전되는 전류 성분','[I(+u)−I(−u)]/2. 접촉 종류를 확정하지 않습니다.'),
 'even_current':('전압 반전에도 남는 전류 성분','[I(+u)+I(−u)]/2. offset·비대칭이 모두 기여할 수 있습니다.'),
 'g0':('지정 저바이어스 범위의 offset 포함 선형 기울기','I=Ioffset+G0·V. 전체 2단자 기울기이며 고유 접촉저항이 아닙니다.'),
 'offset':('저바이어스 선형 적합의 0전압 절편','영점 보정으로 원본 전류를 수정하지 않습니다.'),
 'g_secant':('평가점의 signed Id/Vd','원점과 평가점을 잇는 기울기이며 gds나 G0와 구별합니다.'),
 'gds':('평가점 주변 전압 창의 국소 미분 dId/dVd','실제 전압 좌표에 2차 다항식을 적합합니다. 창·누설·노이즈에 민감합니다.'),
 'nonlinearity':('평가 전류와 저바이어스 선형 예측의 차이','I(u)−[Ioffset+G0·u]. 특정 메커니즘의 증거로 확정하지 않습니다.'),
 'current_max':('해당 branch의 최대 |Id|와 gate 위치','사전 지정 ON 상태가 아니므로 Ion으로 부르지 않습니다.'),
 'current_min':('해당 branch의 최소 |Id|와 gate 위치','검출한계·부호 교차·고립 최소값을 확인해야 하며 Ioff가 아닙니다.'),
 'range_ratio':('branch 내 최대/최소 |Id|의 비','임의 극값의 전류 범위비이며 소자 ON/OFF 비로 확정하지 않습니다.'),
 'gate_ratio':('사전 지정 두 gate 전압의 |Id| 비','같은 Vd·branch 안의 변조 관측. 검출한계 미상 시 분모 신뢰도는 미평가입니다.'),
 'gate_delta':('사전 지정 gate 끝점 사이 signed 전류 차','Id(Vg 상한)−Id(Vg 하한). 다른 stress 범위와 자동 비교하지 않습니다.'),
 'gm_peak':('branch 내부에서 가장 큰 |signed gm|와 위치','국소 다항식 창마다 값을 보존합니다. 미분 peak를 채널이나 물리 문턱으로 확정하지 않습니다.'),
 'gm_fwhm':('gm 절댓값 peak 양쪽 반높이 사이 gate 폭','양쪽 교차가 없으면 범위에서 잘린 peak이며 폭을 임의 채우지 않습니다.'),
 'leakage_ratio':('동일 원본점의 |Ig|/|Id|','오염 가능성 지표입니다. Ig를 Id에서 정확히 차감할 근거가 아닙니다.'),
 'leakage_max':('측정된 최대 |Ig|','Ig 누락은 누설 0으로 간주하지 않습니다.'),
 'inverse_log_slope':('선택 단조 구간의 역 로그 전류 기울기','floor·누설·아임계 영역이 확인되지 않으면 탐색 기울기이며 검증된 SS가 아닙니다.'),
 'vcc':('명시한 |Id| 기준과 branch의 유일 교차 gate 전압','constant-current operational 기준입니다. 물리 문턱전압이나 모델 기반 VT가 아닙니다.'),
 'hysteresis_voltage':('같은 전류 기준에서 reverse−forward gate 차이','같은 측정의 인접 정·역 branch 비교. 다른 stress나 반복을 섞지 않습니다.'),
 'hysteresis_current':('같은 gate에서 reverse−forward signed 전류 차이','획득 순서를 보존한 왕복 차이이며 독립 반복의 통계 오차가 아닙니다.'),
}

def finite(value):
    try:return float(value) if math.isfinite(float(value)) else None
    except (TypeError,ValueError):return None

def value_of(record):
    return record.get('value') if record.get('value') is not None else record.get('value_assuming_si')

def support(frame,indices):
    records=[]
    for i in indices:
        row=frame.iloc[int(i)]
        records.append({'acquisition_order':int(row.get('acquisition_order',i)),
            'source_row':int(row.get('source_row',i+1)),'sheet':str(row.get('source_sheet',row.get('sheet',''))),
            'id_cell':row.get('source_id_cell'),'x_cell':row.get('source_x_cell'),
            'id_numeric':finite(row.get('id')),'raw_id':str(row.get('raw_id_cell_value',row.get('id'))),
            'raw_x':str(row.get('raw_x_cell_value','')),'vd_numeric':finite(row.get('vd')),'vg_numeric':finite(row.get('vg')),
            'ig_numeric':finite(row.get('ig')),'ig_cell':row.get('source_ig_cell'),
            'point_flags':str(row.get('point_flags','')),'metric_eligible':bool(row.get('metric_eligible',True))})
    return records

def metric(name,value,unit,frame,indices,*,units_known=True,dimensionless=False,tier='exploratory',reason=None,**fields):
    number=finite(value)
    meaning,limitation=MEANINGS.get(name,(name,'측정 조건과 계산 근거를 함께 확인하세요.'))
    known=units_known or dimensionless
    return {'parameter':name,'value':number if known else None,'value_assuming_si':number if not known else None,
        'unit':unit,'availability':'held' if number is None else 'exploratory' if tier!='observation' or not known else 'observation',
        'tier':tier,'reason':reason or ('method_supported' if known else 'SI_units_assumed_not_confirmed'),
        'unit_basis':'declared_or_user_confirmed' if units_known else 'SI_assumption',
        'meaning':meaning,'limitation':limitation,'method_version':METHOD_VERSION,
        'source_points':support(frame,indices),'uncertainty':None,
        'uncertainty_reason':'no_independent_repeats_or_noise_model',**fields}

def sample(frame,axis,target,column='id'):
    if column not in frame:return {'value':None,'reason':'column_not_measured','indices':[]}
    x=frame[axis].to_numpy(float);y=frame[column].to_numpy(float)
    eligible=np.asarray(frame.get('metric_eligible',np.ones(len(frame),bool)),bool)&np.isfinite(y)
    exact=np.flatnonzero(x==target)
    if len(exact):
        if not eligible[exact].all():return {'value':None,'reason':'excluded_exact_point','indices':exact.tolist()}
        if len(set(y[exact]))>1:return {'value':None,'reason':'duplicate_voltage_different_currents','indices':exact.tolist()}
        return {'value':float(y[exact[0]]),'reason':'exact_original_point','indices':exact.tolist(),
                'evaluation_voltage':float(target),'weights':[1.0]}
    hits=[]
    for i in range(len(x)-1):
        contiguous=('acquisition_order' not in frame or frame.iloc[i+1]['acquisition_order']==frame.iloc[i]['acquisition_order']+1)
        same=('segment_id' not in frame or frame.iloc[i+1]['segment_id']==frame.iloc[i]['segment_id'])
        if min(x[i:i+2])<target<max(x[i:i+2]) and eligible[i:i+2].all() and same and contiguous:hits.append(i)
    if len(hits)!=1:return {'value':None,'reason':'no_unique_adjacent_support_no_extrapolation','indices':[]}
    i=hits[0];w=(target-x[i])/(x[i+1]-x[i])
    return {'value':float((1-w)*y[i]+w*y[i+1]),'reason':'adjacent_signed_linear_interpolation',
        'indices':[i,i+1],'evaluation_voltage':float(target),'bracket':[float(x[i]),float(x[i+1])],
        'distance_to_points':[float(abs(target-x[i])),float(abs(target-x[i+1]))], 'weights':[float(1-w),float(w)]}

def local_derivatives(frame,axis,widths,min_unique):
    """No interpolation, resampling, duplicate averaging, or cross-gap fits."""
    x=frame[axis].to_numpy(float);y=frame['id'].to_numpy(float)
    valid=np.asarray(frame.get('metric_eligible',np.ones(len(frame),bool)),bool)&np.isfinite(x)&np.isfinite(y)
    duplicates=np.zeros(len(x),bool)
    if len(x)>1:
        equal=np.diff(x)==0;duplicates[:-1]|=equal;duplicates[1:]|=equal
    valid &= ~duplicates
    segments=np.zeros(len(x),int)
    for i in range(1,len(x)):
        gap=('segment_id' in frame and frame.iloc[i]['segment_id']!=frame.iloc[i-1]['segment_id'])
        order=('acquisition_order' in frame and frame.iloc[i]['acquisition_order']!=frame.iloc[i-1]['acquisition_order']+1)
        segments[i]=segments[i-1]+int(gap or order or not valid[i] or not valid[i-1])
    outputs=[]
    for width in widths:
        derivative=np.full(len(x),np.nan);interior=np.zeros(len(x),bool);point_support={}
        for i in np.flatnonzero(valid):
            chosen=np.flatnonzero(valid&(segments==segments[i])&(np.abs(x-x[i])<=width/2+1e-10))
            if len(np.unique(x[chosen]))<min_unique:continue
            dx=x[chosen]-x[i];yscale=max(float(np.max(np.abs(y[chosen]))),np.finfo(float).tiny)
            coefficients=np.linalg.lstsq(np.column_stack([np.ones(len(dx)),dx,dx**2]),y[chosen]/yscale,rcond=None)[0]
            derivative[i]=coefficients[1]*yscale
            interior[i]=x[chosen].min()<=x[i]-width/2+1e-10 and x[chosen].max()>=x[i]+width/2-1e-10
            point_support[int(i)]=chosen.tolist()
        outputs.append({'width':float(width),'values':derivative,'internal':interior,'support':point_support})
    return outputs,duplicates

def ratio(numerator,denominator,floor=None):
    a,b=abs(numerator),abs(denominator)
    if floor is not None:
        if a<floor and b<floor:return None,{'reason':'both_below_known_floor','floor':floor}
        if b<floor:return None,{'reason':'denominator_below_known_floor','bound_type':'lower','bound_value':a/floor,'floor':floor}
        if a<floor:return None,{'reason':'numerator_below_known_floor','bound_type':'upper','bound_value':floor/b,'floor':floor}
    if b==0:return None,{'reason':'zero_denominator_no_epsilon'}
    result=a/b
    if not np.isfinite(result):return None,{'reason':'nonfinite_ratio'}
    return result,{'reason':'same_current_scale_ratio_floor_unassessed' if floor is None else 'above_recorded_floor',
                  'denominator_confidence':'not_assessed' if floor is None else 'above_recorded_floor'}

def output_metrics(frame,units_known,cfg):
    records=[];x=frame['vd'].to_numpy(float);y=frame['id'].to_numpy(float)
    valid=np.asarray(frame.get('metric_eligible',np.ones(len(frame),bool)),bool)
    floor=cfg.data['science']['detection_limit_a'] if units_known and cfg.data['science']['detection_limit_evidence'] else None
    base=dict(units_known=units_known)
    fits=[]
    for width in POLICY['g0_half_windows']:
        indices=np.flatnonzero(valid&(np.abs(x)<=width+1e-8))
        repeated=np.isin(x[indices],x[indices][np.array([np.sum(x[indices]==v)>1 for v in x[indices]],dtype=bool)])
        indices=indices[~repeated]
        window_indices=np.flatnonzero(np.abs(x)<=width+1e-8)
        contiguous=(len(window_indices)==len(indices) and (len(indices)<2 or np.all(np.diff(indices)==1)))
        if len(indices)>1 and 'acquisition_order' in frame:
            contiguous=contiguous and np.all(np.diff(frame.iloc[indices]['acquisition_order'])==1)
        if len(indices) and 'segment_id' in frame:
            contiguous=contiguous and frame.iloc[indices]['segment_id'].nunique()==1
        adequate=contiguous and len(np.unique(x[indices]))>=POLICY['g0_min_unique'] and np.any(x[indices]<0) and np.any(x[indices]>0)
        fields={'window':[-width,width],'definition':'I=offset+G0*V, free intercept, ordinary least squares',
                'distinct_points':len(np.unique(x[indices])),'engineering_default':True}
        if adequate:
            scale=max(float(np.max(np.abs(y[indices]))),np.finfo(float).tiny)
            matrix=np.column_stack([np.ones(len(indices)),x[indices]])
            c=np.linalg.lstsq(matrix,y[indices]/scale,rcond=None)[0]*scale
            residual=y[indices]-matrix@c
            fields.update(offset=float(c[0]),residual_rmse=float(np.sqrt(np.mean(residual**2))),
                          maximum_residual=float(np.max(np.abs(residual))))
            fits.append((width,float(c[0]),float(c[1])))
            records.append(metric('g0',c[1],'S',frame,indices,**base,**fields))
            records.append(metric('offset',c[0],'A',frame,indices,**base,**fields))
        else:records.append(metric('g0',None,'S',frame,indices,**base,reason='needs_5_distinct_two_polarity_points_in_declared_window',**fields))
    if fits:
        slopes=[f[2] for f in fits]
        for record in records:
            if record['parameter']=='g0':record['window_sensitivity_range']=max(slopes)-min(slopes) if len(slopes)>1 else None
    derivatives,duplicates=local_derivatives(frame,'vd',POLICY['gds_widths'],POLICY['gds_min_unique'])
    for u in POLICY['rr_abs_voltages']:
        pos,neg=sample(frame,'vd',u),sample(frame,'vd',-u)
        indices=sorted(set(pos['indices']+neg['indices']))
        fields={'evaluation_abs_voltage':u,'polarity_samples':{'positive':pos,'negative':neg},
                'definition':'abs(Id(+u))/abs(Id(-u)); no polarity swapping'}
        if pos['value'] is not None and neg['value'] is not None:
            rr,state=ratio(pos['value'],neg['value'],floor)
            records.append(metric('rr',rr,'1',frame,indices,dimensionless=True,**base,**fields,**state))
            records.append(metric('log10_rr',math.log10(rr) if rr and rr>0 else None,'decade',frame,indices,dimensionless=True,**base,**fields,**state))
            total=abs(pos['value'])+abs(neg['value'])
            records.append(metric('asymmetry',(abs(pos['value'])-abs(neg['value']))/total if total else None,'1',frame,indices,dimensionless=True,**base,**fields))
            records.append(metric('odd_current',(pos['value']-neg['value'])/2,'A',frame,indices,**base,**fields))
            records.append(metric('even_current',(pos['value']+neg['value'])/2,'A',frame,indices,**base,**fields))
        else:records.append(metric('rr',None,'1',frame,indices,dimensionless=True,**base,reason='missing_or_ambiguous_polarity_samples',**fields))
        for voltage,point in ((u,pos),(-u,neg)):
            records.append(metric('signed_current',point['value'],'A',frame,point['indices'],tier='observation',**base,evaluation_voltage=voltage,definition='signed exported Id at declared Vd',sample=point))
            records.append(metric('g_secant',point['value']/voltage if point['value'] is not None else None,'S',frame,point['indices'],**base,evaluation_voltage=voltage,definition='signed Id/Vd',sample=point))
            for derivative in derivatives:
                temporary=frame.copy();temporary['derivative']=derivative['values']
                sampled=sample(temporary,'vd',voltage,'derivative')
                used=sorted({j for i in sampled['indices'] for j in derivative['support'].get(i,[])})
                records.append(metric('gds',sampled['value'],'S',frame,used,**base,evaluation_voltage=voltage,
                    window_width=derivative['width'],definition='coefficient of dx from local quadratic in actual Vd coordinates',
                    reason=sampled['reason'] if sampled['value'] is not None else 'insufficient_local_derivative_support',
                    full_window_internal=bool(sampled['indices'] and all(derivative['internal'][i] for i in sampled['indices'])),sample=sampled))
            if fits and point['value'] is not None:
                width,offset,slope=fits[0]
                records.append(metric('nonlinearity',point['value']-offset-slope*voltage,'A',frame,point['indices'],**base,
                    evaluation_voltage=voltage,g0_window=[-width,width],definition='observed I minus offset+G0*V',sample=point))
    return records,derivatives,duplicates

def monotone_crossings(frame,target):
    x=frame['vg'].to_numpy(float);y=np.abs(frame['id'].to_numpy(float));valid=np.asarray(frame.get('metric_eligible',np.ones(len(frame),bool)),bool)
    hits=[]
    for i in range(len(x)-1):
        if not valid[i:i+2].all() or x[i]==x[i+1] or y[i]==y[i+1]:continue
        if 'segment_id' in frame and frame.iloc[i]['segment_id']!=frame.iloc[i+1]['segment_id']:continue
        if 'acquisition_order' in frame and frame.iloc[i+1]['acquisition_order']!=frame.iloc[i]['acquisition_order']+1:continue
        if (y[i]-target)*(y[i+1]-target)<=0:
            neighbourhood=np.arange(max(0,i-2),min(len(x),i+4))
            if len(neighbourhood)<5 or not valid[neighbourhood].all():continue
            if 'segment_id' in frame and frame.iloc[neighbourhood]['segment_id'].nunique()!=1:continue
            if 'acquisition_order' in frame and not np.all(np.diff(frame.iloc[neighbourhood]['acquisition_order'])==1):continue
            raw=frame.iloc[neighbourhood]['id'].to_numpy(float)
            changes=np.diff(y[neighbourhood])
            if np.any(raw[:-1]*raw[1:]<=0) or not (np.all(changes>=0) or np.all(changes<=0)):continue
            v=x[i]+(target-y[i])*(x[i+1]-x[i])/(y[i+1]-y[i]);hits.append((float(v),[i,i+1]))
    unique={round(v,12) for v,_ in hits}
    return hits[0] if len(unique)==1 else (None,sorted({i for _,indices in hits for i in indices}))

def half_width(x,g,index):
    height=abs(g[index])/2;left=None;right=None;used=[]
    for i in range(index-1,-1,-1):
        if not np.isfinite(g[i:i+2]).all():break
        a,b=abs(g[i]),abs(g[i+1])
        if (a-height)*(b-height)<=0 and a!=b:
            left=x[i]+(height-a)*(x[i+1]-x[i])/(b-a);used.extend([i,i+1]);break
    for i in range(index,len(x)-1):
        if not np.isfinite(g[i:i+2]).all():break
        a,b=abs(g[i]),abs(g[i+1])
        if (a-height)*(b-height)<=0 and a!=b:
            right=x[i]+(height-a)*(x[i+1]-x[i])/(b-a);used.extend([i,i+1]);break
    return abs(float(right-left)) if left is not None and right is not None else None,{'left_half_height_v':finite(left),'right_half_height_v':finite(right),'censored':left is None or right is None,'half_height_point_indices':used}

def transfer_metrics(frame,units_known,cfg):
    records=[];x=frame['vg'].to_numpy(float);y=frame['id'].to_numpy(float)
    valid=np.asarray(frame.get('metric_eligible',np.ones(len(frame),bool)),bool)
    indices=np.flatnonzero(valid&np.isfinite(y));base=dict(units_known=units_known)
    floor=cfg.data['science']['detection_limit_a'] if units_known and cfg.data['science']['detection_limit_evidence'] else None
    if len(indices):
        high=int(indices[np.argmax(np.abs(y[indices]))]);low=int(indices[np.argmin(np.abs(y[indices]))])
        crossing=bool(np.any(y[:-1]*y[1:]<=0));flags=['sign_crossing'] if crossing else []
        for name,index in [('current_max',high),('current_min',low)]:
            records.append(metric(name,abs(y[index]),'A',frame,[index],tier='observation',**base,
                evaluation_gate_voltage=float(x[index]),signed_current=float(y[index]),flags=flags,
                definition='argmax/argmin abs(Id) among eligible original points'))
        r,state=ratio(y[high],y[low],floor)
        records.append(metric('range_ratio',r,'1',frame,[high,low],dimensionless=True,**base,**state,flags=flags,
            definition='max(abs(Id))/min(abs(Id)); not Ion/Ioff',gate_voltage_at_max=float(x[high]),gate_voltage_at_min=float(x[low])))
    for lo,hi in POLICY['gate_pairs']:
        a,b=sample(frame,'vg',lo),sample(frame,'vg',hi);used=sorted(set(a['indices']+b['indices']))
        fields={'gate_pair':[lo,hi],'samples':{'lower':a,'upper':b},'original_gate_range':[float(x.min()),float(x.max())]}
        r,state=ratio(b['value'],a['value'],floor) if a['value'] is not None and b['value'] is not None else (None,{'reason':'declared_gate_pair_outside_coverage_or_ambiguous'})
        records.append(metric('gate_ratio',r,'1',frame,used,dimensionless=True,**base,**state,**fields,definition='abs(Id(upper gate))/abs(Id(lower gate))'))
        records.append(metric('gate_delta',b['value']-a['value'] if a['value'] is not None and b['value'] is not None else None,'A',frame,used,**base,**fields,definition='signed Id(upper gate)-Id(lower gate)'))
    derivatives,duplicates=local_derivatives(frame,'vg',POLICY['gm_widths'],POLICY['gm_min_unique'])
    peaks=[]
    for derivative in derivatives:
        candidates=np.flatnonzero(derivative['internal']&np.isfinite(derivative['values']))
        fields={'window_width':derivative['width'],'min_unique_points':POLICY['gm_min_unique'],
            'definition':'signed local quadratic derivative; max abs among full-window internal points',
            'excluded_endpoints':True,'supported_internal_points':len(candidates)}
        if not len(candidates):
            records.append(metric('gm_peak',None,'A/V',frame,[],**base,reason='no_internal_full_window_support',**fields));continue
        peak=int(candidates[np.argmax(np.abs(derivative['values'][candidates]))]);gm=float(derivative['values'][peak])
        local_peaks=[int(i) for i in candidates if i>0 and i<len(x)-1 and np.isfinite(derivative['values'][i-1:i+2]).all()
            and abs(derivative['values'][i])>=abs(derivative['values'][i-1]) and abs(derivative['values'][i])>abs(derivative['values'][i+1])]
        fields.update(evaluation_gate_voltage=float(x[peak]),signed_gm=gm,
            other_peak_positions=[float(x[i]) for i in local_peaks if i!=peak])
        records.append(metric('gm_peak',gm,'A/V',frame,derivative['support'][peak],**base,**fields))
        width,bounds=half_width(x,derivative['values'],peak)
        width_support=sorted(set(derivative['support'][peak])|{j for i in bounds['half_height_point_indices'] for j in derivative['support'].get(i,[])})
        records.append(metric('gm_fwhm',width,'V',frame,width_support,**base,
            reason='half_height_outside_support_censored' if width is None else 'two_half_height_crossings',**fields,**bounds))
        peaks.append((gm,float(x[peak])))
    for record in records:
        if record['parameter']=='gm_peak':
            record['peak_position_sensitivity_v']=float(np.ptp([p[1] for p in peaks])) if len(peaks)>=2 else None
            record['peak_amplitude_sensitivity']=float(np.ptp([abs(p[0]) for p in peaks])) if len(peaks)>=2 else None
    # Constant-current engineering criteria require known SI units; no arbitrary
    # per-curve relative criterion is promoted to a physical threshold.
    criteria=[1e-10,1e-9,1e-8]
    for criterion in criteria:
        v,used=monotone_crossings(frame,criterion) if units_known else (None,[])
        records.append(metric('vcc',v,'V',frame,used,**base,criterion_a=criterion,
            definition='unique abs(Id) crossing of declared constant current',
            reason='unique_operational_crossing_floor_unassessed' if v is not None else 'SI_current_criterion_unavailable_or_multiple_crossings'))
    # Contiguous log-slope windows are exploratory unless independent floor and
    # subthreshold/leakage evidence exist. Predeclared relative ranges are not SS.
    positive=valid&(np.abs(y)>0)
    runs=[];start=None;direction=0
    for i in range(len(y)):
        contiguous=i>0 and positive[i-1] and frame.iloc[i].get('segment_id',0)==frame.iloc[i-1].get('segment_id',0)
        change=np.sign(abs(y[i])-abs(y[i-1])) if i>0 else 0
        if not positive[i] or (start is not None and (not contiguous or y[i]*y[i-1]<=0 or (direction and change and change!=direction))):
            if start is not None:runs.append(np.arange(start,i));start=None
            direction=0
        if positive[i]:
            if start is None:start=i
            if change:direction=int(change)
    if start is not None:runs.append(np.arange(start,len(y)))
    supported=[r for r in runs if len(np.unique(x[r]))>=POLICY['ss_min_unique'] and np.ptp(np.log10(np.abs(y[r])))>=POLICY['ss_min_decades']]
    if supported:
        chosen=max(supported,key=lambda r:(np.ptp(np.log10(np.abs(y[r]))),len(r)))
        matrix=np.column_stack([np.ones(len(chosen)),x[chosen]])
        c=np.linalg.lstsq(matrix,np.log10(np.abs(y[chosen])),rcond=None)[0]
        residual=np.log10(np.abs(y[chosen]))-matrix@c
        records.append(metric('inverse_log_slope',1000/abs(c[1]) if c[1] else None,'mV/dec',frame,chosen,**base,
            reason='exploratory_monotone_log_slope_not_verified_subthreshold',gate_window=[float(x[chosen].min()),float(x[chosen].max())],
            log_current_span_decades=float(np.ptp(np.log10(np.abs(y[chosen])))),log_fit_rmse_decades=float(np.sqrt(np.mean(residual**2))),
            signed_slope_dec_per_v=float(c[1]),definition='1000/abs(least_squares slope of log10 abs(Id) versus Vg)',
            region_selection='longest_log_span contiguous same-sign monotone run; engineering exploratory rule',trusted_ss=False))
    else:records.append(metric('inverse_log_slope',None,'mV/dec',frame,[],**base,reason='no_contiguous_monotone_1decade_5point_window'))
    return records,derivatives,duplicates

def leakage_metrics(frame,ig_units_known,id_units_known):
    ratio_units_known=ig_units_known and id_units_known
    if 'ig' not in frame:return [metric(name,None,unit,frame,[],units_known=known,unit_dependencies=dependencies,reason='Ig_not_recorded')
        for name,unit,known,dependencies in [('leakage_max','A',ig_units_known,['ig']),('leakage_ratio','1',ratio_units_known,['ig','id'])]]
    ig=frame['ig'].to_numpy(float);ids=frame['id'].to_numpy(float)
    measured=np.flatnonzero(np.isfinite(ig));eligible=np.flatnonzero(np.isfinite(ig)&np.isfinite(ids)&(ids!=0)&np.asarray(frame.get('metric_eligible',np.ones(len(frame),bool)),bool))
    records=[]
    if len(measured):
        i=int(measured[np.argmax(np.abs(ig[measured]))])
        records.append(metric('leakage_max',abs(ig[i]),'A',frame,[i],units_known=ig_units_known,tier='observation',unit_dependencies=['ig'],definition='max abs measured Ig'))
    else:records.append(metric('leakage_max',None,'A',frame,[],units_known=ig_units_known,unit_dependencies=['ig'],reason='Ig_nonfinite_or_missing'))
    if len(eligible):
        values=np.abs(ig[eligible]/ids[eligible]);i=int(eligible[np.argmax(values)])
        records.append(metric('leakage_ratio',max(values),'1',frame,[i],units_known=ratio_units_known,dimensionless=False,unit_dependencies=['ig','id'],
            definition='max same-point abs(Ig)/abs(Id); both channels converted to SI or SI assumed explicitly',
            reason='same_point_ratio_current_channel_scale_must_match'))
    else:records.append(metric('leakage_ratio',None,'1',frame,[],units_known=ratio_units_known,unit_dependencies=['ig','id'],reason='no_eligible_nonzero_Id_and_measured_Ig_pair'))
    return records
