"""Plots of additional FET data with explicit definitions and held-state labels."""
import math
import matplotlib.pyplot as plt
from .plot_style import export_theme,format_axes,palette,EXPORT_DPI
from .note_figures import subtitle

LABELS={'conductance':'G = Id/Vds (S)','resistance':'R = Vds/Id (Ω)',
        'gds':'gds = dId/dVds (S)','differential_resistance':'rd = 1/gds (Ω)',
        'leakage_ratio':'|Ig|/|Id| (1)','mobility_linear':'Signed effective μFE (cm²/(V s))'}


def val(p):return p.get('value') if p.get('value') is not None else p.get('candidate_value_assuming_si')


@export_theme
def fet_figures(report,summary,destination):
    files=[];groups={g['group_id']:g for g in summary.get('groups',[])}
    for gid,g in groups.items():
        for parameter,label in LABELS.items():
            points=[p for p in report['points'] if p['group_id']==gid and p['parameter']==parameter and val(p) is not None]
            if not points:continue
            # Avoid dozens of per-gate output figures; those use block panels below.
            if g['axis']=='vd' and parameter in ('conductance','resistance','gds','differential_resistance'):continue
            fig,ax=plt.subplots(figsize=(9,5))
            ax.plot([p['evaluation_voltage_v'] for p in points],[val(p) for p in points],color=palette(1)[0],marker='.',label=report['definitions'][parameter])
            format_axes(ax,g['axis'],label)
            tag='V/A 가정 참고값 · 정량 사용 보류' if g.get('units_review_required',True) else '참고 후보 · 검증 전'
            ax.set_title(subtitle(summary,g)+'\n'+tag,fontsize=9)
            if parameter=='mobility_linear':ax.text(.02,.98,'Cox·선형 동작 가정; 접촉 보정 없는 유효 이동도',transform=ax.transAxes,va='top',fontsize=8)
            ax.legend(fontsize=7);fig.tight_layout();name=f'{gid}_fet_{parameter}.png'
            fig.savefig(destination/name,dpi=EXPORT_DPI);plt.close(fig);files.append(name)
        arrays=[p for p in report.get('method_arrays',[]) if p['group_id']==gid]
        if arrays:
            fig,axes=plt.subplots(3,1,figsize=(9,9),sharex=True,gridspec_kw={"height_ratios":[3,1,2]})
            x=[p['evaluation_voltage_v'] for p in arrays]
            axes[0].plot(x,[p['y_function_sqrt_a_v'] for p in arrays],color=palette(1)[0],label='Y = |Id| / sqrt(|gm|)')
            fit=[p for p in arrays if p['y_fit_used']]
            excluded=[p for p in arrays if not p['y_fit_used']]
            if fit:axes[0].plot([p['evaluation_voltage_v'] for p in fit],[p['y_fit_sqrt_a_v'] for p in fit],color='red',linestyle='--',label='YFM 선형 후보 구간의 모델')
            if excluded:axes[0].plot([p['evaluation_voltage_v'] for p in excluded],[p['y_function_sqrt_a_v'] for p in excluded],'x',color='gray',label='YFM 피팅 구간 밖')
            format_axes(axes[0],'vg','Y function (√(A·V))')
            axes[0].set_title(subtitle(summary,g)+'\nYFM · SS 탐색 후보'+(' · V/A 가정 · 정량 사용 보류' if g.get('units_review_required',True) else ''),fontsize=9)
            axes[0].legend(fontsize=7)
            if fit:
                axes[0].axvspan(min(p['evaluation_voltage_v'] for p in fit),max(p['evaluation_voltage_v'] for p in fit),color='gray',alpha=.08)
                axes[1].plot([p['evaluation_voltage_v'] for p in fit],[p['y_function_sqrt_a_v']-p['y_fit_sqrt_a_v'] for p in fit],color=palette(1)[0],label='잔차 = 측정 Y − 모델 Y')
            format_axes(axes[1],'vg','Y residual (√(A·V))');axes[1].axhline(0,color='gray',linestyle='--')
            if fit:axes[1].legend(fontsize=7)
            ss=[p for p in arrays if p['ss_summary_used']]
            if ss:
                axes[2].plot([p['evaluation_voltage_v'] for p in ss],[p['ss_local_mv_per_dec'] for p in ss],color=palette(1)[0],label='SS local · 표의 min/average 평가 구간')
                metrics=[m for m in report['extractions'] if m['group_id']==gid and m['parameter']=='ss_average' and val(m) is not None]
                if metrics:axes[2].axhline(val(metrics[0]),color='red',linestyle='--',label='같은 구간의 SS average')
            format_axes(axes[2],'vg','Local SS candidate (mV/dec)')
            if ss:axes[2].legend(fontsize=7)
            else:axes[2].text(.03,.9,'평가 가능한 연속 저전류 구간 부족 · SS 보류',transform=axes[2].transAxes,va='top')
            fig.tight_layout();name=f'{gid}_fet_yfm_ss.png';fig.savefig(destination/name,dpi=EXPORT_DPI);plt.close(fig);files.append(name)
    # Output G(Vg) at existing RR evaluation voltages. Use stored-point ratios;
    # do not refit a zero-bias conductance or substitute a derivative definition.
    blocks={}
    for g in summary.get('groups',[]):
        if g['axis']=='vd':blocks.setdefault((g.get('gate_block_id'),g.get('direction'),g.get('branch_index')),[]).append(g)
    for block_index,(key,gs) in enumerate(blocks.items()):
        for parameter,label in [('conductance','G = Id/Vds (S)'),('gds','gds = dId/dVds (S)')]:
            points=report['points'];target_voltages=sorted({s*rr['evaluation_abs_vd_v'] for g in gs for rr in g.get('rr_series',[]) for s in (-1,1)})
            fig,ax=plt.subplots(figsize=(9,5));drawn=False
            for target,color in zip(target_voltages,palette(len(target_voltages))):
                selected=[]
                for g in gs:
                    vg=g.get('conditions',{}).get('vg')
                    if vg is None:continue
                    # Exact existing measured coordinates only: no new interpolation.
                    match=[p for p in points if p['group_id']==g['group_id'] and p['parameter']==parameter and p['evaluation_voltage_v']==target and val(p) is not None]
                    if len(match)==1:selected.append((vg,val(match[0])))
                if selected:
                    selected.sort();ax.plot([p[0] for p in selected],[p[1] for p in selected],marker='.',color=color,label=f'Vds={target:g} V');drawn=True
            if drawn:
                format_axes(ax,'vg',label);ax.set_title(subtitle(summary,gs[0])+'\n'+parameter+'(Vg) · '+str(key[0])+' / '+str(key[1])+(' · V/A 가정 참고값 · 정량 사용 보류' if any(g.get('units_review_required',True) for g in gs) else ' · 참고 후보'),fontsize=9)
                ax.legend(fontsize=7);fig.tight_layout();name=f'fet_{parameter}_gate_block_{block_index+1:02d}.png';fig.savefig(destination/name,dpi=EXPORT_DPI);files.append(name)
            plt.close(fig)
    return files
