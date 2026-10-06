"""Ordered Figure 2 panels from stored acquisition arrays, with a file manifest."""
import hashlib
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from PIL import Image
from matplotlib.ticker import LogFormatter,LogLocator,NullFormatter
from .plot_style import export_theme, EXPORT_DPI, palette, bias_colors, RAINBOW
from .note_presentation import representative

TITLES={'a':'소자 구조와 측정 조건','b':'Log transfer · |Id| 및 |Ig|','c':'Signed transfer',
        'd':'Signed output','e':'직접 SS vs |Id|','f':'TLM length series','g':'Rc vs nS',
        'h':'Rsh 및 μcon vs nS','i':'Gate-dependent signed G','j':'Raw / local gm',
        'k':'gm/Vds 및 두 정규화 gm','l':'RR 및 AG','m':'Signed μFE 후보'}


def verify_png(path):
    path=Path(path)
    if not path.is_file() or path.stat().st_size==0:raise ValueError('PNG file missing or empty')
    with Image.open(path) as im:
        im.verify()
    with Image.open(path) as im:
        im.load();size=list(im.size)
    return {'size_bytes':path.stat().st_size,'pixels':size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'decoded':True}


@export_theme
def research_panels(curves,summary,directory,additional,report):
    directory=Path(directory);manifest=[];files=[]
    chosen=representative(summary)
    # First acquisition block/direction/order only; no averaging across history.
    scope=[g for g in summary.get('groups',[]) if chosen and g.get('gate_block_id')==chosen.get('gate_block_id') and g.get('direction')==chosen.get('direction') and g.get('branch_index')==chosen.get('branch_index')]
    transfer=[g for g in scope if g['axis']=='vg'];output=[g for g in scope if g['axis']=='vd']
    width=additional.get('settings',{}).get('channel_width_m',{})
    W=width.get('value') if width.get('status')=='confirmed' and width.get('source') else None
    W=W if isinstance(W,(int,float)) and W>0 else None
    scale=1/(W*1e6) if W else 1
    current_unit='A/μm' if W else 'A'
    held=any(g.get('units_review_required',True) for g in scope)
    suffix='V/A 가정 참고값 · 정량 사용 보류' if held else '단위 확인 · 모델/영역 해석은 후보'
    ids={g['group_id'] for g in scope}
    def data(g):return curves[curves['group_id']==g['group_id']]
    def label(g):
        fixed='vd' if g['axis']=='vg' else 'vg'
        direction={'forward':'증가','reverse':'감소'}.get(g.get('direction'),'방향 미확인')
        return f'{fixed.upper()}={g.get("conditions",{}).get(fixed)} V · {direction}'
    def plot_curves(ax,groups,column='id_a',absolute=False,log=False,normalize=False):
        drawn=False
        colors,values,norm,fixed=bias_colors(groups,groups[0]['axis']) if groups else ({},{},None,None)
        for g in groups:
            d=data(g)
            if column not in d:continue
            y=d[column].to_numpy(dtype=float)
            if absolute:y=np.abs(y)
            if normalize:y=y*scale
            if log:y=np.where(y>0,y,np.nan)
            if not np.isfinite(y).any():continue
            ax.plot(d['x_v'],y,color=colors[g['group_id']],label=label(g) if len(groups)<=10 else None);drawn=True
        if len(groups)>10 and norm is not None and norm.vmin!=norm.vmax:
            ax.figure.colorbar(matplotlib.cm.ScalarMappable(norm=norm,cmap=RAINBOW),ax=ax,pad=.02).set_label(f'Fixed {fixed.upper()} (V)')
        if log:ax.set_yscale('log')
        return drawn
    def unavailable(letter,reason,state='unavailable'):
        manifest.append({'panel':letter,'title':TITLES[letter],'generation_status':state,'metric_status':'held' if state=='held' else 'unavailable','file':None,'reason':reason})
    def save(letter,fig,axes,caption):
        name=f'figure2_{letter}.png'
        entry={'panel':letter,'title':TITLES[letter],'generation_status':'failed','metric_status':'held' if held else 'candidate',
               'file':None,'scope_group_ids':sorted(ids),'caption':caption,'source_data':'curves.csv + research_report.json + fet_parameters.json',
               'units_note':suffix,'source_sha256':summary.get('source_sha256')}
        try:
            for ax in np.asarray(axes,dtype=object).reshape(-1):
                if ax.get_xscale()=='log':
                    ax.xaxis.set_major_formatter(LogFormatter(base=10));ax.xaxis.set_minor_formatter(NullFormatter())
                    lo,hi=ax.get_xlim()
                    if 0<lo<hi and hi/lo<10:
                        ax.xaxis.set_major_locator(LogLocator(base=10,subs=(1.,2.,3.,4.,6.,8.)))
                        ax.xaxis.set_major_formatter(LogFormatter(base=10,minor_thresholds=(float('inf'),float('inf'))))
                if ax.get_yscale()=='log':
                    ax.yaxis.set_major_formatter(LogFormatter(base=10));ax.yaxis.set_minor_formatter(NullFormatter())
                    lo,hi=ax.get_ylim()
                    if 0<lo<hi and hi/lo<10:
                        ax.yaxis.set_major_locator(LogLocator(base=10,subs=(1.,2.,3.,4.,6.,8.)))
                        ax.yaxis.set_major_formatter(LogFormatter(base=10,minor_thresholds=(float('inf'),float('inf'))))
                ax.grid(True,alpha=.2)
                if ax.get_legend_handles_labels()[0]:ax.legend(fontsize=7)
                ax.tick_params(labelsize=9)
            fig.suptitle(f'Figure 2{letter} · {TITLES[letter]}\n{suffix}',fontsize=11)
            fig.tight_layout(rect=(0,0,1,.91));fig.savefig(directory/name,dpi=EXPORT_DPI)
            entry.update(generation_status='generated',file=name,verification=verify_png(directory/name))
            files.append(name)
        except (OSError,ValueError,RuntimeError) as error:
            entry['reason']=f'{type(error).__name__}: {error}'
        finally:plt.close(fig)
        manifest.append(entry)
    unavailable('a','구조 이미지를 임의 생성하지 않았습니다. 사용자 확인 치수와 출처는 본문 구조 표에 표시합니다.','metadata_table')
    for letter,absolute,log in [('b',True,True),('c',False,False)]:
        if not transfer:unavailable(letter,'Id–Vg 원본 배열이 없습니다.');continue
        fig,ax=plt.subplots(figsize=(9,5));drawn=plot_curves(ax,transfer,absolute=absolute,log=log,normalize=True)
        if not drawn:
            plt.close(fig);unavailable(letter,'표시 가능한 유한 전류가 없습니다. log는 비영 전류가 필요합니다.');continue
        if letter=='b':
            for g in transfer:
                d=data(g)
                if 'ig_a' in d and d['ig_a'].notna().any():ax.plot(d['x_v'],np.abs(d['ig_a'])*scale,linestyle=':',label='|Ig| · '+label(g))
            floor=report['detection_floor']['value_a']
            if floor:ax.axhline(floor*scale,color='gray',ls='--',label='기록된 detection floor')
            for g in transfer:
                d=data(g);magnitude=d['id_a'].abs();valid=magnitude[magnitude>0]
                if len(valid):
                    for index,mark in [(valid.idxmin(),'v'),(valid.idxmax(),'^')]:ax.plot([d.loc[index,'x_v']],[magnitude.loc[index]*scale],mark,color='black',ls='none',label='측정 min' if mark=='v' else '측정 max')
        ax.set_xlabel('Vg (V)');ax.set_ylabel(('Absolute current' if absolute else 'Signed Id')+f' ({current_unit})'+(' · V/A assumed' if held else ''))
        save(letter,fig,[ax],f'원본 순서·부호·블록을 보존한 {len(transfer)}개 개별 transfer 곡선. '+('W 확인값으로 폭 정규화. ' if W else 'W 미확인: 절대 전류만 표시. ')+('Ig 점선은 측정 배열이 있을 때만 표시. 0은 log에서 제외; floor는 새로 추정하지 않음.' if log else '서로 다른 sweep을 합치거나 평균하지 않음.'))
    if output:
        fig,ax=plt.subplots(figsize=(9,5));plot_curves(ax,output,normalize=True)
        ax.set_xlabel('Vds (V)');ax.set_ylabel(f'Signed Id ({current_unit})'+(' · V/A assumed' if held else ''))
        save('d',fig,[ax],f'실제 output 배열 {len(output)}개: 고정 Vg별 원본 순서. Transfer를 output으로 변환하지 않음.')
    else:unavailable('d','고정 Vg의 실제 Id–Vds output 측정이 필요합니다. Transfer에서 변환하지 않습니다.')
    ss=[r for r in report['direct_metrics'] if r['group_id'] in ids and r['parameter']=='ss_direct' and not r['endpoint'] and r['summary_selected']]
    if ss:
        fig,ax=plt.subplots(figsize=(9,5))
        for g in transfer:
            points=[r for r in ss if r['group_id']==g['group_id']]
            ax.plot([abs(r['signed_current_a'])*scale for r in points],[r['value'] if r['value'] is not None else r['candidate_value_assuming_si'] if r['candidate_value_assuming_si'] is not None else r['candidate_value_exploratory'] for r in points],'.-',label=label(g))
        ax.set_xscale('log');ax.set_xlabel(f'|Id| ({current_unit})');ax.set_ylabel('Direct SS (mV/dec)')
        save('e',fig,[ax],'1000/|d(log10|Id|)/dVg|; 실제 spacing; 내부점·같은 선택 구간. 10–30% 자동 구간은 탐색 후보이며 subthreshold/floor/온도 검증을 뜻하지 않음. Id/gm 방식과 수치적으로 같다고 가정하지 않음.')
        if any(r['metric_status']=='held' for r in ss):manifest[-1]['metric_status']='held'
    else:unavailable('e','연속·단조·동일 부호의 SS 선택 구간이 없습니다. 검출한계와 subthreshold 구간을 확인하세요.','held' if transfer else 'unavailable')
    unavailable('f','동일 조건의 여러 L(권장 ≥4), W, low-bias 선형 영역과 TLM 저항·잔차 자료가 필요합니다.')
    unavailable('g','접촉 분리 Rc와 검증된 nS가 필요합니다. Rs/Vds÷Id를 Rc로 대체하지 않습니다.')
    unavailable('h','접촉 분리 Rsh와 검증된 양의 nS가 필요합니다. μFE를 μcon으로 대체하지 않습니다.')
    gp=[p for p in additional.get('points',[]) if p['parameter']=='conductance' and p['group_id'] in ids and p['axis']=='vg']
    if gp:
        fig,ax=plt.subplots(figsize=(9,5))
        for g in transfer:
            points=[p for p in gp if p['group_id']==g['group_id']]
            ax.plot([p['evaluation_voltage_v'] for p in points],[p['value'] if p['value'] is not None else p['candidate_value_assuming_si'] for p in points],label=label(g))
        ax.set_xlabel('Vg (V)');ax.set_ylabel('Signed G = Id / Vds (S)');ax.axhline(0,color='gray',ls='--')
        save('i',fig,[ax],'고정 signed Vds별 G=Id/Vds. +Vds만 있으면 +만 표시. gds=dId/dVds 또는 Rc가 아님; 극성별 직접 관측 후보.')
    elif output:
        u=report['primary_evaluation_abs_vds_v'];fig,ax=plt.subplots(figsize=(9,5));drawn=False
        for sign,color in [(1,'#8a2be2'),(-1,'#159a8a')]:
            points=[p for p in additional.get('points',[]) if p['parameter']=='conductance' and p['group_id'] in ids and p['axis']=='vd' and p['evaluation_voltage_v']==sign*u and p['fixed_voltages_v'].get('vg') is not None]
            if not points:continue
            x=[p['fixed_voltages_v']['vg'] for p in points];y=[p['value'] if p['value'] is not None else p['candidate_value_assuming_si'] for p in points]
            ax.plot(x,y,'.',color=color,ls='none',label=f'Vds={sign*u:g} V · 원본 측정점');drawn=True
        ax.set_xlabel('Vg (V)');ax.set_ylabel('Signed G = Id / Vds (S)');ax.axhline(0,color='gray',ls='--')
        if drawn:save('i',fig,[ax],f'Output 각 곡선의 정확히 측정된 Vds=±{u:g} V 전류로 G=Id/Vds. 개별 원본 점만 표시하며 보간·반복 평균 없음. 초기 상태/history 미확인은 별도이며 ΔG/AG·비교 성능을 확정하지 않음.')
        else:plt.close(fig);unavailable('i',f'평가 Vds=±{u:g} V의 정확한 output 원본점이 없습니다.','held')
    else:unavailable('i','비영 고정 Vds의 Id–Vg 또는 지정 bias의 output 원본 배열이 필요합니다.')
    if transfer and 'gm_a_per_v' in curves:
        fig,ax=plt.subplots(figsize=(9,5));plot_curves(ax,transfer,'gm_a_per_v')
        for g in transfer:
            d=data(g)
            for column in d:
                if column.startswith('gm_local_w') and column.endswith('_a_per_v') and d[column].notna().any():
                    width=column.removeprefix('gm_local_w').removesuffix('_a_per_v')
                    ax.plot(d['x_v'],d[column],ls='--',label=f'Local {width} V (전체 폭) · '+label(g))
            if 'gm_raw_endpoint' in d:
                end=d[d['gm_raw_endpoint'].fillna(False).astype(bool)];ax.plot(end['x_v'],end['gm_a_per_v'],'rx',label='one-sided raw endpoints')
        ax.set_xlabel('Vg (V)');ax.set_ylabel('Signed gm (A/V)');ax.axhline(0,color='gray',ls='--')
        save('j',fig,[ax],'저장된 signed raw gm과 local polynomial 전압 전체 폭별 gm. 끝점 ×는 내부 peak 후보가 아님. order·최소 n·실제 spacing은 근거 JSON; 가중치 균일, 반복 평균/재표본화 없음.')
        fig,axes=plt.subplots(3,1,figsize=(9,9),sharex=True)
        columns=[('gm_over_vd_a_per_v2','gm / signed Vds (A/V²)'),('gm_signed_over_max_abs','signed gm / max|gm| (1)'),('gm_abs_over_max_abs','|gm| / max|gm| (1)')]
        drawn=False
        for ax,(column,ylabel) in zip(axes,columns):drawn=plot_curves(ax,transfer,column) or drawn;ax.set_ylabel(ylabel);ax.axhline(0,color='gray',ls='--')
        axes[-1].set_xlabel('Vg (V)')
        if drawn:save('k',fig,axes,'각 원본 곡선의 raw gm 기준. gm/Vds는 A/V², 두 정규화는 무차원. Vds=0 또는 max|gm|=0은 계산하지 않으며 0으로 대체하지 않음.')
        else:plt.close(fig);unavailable('k','비영 Vds 및 비영 max|gm|이 필요합니다.','held')
    else:
        unavailable('j','측정 transfer와 유효 gm 배열이 필요합니다.');unavailable('k','유효 raw gm 배열이 필요합니다.')
    pairs=[p for p in report['polarity_pairs'] if p['positive_group'] in ids and p.get('vg_v') is not None and (p['rr'] is not None or p['rr_lower_bound'] is not None)]
    if pairs:
        fig,axes=plt.subplots(2,1,figsize=(9,7),sharex=True)
        for u in sorted({p['evaluation_abs_vds_v'] for p in pairs}):
            points=[p for p in pairs if p['evaluation_abs_vds_v']==u];exact=[p for p in points if p['rr'] is not None];bounds=[p for p in points if p['rr_lower_bound'] is not None]
            axes[0].plot([p['vg_v'] for p in exact],[p['rr'] for p in exact],'.',label=f'|Vds|={u:g} V · ratio candidate')
            axes[0].plot([p['vg_v'] for p in bounds],[p['rr_lower_bound'] for p in bounds],'^',ls='none',label=f'|Vds|={u:g} V · lower bound only')
            axes[1].plot([p['vg_v'] for p in exact],[p['a_g'] for p in exact],'.',label=f'|Vds|={u:g} V')
        axes[0].set_yscale('log');axes[0].set_ylabel('RR (1)');axes[0].axhline(1,color='gray',ls='--')
        axes[1].set_ylabel('AG (1)');axes[1].axhline(0,color='gray',ls='--');axes[1].set_xlabel('Vg (V)')
        save('l',fig,axes,'고정 |Vds|별 signed 전류 짝. RR=|I(+u)|/|I(−u)|. signed G 유지; ΔG=|G+|−|G−|; AG=ΔG/(|G+|+|G−|). △는 하한이며 최대 RR 순위·정확한 AG에 넣지 않음. 불확정 이력·floor·양전류 미검출은 보류. 각 bracket 원본점·가중치는 JSON.')
        if all(p['rr'] is None for p in pairs):manifest[-1]['metric_status']='bound'
    else:unavailable('l','동일 원래 sweep·방향·블록/순서·확인 이력, ±Vds 전류와 검증된 floor가 필요합니다.','held')
    mobility=[p for p in additional.get('points',[]) if p['parameter']=='mobility_linear' and p['group_id'] in ids]
    if mobility:
        fig,ax=plt.subplots(figsize=(9,5))
        for g in transfer:
            points=[p for p in mobility if p['group_id']==g['group_id']]
            ax.plot([p['evaluation_voltage_v'] for p in points],[p['value'] if p['value'] is not None else p['candidate_value_assuming_si'] for p in points],label=label(g))
        ax.set_xlabel('Vg (V)');ax.set_ylabel('Signed μFE (cm²/(V s))');ax.axhline(0,color='gray',ls='--')
        save('m',fig,[ax],'μFE=L gm/(W Cox signed Vds), SI×10⁴ → cm²/(V s). geometry 출처는 본문; Cox 가정/선형 영역 미확인은 후보·보류. 2-terminal 유효 이동도이며 고유 이동도 또는 μcon 확정 아님.')
    else:unavailable('m','L/W/Cox, 비영 Vds와 유효 gm이 필요합니다. 선형 영역을 별도 확인하세요.','held' if transfer else 'unavailable')
    manifest.sort(key=lambda p:p['panel'])
    from .util import write_json
    write_json(directory/'figure2_manifest.json',{'report_format':'fet-research-note-2','panels':manifest,'scope':'first original acquisition block/direction/order; all prior curves retained in audit','no_fabricated_structure':True})
    return files,manifest
