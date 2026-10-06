"""Readable Korean research note, backed by existing arrays and checked figures."""
import json
import os
from pathlib import Path
from .note_presentation import (cell,number,field,conditions,representative,key_metrics,
                                usability,next_action,details,group_condition,metric_text,yaml_scalar)
from .research_panels import verify_png
from .metric_store import read_metric_json,EvidenceStore

STATUS={'confirmed':'확인','assumed':'가정','inferred':'추정','conflict':'충돌','missing':'미확인',
        'candidate':'후보','held':'보류','unavailable':'추출 불가','bound':'하한','ambiguous':'모호함','valid':'관측 유효'}


def render_research_note(summary,assets,directory):
    directory=Path(directory)
    store=EvidenceStore(directory)
    report=read_metric_json(directory/'research_report.json',store)
    additional=read_metric_json(directory/'fet_parameters.json',store)
    manifest=json.loads((directory/'figure2_manifest.json').read_text(encoding='utf-8'))['panels']
    g=representative(summary);axis=(g or {}).get('axis','vg');context=summary.get('research_context',{})
    fixed='vd' if axis=='vg' else 'vg'
    direction={'forward':'증가','reverse':'감소'}.get((g or {}).get('direction'),'미확인')
    block=str((g or {}).get('gate_block_id','미확인')).replace('block-','')
    human_group=f'{fixed.upper()}={number((g or {}).get("conditions",{}).get(fixed),"V")} · {direction} 방향 · 원본 블록 {block}'
    display_conditions=conditions(summary,g).replace(group_condition(g),human_group)
    note_parent=Path(summary.get('vault_note_relative_path','Experiments/result.md')).parent
    base=os.path.relpath(Path(assets),note_parent).replace('\\','/')
    def link(name,label=None):return f'[{label or name}](<{base}/{name}>)'
    def image(name,label):return f'![{label}](<{base}/{name}>)'
    def state(item):return STATUS.get(item.get('metric_status',item.get('status')),'미확인')
    def value(item):
        v=item.get('value');candidate=item.get('candidate_value_assuming_si')
        return number(v,item.get('unit','1')) if v is not None else number(candidate,item.get('unit','1'))+' · V/A 가정 참고값' if candidate is not None else '추출하지 않음'
    def fmt(item):
        v=item.get('value')
        return number(v,item.get('unit','1')) if isinstance(v,(int,float)) else cell(v) if v is not None else '미확인'
    lines=['---','type: experiment','report_format: fet-research-note-2',f'analysis_version: {cell(summary.get("version"))}',
           f'metadata_status: {yaml_scalar(context.get("metadata_status","missing"))}',
           f'metadata_review_required: {str(context.get("metadata_review_required",True)).lower()}',
           f'measurement_date_status: {yaml_scalar(context.get("fields",{}).get("measurement_date",{}).get("status","missing"))}',
           f'measurement_time_status: {yaml_scalar(context.get("fields",{}).get("measurement_time",{}).get("status","missing"))}',
           f'measurement_date: {yaml_scalar(context.get("measurement_date"))}',f'device_name: {yaml_scalar(context.get("device_name"))}',
           f'illumination: {yaml_scalar(context.get("illumination"))}','---',
           '# '+cell(summary.get('source_filename','FET 연구 결과')),'',
           '## 연구 질문','',('게이트 전압에 따른 전류 변화와 극성별 전도도는 어떤 조건에서 비교할 수 있을까?' if axis=='vg' else '같은 게이트 조건에서 드레인 극성에 따라 전류와 전도도는 어떻게 달라질까?'),
           '',display_conditions,'','## 현재 발견과 판단','',
           '**곡선 열람 가능 · 직접 파생 관측은 후보 · 조건/모델별 연구 사용 검토 필요**','',
           f'이 파일의 원본 순서를 보존한 개별 곡선 {len(summary.get("groups",[]))}개를 관측했습니다. 반복 횟수나 소자 수로 간주하지 않습니다.',
           '측정 배열·signed 전류·gm은 관측 근거입니다. 자동 구간 SS, YFM, μFE는 가정과 조건을 검토해야 하는 후보이며, QC PASS는 물리 모델이나 연구 사용 가능성의 검증을 뜻하지 않습니다.',
           '', '**다음 행동 한 가지:** '+next_action(summary),'']
    items,assumptions=key_metrics(summary,directory)
    items=[(a,b,c.replace(group_condition(g),human_group)) for a,b,c in items]
    if axis=='vd':
        # Legacy RR remains in the audit. The new first screen requires floor/history.
        items=[]
        for parameter,label in [('conductance','Signed G=Id/Vds'),('gds','국소 gds=dId/dVds')]:
            candidates=[p for p in additional.get('points',[]) if p['group_id']==(g or {}).get('group_id') and p['parameter']==parameter]
            if candidates:
                p=min(candidates,key=lambda p:abs(p['evaluation_voltage_v']-report['primary_evaluation_abs_vds_v']))
                items.append((label,value(p)+' · '+state(p),'Vds='+number(p['evaluation_voltage_v'],'V')))
        detected=[p for p in report['polarity_pairs'] if p['positive_group']==(g or {}).get('group_id') and p['rr'] is not None]
        if detected:
            p=detected[0];items.append(('RR',number(p['rr'],'1')+' · 후보','abs(Vds)='+number(p['evaluation_abs_vds_v'],'V')))
    if items:
        lines+=['| 핵심 수치 (최대 3개) | 값과 상태 | 평가 조건 |','|---|---|---|']
        lines += [f'| {cell(a)} | {cell(b)} | {cell(c)} |' for a,b,c in items[:3]]
    if assumptions and axis=='vg':
        lines+=['','> V/A 가정 참고값 · 정량 사용 보류: '+cell('; '.join(assumptions[:3]))]
    lines+=['','## 1. 구조와 측정 조건 · Figure 2a','',
            '구조 이미지는 제공되지 않아 확인값과 출처를 표로 표시합니다. 미확인 재료·접촉 구조·환경을 채워 넣지 않습니다.','',
            '| 항목 | 값 | 상태 | 출처·충돌 근거 |','|---|---|---|---|']
    settings=additional.get('settings',{})
    names={'channel_length_m':'채널 L','channel_width_m':'채널 W','oxide_thickness_m':'산화막 두께','dielectric':'유전체',
           'relative_permittivity':'εr','cox_f_per_m2':'Cox','linear_regime':'선형 영역 검증'}
    for key,label in names.items():
        item=settings.get(key,{})
        lines.append(f'| {label} | {fmt(item)} | {state(item)} | {cell(item.get("source","근거 없음"))} |')
    for key,label in [('device_name','소자'),('measurement_date','실제 측정일'),('measurement_time','실제 측정 시각'),
                      ('illumination','광 조건'),('sweep_delay_s','sweep delay'),('hold_s','hold'),('pre_bias','pre-bias'),('history','stress/측정 이력'),('environment','환경')]:
        item=context.get('fields',{}).get(key,{})
        evidence='; '.join(f'{c.get("value")} ({c.get("source")})' for c in item.get('candidates',[]))
        lines.append(f'| {label} | {fmt(item)} | {state(item)} | {cell(evidence or item.get("source","근거 없음"))} |')
    instrument=summary.get('instrument_settings',{})
    lines += [f'| Keithley 시각 (참고) | {cell(instrument.get("measurement_timestamp_raw","미확인"))} | 참고 | 실제 측정일을 대체하지 않음; timezone 미확인 |',
              f'| 원래 sweep / 고정 bias / 방향 | {cell(human_group)} | 원본 기록 | {cell((g or {}).get("original_sweep",{}))} |',
              f'| 검출한계 | {number(report["detection_floor"]["value_a"],"A") if report["detection_floor"]["value_a"] else "미확인"} | {"확인 근거 기록" if report["detection_floor"]["evidence"] else "보류"} | {cell(report["detection_floor"]["evidence"] or "현재 데이터에서 임의 추정하지 않음")} |',
              '| 재료·접촉 길이/종류·채널 두께·온도·EOT | 미확인 | 보류 | 별도 확인 정보가 필요함 |','',
              '단위 확인은 전압·전류 의존성만 갱신합니다. SS 구간·YFM 모델·μFE 선형 영역·RR floor 및 history 검증은 각각 별도로 남습니다.',
              'L/W 확인은 명목 치수의 출처 확인입니다. 치수 불확도와 모델 유효성은 별도이며, 현재 프로필에는 불확도가 등록되지 않았습니다.',
              '원래 gate sweep ±20 V와 ±40 V는 서로 다른 stress 조건입니다. crop을 하더라도 같은 비교 조건으로 처리하지 않습니다.','',
              '## 2. 수치 · 추출 방법 · bias · provenance','',
              '| 지표 | 값·상태 | 방법 | bias·선택 구간 | 원본 근거·한계 |','|---|---|---|---|---|']
    gid=(g or {}).get('group_id');points=[p for p in additional.get('points',[]) if p['group_id']==gid]
    for name,label in [('conductance','Signed G'),('gm','Signed raw gm'),('gm_over_vds','gm/Vds'),('normalized_gm','Signed 정규화 gm'),('normalized_abs_gm','절댓값 정규화 gm'),('mobility_linear','Signed μFE')]:
        selected=[p for p in points if p['parameter']==name]
        if selected:
            p=min(selected,key=lambda p:abs(p['evaluation_voltage_v']))
            lines.append(f'| {label} | {value(p)} · {state(p)} | {cell(p["definition"])} | Vg/Vds={number(p["evaluation_voltage_v"],"V")} · {cell(p["fixed_voltages_v"])} | 원본 행 {p.get("source_row")} · {cell(p.get("source_x_cell"))}/{cell(p.get("source_id_cell"))}; {cell("; ".join(p.get("assumptions",[])) or "직접 파생 관측 후보")} |')
        else:lines.append(f'| {label} | 추출하지 않음 · 보류 | 비영 분모와 유효 측정 배열 필요 | {cell((g or {}).get("conditions",{}))} | 0 또는 결측을 대체하지 않음 |')
    for p in additional.get('extractions',[]):
        if p['group_id']!=gid or p['parameter'] not in ('vth_yfm','ss_min','ss_average','vth_additional','on_off_ratio'):continue
        lines.append(f'| {cell(p["parameter"])} (기존 후보 보존) | {value(p)} · {state(p)} | {cell(p.get("definition","필수 자료 필요"))} | {cell(p.get("window_v","미확인"))} | 자동 구간/모델 검증 전; {cell(p.get("source_rows",[]))} |')
    for parameter,label in [('id_over_width','Signed Id/W'),('gm_over_width','Signed gm/W')]:
        selected=[p for p in report['direct_metrics'] if p['group_id']==gid and p['parameter']==parameter]
        if selected:
            p=min(selected,key=lambda p:abs(p['evaluation_voltage_v']))
            lines.append(f'| {label} | {value(p)} · {state(p)} | {cell(p["formula"])} | Vg/Vds={p["evaluation_voltage_v"]} V | 확인 W 명목값 사용; 원본 행 {p["source_row"]}; 치수 불확도 별도 |')
        else:lines.append(f'| {label} | 추출하지 않음 · 보류 | 확인 W와 유효 배열 필요 | 개별 bias·방향 | W를 임의 설정하지 않음 |')
    ratio=(g or {}).get('transfer_metrics',{}).get('current_range_ratio',{})
    lines.append(f'| 측정 Imax/Imin | {value(ratio)} · {state(ratio)} | 관측 abs(Id) 범위의 비; device Ion/Ioff가 아님 | {cell(ratio.get("evaluated_range_v"))} | 검출한계·지정 on/off 점은 별도 확인 |')
    lines+=['| ΔVT / hysteresis | 추출하지 않음 · 보류 | 같은 Vth 정의의 순·역 sweep 필요 | 원래 stress·순서·history 일치 필요 | 임의 차이를 hysteresis로 명명하지 않음 |',
            '| gm+/gm− | 사용 가능한 고정 Vds의 signed gm만 제공 | dId/dVg | 양·음 bias는 Figure 2j 범례 참조 | 없는 극성을 복제하거나 부호 반전하여 만들지 않음 |']
    group=next((p for p in report['groups'] if p['group_id']==gid),{})
    ss=group.get('ss_summary',{})
    for key,label in [('value_min','직접 SS min'),('value_average','직접 SS average')]:
        v=ss.get(key);assumed=ss.get('candidate_min_assuming_si' if key=='value_min' else 'candidate_average_assuming_si')
        txt=number(v,'mV/dec') if v is not None else number(assumed,'mV/dec')+' · V/A 가정 참고값' if assumed is not None else '추출하지 않음'
        exploratory=ss.get('exploratory_min' if key=='value_min' else 'exploratory_average')
        if exploratory is not None:txt=number(exploratory,'mV/dec')+' · 탐색 배열 참고값 · 검출한계 미확인'
        lines.append(f'| {label} | {txt} · {state(ss)} | 1000/abs(d(log10(abs(Id)))/dVg); {cell(ss.get("weighting"))} | {cell(ss.get("window_v"))}; n={ss.get("n",0)}; {cell(ss.get("span_decades"))} dec | floor·subthreshold·온도 검증 별도; 자동 10–30%는 후보 |')
    detected=[p for p in report['polarity_pairs'] if p['positive_group']==gid and p['rr'] is not None]
    bounded=[p for p in report['polarity_pairs'] if p['positive_group']==gid and p['rr_lower_bound'] is not None]
    if detected:
        p=min(detected,key=lambda p:abs(p['vg_v'] or 0))
        lines.append(f'| RR / ΔG / AG | {number(p["rr"],"1")} / {number(p["delta_g_s"],"S")} / {number(p["a_g"],"1")} · 후보 | abs(I(+u))/abs(I(−u)); signed G 유지; ΔG=abs(G+)−abs(G−); AG=ΔG/(abs(G+)+abs(G−)) | abs(Vds)={p["evaluation_abs_vds_v"]} V; Vg={p["vg_v"]} V | 양극성 detected·조건 검토; 양쪽 support와 가중치 '+link('research_report.json','근거 JSON')+' |')
    elif bounded:
        p=bounded[0];lines.append(f'| RR 하한 | ≥{p["rr_lower_bound"]:g} · 하한 | 음전류 미검출·확인 floor 사용 | abs(Vds)={p["evaluation_abs_vds_v"]} V; Vg={p["vg_v"]} V | 측정 최대 RR 또는 정확한 AG로 해석하지 않음 |')
    else:lines.append('| RR / ΔG / AG | 추출하지 않음 · 보류 | ±Vds 짝·history·floor 확인 필요 | 평가 abs(Vds) 필수 | 원래 범위·블록·방향·순서를 보존하여 비교 |')
    for name,label in [('Rc','Rc'),('TLM','Rsh / TLM'),('mu_con','μcon'),('nS','nS'),('DIBL','DIBL'),('Isat','Isat')]:
        lines.append(f'| {label} | 추출하지 않음 | 추가 측정·모델 조건 필요 | 비교 조건 미확인 | {cell(report["unavailable"][name])} |')
    lines+=['','전체 행별 값·정의·SI 단위·source hash·원본 행/셀: '+link('fet_parameters.csv','추가 지표 CSV')+' · '+link('research_report.json','새 계산 근거 JSON'),
            'YFM은 signed Vds/2 보정과 보정 전 절편을 모두 근거 JSON에 보존합니다. R=Vds/Id, 1/gds, Rs는 각각 정의가 다르며 Rc의 증거가 아닙니다.','',
            '## 3. Figure 2 · a–m 패널','',
            '아래 그림은 첫 원래 획득 블록·방향·순서에 속한 개별 곡선입니다. 다른 블록과 모든 이전 그림은 감사 영역에서 확인할 수 있습니다.','']
    for panel in manifest:
        letter=panel['panel'];lines += [f'### Figure 2{letter}. {panel["title"]}','']
        name=panel.get('file');verified=False
        if panel['generation_status']=='generated' and name:
            try:verify_png(directory/name);verified=True
            except (OSError,ValueError):pass
        if verified:
            lines += [image(name,'Figure 2'+letter),link(name,'실제 PNG 열기'),'','상태: 생성·PNG 읽기 검증 완료 · '+STATUS.get(panel.get('metric_status'),'후보'),
                      panel.get('caption','')+' · '+panel.get('units_note',''),
                      '데이터: '+link('curves.csv','원본 순서 곡선 CSV')+' · '+link('research_report.json','계산·구간·배제 근거'),'']
        else:
            status='생성 실패' if panel['generation_status']=='failed' or (panel['generation_status']=='generated' and not verified) else '구조 표로 제공' if letter=='a' else '보류' if panel['generation_status']=='held' else '미생성 · 추출 불가'
            lines += ['**'+status+'** — '+cell(panel.get('reason','생성 기록의 PNG를 읽을 수 없습니다.')),'']
    lines+=['## 4. 비교 조건 · Table 2','',
            '| 비교 차원 | 현재 범위 | 비교 전에 필요한 확인 |','|---|---|---|',
            f'| 데이터 범위 | 파일 1개 · 개별 곡선 {len(summary.get("groups",[]))}개 · 소자/독립 반복 수 미확인 | 반복·방향·블록을 합치지 않음 |',
            '| 원래 sweep/stress | '+cell((g or {}).get('original_sweep',{}))+' | ±20/±40을 crop으로 동등화 금지 |',
            '| bias·환경·timing | '+cell(display_conditions)+' | 전극·극성·pre-bias·history·광·온도 확인 |',
            '| 단위·모델 | 개별 지표 상태 유지 | 단위 확인과 SS/YFM/μFE/RR 검증 분리 |',
            '| 문헌·다른 소자 | 이 파일에서 성능 순위를 산출하지 않음 | 동일 정의·geometry·bias·환경·접촉 처리·독립 반복 필요 |','',
            '## 5. 의미와 한계 · 다음 확인','',
            '관측된 전류 변화와 국소 미분은 측정 조건에 의존합니다. Rs/a/j0 등 유효 모델 계수만으로 고유 접촉저항·장벽·전도 경로를 입증하지 않습니다.','',
            '1. 실제 측정일/시간, 광 조건, delay 충돌, 단위·stress 이력을 확인합니다.',
            '2. 같은 원래 sweep·블록·순서의 ±Vds transfer/output과 검출한계 근거를 확보합니다.',
            '3. 접촉 분리·이동도 해석이 필요하면 TLM/4-probe, 검증된 nS와 독립 반복을 추가합니다.','',
            '참고 형식: [Nature Electronics 논문](https://doi.org/10.1038/s41928-022-00798-8). 이 노트의 수치는 해당 문헌이나 예시값에서 복사하지 않았습니다.','',
            '<details>','<summary>감사 상세 · 기존 계산/QC · 모든 이전 그림과 원본 근거</summary>','',
            '자동 생성은 기존 연구노트와 사용자 메모를 덮어쓰지 않습니다. 기존 QC·미확인 지표·원래 배열 및 링크는 아래에 보존합니다.','']
    lines+=details(summary,assets,directory)
    lines += ['','추가 출력 계약 근거: '+link('research_report.json')+' · '+link('figure2_manifest.json'),'']
    for p in sorted(directory.iterdir()):
        if p.is_file() and p.suffix.lower() in ('.csv','.json','.png'):lines.append('- '+link(p.name))
    lines+=['','</details>','']
    return '\n'.join(lines)
