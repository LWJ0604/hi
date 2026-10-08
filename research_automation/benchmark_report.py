"""Readable raw-data report; detailed numerical evidence stays in CSV/diagnostics."""
from datetime import datetime,timezone
import html
import json
from pathlib import Path
import shutil
from urllib.parse import quote

import markdown
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from matplotlib.ticker import FuncFormatter,NullFormatter,LogLocator
import numpy as np
import pandas as pd

from . import __version__,code_fingerprint
from .benchmark_data import load_source,output_benchmarks,transfer_benchmarks
from .device_metadata import value
from .plot_style import export_theme
from .util import digest

COLORS=['#216da9','#d06e24','#31855b','#8064aa']


def num(x,scale=1):
    try:return f'{float(x)*scale:.3g}' if x is not None and np.isfinite(float(x)) else '미확인'
    except (TypeError,ValueError):return '미확인'


def readable(item):
    if not isinstance(item,dict):return str(item) if item is not None else '미확인'
    result=item.get('value')
    if result is None:return '미확인'
    state={'user_confirmed':'사용자 확인','assumed':'가정','reported':'보고값',
        'user_reported':'사용자 보고','filename_reported':'파일명 기록',
        'unconfirmed':'미확인','reported_unconfirmed':'적용 미확인',
        'naming_rule':'이름 규칙 자동 입력 · 사람의 실측 확인 아님'}.get(item.get('verification'),'출처 확인 필요')
    evidence=item.get('evidence',{})
    source=('날짜 폴더 '+str(evidence.get('folder_name','')) if item.get('source')=='folder_name' else
            'Excel 파일명 '+str(evidence.get('filename','')) if item.get('verification')=='naming_rule' else
            str(item.get('source') or '출처 미기록'))
    return html.escape(str(result)+(' '+str(item['unit']) if item.get('unit') else '')+' · '+state+' · '+source)


def table(headers,rows):
    esc=lambda x:html.escape(str(x)).replace('|','&#124;').replace('\n',' ')
    return '\n'.join(['| '+' | '.join(map(esc,headers))+' |','|'+'|'.join(['---']*len(headers))+'|']+
        ['| '+' | '.join(map(esc,row))+' |' for row in rows])


def clean_json(item):
    if isinstance(item,dict):return {str(k):clean_json(v) for k,v in item.items()}
    if isinstance(item,(tuple,list)):return [clean_json(v) for v in item]
    if isinstance(item,np.generic):return clean_json(item.item())
    if isinstance(item,float) and not np.isfinite(item):return None
    if isinstance(item,Path):return str(item)
    return item


def write_diagnostic(path,item):
    path.write_text(json.dumps(clean_json(item),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def savefig(out,name,fig):
    for ax in fig.axes:
        if ax.get_yscale()=='log':
            lower,upper=ax.get_ylim()
            if 0<lower<upper and upper/lower<10:
                ax.yaxis.set_major_locator(LogLocator(base=10,subs=(1.,2.,3.,4.,5.,6.,7.,8.,9.)))
            ax.yaxis.set_major_formatter(FuncFormatter(lambda x,pos:f'{x:g}'))
            ax.yaxis.set_minor_formatter(NullFormatter())
    for label in fig.findobj(match=matplotlib.text.Text):label.set_text(label.get_text().replace('−','-'))
    try:
        fig.savefig(out/'images'/(name+'.png'),dpi=160,bbox_inches='tight',facecolor='white')
        fig.savefig(out/'images'/(name+'.svg'),bbox_inches='tight',facecolor='white')
    finally:plt.close(fig)
    return 'images/'+name+'.png'


def panels(count,rows=1):
    # Acquisition blocks never share a data line. Large acquisitions paginate.
    fig,axes=plt.subplots(rows,count,figsize=(max(7,5.7*count),4.4*rows),squeeze=False,layout='constrained')
    return fig,axes


@export_theme
def figures(loaded,output,transfer,out,prefix):
    images={};traces=loaded['traces'];rr=output['rr'];p=output['parameters'];res=output['residuals']
    blocks=list(dict.fromkeys(t['block'] for t in traces if t['axis']=='vd'))
    for page in range(0,len(blocks),3):
        bs=blocks[page:page+3];suffix=f'-{page//3+1}' if len(blocks)>3 else ''
        for kind in ('RR','Ipm','output_linear','output_log'):
            fig,axes=panels(len(bs))
            for b,ax in zip(bs,axes[0]):
                ts=[t for t in traces if t['block']==b and t['axis']=='vd']
                if kind in ('RR','Ipm') and not rr.empty:
                    for k,(u,d) in enumerate(rr[rr.block==b].groupby('abs_Vd_V',sort=False)):
                        x=d.Vg_V if d.Vg_V.notna().all() else d.trace_number
                        if kind=='RR':ax.plot(x,d.RR,'o-',ms=3,color=COLORS[k%4],label=f'|Vd| = {u:g} V')
                        else:
                            ax.plot(x,d.abs_Iplus_A*1e6,color=COLORS[k%4],label=f'+{u:g} V')
                            ax.plot(x,d.abs_Iminus_A*1e6,'--',color=COLORS[k%4],label=f'-{u:g} V')
                    ax.set_xlabel('Vg (V)' if rr[rr.block==b].Vg_V.notna().all() else '기록 순서')
                    if kind=='RR':ax.axhline(1,color='#555',ls='--',lw=1,label='RR = 1')
                    if kind=='RR' or any(np.any(t['frame'].id!=0) for t in ts):ax.set_yscale('log')
                    ax.set_ylabel('RR = |Id(+Vd)| / |Id(-Vd)|' if kind=='RR' else '|Id| (µA)')
                    ax.legend(fontsize=8,ncol=2)
                else:
                    gates=[t['gate'] for t in ts if t['gate'] is not None]
                    norm=Normalize(min(gates),max(gates)) if gates else None
                    for t in ts:
                        d=t['frame'];y=(np.abs(d.id) if kind=='output_log' else d.id)*1e6
                        ax.plot(d.vd,y,color=plt.get_cmap('viridis')(norm(t['gate'])) if norm and t['gate'] is not None else '#216da9',lw=1,alpha=.8)
                    ax.set(xlabel='Vd (V)',ylabel='|Id| (µA)' if kind=='output_log' else 'Id (µA)')
                    if kind=='output_log' and any(np.any(t['frame'].id!=0) for t in ts):ax.set_yscale('log')
                    if norm:fig.colorbar(plt.cm.ScalarMappable(norm=norm,cmap='viridis'),ax=ax,label='Vg (V)')
                ax.set_title(f'출력 블록 {b} · {len(ts)}개 기록 구간')
            images.setdefault(kind,[]).append(savefig(out,prefix+'-'+kind+suffix,fig))
        reps=output['representatives'];selected=[t for t in traces if reps.get(t['block'])==t['number'] and t['block'] in bs]
        if not p.empty:
            for kind in ('polarity_overlay','polarity_residual'):
                fig,axes=panels(2,len(bs))
                for i,t in enumerate(selected):
                    for col,label in enumerate(('+Vd','−Vd')):
                        ax=axes[i,col];d=res[(res.trace_number==t['number'])&(res.polarity==label)]
                        if kind=='polarity_overlay':
                            raw=t['frame'];raw=raw[raw.vd*(1 if col==0 else -1)>0]
                            ax.plot(abs(raw.vd),abs(raw.id)*1e6,'o',color='#333',ms=3,label='원시 |Id|')
                        for k,(model,q) in enumerate(d.groupby('model',sort=False)):
                            ax.plot(q.abs_Vd_V,q.relative_residual_pct if kind=='polarity_residual' else q.predicted_abs_Id_A*1e6,color=COLORS[k%4],lw=1.7,label=model)
                        ax.set(xlabel='|Vd| (V)',ylabel='(모델-원시)/|원시| (%)' if kind=='polarity_residual' else '|Id| (µA)',title=f'블록 {t["block"]} · Vg {num(t["gate"])} V · {label}')
                        if kind=='polarity_residual':ax.axhline(0,color='#555',lw=1)
                        elif not d.empty:ax.set_yscale('log')
                        ax.legend(fontsize=8)
                images.setdefault(kind,[]).append(savefig(out,prefix+'-'+kind+suffix,fig))
            fig,axes=panels(len(bs),2)
            for b,ax1,ax2 in zip(bs,axes[0],axes[1]):
                for (model,polarity),d in p[p.block==b].groupby(['model','polarity'],sort=False):
                    x=d.Vg_V if d.Vg_V.notna().all() else d.trace_number
                    ax1.plot(x,d.n_effective if p.n_effective.notna().any() else d.a_V,label=polarity+' '+model,lw=1.5)
                    if model=='Shockley+Rs':ax2.plot(x,d.Rs_ohm/1e6,label=polarity,lw=1.5)
                ax1.set(xlabel='Vg (V)' if p.Vg_V.notna().all() else '기록 순서',ylabel='유효 n · 입력 온도' if p.n_effective.notna().any() else '유효 a (V)',title=f'출력 블록 {b}');ax1.legend(fontsize=8)
                ax2.set(xlabel=ax1.get_xlabel(),ylabel='유효 Rs (MΩ)');ax2.legend(fontsize=8)
            images.setdefault('coefficients',[]).append(savefig(out,prefix+'-coefficients'+suffix,fig))
        signed=output['signed_points']
        if not signed.empty:
            fig,axes=panels(len(bs),2)
            for t,ax,r_ax in zip(selected,axes[0],axes[1]):
                raw=t['frame'];ax.plot(raw.vd,raw.id*1e6,'o',ms=3,color='#333',label='원시 Id')
                for model,d in signed[(signed.trace_number==t['number'])&signed.n_fixed.isna()].groupby('model',sort=False):
                    # Draw only the evaluated points; no bridge over excluded central span.
                    for sign in (-1,1):
                        q=d[d.Vd_V*sign>0];ax.plot(q.Vd_V,q.predicted_Id_A*1e6,lw=1.7,label=model if sign==1 else None)
                    r_ax.plot(d.Vd_V,d.residual_span_pct,'o',ms=3,label=model)
                ax.set(xlabel='Vd (V)',ylabel='Id (µA)',title=f'블록 {t["block"]} · Vg {num(t["gate"])} V');ax.legend(fontsize=8)
                r_ax.set(xlabel='Vd (V)',ylabel='잔차/원시 전류 span (%)');r_ax.axhline(0,color='#555',lw=1)
            images.setdefault('single_diode',[]).append(savefig(out,prefix+'-single-diode'+suffix,fig))
        prof=output['profiles']
        if not prof.empty:
            fig,axes=panels(len(bs))
            for b,ax in zip(bs,axes[0]):
                for label,d in prof[(prof.block==b)&(prof.Rs_ohm<=1.5e6)].groupby('polarity',sort=False):ax.plot(d.Rs_ohm/1e6,d.RMSE_ln,label=label,lw=1.7)
                ax.set(xlabel='고정 Rs (MΩ)',ylabel='RMSE ln(|Id|)',title=f'출력 블록 {b}',yscale='log');ax.legend()
            images.setdefault('profile',[]).append(savefig(out,prefix+'-Rs-profile'+suffix,fig))
    vg=[t for t in traces if t['axis']=='vg']
    for i,t in enumerate(vg):
        d=t['frame'];suffix=f'-{i+1}'
        for log in (False,True):
            fig,ax=plt.subplots(figsize=(9.5,4.5),layout='constrained');ax.plot(d.vg,(abs(d.id) if log else d.id)*1e6,color=COLORS[0],lw=1.8)
            ax.set(xlabel='Vg (V)',ylabel='|Id| (µA)' if log else 'Id (µA)',title=f'Id-Vg · Vd {num(t["fixed_vd"])} V · {num(t["start"])} → {num(t["end"])} V')
            if log and np.any(d.id!=0):ax.set_yscale('log')
            images.setdefault('transfer',[]).append(savefig(out,prefix+'-IdVg-'+('log' if log else 'linear')+suffix,fig))
        g=transfer['frame'];g=g[g.trace_number==t['number']]
        fig,axes=plt.subplots(2,1,figsize=(9.5,7),sharex=True,layout='constrained')
        for col in g:
            if col.startswith('gm_'):axes[0].plot(g.Vg_V,g[col]*1e9,label='중앙차분' if col=='gm_central_A_V' else '국소 '+col.split('_')[3]+' 창',lw=1.4)
        axes[0].set(ylabel='gm (nS)',title='gm = dId/dVg · 원시 Id에서 계산');axes[0].legend(fontsize=8)
        axes[1].plot(g.Vg_V,g.Ig_A*1e12,color=COLORS[1],lw=1.5);axes[1].set(xlabel='Vg (V)',ylabel='Ig (pA)',title='원시 gate current' if g.Ig_A.notna().any() else 'Ig 기록 없음')
        images.setdefault('gm',[]).append(savefig(out,prefix+'-gm-Ig'+suffix,fig))
        cols=[c for c in g if c.startswith('mu_apparent_')]
        if cols:
            fig,ax=plt.subplots(figsize=(9.5,4.5),layout='constrained')
            for col in cols:ax.plot(g.Vg_V,g[col],label='중앙차분' if 'central' in col else col.split('_')[2]+' 창',lw=1.4)
            ax.set(xlabel='Vg (V)',ylabel='선형식 참고값 (cm²/V·s)',title='µ = gm L / (W Cox Vd) · 적용 구간 확인 필요');ax.legend(fontsize=8)
            images.setdefault('mobility',[]).append(savefig(out,prefix+'-mobility'+suffix,fig))
    return images


def image_lines(images,key):
    return ['![측정 그래프]('+path+')\n' for path in images.get(key,[])]


def source_section(loaded,output,transfer,images,prefix):
    c=loaded['context'];data=c['data'];geom=loaded['geometry'];cond=loaded['conditions'];name=loaded['path'].name
    rr=output['rr'];p=output['parameters'];reps=list(output['representatives'].values());rows=[]
    lines=['## '+html.escape(name)+'\n']
    if not rr.empty:
        lines+=['### RR(Vg)\n','**정의:** RR = |Id(+u)| / |Id(−u)|. 평가 |Vd|=u를 범례에 표시하며 분자·분모 방향은 고정합니다. 원본의 정확한 전압점과 셀 주소를 사용합니다.\n']+image_lines(images,'RR')
        for (b,u),d in rr.groupby(['block','abs_Vd_V'],sort=False):
            at0=d[np.isclose(pd.to_numeric(d.Vg_V,errors='coerce').to_numpy(dtype=float),0,atol=1e-8)]
            rows.append([b,num(u),num(d.RR.min()),num(d.RR.max()),num(at0.RR.iloc[0]) if len(at0)==1 else '해당 점 없음'])
        lines+=[table(['출력 블록','|Vd| (V)','RR 최소','RR 최대','Vg=0 V RR'],rows)+'\n',
            '[RR와 원본 대응 전류](csv/'+prefix+'-RR.csv)\n','### 대응 Iplus / Iminus\n']+image_lines(images,'Ipm')
        lines+=['실선은 |Id(+u)|, 점선은 |Id(−u)|입니다. 원시 전류 부호와 측정 순서는 CSV에 보존합니다. 출력 블록은 기록된 전압 순서로만 나눴으며 독립 반복이나 물리적 forward/reverse로 확정하지 않습니다. 검출한계 근거가 없으면 작은 분모의 신뢰도를 확정할 수 없습니다.\n']
    lines+=['### 소자와 측정조건\n',table(['항목','값과 출처'],[
        ['소자',readable(data.get('device_name'))],['실제 측정일',readable(cond.get('measurement_date'))],
        ['실제 측정시간',readable(cond.get('measurement_time'))],['광 조건',readable(cond.get('illumination'))],
        ['선택 전극쌍',geom['electrode_pair'] or '미선택'],['확인된 L / W (µm)',num(geom['L_um'])+' / '+num(geom['W_um'])],
        ['산화막 두께 (nm)',num(geom['tox_nm'])],['유전율 εr',num(geom['epsr'])+(' · 가정' if geom['epsr_verification']=='assumed' else ' · 입력값')],
        ['온도 (°C)',num(geom['temperature_C'])],['전극',str(data.get('structure',{}).get('electrodes',{}).get('metal','미확인'))]])+'\n']
    for notice in loaded.get('condition_notices',[]):
        lines+=['**조건 확인:** '+html.escape(notice)+'\n']
    condition_rows=[]
    for b in dict.fromkeys(t['block'] for t in loaded['traces']):
        ts=[t for t in loaded['traces'] if t['block']==b];first,last=ts[0],ts[-1]
        fixed='Vg '+num(first['gate'])+' → '+num(last['gate']) if first['axis']=='vd' else 'Vd '+num(first['fixed_vd'])
        condition_rows.append([b,'Vd' if first['axis']=='vd' else 'Vg',num(first['start'])+' → '+num(first['end']),fixed,len(ts),sum(len(t['frame']) for t in ts)])
    lines+=[table(['블록','가변 전압','기록 순서 (V)','고정 전압 조건 (V)','기록 구간 수','원시 점 수'],condition_rows[:12])+'\n',
        '[전체 구간별 조건·전압 방향](csv/'+prefix+'-segments.csv)\n']
    unit_rows=[]
    for record in loaded['records']:
        for key,mapping in record.get('column_mapping',{}).items():
            if key not in ('vd','vg','id','ig'):continue
            unit_rows.append(({'vd':'Drain 전압 Vd','vg':'Gate 전압 Vg','id':'Drain 전류 Id','ig':'Gate 전류 Ig'}[key],mapping.get('declared_unit') or (loaded['cfg'].data['measurement_profile'].get('voltage_unit' if key in ('vd','vg') else 'current_unit') if mapping.get('unit_source')=='user_profile' else None) or ('V' if key in ('vd','vg') else 'A'),
                '파일 헤더' if mapping.get('unit_source')=='file_header' else '장비 고정 설정값' if mapping.get('unit_source')=='instrument_program_V' else '사용자 단위 프로필' if mapping.get('unit_source')=='user_profile' else '단위 미확인 · SI 가정',
                '파일 단위 우선 · 사용자 기본값과 충돌' if mapping.get('unit_conflict') else ''))
    lines+=[table(['열','환산 전 단위','출처','확인 사항'],list(dict.fromkeys(unit_rows)))+'\n',
        '장비 시각은 참고 기록이며 실제 측정일을 대신하지 않습니다. 서로 다른 원래 gate 범위를 잘라 같은 stress 조건으로 취급하지 않습니다.\n']
    if any(mapping.get('unit_status')!='confirmed' for record in loaded['records'] for key,mapping in record.get('column_mapping',{}).items() if key in ('vd','vg','id','ig')):
        lines+=['**단위 확인 대기:** 단위가 없는 열의 원시 그래프 척도는 SI 가정입니다. 단위에 의존하는 정량값은 계산 보류 이유를 표시합니다.\n']
    settings=loaded['records'][0].get('instrument_settings',{}) if loaded['records'] else {}
    user_delay=cond.get('sweep_delay_user_s');setting_delay=cond.get('sweep_delay_settings_s',settings.get('sweep_delay_s'))
    if user_delay is not None or setting_delay is not None:
        conflict=user_delay is not None and setting_delay is not None and num(user_delay)!=num(setting_delay)
        lines+=['Sweep delay: 사용자 '+num(user_delay)+' s / 장비 설정 '+num(setting_delay)+' s'+(' · 불일치 유지' if conflict else '')+'. Hold: '+num(cond.get('hold_time_settings_s',settings.get('hold_time_s')))+' s.\n']
    if settings:
        compliance=settings.get('compliance_a',{});terminals=settings.get('terminals',{})
        lines+=['Compliance: drain '+num(compliance.get('vd'))+' A / gate '+num(compliance.get('vg'))+' A. 전압 기록: '+', '.join(axis+' '+('설정 전압' if str(info.get('measure v','')).casefold()=='programmed' else '장비 기록 · 구분 확인 필요') for axis,info in terminals.items())+'.\n']
    lines+=['[원시 추출점과 셀 근거](csv/'+prefix+'-raw.csv) · [선택 원본 사본](inputs/'+quote(prefix+loaded['path'].suffix.lower())+')\n']
    if images.get('output_linear'):
        lines+=['### 원시 Id–Vd\n']+image_lines(images,'output_linear')+image_lines(images,'output_log')
        lines+=['선형은 부호 있는 Id, 로그는 |Id|입니다. 각 기록 구간과 gate 조건을 분리하고 원점 부근 값도 보존했습니다.\n']
    if transfer['metrics']:
        lines+=['### 원시 Id–Vg와 기초 지표\n']+image_lines(images,'transfer')
        for m in transfer['metrics']:
            metric_rows=[['측정 범위 |Id| 최소 / 최대 (µA)',num(m['min_abs_id'],1e6)+' / '+num(m['max_abs_id'],1e6)],
                ['측정 범위 전류비',num(m['current_range_ratio'])+' = max |Id| / min |Id|'],
                ['최대 |Ig| (pA)',num(m.get('max_abs_ig'),1e12)],['최대 |Ig| / |Id|',num(m.get('leakage',{}).get('ratio'))]]
            for peak in m['gm_peaks']:metric_rows.append(['gm, 국소 '+num(peak['width'])+' V 창 (nS)',num(peak['value_A_V'],1e9)+' @ Vg '+num(peak['Vg_V'])+' V'])
            lines+=[table(['지표','計算값·정의'.replace('計算','계산')],metric_rows)+'\n']
        lines+=image_lines(images,'gm')+['gm은 실제 전압 간격의 중앙차분과 국소 2차식 미분입니다. 국소 창은 최소 5점과 완전한 창을 요구하며 양 끝점은 해당 계산을 보류합니다. 장비 GM 열을 재사용하지 않습니다.\n']+image_lines(images,'mobility')
        if images.get('mobility'):
            lines+=['**선형식 적용 참고값:** µ = gm L/(W Cox Vd), Cox = ε₀εr/tox = '+num(geom['Cox_F_m2'],1e5)+' nF/cm². '+('선형영역 미확인 상태이며 물리적 이동도를 확정하지 않습니다.' if not all(m['linear_region_confirmed'] for m in transfer['metrics']) else '입력에서 선형영역 적용을 확인한 조건입니다.')+'\n']
            for m in transfer['metrics']:
                lines+=['국소 창별 계산 이동도: '+', '.join(num(k['width'])+' V 창 '+num(k['mu_apparent_cm2_Vs'])+' cm²/V·s' for k in m['gm_peaks'])+'. 사용자 참고 입력 이동도: '+readable(m['reference_mobility_input'])+'.\n']
        lines+=['Vth와 SS는 적용 구간을 지정하지 않아 추출하지 않았습니다. [gm·이동도 계산 CSV](csv/'+prefix+'-gm.csv)\n']
    if not output['signed'].empty:
        low,high=loaded['cfg'].data['benchmark']['fit_range_v']
        lines+=['### 단일 다이오드식과 전체 극성 비교\n',
            'I = s Is {exp(s Vd/a) − 1}, a=n kT/q. Rs 포함식은 s Vd = a ln(1+s I/Is)+s I Rs입니다. s=±1 중 같은 평가점의 부호 있는 전류 잔차 제곱합이 작은 방향을 표시합니다. 양·음 극성에 하나의 계수를 공유하는 비교식입니다.\n',
            '각 출력 블록에서 Vg가 0 V에 가장 가까운 구간의 양·음 |Vd|='+num(low)+'~'+num(high)+' V 원본점을 평가했습니다. 전류 offset은 0 고정이며 compliance 제외 규칙은 극성별 근사와 같습니다. 입력 온도는 '+num(geom['temperature_C'])+' °C이며, 온도가 없으면 n=1 고정 비교와 유효 n 변환만 보류합니다.\n']+image_lines(images,'single_diode')
        rows=[[r.block,num(r.Vg_V),r.model,'자유' if pd.isna(r.n_fixed) else num(r.n_fixed)+' 고정',f'{r.orientation:+g}',num(r.n_effective),num(r.Rs_ohm,1e-6),num(r.NRMSE_span_pct),num(r.RMSE_negative_A,1e9),num(r.RMSE_positive_A,1e9)] for r in output['signed'].itertuples()]
        lines+=[table(['블록','Vg (V)','모델','n 조건','s','유효 n','Rs (MΩ)','NRMSE (%)','−Vd RMSE (nA)','+Vd RMSE (nA)'],rows)+'\n',
            'NRMSE는 평가점의 원시 전류 span으로 정규화합니다. 중앙 제외 구간을 모델 선으로 연결하지 않았습니다. n=1·Rs=0 비교에서는 Is를 선형 최소제곱으로 직접 계산합니다. [전체 수치](csv/'+prefix+'-single-diode.csv) · [점별 잔차](csv/'+prefix+'-single-residuals.csv)\n']
    if not p.empty:
        low,high=loaded['cfg'].data['benchmark']['fit_range_v']
        lines+=['### 극성별 |Id| 근사: Shockley / Shockley+Rs\n',
            '**기본식:** j = Is {exp(u/a) − 1}. **Rs 포함식:** u = a ln(1+j/Is)+j Rs, u=|Vd|, j=|Id|. 각 극성·gate·블록을 독립적으로 계산합니다.\n',
            '평가 구간 '+num(low)+'~'+num(high)+' V, ln(j모델)−ln(j원시)의 제곱합을 최소화합니다. Is·a는 자유 변수이며 Rs는 기본식에서 0 고정, 포함식에서 자유입니다. 전류 offset은 0 고정이며 주 결과의 기준선을 빼지 않습니다. Is 범위 10⁻¹⁸~10⁻² A, a 0.001~100 V, Rs 0~10¹¹ Ω입니다. 유한하고 |Id|>0인 점을 사용하며 기록된 compliance flag와 설정 drain compliance의 '+num(loaded['cfg'].data['science']['compliance_proximity_ratio']*100)+'% 이상 점은 제외합니다.\n']+image_lines(images,'polarity_overlay')+image_lines(images,'polarity_residual')
        rows=[]
        for r in p[p.trace_number.isin(reps)].itertuples():
            rows.append([r.block,num(r.Vg_V),r.polarity,r.model,r.n_points,num(r.a_V),num(r.n_effective),num(r.Is_A,1e9),num(r.Rs_ohm,1e-6),num(r.RMSE_ln),num(r.NRMSE_span_pct),'해당 없음' if r.model=='Shockley' else num(r.corr_a_Rs_local)])
        lines+=[table(['블록','Vg (V)','극성','모델','점 수','a (V)','유효 n','Is (nA)','Rs (MΩ)','RMSE ln','NRMSE (%)','a–Rs 상관'],rows)+'\n',
            '대표 구간은 각 블록에서 Vg가 0 V에 가장 가까운 기록입니다. 잔차 부호는 모델−원시이며 상대 잔차는 (모델−원시)/|원시|×100입니다. n은 입력 온도가 있을 때만 a/(kT/q)로 계산합니다. Rs·a·Is는 유효 모델 계수이며 고유 접촉저항·장벽·전류 경로를 증명하지 않습니다.\n']+image_lines(images,'coefficients')
        lines+=['[전체 '+str(len(p))+'개 피팅 계수](csv/'+prefix+'-fit-parameters.csv) · [원본점·점별 잔차](csv/'+prefix+'-fit-residuals.csv)\n','### 구간·offset 민감도와 계수 안정성\n']
        warns=[]
        if (p.corr_a_Rs_local.abs()>.95).any():warns.append('a–Rs 상관이 강한 해가 있습니다. 잔차가 작아도 계수의 식별성이 낮을 수 있습니다.')
        if (pd.to_numeric(p.n_effective,errors='coerce')>10).any():warns.append('큰 유효 n이 포함돼 있습니다. 피팅 품질과 단순 비교식의 적용 한계를 함께 확인하세요.')
        if p.near_parameter_bound.any():warns.append('탐색 경계에 가까운 계수가 있습니다.')
        if not p.optimizer_success.all():warns.append('수치 최적화가 종료 조건을 충족하지 못한 결과가 있어 해당 계수를 확정할 수 없습니다.')
        lines+=[' '.join(warns)+' 국소 Jacobian 상관은 측정 노이즈나 독립 반복으로 검증된 신뢰구간이 아닙니다.\n']
        sensitivity=output['sensitivity'];rows=[]
        for r in p[(p.model=='Shockley+Rs')&p.trace_number.isin(reps)].itertuples():
            q=sensitivity[(sensitivity.trace_number==r.trace_number)&(sensitivity.polarity==r.polarity)&(sensitivity.model==r.model)]
            rows.append([r.block,num(r.Vg_V),r.polarity,num(r.n_effective),num(min(q.a_V.min(),r.a_V))+'~'+num(max(q.a_V.max(),r.a_V)),num(min(q.Rs_ohm.min(),r.Rs_ohm),1e-6)+'~'+num(max(q.Rs_ohm.max(),r.Rs_ohm),1e-6)])
        lines+=[table(['블록','Vg (V)','극성','기준 유효 n','구간·offset a 범위 (V)','Rs 범위 (MΩ)'],rows)+'\n']+image_lines(images,'profile')
        lines+=['대표 구간의 평가 하한·상한과 I(0) 제거를 각각 바꿔 계산했습니다. Rs 고정 프로파일은 Is·a를 다시 맞춘 수치 오차이며 신뢰구간으로 변환하지 않습니다. [구간·offset 민감도](csv/'+prefix+'-sensitivity.csv) · [Rs 프로파일](csv/'+prefix+'-Rs-profile.csv) · [원점 offset](csv/'+prefix+'-offsets.csv)\n']
    holds=output['holds']+transfer['holds']
    if holds or c['warnings']:
        reasons=list(dict.fromkeys([h['reason'] for h in holds]+c['warnings']))
        lines+=['### 계산 보류·확인 사항\n']+['- '+html.escape(reason)+'\n' for reason in reasons[:12]]
        lines+=['조건이 부족한 계산만 보류하며 위 원시 그래프와 다른 계산 결과는 유지합니다.\n']
    return lines


def export(sources,cfg,directory,*,pair_reason='단독 선택',stop_event=None,on_progress=None):
    out=Path(directory);out.mkdir(parents=True,exist_ok=True)
    for sub in ('inputs','images','csv','diagnostics','metadata'):(out/sub).mkdir(exist_ok=True)
    loaded_files=[];models=[];lines=['# 측정 결과\n','생성일 '+datetime.now(timezone.utc).date().isoformat()+' · 연구 자동화 '+__version__+'\n']
    if len(sources)>1:lines+=['파일 연결: '+pair_reason+'. 배선·측정일·사전 이력이 확인되지 않은 연결은 잠정 검토입니다. 서로 다른 stress 범위의 결과를 crop·평균해 직접 비교하지 않습니다.\n']
    receipts=[];summaries=[]
    for index,source in enumerate(sources,1):
        if stop_event is not None and stop_event.is_set():break
        source=Path(source);prefix=f'{index:02d}';fingerprint=digest(source)
        if source.stat().st_size>cfg.data['ingest']['max_bytes']:raise ValueError('입력 크기 한도를 초과했습니다: '+source.name)
        snapshot=out/'inputs'/(prefix+source.suffix.lower());shutil.copyfile(source,snapshot)
        if digest(snapshot)!=fingerprint or digest(source)!=fingerprint:raise ValueError('원본이 처리 중 변경되었습니다. 저장 완료 후 다시 실행하세요.')
        if on_progress:on_progress({'source':source.name,'status':'processing'})
        loaded=load_source(source,cfg,snapshot);output=output_benchmarks(loaded,cfg);transfer=transfer_benchmarks(loaded,cfg)
        if not loaded['traces']:raise ValueError('계산할 측정점이 없습니다: '+source.name)
        loaded_files.append(loaded)
        images=figures(loaded,output,transfer,out,prefix)
        exports={'raw':loaded['points'],'RR':output['rr'],'fit-parameters':output['parameters'],
            'fit-residuals':output['residuals'],'single-diode':output['signed'],'single-residuals':output['signed_points'],
            'offsets':output['offsets'],'sensitivity':output['sensitivity'],'Rs-profile':output['profiles'],'gm':transfer['frame'],
            'segments':pd.DataFrame([{k:v for k,v in t.items() if k not in ('frame','record')} for t in loaded['traces']])}
        for name,frame in exports.items():
            if frame.empty and not len(frame.columns):frame=pd.DataFrame(columns=['not_available'])
            frame.to_csv(out/'csv'/(prefix+'-'+name+'.csv'),index=False,encoding='utf-8-sig',float_format='%.17g')
        write_diagnostic(out/'diagnostics'/(prefix+'-source.json'),{'source':str(source),'sha256':fingerprint,
            'metadata':loaded['context'],'geometry':loaded['geometry'],'conditions':loaded['conditions'],
            'condition_notices':loaded.get('condition_notices',[]),
            'records':[{k:v for k,v in record.items() if k not in ('data','points')} for record in loaded['records']],
            'ignored':loaded['ignored'],'holds':output['holds']+transfer['holds'],'transfer_metrics':transfer['metrics']})
        for i,receipt in enumerate(loaded['context']['sources'],1):
            metadata=Path(receipt['path']);saved=out/'metadata'/(prefix+'-'+str(i)+'-device.md');shutil.copyfile(metadata,saved)
            if digest(saved)!=receipt['sha256'] or digest(metadata)!=receipt['sha256']:raise ValueError('device.md가 처리 중 바뀌었습니다. 다시 실행하세요.')
        if digest(source)!=fingerprint:raise ValueError('원본이 계산 중 변경되었습니다. 다시 실행하세요.')
        receipts.append({'source':str(source),'sha256':fingerprint,'snapshot':snapshot.relative_to(out).as_posix()})
        summaries.append({'file':source.name,'points':len(loaded['points']),'traces':len(loaded['traces']),
            'output_blocks':len(output['representatives']),'fit_count':len(output['parameters']),
            'transfer_metrics':transfer['metrics'],'RR_min':output['rr'].RR.min() if not output['rr'].empty else None,
            'RR_max':output['rr'].RR.max() if not output['rr'].empty else None})
        section=source_section(loaded,output,transfer,images,prefix)
        split=next((i for i,line in enumerate(section) if line.startswith('### 단일 다이오드') or line.startswith('### 극성별')),len(section))
        lines+=section[:split]
        if split<len(section):models+=['## 모델 비교 · '+html.escape(source.name)+'\n']+section[split:]
    lines+=models
    lines+=['## 자료와 다음 확인\n','확인이 필요한 조건 한 가지를 `device.md`에 출처와 함께 기록한 뒤 선택 파일의 보고서를 다시 생성하세요. YAML 아래 사용자 메모와 기존 노트는 수정하지 않습니다.\n',
        '[입력 소자 정보 사본](metadata/) · [분리 진단 자료](diagnostics/) · [수치와 원본 셀 근거](csv/)\n']
    body='\n'.join(lines);(out/'report.md').write_text(body,encoding='utf-8')
    rendered=markdown.markdown(body,extensions=['tables','fenced_code'])
    style='body{font:16px/1.7 "Malgun Gothic",Arial,sans-serif;color:#172638;background:#f4f6f8;margin:0}main{max-width:1120px;margin:24px auto;padding:32px;background:white}h1,h2,h3{color:#173a60}h2,h3{margin-top:32px;padding-top:12px;border-top:1px solid #dce4ed}img{max-width:100%;height:auto;display:block;margin:20px auto}table{border-collapse:collapse;width:100%;font-size:13px;line-height:1.5;margin:18px 0}td,th{padding:9px;border-bottom:1px solid #dce4ed;text-align:left}th{background:#edf3f8}a{color:#1b639f}@media(max-width:780px){main{padding:16px;margin:0}table{display:block;overflow-x:auto}}@media print{main{margin:0;padding:0}img,table{break-inside:avoid}}'
    (out/'report.html').write_text('<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>측정 결과</title><style>'+style+'</style></head><body><main>'+rendered+'</main></body></html>',encoding='utf-8')
    write_diagnostic(out/'diagnostics'/'summary.json',{'version':__version__,'code_sha256':code_fingerprint(),'sources':receipts,'files':summaries,'pair_reason':pair_reason})
    return {'html':str(out/'report.html'),'markdown':str(out/'report.md'),'files':len(loaded_files),
        'fit_count':sum(item['fit_count'] for item in summaries),'points':sum(item['points'] for item in summaries),'summary':clean_json(summaries)}
