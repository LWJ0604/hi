"""Acquisition-order benchmarks. No invented repeats, pairs or physical labels."""
import copy
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.constants import Boltzmann,elementary_charge,epsilon_0

from .ingest import load_measurements
from .device_metadata import context_for,measurement_config,run_conditions,value
from .benchmark_models import fit_branch,fit_signed,model_current
from .benchmark_models import LOW2,HIGH2
from scipy.optimize import least_squares


def monotone_segments(frame,axis):
    """Split only proven voltage turns, dwells and source-row gaps; retain order."""
    if frame.empty:return []
    x=frame[axis].to_numpy(float);starts=[];start=0;direction=0
    for i in range(1,len(x)):
        delta=x[i]-x[i-1];step=int(np.sign(delta))
        gap=int(frame.iloc[i]['source_row'])-int(frame.iloc[i-1]['source_row'])!=1
        if gap or not step:
            if i>start:starts.append(frame.iloc[start:i].copy())
            start=i;direction=0
        elif direction and step!=direction:
            starts.append(frame.iloc[start:i].copy());start=i-1;direction=step
        else:direction=step
    starts.append(frame.iloc[start:].copy())
    return starts


def geometry(context,cfg):
    def mapping(item,path):
        if isinstance(item,dict):return item
        if item is not None:context['warnings'].append('조건 필드 '+path+'의 형식이 잘못되어 해당 계산을 보류합니다.')
        return {}
    data=context['data'];selected=data.get('active_electrode_pair')
    key=cfg.data['benchmark']['electrode_pair'] if selected is None else selected
    if isinstance(key,dict):key=key.get('value')
    if key is not None and (not isinstance(key,str) or not key.strip()):
        context['warnings'].append('계산 전극쌍은 이름 한 개를 입력하세요. 형식 오류로 이동도 계산을 보류합니다.');key=None
    pairs=mapping(data.get('electrode_pairs',{}),'electrode_pairs')
    pair=mapping(pairs.get(key,{}),'electrode_pairs.'+str(key)) if key else {}
    L=value(pair.get('L'),'um',confirmed=True,positive=True)
    W=value(pair.get('W'),'um',confirmed=True,positive=True)
    dielectric=mapping(mapping(data.get('structure',{}),'structure').get('gate_dielectric',{}),'structure.gate_dielectric')
    tox=value(dielectric.get('thickness'),'nm',confirmed=True,positive=True)
    er=value(dielectric.get('relative_permittivity'),'dimensionless',positive=True)
    temperature=value(mapping(data.get('run_conditions',{}),'run_conditions').get('temperature'),'degC')
    thermal=Boltzmann*(temperature+273.15)/elementary_charge if temperature is not None and temperature>-273.15 else None
    cox=epsilon_0*er/(tox*1e-9) if tox and er else None
    return {'electrode_pair':key,'L_um':L,'W_um':W,'tox_nm':tox,'epsr':er,
            'epsr_verification':dielectric.get('relative_permittivity',{}).get('verification') if isinstance(dielectric.get('relative_permittivity'),dict) else None,
            'Cox_F_m2':cox,'temperature_C':temperature,'thermal_voltage_V':thermal}


def load_source(source,cfg,read_path=None):
    context=context_for(source,cfg);local=measurement_config(context,cfg)
    from .metadata_review import load_override
    from .util import digest
    relative=Path(source).resolve().relative_to(cfg.paths['inbox']).as_posix()
    override=load_override(cfg,relative,digest(read_path or source));context['override']=override
    fields=override.get('fields',{})
    unit_check=fields.get('units_confirmed',{})
    if unit_check.get('value') is True and unit_check.get('status')=='confirmed' and not local.data['measurement_profile']['confirmed']:
        local.data['measurement_profile']={'voltage_unit':'V','current_unit':'A','confirmed':True,'source':'선택 파일의 사용자 단위 확인 이력'}
    records,ignored=load_measurements(read_path or source,local,{})
    tables=[];traces=[];last=None;block=0;gate_step=0.;number=0
    for record in records:
        axis=record['axis'];data=record['data']
        keys=[k for k in record['group_by'] if k in data]
        runs=data[keys].ne(data[keys].shift()).any(axis=1).cumsum() if keys else pd.Series(0,index=data.index)
        for _,run in data.groupby(runs,sort=False):
            for part in monotone_segments(run,axis):
                if part.empty:continue
                number+=1
                gate=float(part.vg.iloc[0]) if 'vg' in part and part.vg.nunique()==1 else None
                direction=int(np.sign(part[axis].iloc[-1]-part[axis].iloc[0]))
                source_sheet=record.get('source_sheet',record['name'])
                state=(source_sheet,axis,direction)
                reset=last is None or last['state']!=state or gate is None or last['gate'] is None
                if not reset:
                    delta=gate-last['gate']
                    if delta==0 or gate_step and delta*gate_step<0:reset=True
                    elif delta and not gate_step:gate_step=delta
                if reset:block+=1;gate_step=0.
                last={'state':state,'gate':gate}
                part=part.reset_index(drop=True);part['block']=block;part['trace_number']=number;part['axis']=axis
                part['source_filename']=Path(source).name;part['source_sheet']=source_sheet
                from .ingest import cell_address
                if 'ig' in part:
                    part['source_ig_cell']=[cell_address(record['column_mapping'].get('ig',{}).get('source_column'),int(row)) for row in part.source_row]
                tables.append(part)
                traces.append({'number':number,'block':block,'axis':axis,'direction':direction,
                    'gate':gate,'fixed_vd':float(part.vd.iloc[0]) if 'vd' in part and part.vd.nunique()==1 else None,
                    'frame':part,'record':record,'start':float(part[axis].iloc[0]),'end':float(part[axis].iloc[-1])})
    from .device_metadata import resolved_run_conditions
    role,conditions,condition_notices=resolved_run_conditions(source,context,cfg,fields)
    for key in ('measurement_time',):
        if key in fields:
            entry=fields[key]
            conditions[key]={'value':entry.get('value'),'verification':'user_confirmed' if entry.get('status')=='confirmed' else 'unconfirmed','source':'user_override','history':entry.get('history',[])}
    if 'sweep_delay_s' in fields:conditions['sweep_delay_user_s']=fields['sweep_delay_s'].get('value')
    return {'path':Path(source),'context':context,'cfg':local,'records':records,'ignored':ignored,
            'traces':traces,'points':pd.concat(tables,ignore_index=True) if tables else pd.DataFrame(),
            'role':role,'conditions':conditions,'condition_notices':condition_notices,'geometry':geometry(context,cfg)}


def _eligible(frame,record,cfg):
    valid=np.isfinite(frame.id.to_numpy(float))
    if 'compliance_flag' in frame:valid&=~frame.compliance_flag.fillna(False).to_numpy(bool)
    compliance=record.get('compliance_a',record.get('instrument_settings',{}).get('compliance_a',{})).get('vd')
    if compliance is not None:valid&=np.abs(frame.id.to_numpy(float))<cfg.data['science']['compliance_proximity_ratio']*compliance
    return valid


def output_benchmarks(loaded,cfg,*,fit=True):
    rr=[];parameters=[];residuals=[];signed=[];signed_points=[];offsets=[];sensitivity=[];profiles=[];holds=[]
    low,high=cfg.data['benchmark']['fit_range_v'];minimum=cfg.data['benchmark']['min_fit_points']
    thermal=loaded['geometry']['thermal_voltage_V']
    output=[t for t in loaded['traces'] if t['axis']=='vd']
    representatives={}
    for trace in output:
        candidates=representatives.setdefault(trace['block'],[]);candidates.append(trace)
    representatives={b:min(ts,key=lambda t:abs(t['gate']) if t['gate'] is not None else float('inf'))['number'] for b,ts in representatives.items()}
    for trace in output:
        d=trace['frame'];v=d.vd.to_numpy(float);ids=d.id.to_numpy(float);eligible=_eligible(d,trace['record'],cfg)
        mapping=trace['record']['column_mapping']
        units_known=all(mapping.get(key,{}).get('unit_status')=='confirmed' for key in ('vd','id'))
        common={'block':trace['block'],'trace_number':trace['number'],'Vg_V':trace['gate'],'source_filename':loaded['path'].name}
        for u in cfg.data['science']['rr_voltages_v']:
            plus=np.flatnonzero(np.isclose(v,u,atol=1e-8,rtol=0));minus=np.flatnonzero(np.isclose(v,-u,atol=1e-8,rtol=0))
            row={**common,'abs_Vd_V':u,'RR':None,'Iplus_A':None,'Iminus_A':None,'abs_Iplus_A':None,'abs_Iminus_A':None}
            if len(plus)!=1 or len(minus)!=1:
                row['reason']='평가 전압의 원본점이 없거나 중복되어 직접 비를 계산하지 않음'
            else:
                p,m=int(plus[0]),int(minus[0]);denominator=abs(ids[m])
                row.update(Iplus_A=float(ids[p]),Iminus_A=float(ids[m]),abs_Iplus_A=abs(float(ids[p])),abs_Iminus_A=denominator,
                    plus_source_row=int(d.iloc[p].source_row),minus_source_row=int(d.iloc[m].source_row),
                    plus_source_Id_cell=d.iloc[p].source_id_cell,minus_source_Id_cell=d.iloc[m].source_id_cell,
                    source_sheet=d.iloc[p].source_sheet)
                floor=cfg.data['science']['detection_limit_a'] if cfg.data['science']['detection_limit_evidence'] else None
                if not units_known:row['reason']='평가 전압 또는 전류 단위가 미확인으로 RR 계산 보류'
                elif not eligible[p] or not eligible[m]:row['reason']='해당 원본점의 측정 제한 표시로 비 계산 제외'
                elif denominator==0:row['reason']='분모 원시 전류가 0이므로 비를 정의하지 않음'
                elif floor is not None and denominator<floor:row['reason']='분모가 확인된 검출한계보다 작음'
                else:row.update(RR=abs(float(ids[p]))/denominator,reason='원본 전압점 직접 계산; 검출한계 신뢰도는 별도')
            rr.append(row)
        zero=np.flatnonzero(np.isclose(v,0,atol=1e-8,rtol=0));i0=float(ids[zero[0]]) if len(zero)==1 else None
        near=ids[np.abs(v)<=.2+1e-8]
        offsets.append({**common,'I0_A':i0,'near_zero_min_A':float(np.min(near)) if len(near) else None,'near_zero_max_A':float(np.max(near)) if len(near) else None})
        if not fit:continue
        if not units_known:
            holds.append({**common,'calculation':'RR and diode model','reason':'전압·전류 단위를 확인하면 RR과 다이오드 비교 계수를 계산할 수 있음'});continue
        for sign,label in ((1,'+Vd'),(-1,'−Vd')):
            mask=eligible&(sign*v>0)&(np.abs(v)>=low-1e-8)&(np.abs(v)<=high+1e-8)&(np.abs(ids)>0)
            selected=d.loc[mask].copy()
            if len(selected)<minimum or selected.vd.nunique()<minimum:
                holds.append({**common,'calculation':'polarity fit','polarity':label,'reason':'선택 구간의 서로 다른 유효 전압점이 '+str(minimum)+'개 미만'});continue
            x=np.abs(selected.vd.to_numpy());j=np.abs(selected.id.to_numpy())
            for model in ('Shockley','Shockley+Rs'):
                try:
                    result,pred=fit_branch(x,j,model)
                    result.update(common,polarity=label,window_low_V=low,window_high_V=high,
                        n_effective=result['a_V']/thermal if thermal else None,I0_A=i0,
                        abs_I0_over_min_fit_I=abs(i0)/float(j.min()) if i0 is not None else None)
                    parameters.append({k:v for k,v in result.items() if k not in ('params','multi_start_log_SSE')})
                    for row,estimate in zip(selected.itertuples(),pred):
                        residuals.append({**common,'model':model,'polarity':label,'Vd_V':row.vd,'abs_Vd_V':abs(row.vd),
                            'Id_raw_A':row.id,'abs_Id_A':abs(row.id),'predicted_abs_Id_A':estimate,'residual_A':estimate-abs(row.id),
                            'residual_ln':np.log(estimate/abs(row.id)),'relative_residual_pct':(estimate-abs(row.id))/abs(row.id)*100,
                            'source_row':row.source_row,'source_Id_cell':row.source_id_cell,'source_sheet':row.source_sheet})
                    if trace['number']==representatives[trace['block']]:
                        for a,b,subtract in ((max(.01,low-.2),high,False),(low+.2,high,False),(low,max(low+.1,high-.2),False),(low,high,True)):
                            if subtract and i0 is None:continue
                            selected2=d.loc[eligible&(sign*v>0)&(np.abs(v)>=a-1e-8)&(np.abs(v)<=b+1e-8)].copy()
                            current=np.abs(selected2.id.to_numpy()-(i0 if subtract else 0));good=current>0
                            if good.sum()<minimum or selected2.loc[good,'vd'].nunique()<minimum:continue
                            res,_=fit_branch(np.abs(selected2.vd.to_numpy()[good]),current[good],model)
                            sensitivity.append({**common,'polarity':label,'model':model,'window_low_V':a,'window_high_V':b,
                                'offset_subtracted':subtract,'a_V':res['a_V'],'n_effective':res['a_V']/thermal if thermal else None,
                                'Rs_ohm':res['Rs_ohm'],'Is_A':res['Is_A'],'RMSE_ln':res['RMSE_ln']})
                        if model=='Shockley+Rs':
                            for resistance in np.unique(np.r_[0,np.geomspace(.005,100,55)*1e6,result['Rs_ohm']]):
                                def residual_profile(p):
                                    return np.log(np.maximum(model_current(x,np.exp(p[0]),np.exp(p[1]),resistance),1e-300))-np.log(j)
                                fixed=least_squares(residual_profile,result['params'][:2],bounds=(LOW2,HIGH2),max_nfev=400)
                                profiles.append({**common,'polarity':label,'Rs_ohm':resistance,'a_V':float(np.exp(fixed.x[1])),
                                    'log_SSE':float(np.sum(fixed.fun**2)),'RMSE_ln':float(np.sqrt(np.mean(fixed.fun**2))),
                                    'optimizer_success':bool(fixed.success)})
                except (ValueError,RuntimeError,FloatingPointError,np.linalg.LinAlgError) as error:
                    holds.append({**common,'calculation':model,'polarity':label,'reason':'선택 구간에서 안정된 수치해를 구하지 못함','diagnostic':str(error)})
        if trace['number']==representatives[trace['block']]:
            selected=d.loc[eligible&(np.abs(v)>=low-1e-8)&(np.abs(v)<=high+1e-8)]
            for fixed in ([None,1.] if thermal else [None]):
                for model in ('Shockley','Shockley+Rs'):
                    try:
                        res,pred=fit_signed(selected.vd.to_numpy(),selected.id.to_numpy(),model,fixed,thermal)
                        signed.append({**common,**res,'window_low_V':low,'window_high_V':high})
                        span=np.ptp(selected.id.to_numpy())
                        for row,estimate in zip(selected.itertuples(),pred):
                            signed_points.append({**common,'model':model,'n_fixed':fixed,'Vd_V':row.vd,'Id_A':row.id,
                                'predicted_Id_A':estimate,'residual_A':estimate-row.id,'residual_span_pct':(estimate-row.id)/span*100 if span else None,
                                'source_row':row.source_row,'source_Id_cell':row.source_id_cell})
                    except (ValueError,RuntimeError,FloatingPointError,np.linalg.LinAlgError) as error:
                        holds.append({**common,'calculation':'single diode '+model,'reason':'양·음 평가점 또는 온도·수치해가 부족함','diagnostic':str(error)})
    return {'rr':pd.DataFrame(rr),'parameters':pd.DataFrame(parameters),'residuals':pd.DataFrame(residuals),
            'signed':pd.DataFrame(signed),'signed_points':pd.DataFrame(signed_points),'offsets':pd.DataFrame(offsets),
            'sensitivity':pd.DataFrame(sensitivity),'profiles':pd.DataFrame(profiles),'holds':holds,'representatives':representatives}


def transfer_benchmarks(loaded,cfg):
    frames=[];metrics=[];holds=[];geom=loaded['geometry']
    for trace in loaded['traces']:
        if trace['axis']!='vg':continue
        d=trace['frame'];x=d.vg.to_numpy(float);y=d.id.to_numpy(float)
        mapping=trace['record']['column_mapping']
        current_known=mapping.get('id',{}).get('unit_status')=='confirmed'
        derivative_known=current_known and mapping.get('vg',{}).get('unit_status')=='confirmed'
        eligible=_eligible(d,trace['record'],cfg);central=np.full(len(x),np.nan)
        if derivative_known and len(x)>=3 and np.all(np.diff(x)!=0):
            central=np.gradient(y,x,edge_order=2);central[[0,-1]]=np.nan
            for i in range(1,len(x)-1):
                if not eligible[i-1:i+2].all():central[i]=np.nan
        frame=pd.DataFrame({'trace_number':trace['number'],'Vg_V':x,'Id_A':y,'gm_central_A_V':central,
            'Ig_A':d.ig.to_numpy() if 'ig' in d else np.nan,'source_row':d.source_row,
            'source_id_cell':d.source_id_cell,'source_x_cell':d.source_x_cell,'source_sheet':d.source_sheet})
        for width in cfg.data['benchmark']['gm_windows_v']:
            derivative=[]
            for voltage in x:
                mask=np.abs(x-voltage)<=width/2+1e-8
                if not derivative_known or np.min(x)>voltage-width/2 or np.max(x)<voltage+width/2 or np.unique(x[mask]).size<5 or not eligible[mask].all():derivative.append(np.nan)
                else:derivative.append(np.linalg.lstsq(np.column_stack([np.ones(mask.sum()),x[mask]-voltage,(x[mask]-voltage)**2]),y[mask],rcond=None)[0][1])
            frame[f'gm_local_quadratic_{width:g}V_A_V']=derivative
        bias=trace['fixed_vd'];factor=geom['L_um']/geom['W_um']/geom['Cox_F_m2']/bias*1e4 if derivative_known and mapping.get('vd',{}).get('unit_status')=='confirmed' and geom['L_um'] and geom['W_um'] and geom['Cox_F_m2'] and bias else None
        if factor is not None:
            frame['mu_apparent_central_cm2_Vs']=central*factor
            for width in cfg.data['benchmark']['gm_windows_v']:frame[f'mu_apparent_{width:g}V_cm2_Vs']=frame[f'gm_local_quadratic_{width:g}V_A_V']*factor
        absids=np.abs(y);nonnull=absids[np.isfinite(absids)]
        record={'trace_number':trace['number'],'fixed_vd':bias,'start':trace['start'],'end':trace['end'],
            'min_abs_id':float(nonnull.min()) if len(nonnull) and current_known else None,'max_abs_id':float(nonnull.max()) if len(nonnull) and current_known else None,
            'current_range_ratio':float(nonnull.max()/nonnull.min()) if len(nonnull) and nonnull.min()>0 else None,
            'reference_mobility_input':copy.deepcopy(loaded['context']['data'].get('reference_inputs',{}).get('mobility_cm2_Vs',{})),
            'linear_region_confirmed':loaded['conditions'].get('linear_region_confirmed') is True,'mobility_factor':factor,'gm_peaks':[]}
        for width in cfg.data['benchmark']['gm_windows_v']:
            column=f'gm_local_quadratic_{width:g}V_A_V';finite=np.isfinite(frame[column].to_numpy())
            if finite.any():
                indices=np.flatnonzero(finite);i=int(indices[np.argmax(np.abs(frame[column].to_numpy()[finite]))])
                record['gm_peaks'].append({'width':width,'value_A_V':float(frame[column].iloc[i]),'Vg_V':float(x[i]),
                    'mu_apparent_cm2_Vs':float(frame[column].iloc[i]*factor) if factor is not None else None})
        if 'ig' in d and mapping.get('ig',{}).get('unit_status')=='confirmed':
            ig=d.ig.to_numpy(float);finite=np.isfinite(ig)
            record['max_abs_ig']=float(np.max(np.abs(ig[finite]))) if finite.any() else None
            ratio=finite&eligible&(absids>0)&current_known
            if ratio.any():
                indices=np.flatnonzero(ratio);i=int(indices[np.argmax(np.abs(ig[ratio]/y[ratio]))])
                record['leakage']={'ratio':float(abs(ig[i]/y[i])),'Id_A':float(y[i]),'Ig_A':float(ig[i]),'Vg_V':float(x[i]),'Vd_V':bias,'source_row':int(d.iloc[i].source_row)}
        if factor is None:holds.append({'calculation':'apparent mobility','trace_number':trace['number'],'reason':'선택 전극쌍의 확인된 L/W, 산화막/Cox 또는 고정 Vd가 부족함'})
        if not derivative_known:holds.append({'calculation':'gm','trace_number':trace['number'],'reason':'Gate 전압 또는 drain 전류 단위를 확인하면 gm을 계산할 수 있음'})
        if not record['gm_peaks']:holds.append({'calculation':'gm local','trace_number':trace['number'],'reason':'완전한 국소 창에 유효 전압점 5개 이상이 없음'})
        frames.append(frame);metrics.append(record)
    return {'frame':pd.concat(frames,ignore_index=True) if frames else pd.DataFrame(),'metrics':metrics,'holds':holds}
