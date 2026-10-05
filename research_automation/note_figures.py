"""Evidence views drawn from cached curves, never refitted or resampled."""
import math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from .note_presentation import representative, conditions, group_condition
from .plot_style import export_theme, format_axes, palette, bias_colors, EXPORT_DPI


def subtitle(summary, group):
    from .note_presentation import field,number
    fixed='vg' if group.get('axis')=='vd' else 'vd'
    sweep=group.get('original_sweep',{})
    lo=sweep.get('min_v',group.get('x_min_v'));hi=sweep.get('max_v',group.get('x_max_v'))
    direction={'forward':'증가','reverse':'감소'}.get(group.get('direction'),'미확인')
    first=f'{field(summary,"measurement_date")} · {field(summary,"device_name")} · {field(summary,"illumination")}'
    second=f'{fixed.capitalize()}={number(group.get("conditions",{}).get(fixed),"V")} · sweep {number(lo,"V")}~{number(hi,"V")} · delay {field(summary,"sweep_delay_s")}'
    third=f'{group.get("gate_block_id","블록 미확인")} / {group.get("group_id","곡선 미확인")} · {direction} 방향 (원본 기록)'
    if group.get('units_review_required'):third+=' · V/A 가정 · 정량 사용 보류'
    return first+'\n'+second+'\n'+third


@export_theme
def evidence_figures(curves, summary, destination):
    group=representative(summary)
    if not group:return []
    files=[]
    data=curves[curves['group_id']==group['group_id']]
    if data.empty:return []
    transfer=group['axis']=='vg'
    figure,axes=plt.subplots(2 if transfer else 1,1,figsize=(9,7 if transfer else 5),squeeze=False,sharex=True)
    ax=axes[0,0]
    ax.plot(data['x_v'],data['id_a'],color=palette(1)[0],label='측정 Id (부호 보존)')
    if 'metric_eligible' in data:
        bad=data[~data['metric_eligible'].astype(bool)]
        if len(bad):ax.plot(bad['x_v'],bad['id_a'],'rx',label='지표 평가 제외점')
    format_axes(ax,group['axis'],r'Drain current, $I_D$ (A)')
    ax.set_title(subtitle(summary,group),fontsize=9)
    ax.legend(fontsize=10)
    if transfer:
        ax=axes[1,0]
        raw='gm_a_per_v' if 'gm_a_per_v' in data else None
        if raw:ax.plot(data['x_v'],data[raw],color='#777777',label='Raw gm (비평활)')
        smoothed=[c for c in data if c.startswith('gm_local_w') and c.endswith('_a_per_v') and data[c].notna().any()]
        for column,color in zip(smoothed,palette(len(smoothed))):
            width=column.removeprefix('gm_local_w').removesuffix('_a_per_v')
            ax.plot(data['x_v'],data[column],color=color,label=f'Local {width} V (주변 구간 전체 폭)')
        if raw and 'gm_raw_endpoint' in data:
            end=data[data['gm_raw_endpoint'].astype(bool)]
            ax.plot(end['x_v'],end[raw],'rx',label='Raw 끝점 (내부 후보 아님)')
        internal=group.get('transfer_metrics',{}).get('internal_peak_abs',{})
        x=internal.get('vg_v'); y=internal.get('signed_gm_a_per_v')
        if isinstance(x,(int,float)) and isinstance(y,(int,float)) and math.isfinite(x) and math.isfinite(y):
            ax.plot([x],[y],marker='o',color='black',markerfacecolor='white',markersize=8,linestyle='none',label='저장된 내부 후보')
        format_axes(ax,'vg',r'Transconductance, $g_m$ (A/V)')
        ax.axhline(0,color='gray',linestyle='--');ax.legend(fontsize=9)
    figure.tight_layout()
    name='note_representative.png';figure.savefig(destination/name,dpi=EXPORT_DPI);plt.close(figure);files.append(name)
    # One acquisition block/direction per panel; shared axes preserve the scale.
    selected=[g for g in summary['groups'] if g['axis']==group['axis']]
    blocks={}
    for g in selected:blocks.setdefault((g.get('gate_block_id'),g.get('direction')),[]).append(g)
    if len(selected)>10 and len(blocks)>1:
        items=list(blocks.items())
        # Pagination avoids an unreadably tall figure while keeping every block.
        for page in range(0,len(items),4):
            chunk=items[page:page+4]
            fig,axes=plt.subplots(len(chunk),1,figsize=(9,3*len(chunk)),sharex=True,sharey=True,squeeze=False)
            for ax,((block,direction),groups) in zip(axes[:,0],chunk):
                colors,values,norm,fixed=bias_colors(groups,group['axis'])
                for g in groups:
                    d=curves[curves['group_id']==g['group_id']]
                    ax.plot(d['x_v'],d['id_a'],color=colors[g['group_id']])
                format_axes(ax,group['axis'],r'Drain current, $I_D$ (A)')
                ax.set_title(subtitle(summary,groups[0])+f'\n{block} / {direction} · 개별 곡선 {len(groups)}',fontsize=8)
                if norm is not None and norm.vmin!=norm.vmax:
                    import matplotlib
                    from .plot_style import RAINBOW,voltage_label
                    fig.colorbar(matplotlib.cm.ScalarMappable(norm=norm,cmap=RAINBOW),ax=ax,pad=.02).set_label(voltage_label(fixed))
            # Include all points across every page when fixing common scales.
            d=curves[curves['group_id'].isin([g['group_id'] for g in selected])]
            lo,hi=d['id_a'].min(),d['id_a'].max()
            if math.isfinite(lo) and math.isfinite(hi) and hi>lo:
                axes[0,0].set_ylim(lo-.05*(hi-lo),hi+.05*(hi-lo))
            fig.tight_layout();name=f'note_blocks_{page//4+1:02d}.png'
            fig.savefig(destination/name,dpi=EXPORT_DPI);plt.close(fig);files.append(name)
    return files


@export_theme
def parameter_figures(curves, summary, destination):
    """Plot already extracted arrays/metrics only. No new parameter definitions."""
    files=[]
    for group in summary.get('groups',[]):
        if group['axis']!='vg':continue
        data=curves[curves['group_id']==group['group_id']]
        suffix=' · V/A 가정 시 참고값 · 정량 사용 보류' if group.get('units_review_required',True) else ' · 참고 후보 (검증 전)'
        definitions=[('gm_over_vd_a_per_v2',r'$g_m / V_{DS}$ (A/V²)','gm/vds: 저장된 signed raw gm을 고정 Vds로 나눈 값'),
                     ('gm_signed_over_max_abs',r'$g_m / \max|g_m|$ (1)','정규화 gm: signed gm / 해당 개별 곡선의 max|raw gm|'),
                     ('gm_abs_over_max_abs',r'$|g_m| / \max|g_m|$ (1)','정규화 |gm|: |gm| / 해당 개별 곡선의 max|raw gm|')]
        for column,ylabel,definition in definitions:
            if column not in data or not data[column].notna().any():continue
            fig,ax=plt.subplots(figsize=(9,5))
            ax.plot(data['x_v'],data[column],color=palette(1)[0],label=definition)
            if 'gm_raw_endpoint' in data:
                end=data[data['gm_raw_endpoint'].astype(bool)]
                ax.plot(end['x_v'],end[column],'rx',label='Raw 끝점 · 내부 peak 후보 아님')
            format_axes(ax,'vg',ylabel);ax.set_title(subtitle(summary,group)+suffix,fontsize=9)
            ax.legend(fontsize=7);fig.tight_layout()
            name=group['group_id']+'_parameter_'+column+'.png';fig.savefig(destination/name,dpi=EXPORT_DPI);plt.close(fig);files.append(name)
    blocks={}
    for g in summary.get('groups',[]):
        if g['axis']=='vd' and g.get('rr_series'):
            key=(g.get('gate_block_id'),g.get('direction'),g.get('branch_index'))
            blocks.setdefault(key,[]).append(g)
    for index,(key,groups) in enumerate(blocks.items()):
        voltages=sorted({m['evaluation_abs_vd_v'] for g in groups for m in g['rr_series']})
        fig,ax=plt.subplots(figsize=(9,5));drawn=False;assumed=False
        for u,color in zip(voltages,palette(len(voltages))):
            points=[];bounds=[]
            for g in groups:
                vg=g.get('conditions',{}).get('vg')
                m=next((m for m in g['rr_series'] if m['evaluation_abs_vd_v']==u),{})
                if vg is None or m.get('metric_status')=='ambiguous':continue
                value=m.get('value') if not g.get('units_review_required',True) and m.get('metric_status') in ('valid','candidate') else None
                is_assumed=False
                if value is None and m.get('candidate_value_assuming_si') is not None:
                    value=m['candidate_value_assuming_si'];assumed=True;is_assumed=True
                if value is not None:points.append((vg,value,is_assumed))
                if not g.get('units_review_required',True) and m.get('metric_status')=='bound' and m.get('bound_value') is not None:
                    bounds.append((vg,m['bound_value'],m.get('bound_type')))
            points.sort()
            if points:
                # Duplicate coordinates stay as points, rather than averaging repeats.
                style='--' if any(p[2] for p in points) else '-'
                if len({p[0] for p in points})<len(points):style='none'
                ax.plot([p[0] for p in points],[p[1] for p in points],color=color,marker='.',linestyle=style,label=f'|Vd|={u:g} V'+(' · V/A 가정 참고값' if any(p[2] for p in points) else ' · 저장 상태 참조'))
                drawn=True
            for x,y,kind in bounds:
                marker='^' if str(kind).startswith('lower') else 'v'
                ax.plot([x],[y],color=color,marker=marker,linestyle='none',label=f'|Vd|={u:g} V · '+('하한' if marker=='^' else '상한'));drawn=True
        if drawn:
            format_axes(ax,'vg','Rectification ratio, RR (1)')
            ax.set_title(subtitle(summary,groups[0])+'\nRR(Vg) · '+str(key[0])+' / '+str(key[1])+(' · V/A 가정 참고값 · 정량 사용 보류' if assumed else ' · 저장 지표의 상태 유지'),fontsize=9)
            ax.legend(fontsize=7);fig.tight_layout();name=f'parameter_rr_block_{index+1:02d}.png'
            fig.savefig(destination/name,dpi=EXPORT_DPI);files.append(name)
        plt.close(fig)
    return files
