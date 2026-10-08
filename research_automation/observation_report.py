"""Numerical, self-contained local research report with source evidence."""
import html
import json
import re
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter, NullFormatter

from .observation_metrics import value_of, METHOD_VERSION
from .plot_style import export_theme, palette

NAMES={'rr':'RR','gm_peak':'gm peak','gm_fwhm':'gm 반높이 폭','current_max':'최대 |Id|','range_ratio':'최대/최소 |Id|',
       'g0':'G0','leakage_ratio':'최대 |Ig/Id|','leakage_max':'최대 |Ig|','inverse_log_slope':'역 log 기울기'}


def num(v):
    return '보류' if v is None else f'{v:.4g}'.replace('-','−')


def quantity(value,unit):
    if value is None:return '보류'
    if unit=='1':return num(value)
    if unit in ('A','A/V','S') and value:
        for scale,prefix in [(1e-3,'m'),(1e-6,'µ'),(1e-9,'n'),(1e-12,'p'),(1e-15,'f')]:
            if abs(value)>=scale and abs(value)<scale*1000:
                return num(value/scale)+' '+prefix+unit
    return num(value)+' '+unit


def branch_label(branch,include_id=True):
    labels={'vg':'Vg','vd':'Vd'}
    conditions=', '.join(labels.get(k,k)+'='+quantity(v,'V') for k,v in branch['conditions'].items())
    direction={'forward':'순방향','reverse':'역방향'}.get(branch['direction'],branch['direction'])
    label=', '.join(s for s in (conditions,direction) if s)
    return label+(' ('+branch['branch_id']+')' if include_id else '')


def condition_line(result):
    parts=[]
    for axis,label in [('vd','Vd'),('vg','Vg')]:
        branches=[b for b in result['branches'] if b['axis']==axis]
        if not branches:continue
        ranges=sorted({(b['original_sweep']['minimum'],b['original_sweep']['maximum']) for b in branches})
        parts.append(label+' 원래 범위 '+', '.join(quantity(a,'V')+' ~ '+quantity(b,'V') for a,b in ranges))
        directions={b['direction'] for b in branches}
        parts.append('순·역 왕복' if {'forward','reverse'}<=directions else ' / '.join({'forward':'순방향','reverse':'역방향'}.get(d,d) for d in sorted(directions)))
    settings=result['instrument_settings']
    for key,label in [('hold_time_s','hold'),('sweep_delay_s','장비 delay')]:
        value=settings.get(key)
        parts.append(label+' '+('미기록' if value is None else str(value)+' s'))
    delay=result.get('metadata_fields',{}).get('sweep_delay_s',{})
    if delay.get('value') is not None:
        parts.append('별도 delay '+str(delay['value'])+' s ('+str(delay.get('source'))+', '+str(delay.get('status'))+')')
    parts.append('실제 날짜·광 조건은 확인 상태 참조')
    return ' · '.join(parts)


def selected(branch):
    wanted=[('rr',lambda m:m.get('evaluation_abs_voltage')==1),('g0',lambda m:m.get('window')==[-.1,.1])] if branch['axis']=='vd' else [
        ('gm_peak',lambda m:m.get('window_width')==2),('current_max',lambda m:True)]
    records=[]
    for parameter,rule in wanted:
        candidates=[m for m in branch['metrics'] if m['parameter']==parameter and rule(m)]
        if candidates:records.append(candidates[0])
    records.extend(m for m in branch['metrics'] if m['parameter']=='leakage_ratio')
    return records


def shown(m):
    value=value_of(m)
    if value is None:return '보류'
    suffix=' (SI 가정)' if m.get('value_assuming_si') is not None else ''
    return quantity(value,m['unit'])+suffix


@export_theme
def figures(result,points,directory):
    branches=result['branches'];colors=palette(len(branches)); paths=[]
    axes=set(b['axis'] for b in branches)
    for axis in sorted(axes):
        fig,axs=plt.subplots(1,2,figsize=(12,4.8))
        for b,color in zip(branches,colors):
            if b['axis']!=axis:continue
            f=points[points['branch_id']==b['branch_id']]
            label=b['branch_id']+' '+','.join(f'{k}={v:g}' for k,v in b['conditions'].items())+' '+b['direction']
            line='--' if b['direction']=='reverse' else '-'
            axs[0].plot(f[axis],f['id'],line,color=color,label=label,linewidth=1.3)
            y=np.abs(f['id'].to_numpy(float));axs[1].plot(f[axis],np.where(y>0,y,np.nan),line,color=color,linewidth=1.3)
            if axis=='vg' and 'ig' in f:
                ig=np.abs(f['ig'].to_numpy(float));axs[1].plot(f[axis],np.where(ig>0,ig,np.nan),':',color=color,linewidth=.8)
        known=all(b['units_confirmed'] for b in branches if b['axis']==axis)
        for ax in axs:
            ax.set_xlabel(('Vd' if axis=='vd' else 'Vg')+' (V'+(')' if known else ', SI 가정)'))
            ax.set_ylabel('Id (A'+(')' if known else ', SI 가정)'));ax.grid(alpha=.25)
        axs[0].set_title('signed 전류 · 모든 branch');axs[1].set_title('|전류| · 점선 Ig는 누설 참고');axs[1].set_yscale('log')
        axs[1].yaxis.set_major_formatter(FuncFormatter(lambda value,position:f'{value:.0e}'))
        axs[1].yaxis.set_minor_formatter(NullFormatter())
        if sum(b['axis']==axis for b in branches)<=8:axs[0].legend(fontsize=7)
        else:axs[0].text(.02,.98,f'{sum(b["axis"]==axis for b in branches)} branches · 색 순서는 표 순서',transform=axs[0].transAxes,va='top')
        fig.tight_layout();name=axis+'_curves.png';fig.savefig(directory/name,dpi=160);plt.close(fig);paths.append(name)
        fig,ax=plt.subplots(figsize=(9,4.8))
        if axis=='vd':
            evaluation_colors=palette(len(result['policy']['rr_abs_voltages']))
            for u,color in zip(result['policy']['rr_abs_voltages'],evaluation_colors):
                by_direction={};previous={}
                for b in branches:
                    if b['axis']!=axis:continue
                    m=next((m for m in b['metrics'] if m['parameter']=='rr' and m.get('evaluation_abs_voltage')==u),None)
                    if m is not None and value_of(m) is not None and 'vg' in b['conditions']:
                        # Separate sheet/run resets; sorting is plotting only and
                        # never changes acquisition order or extraction records.
                        base=(b.get('source_sheet') or b['sheet'],b['direction'])
                        gate=b['conditions']['vg'];state=previous.get(base,{'gate':gate,'step':0.,'block':0})
                        delta=gate-state['gate']
                        if state['step'] and delta*state['step']<0 and abs(delta)>2*abs(state['step']):
                            state['block']+=1;state['step']=0.
                        elif delta and not state['step']:state['step']=delta
                        state['gate']=gate;previous[base]=state
                        key=(*base,state['block'])
                        by_direction.setdefault(key,[]).append((gate,value_of(m)))
                first=True
                for key,values in by_direction.items():
                    xx,yy=zip(*values);ax.plot(xx,yy,'o--' if key[1]=='reverse' or key[2] else 'o-',color=color,
                        markersize=2,linewidth=1,label=f'|Vd|={u:g}' if first else '_nolegend_');first=False
            ax.set_yscale('log');ax.axhline(1,color='gray',linewidth=.8);ax.set_xlabel('원래 gate 조건 (V, SI 가정 가능)');ax.set_ylabel('RR=|I(+u)|/|I(-u)|');ax.set_title('평가 전압별 정류비 · 검출한계 미확인 시 탐색값')
            ax.yaxis.set_major_formatter(FuncFormatter(lambda value,position:f'{value:.3g}'))
            ax.yaxis.set_minor_formatter(NullFormatter())
            if ax.get_legend_handles_labels()[0]:ax.legend(fontsize=8,title='평가 전압(V, SI 가정 가능)')
        else:
            for b,color in zip(branches,colors):
                if b['axis']!=axis:continue
                f=points[points['branch_id']==b['branch_id']]
                for width in result['policy']['gm_widths']:
                    column=f'derivative_width_{width:g}'
                    if column in f:ax.plot(f[axis],f[column],label=f'{b["branch_id"]} {b["direction"]}; window {width:g} V',color=color,linestyle='-' if width==2 else '--',linewidth=1)
            ax.set_xlabel('Vg (V, SI 가정 가능)');ax.set_ylabel('signed gm (A/V, SI 가정 가능)');ax.set_title('gm · 창 폭 1/2/4 V 민감도 · 끝점은 peak 선택에서 제외')
            if len(ax.lines)<=12:ax.legend(fontsize=6)
        ax.grid(alpha=.25);fig.tight_layout();name=axis+'_metrics.png';fig.savefig(directory/name,dpi=160);plt.close(fig);paths.append(name)
    return paths


def observation_sentences(result):
    branches=result['branches'];lines=[]
    output=[(b,m) for b in branches for m in b['metrics'] if m['parameter']=='rr' and m.get('evaluation_abs_voltage')==1 and value_of(m) is not None]
    if output:
        lo=min(output,key=lambda item:value_of(item[1]));hi=max(output,key=lambda item:value_of(item[1]))
        lines.append(f'|Vd|=1 V에서 RR은 {len(output)} branch에서 계산되며 {num(value_of(lo[1]))} ({branch_label(lo[0])})–{num(value_of(hi[1]))} ({branch_label(hi[0])})입니다. 분모 검출한계 신뢰도는 별도 확인이 필요합니다.')
        below=sum(value_of(m)<1 for _,m in output)
        lines.append(f'그중 {below}/{len(output)} branch는 RR<1입니다. 이는 고정 정의에서 음전압 쪽 |Id|가 더 큼을 뜻하며 polarity를 뒤집어 RR을 크게 만들지 않았습니다.')
    transfer=[(b,m) for b in branches for m in selected(b) if m['parameter']=='gm_peak' and value_of(m) is not None]
    if transfer:
        lines.append('2 V 창 gm peak: '+'; '.join(f'{branch_label(b)}: {shown(m)} @ Vg={quantity(m.get("evaluation_gate_voltage"),"V")}' for b,m in transfer[:4])+'. 추가 branch는 접힌 전체 결과에 있습니다.')
        positions=[m.get('peak_position_sensitivity_v') for _,m in transfer if m.get('peak_position_sensitivity_v') is not None]
        if positions:lines.append(f'1/2/4 V 창을 바꾸었을 때 peak 위치 차이는 최대 {num(max(positions))} V입니다. 이 값은 평활 민감도이며 반복 측정의 신뢰구간이 아닙니다.')
    leak=[(b,m) for b in branches for m in b['metrics'] if m['parameter']=='leakage_ratio' and value_of(m) is not None]
    if leak:
        b,m=max(leak,key=lambda item:value_of(item[1]))
        point=m['source_points'][0]
        support=', '.join(label+'='+quantity(point.get(key),unit) for key,label,unit in
            [('vd_numeric','Vd','V'),('vg_numeric','Vg','V'),('id_numeric','분모 Id','A'),('ig_numeric','Ig','A')] if point.get(key) is not None)
        lines.append(f'같은 점의 최대 |Ig/Id|는 {shown(m)} ({branch_label(b)})입니다. 평가점: {support}. 전류 채널 단위와 작은 Id의 검출한계를 확인해야 하며 Ig를 Id에서 빼지 않았습니다.')
    return lines[:4] or ['계산 가능한 관측값이 없습니다. 누락 열, branch 분할, compliance 및 단위 근거를 확인하세요.']


def measurement_description(result,source_info,title):
    axes={b['axis'] for b in result['branches']}
    measured=' / '.join(name for axis,name in [('vd','Id–Vd'),('vg','Id–Vg')] if axis in axes) or '전류·전압'
    fields=result.get('metadata_fields',{})
    parts=[f'원본 열과 sweep에서 확인한 측정: {measured}.']
    for key,label in [('device_type','소자 종류'),('fold','구조(fold)')]:
        field=fields.get(key,{})
        if field.get('source')=='user_override' and field.get('status')=='confirmed' and field.get('value') is not None:
            parts.append(f'사용자 확인 {label}: {field["value"]}.')
        else:
            parts.append(f'{label}: 미확인.')
    relative=source_info.get('relative_path',title)
    hints=[]
    for pattern,label in [(r'center[ _-]*fold','center-fold'),(r'drain[ _-]*fold','drain-fold')]:
        if re.search(pattern,relative,re.I):hints.append(label)
    if hints:parts.append('파일 경로의 구조 힌트: '+', '.join(hints)+' (사람의 확인 아님).')
    parts.append('전극 연결·치수·광 세기·실제 날짜는 별도 근거가 필요합니다. 모든 branch에 같은 추출법을 적용합니다.')
    return ' '.join(parts)


def export_report(result,points,directory,title,source_info=None):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    source_info=source_info or {};result['source']=source_info
    description=measurement_description(result,source_info,title)
    conditions=condition_line(result)
    from .observation_analysis import write_observations
    write_observations(result,points,directory)
    paths=figures(result,points,directory)
    rows=[];digests=[];flat=[]
    for b in result['branches']:
        selected_metrics=selected(b)
        digests.append({'branch_id':b['branch_id'],'label':branch_label(b),'direction':b['direction'],'conditions':b['conditions'],
            'branch_sweep':b['branch_sweep'],'original_sweep':b['original_sweep'],
            'branch_range':quantity(b['branch_sweep']['start'],'V')+' → '+quantity(b['branch_sweep']['end'],'V'),
            'stress_range':quantity(b['original_sweep']['minimum'],'V')+' ~ '+quantity(b['original_sweep']['maximum'],'V'),
            'metrics':[{**m,'display_value':shown(m),'display_name':NAMES.get(m['parameter'],m['meaning'])} for m in selected_metrics]})
        metric_text='; '.join(NAMES.get(m['parameter'],m['parameter'])+' '+shown(m) for m in selected_metrics)
        rows.append([branch_label(b),b['sheet'],'순방향' if b['direction']=='forward' else '역방향',', '.join(k.upper()+'='+quantity(v,'V') for k,v in b['conditions'].items()),str(b['n']),
            f'{b["branch_sweep"]["start"]:g} → {b["branch_sweep"]["end"]:g}',metric_text])
        for m in b['metrics']:
            flat.append({'branch_id':b['branch_id'],'axis':b['axis'],'direction':b['direction'],'conditions':json.dumps(b['conditions']),
                **{k:v for k,v in m.items() if k not in ('source_points','polarity_samples','samples')},
                'source_rows':','.join(str(p['source_row']) for p in m['source_points']),
                'source_cells':','.join(str(p.get('id_cell')) for p in m['source_points'])})
        evidence=[{**m,'display_value':shown(m),'source_points':m['source_points']} for m in b['metrics']]
        encoded=json.dumps(evidence,ensure_ascii=False,allow_nan=False).replace('<','\\u003c')
        options=''.join('<option value="'+str(i)+'">'+html.escape(m['parameter']+' '+str(m.get('evaluation_abs_voltage',m.get('evaluation_voltage',m.get('window_width',m.get('gate_pair',m.get('criterion_a',''))))))+' : '+shown(m))+'</option>' for i,m in enumerate(evidence))
        page='<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>계산 근거 '+b['branch_id']+'</title><style>body{font:16px/1.6 "Malgun Gothic",sans-serif;max-width:1000px;margin:24px auto;padding:16px}select{font:inherit;padding:8px;max-width:100%}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f1f5f8;padding:16px}</style><a href="report.html#evidence">보고서로 돌아가기</a><h1>'+html.escape(branch_label(b))+'</h1><p>값 → 평가 전압/창/방법 → 제외·보류 이유 → 원본 점. SI 가정은 사용자 확인이 아닙니다.</p><label for="metric">지표 선택 </label><select id="metric">'+options+'</select><pre id="evidence"></pre><script>const metrics='+encoded+';const select=document.getElementById("metric");function show(){const m=metrics[Number(select.value)];document.getElementById("evidence").textContent=JSON.stringify(m,null,2)}select.addEventListener("change",show);show();</script></html>'
        old_script='function show(){const m=metrics[Number(select.value)];document.getElementById("evidence").textContent=JSON.stringify(m,null,2)}'
        readable_script='''function show(){const m=metrics[Number(select.value)],panel=document.getElementById('evidence');panel.replaceChildren();function line(text,tag='p'){const e=document.createElement(tag);e.textContent=text;panel.append(e)}line(m.meaning,'h2');const value=m.value??m.value_assuming_si;line('현재 값: '+m.display_value);const condition=[];for(const [key,label] of [['evaluation_abs_voltage','양/음 평가 전압 크기'],['evaluation_voltage','평가 전압'],['evaluation_gate_voltage','gate 평가 위치'],['window_width','전체 창 폭'],['window','피팅 전압 구간'],['gate_pair','비교 gate쌍'],['criterion_a','전류 기준(A)']]){if(m[key]!==undefined)condition.push(label+': '+JSON.stringify(m[key]))}line(condition.join(' · ')||'선택한 branch 원본 범위 안에서 평가');line(m.value===null&&m.value_assuming_si===null?'보류 이유: 지원 원본 점·단위·유일한 구간의 조건을 충족하지 못했습니다. 아래 세부 기록에 개별 이유가 있습니다.':'평가 상태: 관측/탐색값입니다. 원본 단위·검출한계·창 민감도를 함께 확인하세요.');line('의미와 한계: '+m.limitation);line('사용한 원본 점 ('+m.source_points.length+'개)','h3');const wrap=document.createElement('div');wrap.style.overflow='auto';const table=document.createElement('table');table.style.cssText='border-collapse:collapse;font-size:13px;width:100%';const head=document.createElement('tr');for(const label of ['Sheet','행 / 셀','Vd / Vg (SI 가정 가능)','Id / Ig (SI 가정 가능)','제외 표시']){const td=document.createElement('th');td.textContent=label;td.style.cssText='border:1px solid #ccd6df;padding:7px;text-align:left';head.append(td)}table.append(head);for(const point of m.source_points){const row=document.createElement('tr');for(const text of [point.sheet,point.source_row+' / '+point.id_cell,point.vd_numeric+' / '+point.vg_numeric,point.id_numeric+' / '+point.ig_numeric,point.point_flags||'표시 없음 (완전한 QC 확인과 별개)']){const td=document.createElement('td');td.textContent=text;td.style.cssText='border:1px solid #ccd6df;padding:7px';row.append(td)}table.append(row)}wrap.append(table);panel.append(wrap);const detail=document.createElement('details'),summary=document.createElement('summary'),pre=document.createElement('pre');summary.textContent='계산법·보간 가중치·제외 이유의 전체 기계 판독 기록';pre.textContent=JSON.stringify(m,null,2);detail.append(summary,pre);panel.append(detail)}'''
        page=page.replace('<pre id="evidence"></pre>','<div id="evidence"></div>').replace(old_script,readable_script)
        (directory/('evidence-'+b['branch_id']+'.html')).write_text(page,encoding='utf-8')
    pd.DataFrame(flat).to_csv(directory/'metrics.csv',index=False,encoding='utf-8-sig')
    observations=observation_sentences(result)
    settings=result['instrument_settings']
    fields=result.get('metadata_fields',{})
    field_rows=[]
    for key,item in fields.items():
        field_rows.append([key,str(item.get('value')),str(item.get('source')),str(item.get('status')),
            json.dumps(item.get('candidates',[]),ensure_ascii=False)])
    lines=[f'# {title}', '', '**측정 조건:** '+conditions, '', '[전체 수치 CSV](metrics.csv) · [원본점·계산 근거](report.html#evidence)', '', '## 어떤 측정인가', '',
        description, '',
        f'원본: `{source_info.get("relative_path",title)}` · SHA256 `{source_info.get("sha256","미기록")}`',
        f'동일 방법 `{METHOD_VERSION}` · trace {result.get("trace_count",len(set(b["sheet"] for b in result["branches"])))} · branch {len(rows)} · 원본 순서/turning point/전체 stress 범위 보존', '',
        '## 지금 데이터에서 보이는 것', '']+['- '+s for s in observations]+['',
        '## 조건과 해석 범위', '',
        '단위가 없는 열은 SI 가정값으로 표시합니다. 같은 Id 채널에서 계산한 RR 등 비는 탐색 관측으로 제공하지만 검출한계 미확인 상태의 큰 비를 성능으로 확정하지 않습니다. QC PASS와 연구 해석 가능은 별개입니다. ±20 V와 ±40 V sweep은 다른 stress 조건으로 유지합니다.', '',
        '| 항목 | 값·출처 | 상태 |','|---|---|---|',
        '| 실제 측정일 | 사용자 확인 필요; 폴더/Keithley 시각 참고 | 미확인 |',
        f'| Keithley 기록 | {settings.get("measurement_timestamp_raw","없음")} | 참고 시각 |',
        f'| sweep delay / hold | {settings.get("sweep_delay_s","없음")} / {settings.get("hold_time_s","없음")} (Settings) | 장비 기록; 사용자 값과 충돌 시 유지 |',
        '| 치수·정전용량 | 해당 소자와 연결된 사용자 근거 필요 | μ/고유 Rc/장벽 높이 보류 |','',
        '## 결정적인 그림', '']
    for name in paths:lines+=['![]('+name+')','']
    lines+=['<details><summary>전체 branch 결과 · 수치 CSV와 원본 근거</summary>','','[전체 수치 CSV](metrics.csv)','','| 조건·방향 (보조 ID) | Sheet | 방향 | 고정 조건 | 점 | 해당 branch | 핵심 수치 |','|---|---|---|---|---:|---|---|']
    lines+=['| '+' | '.join(str(c).replace('|','/').replace('\n',' ') for c in r)+' |' for r in rows]
    lines+=['','</details>']
    lines+=['','## 의미와 다음 확인','','RR은 +u/−u 전류 크기의 고정 방향 비입니다. gm은 gate 변화에 대한 signed 전류 기울기이며 peak와 창 폭을 함께 봅니다. G0는 offset을 포함한 영전압 근처 전체 2단자 기울기입니다. 모두 단일 메커니즘을 증명하지 않습니다.', '',
        '**다음 확인 한 가지:** 원본 Keithley 전류·전압 단위와 작은 전류의 검출한계를 확인한 후, 같은 stress·광 조건의 branch끼리 비교하세요.', '',
        '<details><summary>계산 전체·원본 점·방법과 제한</summary>','',
        '[모든 지표 CSV](metrics.csv) · [모든 원본 점 CSV](observation_points.csv) · [상세 근거 JSON](observations.json) · [브라우저 계산 근거 패널](report.html#evidence)', '',
        'Vcc는 명시한 전류 기준의 operational 교차점이며 VT와 구분합니다. 역 log 기울기는 검출한계·누설·subthreshold 영역 미확인 시 SS로 확정하지 않습니다. 독립 반복/노이즈 근거가 없으므로 신뢰구간은 제공하지 않습니다.', '',
        '[Cheng et al., 보고·비교 지침](https://arxiv.org/pdf/2203.16759) · [Bennett et al., gate 의존 접촉저항의 영향](https://poplab.stanford.edu/pdfs/Bennett-TransistorsGateDependentRc-npj2d25.pdf)', '',
        '창 폭과 최소 점 수는 이 도구의 공개된 engineering 기본값이며 문헌의 보편적 문턱이 아닙니다. 사용자 확인 override를 생성하지 않았습니다.', '', '</details>']
    field_md=['','### 값·출처·추정/확인/충돌','','| 항목 | 값 | 출처 | 상태 | 나란히 보존한 후보 |','|---|---|---|---|---|']
    field_md+=['| '+' | '.join(c.replace('|','/') for c in row)+' |' for row in field_rows]
    position=lines.index('## 결정적인 그림')
    lines[position:position]=field_md+['']
    (directory/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    esc=html.escape
    table='<div class="table"><table><thead><tr>'+''.join('<th>'+esc(c)+'</th>' for c in ['조건·방향 (보조 ID)','Sheet','방향','고정 조건','점','branch 범위','핵심 수치'])+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+esc(str(c))+'</td>' for c in row)+'</tr>' for row in rows)+'</tbody></table></div>'
    digest=json.dumps(digests,ensure_ascii=False,allow_nan=False).replace('<','\\u003c')
    document='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'''+esc(title)+'''</title><style>body{font:16px/1.65 "Malgun Gothic",sans-serif;max-width:1100px;margin:32px auto;padding:0 20px;color:#172332;background:#fff}h1{font-size:26px}h2{margin-top:36px}img{max-width:100%;height:auto}.notice{background:#eef3f7;padding:16px;border-left:4px solid #386789}.table{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}td,th{border:1px solid #d3dce4;padding:8px;vertical-align:top}th{text-align:left;background:#edf2f6}select{font:inherit;max-width:100%;padding:8px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}a{color:#194f90}details{margin:20px 0}li{margin:8px 0}</style><body><h1>'''+esc(title)+'''</h1><p class="notice"><strong>측정 조건:</strong> '''+esc(conditions)+'''</p><p><a href="metrics.csv">전체 수치 CSV</a> · <a href="#evidence">원본점·계산 근거</a></p><p>'''+esc(description)+'''</p><h2>지금 데이터에서 보이는 것</h2><ul>'''+''.join('<li>'+esc(s)+'</li>' for s in observations)+'''</ul><div class="notice">단위 없는 전류/전압은 SI 가정입니다. RR 분모의 검출한계는 미확인입니다. ±20 V와 ±40 V stress를 합치지 않습니다. QC 통과만으로 연구 해석 가능을 확정하지 않습니다.<br>다음 확인: Keithley 단위와 작은 전류의 검출한계를 확인하세요.</div><h2>측정 조건</h2><p>원본: '''+esc(source_info.get('relative_path',title))+'''<br>실제 날짜·소자 치수·광 세기: 미확인<br>Settings 시각(참고): '''+esc(str(settings.get('measurement_timestamp_raw','없음')))+'''<br>Settings delay/hold: '''+esc(str(settings.get('sweep_delay_s','없음')))+' / '+esc(str(settings.get('hold_time_s','없음')))+'''</p><h2>원본과 수치 그림</h2>'''+''.join('<img loading="lazy" src="'+name+'" alt="'+esc(name)+'">' for name in paths)+'''<details><summary>전체 '''+str(len(rows))+''' branch 결과 · 수치 CSV와 원본 근거</summary><p><a href="metrics.csv">전체 수치 CSV</a></p>'''+table+'''</details><h2 id="evidence">계산 근거</h2><label for="branch">Branch 선택 </label><select id="branch">'''+''.join('<option value="'+str(i)+'">'+esc(branch_label(b))+'</option>' for i,b in enumerate(digests))+'''</select><div id="panel"></div><details><summary>전체 지표·원본·제한</summary><p><a href="metrics.csv">모든 지표 CSV</a> · <a href="observation_points.csv">원본 점 CSV</a> · <a href="observations.json">상세 JSON</a> · <a href="report.md">Markdown</a></p><p>G0/gds는 전체 2단자 기울기입니다. gm의 창 폭·끝점·누설에 주의하세요. Vcc와 역 log 기울기는 VT/검증된 SS와 구분합니다. 치수·정전용량·모델 미확인으로 μ, 고유 접촉저항, 장벽 높이는 보류합니다. 반복 신뢰구간을 만들지 않았습니다.</p><p><a href="https://arxiv.org/pdf/2203.16759">Cheng 2022</a> · <a href="https://poplab.stanford.edu/pdfs/Bennett-TransistorsGateDependentRc-npj2d25.pdf">Bennett 2025</a> · 방법 '''+METHOD_VERSION+'''</p></details><script>const branches='''+digest+''';const select=document.getElementById('branch');function show(){const b=branches[Number(select.value)],panel=document.getElementById('panel');panel.replaceChildren();const pre=document.createElement('pre');pre.textContent=b.label+'\n해당 branch: '+b.branch_range+'\n전체 trace/stress: '+b.stress_range;panel.append(pre);for(const m of b.metrics){const d=document.createElement('details'),s=document.createElement('summary'),p=document.createElement('pre');s.textContent=m.display_name+': '+m.display_value;p.textContent=m.meaning+'\n계산: '+m.definition+'\n이유: '+m.reason+'\n한계: '+m.limitation+'\n원본 점: '+JSON.stringify(m.source_points,null,2);d.append(s,p);panel.append(d)}}select.addEventListener('change',show);show();</script></body></html>'''
    # Preserve literal JS newlines in quoted text when composing Python strings.
    document=document.replace("+'\n", "+'\\n").replace("'\n계산", "'\\n계산").replace("'\n이유", "'\\n이유").replace("'\n한계", "'\\n한계").replace("'\n원본", "'\\n원본")
    document=document.replace("const pre=document.createElement('pre');", "const link=document.createElement('a');link.href='evidence-'+b.branch_id+'.html';link.textContent='이 branch의 모든 지표와 원본 점 보기';panel.append(link);const pre=document.createElement('pre');")
    metadata_table='<h2>값·출처·추정/확인/충돌</h2><div class="table"><table><tr>'+''.join('<th>'+esc(c)+'</th>' for c in ['항목','값','출처','상태','후보'])+'</tr>'+''.join('<tr>'+''.join('<td>'+esc(c)+'</td>' for c in row)+'</tr>' for row in field_rows)+'</table></div>'
    document=document.replace('<h2>원본과 수치 그림</h2>',metadata_table+'<h2>원본과 수치 그림</h2>')
    actual_date=fields.get('measurement_date',{})
    if actual_date.get('source')=='user_override' and actual_date.get('status')=='confirmed':
        document=document.replace('실제 날짜·소자 치수·광 세기: 미확인','실제 날짜: '+esc(str(actual_date.get('value')))+' (사용자 확인) · 소자 치수·광 세기: 해당 근거 확인')
        lines=[line.replace('| 실제 측정일 | 사용자 확인 필요; 폴더/Keithley 시각 참고 | 미확인 |','| 실제 측정일 | '+str(actual_date.get('value'))+' (사용자 확인) | 확인 |') for line in lines]
        (directory/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    (directory/'report.html').write_text(document,encoding='utf-8')
    return {'markdown':str(directory/'report.md'),'html':str(directory/'report.html'),'branches':len(rows),'metrics':len(flat),'observations':observations}
