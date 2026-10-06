"""Read-only, Korean presentation of saved evidence. No metric certification here."""
import json
import math
from pathlib import Path

QUESTIONS = {
    'vd': '같은 크기의 양·음 드레인 전압에서 전류가 얼마나 다른가?',
    'vg': '게이트 전압에 따라 전류가 어떻게 변하고, 가장 민감한 구간은 어디인가?',
    'photo': '같은 조건에서 빛에 의해 전류가 얼마나 변하는가?',
}
LABELS = {'measurement_date':'측정 날짜', 'measurement_time':'측정 시간',
          'device_name':'소자', 'device_type':'소자 종류', 'illumination':'광 조건',
          'electrodes':'전극', 'polarity':'극성', 'sweep_delay_s':'delay', 'hold_s':'hold',
          'pre_bias':'이전 바이어스', 'environment':'환경', 'history':'측정 이력',
          'optical_power_w':'입사 광파워', 'units_confirmed':'전압·전류 단위 확인'}
STATUS = {'valid':'사용 가능', 'bound':'한계값만 제공', 'candidate':'참고 후보 · 검증 전',
          'ambiguous':'모호함 · 하나의 값으로 판단 불가', 'unavailable':'보류 · 사용 불가',
          'confirmed':'확인됨', 'inferred':'미확인 · 추정', 'missing':'미확인', 'conflict':'서로 다른 기록 · 확인 필요',
          'converged':'수렴한 모델 추정', 'not_run':'추출하지 않음', 'failed':'실패', 'assumed':'가정 · 미확인', 'not_assessed':'평가하지 않음'}
REASONS = {
    'unconfirmed_voltage_or_current_units':'전압·전류 단위 미확인',
    'unconfirmed_units':'전압·전류 단위 미확인', 'unconfirmed_units_for_bound':'한계값의 단위 미확인',
    'detection_limit_unknown':'검출한계 미확인', 'raw_endpoint_maximum':'미분 최대가 스윕 끝점에 있음',
    'constant_current_method_criterion_window_not_set':'문턱전압 추출 기준과 구간 미설정',
    'valid_monotone_subthreshold_window_and_detection_limit_required':'SS 추출 구간·검출한계 확인 필요',
    'confirmed_L_W_Cox_and_linear_regime_required':'소자 치수·게이트 용량·선형 동작 구간 확인 필요',
    'stable_across_configured_windows_noise_and_units_need_confirmation':'여러 미분 구간에서 유지된 내부 후보 · 잡음 검토 필요',
    'raw_endpoint_maximum':'끝점 미분 최대 · 내부 후보와 다름',
}


def yaml_scalar(value):
    return "" if value is None else json.dumps(value,ensure_ascii=False)


def cell(value):
    if value is None:return '미확인'
    if isinstance(value, bool):return '예' if value else '아니요'
    return str(value).replace('|', '\\|').replace('\n', ' ').replace('\r', ' ')


def number(value, unit='1'):
    """Three significant figures. A positive scale preserves the signed value."""
    if value is None:return '추출하지 않음'
    if not isinstance(value, (int,float)) or not math.isfinite(value):return '사용 불가'
    units = {'A':[(1e-12,'pA'),(1e-9,'nA'),(1e-6,'μA'),(1e-3,'mA'),(1,'A')],
             'A/V':[(1e-12,'pA/V'),(1e-9,'nA/V'),(1e-6,'μA/V'),(1e-3,'mA/V'),(1,'A/V')],
             'ohm':[(1,'Ω'),(1e3,'kΩ'),(1e6,'MΩ'),(1e9,'GΩ')],
             'Ω':[(1,'Ω'),(1e3,'kΩ'),(1e6,'MΩ'),(1e9,'GΩ')],
             'S':[(1e-12,'pS'),(1e-9,'nS'),(1e-6,'μS'),(1e-3,'mS'),(1,'S')],
             'm':[(1e-9,'nm'),(1e-6,'μm'),(1e-3,'mm'),(1,'m')]}
    scale, label = 1, '' if unit == '1' else unit
    if unit in units and value:
        scale,label = next(((s,u) for s,u in reversed(units[unit]) if abs(value)>=s), units[unit][0])
    return f'{value / scale:.3g}' + (f' {label}' if label else '')


def state(status):return STATUS.get(status,'확인 필요')


def reason(code):return REASONS.get(code,'평가 조건 또는 근거 부족 · 상세 JSON 확인')


def field(summary, key):
    f = summary.get('research_context',{}).get('fields',{}).get(key,{})
    value=f.get('value')
    if value is None:return '미확인'
    text=number(value, f.get('unit') or '1') if isinstance(value,(int,float)) and not isinstance(value,bool) else cell(value)
    if f.get('status') != 'confirmed':
        source=str(f.get('source',''))
        tag='파일명 추정' if 'filename' in source else ('폴더 추정 · 미확인' if 'folder' in source else '미확인 · 기록값')
        text += f' ({tag})'
    return text


def representative(summary):
    """First acquisition block/direction, nearest known fixed bias to zero, then source order."""
    groups=summary.get('groups',[])
    if not groups:return None
    first=groups[0]
    selected=[g for g in groups if (g.get('axis'),g.get('gate_block_id'),g.get('direction')) ==
              (first.get('axis'),first.get('gate_block_id'),first.get('direction'))]
    fixed='vg' if first['axis']=='vd' else 'vd'
    def key(g):
        v=g.get('conditions',{}).get(fixed)
        return (abs(v) if isinstance(v,(int,float)) and math.isfinite(v) else math.inf, groups.index(g))
    return min(selected,key=key)


def group_condition(g):
    if not g:return '곡선 없음'
    fixed='vg' if g['axis']=='vd' else 'vd'
    bias=number(g.get('conditions',{}).get(fixed),'V')
    d={'forward':'증가 방향','reverse':'감소 방향','constant':'고정 전압'}.get(g.get('direction'),'방향 미확인')
    return f'{fixed.capitalize()}={bias} · {d} · {cell(g.get("gate_block_id"))} / {cell(g.get("group_id"))}'


def conditions(summary, g=None):
    g = g or representative(summary)
    sweep=(g or {}).get('original_sweep',{})
    lo=sweep.get('min_v',(g or {}).get('x_min_v'));hi=sweep.get('max_v',(g or {}).get('x_max_v'))
    unit_tag=' (V 가정 · 미확인)' if g and g.get('units_review_required') else ' (원본 기록)'
    sweep_text=f'{number(lo,"V")}~{number(hi,"V")}{unit_tag}' if lo is not None and hi is not None else '미확인'
    return (f'{field(summary,"measurement_date")} · {field(summary,"device_name")} · {field(summary,"illumination")} · '
            f'{group_condition(g)} (원본 기록 · 확인 상태는 상세 참조) · 원래 sweep {sweep_text} · delay {field(summary,"sweep_delay_s")}')


def metrics(g):
    if not g:return []
    out=list(g.get('rr_series',[]))
    out += [m for m in g.get('transfer_metrics',{}).values() if isinstance(m,dict) and 'metric_status' in m]
    out += [m for o in g.get('output_observables',[]) for m in o.values() if isinstance(m,dict) and 'metric_status' in m]
    return out


def usability(summary):
    if not summary.get('groups'):return ['파일 읽기 실패']
    out=['곡선 열람 가능']
    groups=summary['groups']
    if any(not g.get('units_review_required',True) and any(m.get('metric_status') in ('valid','bound') and
              (m.get('value') is not None or m.get('bound_value') is not None) for m in metrics(g)) for g in groups):
        out.append('정량 지표 사용 가능')
    if summary.get('research_context',{}).get('metadata_status')!='confirmed' or any(g.get('units_review_required',True) for g in groups):out.append('조건 확인 필요')
    if any(m.get('metric_status') in ('unavailable','ambiguous') for g in groups for m in metrics(g)):out.append('일부 지표 보류')
    return out


def next_action(summary):
    if not summary.get('groups'):
        return '원본 파일의 데이터 시트에서 전압·전류 열과 첫 측정행을 확인하고, 분석용 파라미터 표인지 실제 측정 파일인지 구분해 측정 폴더에 기록하세요.'
    if any(g.get('units_review_required',True) for g in summary['groups']):
        return '장비 내보내기 설정에서 DrainI와 DrainV/GateV의 단위를 확인한 뒤, GUI의 ‘메타데이터 검토’에서 단위 확인값·출처·확인 이유를 기록하세요.'
    fields=summary.get('research_context',{}).get('fields',{})
    for key in ('illumination','device_name','measurement_date','history','sweep_delay_s'):
        if fields.get(key,{}).get('status')!='confirmed':
            return f'실험 기록에서 {LABELS[key]}을 확인한 뒤, GUI의 ‘메타데이터 검토’에 확인값과 출처·이유를 기록하세요.'
    if any(m.get('metric_status')=='ambiguous' for g in summary['groups'] for m in metrics(g)):
        return '접힌 상세의 해당 곡선과 원본 셀에서 모호한 평가 구간을 확인하고, 어느 구간을 사용할지 실험 기록에 남기세요.'
    return '현재 저장된 근거에서 우선 해결할 추가 확인 사항이 없습니다. QC PASS는 연구자 검토 완료를 뜻하지 않습니다.'


def metric_text(m, held=False):
    if held or m.get('metric_status')=='unavailable':return '보류 · 사용 불가'
    if m.get('metric_status')=='ambiguous':return '모호함 · 하나의 값으로 판단 불가'
    if m.get('metric_status')=='bound':
        op={'lower': '≥', 'upper':'≤', 'lower_bound':'≥','upper_bound':'≤'}.get(m.get('bound_type'),'한계값')
        return f'{op} {number(m.get("bound_value"),m.get("unit","1"))} · 한계값만 제공'
    return number(m.get('value'),m.get('unit','1'))+' · '+state(m.get('metric_status'))


def key_metrics(summary, directory=None):
    g=representative(summary)
    if not g:return [],[]
    held=g.get('units_review_required',True)
    condition=group_condition(g)
    items=[]; assumptions=[]
    def add(label,m,at):
        items.append((label,metric_text(m,held),at+' · '+condition))
        value=m.get('candidate_value_assuming_si')
        if held and value is not None:
            assumptions.append(f'{label}: {number(value,m.get("unit","1"))} · {at} · 정량 사용 보류')
    if g['axis']=='vd':
        snapshot=summary.get('config_snapshot',{})
        if directory and (Path(directory)/'config_snapshot.json').is_file():
            snapshot=json.loads((Path(directory)/'config_snapshot.json').read_text(encoding='utf-8-sig'))
        cfg=snapshot.get('analysis',{})
        target=cfg.get('rr_voltage_v',cfg.get('rr_voltage',1.0))
        rr=next((r for r in g.get('rr_series',[]) if r.get('evaluation_abs_vd_v')==target),None)
        fallback=rr is None
        if rr is None and g.get('rr_series'):rr=min(g['rr_series'],key=lambda m:abs(m['evaluation_abs_vd_v']-target))
        if rr:
            u=rr['evaluation_abs_vd_v']
            add('RR = |Id(+Vd)| / |Id(-Vd)|',rr,f'|Vd|={number(u,"V")}'+(f' · 설정 {number(target,"V")} 미저장: 가장 가까운 저장 조건' if fallback else ''))
            for sign,key in ((1,'positive_current'),(-1,'negative_current')):
                m=rr.get(key,{})
                add('양 전압 전류' if sign==1 else '음 전압 전류',m,f'Vd={number(sign*u,"V")}')
                if held and m.get('value') is not None:
                    assumptions.append(f'{items[-1][0]}: {number(m["value"],"A")} · Vd={number(sign*u,"V")} · 정량 사용 보류')
    else:
        transfer=g.get('transfer_metrics',{})
        # A stored measured point is selected, never interpolated or used to certify a metric.
        if directory and (Path(directory)/'curves.csv').is_file():
            import pandas as pd
            data=pd.read_csv(Path(directory)/'curves.csv',float_precision='round_trip')
            data=data[data['group_id']==g['group_id']]
            if len(data):
                row=data.iloc[(data['x_v'].abs()).argmin()]
                eligible=row.get('metric_eligible',True)
                m={'value':float(row['id_a']),'unit':'A','metric_status':'candidate' if eligible else 'unavailable'}
                if held:m['candidate_value_assuming_si']=m['value']
                add('원본 측정점의 Id',m,f'Vg={number(float(row["x_v"]),"V")} · 0 V에 가장 가까운 저장점')
        internal=transfer.get('internal_peak_abs',{})
        add('gm 내부 후보의 크기 |gm|',internal,f'Vg={number(internal.get("vg_v"),"V")}')
        extra=next(((k,transfer[k]) for k in ('vth','ss','mobility') if transfer.get(k,{}).get('value') is not None),None)
        if extra:
            k,m=extra;add({'vth':'문턱전압','ss':'서브스레숄드 기울기','mobility':'이동도'}[k],m,'저장된 추출 구간 · 상세 JSON 참조')
        elif transfer.get('raw_peak_abs'):
            m=transfer['raw_peak_abs'];add('raw 미분 최대 |gm|',m,f'Vg={number(m.get("vg_v"),"V")} · '+('끝점 최대 · 내부 후보와 다름' if m.get('endpoint') else '비평활 미분'))
    return items[:3],assumptions[:3]


def fold(title, lines):
    return ['> [!info]- '+title, '>']+['> '+part if part else '>' for line in lines for part in str(line).split('\n')]+['']


def rr_representatives(summary):
    g=representative(summary)
    if not g or g['axis']!='vd':return []
    groups=[x for x in summary['groups'] if (x.get('axis'),x.get('gate_block_id'),x.get('direction')) == (g.get('axis'),g.get('gate_block_id'),g.get('direction'))]
    groups=sorted(groups,key=lambda x:(x.get('conditions',{}).get('vg',math.inf),x['group_id']))
    indices=sorted(set(round(i*(len(groups)-1)/4) for i in range(5)))
    return [groups[i] for i in indices]


def details(summary, assets, directory):
    lines=[]
    table=['| 항목 | 값 | 상태 | 출처 |', '|---|---|---|---|']
    for k,f in summary.get('research_context',{}).get('fields',{}).items():
        table.append(f'| {cell(LABELS.get(k,k))} | {field(summary,k)} | {state(f.get("status"))} | {cell(f.get("source"))} |')
    c=summary.get('research_context',{})
    table += ['',f'실제 측정 시간: {field(summary,"measurement_time")}',
              f'장비 기록 시각: {cell(c.get("equipment_record_time",{}).get("value"))} (측정 날짜와 별개 · 시간대 미확인)',
              f'처리 시각: {cell(summary.get("created_at"))}',
              f'원본 경로: `{cell(summary.get("source_relative_path"))}`',
              f'원본 보관 위치: `{cell(summary.get("source_locations",{}).get("snapshot_relative_to_analysis"))}`',
              f'계산 버전: {cell(summary.get("version"))} · 코드 SHA-256: `{cell(summary.get("code_sha256"))}`',
              f'원본 SHA-256: `{cell(summary.get("source_sha256"))}`',
              f'[[{assets}/result.json|전체 조건·출처·후보·사용자 검토 이력 JSON]]']
    lines += fold('전체 조건·출처·처리 시각',table)
    qc=['## QC','',f'기존 QC: **{cell(summary.get("qc",{}).get("overall"))}**. 원래 상태를 보존하며 연구자 검토 완료로 바꾸지 않았습니다.']
    # Original values/statuses remain verbatim in the immutable JSON evidence.
    qc += ['','```json',json.dumps(summary.get('qc',{}),ensure_ascii=False,indent=2),'```',
           f'[[{assets}/result.json|단계별 QC·원래 상태·원본 행 및 셀]]']
    lines += fold('QC 원래 항목과 상태',qc)
    traces=['대표 RR 조건 규칙: 첫 획득 블록·방향에서 Vg 순서의 최소·25%·중앙·75%·최대 위치를 선택합니다. 곡선의 모양이나 RR 크기로 고르지 않습니다.', '',
            r'| 곡선 | 조건 | 평가 \|Vd\| (V) | RR / 한계값 | 상태 |','|---|---|---|---|---|']
    selected=rr_representatives(summary)
    for g in selected:
        rr=next((r for r in g.get('rr_series',[]) if r['evaluation_abs_vd_v']==1.0),next(iter(g.get('rr_series',[])),{}))
        if rr:traces.append(f'| {g["group_id"]} | {group_condition(g)} | {number(rr.get("evaluation_abs_vd_v"))} | {metric_text(rr,g.get("units_review_required",True))} | {state(rr.get("metric_status"))} |')
    if not selected:traces=['Id–Vg 지표는 원래 미분 구간·원본 셀과 함께 아래 JSON/CSV에 보존했습니다.']
    traces+=['',f'전체 개별 곡선 {len(summary.get("groups",[]))}개. 모든 trace 결과·평가 전압·정밀값·보간 근거는 CSV/JSON에서 확인하세요.',
             *([f'[[{assets}/observable_metrics.csv|전체 지표 CSV]]'] if (Path(directory)/'observable_metrics.csv').is_file() else ['이전 저장 결과에는 신규 지표 CSV가 없습니다. 보존된 원본 JSON/CSV를 확인하세요.']),f'[[{assets}/result.json|전체 trace·피팅 계수·구간·원본 셀 JSON]]','',
             '| 곡선 | 조건 | 원래 sweep | 점 수 |','|---|---|---|---|']
    for g in summary.get('groups',[]):
        s=g.get('original_sweep',{})
        traces.append(f'| {cell(g.get("group_id"))} | {group_condition(g)} | {number(s.get("min_v",g.get("x_min_v")),"V")}~{number(s.get("max_v",g.get("x_max_v")),"V")} | {g.get("n","미확인")} |')
    lines+=fold('대표 조건 3~5개와 전체 trace 결과' if selected else '전체 trace 결과',traces)
    fits=[('Id–Vd: RR = |Id(+u)|/|Id(-u)|.' if representative(summary) and representative(summary)['axis']=='vd' else 'Id–Vg: gm = dId/dVg (부호 보존).'),
          '일반 피팅 잔차는 측정 signed Id − 모델 signed Id입니다. 극성별 정류 모델 그림의 잔차는 측정 |Id| − 모델 |Id|입니다.',
          '피팅 적용점·제외점·구간·계수·실패 이유는 아래 근거에 그대로 보존되어 있습니다. 제외점은 빨간 ×, 모델은 범례로 구분합니다.']
    for g in summary.get('groups',[]):
        if g.get('fits') or g.get('rectifier_models',{}).get('models'):
            fits.append(f'{g["group_id"]}: 실제 수행 모델 '+', '.join(f.get('model','미확인') for f in [*g.get('fits',[]),*g.get('rectifier_models',{}).get('models',[])]))
    for name in ('fit_results.csv','model_diagnostics.csv','rectifier_parameters.csv','result.json'):
        if (Path(directory)/name).is_file():fits.append(f'[[{assets}/{name}|{name}]]')
    lines+=fold('수식·실제 피팅·계수와 잔차 정의',fits)
    fet_path=Path(directory)/'fet_parameters.json'
    if fet_path.is_file():
        from .metric_store import read_metric_json
        report=read_metric_json(fet_path)
        tab=['기존 gm·RR·QC·단위 확인·Vth/SS 필드는 바꾸지 않았습니다. 아래는 추가 관측량과 탐색용 추출입니다.',
             'G=Id/Vds는 직류 할선 전도도이고, gds=dId/dVds는 국소 출력 기울기입니다. R=Vds/Id와 rd=1/gds도 서로 다르며 접촉저항이 아닙니다.',
             'YFM: Y=|Id|/√|gm|의 선형 후보 구간에서 x 절편을 구하고, 점진 채널 선형 모델의 signed Vds/2를 빼 Vth 후보를 표시합니다. 보정 전 절편도 JSON에 보존합니다. YFM 잔차는 관측 Y − 선형 모델 Y이며 회색 영역은 피팅 구간, 회색 ×는 구간 밖 점입니다. 자동 구간은 측정 |Id| 변화폭의 20–80% 중 가장 긴 연속 구간으로 고르며, 가장 좋은 R²를 찾아 고르지 않습니다.',
             'SS min/average는 동일한 표시 구간의 SSlocal=1000 ln(10)|Id/gm| (mV/dec)의 최솟값/산술평균입니다. 자동 저전류 구간은 max|Id|의 10–30%이며, 확인된 아임계 구간을 뜻하지 않습니다.',
             '검출한계·선형 동작·아임계 구간이 확인되지 않으면 YFM·SS·이동도는 탐색용 후보입니다. 단위 미확인 값은 V/A 가정 참고값으로만 표시합니다.', '',
             '| 소자 조건 | 값·단위 | 확인 상태·출처 |', '|---|---|---|']
        names={'channel_length_m':'채널 길이 L','channel_width_m':'채널 폭 W','oxide_thickness_m':'절연막 두께',
               'dielectric':'절연막','relative_permittivity':'상대유전율','cox_f_per_m2':'Cox'}
        for key,label in names.items():
            item=report.get('settings',{}).get(key,{})
            value=number(item.get('value'),item.get('unit','1')) if isinstance(item.get('value'),(int,float)) else cell(item.get('value'))
            tag='가정 · 미확인' if item.get('status')=='assumed' else state(item.get('status'))
            tab.append(f'| {label} | {value} | {tag} · {cell(item.get("source"))} |')
        tab+=['','| 곡선 | 추가 지표 | 값·단위 | 평가 구간·위치 | 상태 |','|---|---|---|---|---|']
        labels={'vth_yfm':'YFM Vth','ss_min':'SS min','ss_average':'SS average','mobility_linear':'선형 이동도',
                'on_off_ratio':'지정 on/off 전류 비율','contact_resistance':'접촉저항','hysteresis_voltage':'전압 히스테리시스',
                'carrier_density':'캐리어 밀도','trap_density':'트랩 밀도'}
        for m in report.get('extractions',[]):
            if m['parameter'] not in labels:continue
            candidate=m.get('candidate_value_assuming_si')
            value=metric_text(m)
            if candidate is not None:value=number(candidate,m.get('unit','1'))+' · V/A 가정 참고값 · 정량 사용 보류'
            window=m.get('window_v');where=(f'{number(window[0],"V")}~{number(window[1],"V")}' if window else '필요 조건 부족')
            if m.get('peak_vg_v') is not None:where+=f' · Vg={number(m["peak_vg_v"],"V")}'
            tab.append(f'| {cell(m["group_id"])} | {labels[m["parameter"]]} | {cell(value)} | {cell(where)} | {state(m.get("metric_status"))} |')
        tab+=['','접촉저항은 TLM/4-probe 자료 없이 추출하지 않습니다. 이동도는 geometry·Cox·동작 구간을 명시한 2-terminal 유효 후보이며 고유 이동도로 확정하지 않습니다.',
              f'[[{assets}/fet_summary.csv|YFM Vth · SS min/average · 추출 상태 전체 표 CSV]]',
              f'[[{assets}/fet_parameters.csv|추가 G · gds · 저항 · gm · 이동도 · 누설의 전체 점 CSV]]',
              f'[[{assets}/fet_parameters.json|추가 지표 정의·구간·가정·모델 계수·원본 행 JSON]]']
        for name in summary.get('figures',[]):
            if ('_fet_' in name or name.startswith('fet_')) and (Path(directory)/name).is_file():tab += [f'![[{assets}/{name}|640]]',f'[[{assets}/{name}|원본 해상도 · {name}]]']
        lines+=fold('추가 2D FET 파라미터 · G(Vg) · YFM · SS min/average · 이동도',tab)
    parameter_images=[]
    for name in summary.get('figures',[]):
        if ('_parameter_' in name or name.startswith('parameter_rr_') or name.endswith('_transfer.png')) and (Path(directory)/name).is_file():
            parameter_images += [f'![[{assets}/{name}|640]]',f'[[{assets}/{name}|원본 해상도 · {name}]]']
    if parameter_images:
        lines+=fold('추출 파라미터 그래프 · gm / gm/Vds / 정규화 gm / RR',[
            '저장된 배열과 지표만 그렸습니다. 새 지표를 추출하거나 보류 상태를 유효값으로 바꾸지 않았습니다.',
            'gm/Vds는 A/V², gm/max|gm|은 부호 있는 무차원 값, |gm|/max|gm|은 절댓값 무차원 값입니다. Vds=0 또는 저장 배열이 없는 지표는 그래프를 만들지 않습니다.',
            'raw gm과 Local gm은 기존 전달 그래프에서 구별합니다. Local 2 V/4 V는 주변 전압 구간의 전체 폭입니다.',
            'RR(Vg)는 같은 원래 획득 블록·방향별 보기입니다. 점선은 V/A 가정 참고값, 삼각형은 한계값이며 반복 점을 평균하지 않습니다.',
            *parameter_images])
    images=['대표 보기는 한 조건의 한 개별 곡선입니다. 전체 보기는 원래 개별 곡선을 보존하며 반복 블록·방향을 합쳐 평균하지 않습니다.']
    for name in summary.get('figures',[]):
        if (Path(directory)/name).is_file() and '_fet_' not in name and not name.startswith('fet_') and '_parameter_' not in name and not name.startswith('parameter_rr_') and not name.endswith('_transfer.png') and name!='note_representative.png':images += [f'![[{assets}/{name}|640]]',f'[[{assets}/{name}|원본 해상도 · {name}]]']
    lines+=fold('추가 그림·전체 보기·원본 해상도',images)
    links=[]
    for p in sorted(Path(directory).iterdir()):
        if p.is_file() and p.suffix.lower() in ('.csv','.json'):links.append(f'[[{assets}/{p.name}|{p.name}]]')
    links+=['parsed_points.csv의 원본 행·셀, curves.csv의 획득 순서와 제외점, result.json의 내부 상태 코드를 통해 근거를 추적할 수 있습니다.']
    lines+=fold('모든 CSV/JSON·원본 셀·정밀값',links)
    return lines


def render_note(summary, assets, directory, figure=None):
    if (Path(directory)/'research_report.json').is_file() and (Path(directory)/'figure2_manifest.json').is_file():
        from .fet_research_note import render_research_note
        return render_research_note(summary,assets,directory)
    g=representative(summary); axis=(g or {}).get('axis','vd')
    items,assumptions=key_metrics(summary,directory)
    held=any(x.get('units_review_required',True) for x in summary.get('groups',[]))
    judgment=('원본 곡선은 열람할 수 있지만 정량 지표는 보류 중입니다. 전압·전류 단위가 아직 확인되지 않았습니다.' if held else
              '저장된 원본 곡선과 아래 상태에 해당하는 지표를 열람할 수 있습니다. '+
              next((f'{label}는 {value}이며 {at}에서 평가했습니다.' for label,value,at in items if '추출하지 않음' not in value and '보류' not in value), '핵심 지표를 사용하기 위한 근거가 부족해 결론을 보류합니다.'))
    if not g:judgment='파일을 읽지 못해 곡선과 정량 지표를 제공할 수 없습니다. 원본 파일의 측정 열과 데이터 시작 행을 확인해야 합니다.'
    c=summary.get('research_context',{})
    lines=['---','type: experiment',f'version: {cell(summary.get("version"))}',
           f'measurement_date: {yaml_scalar(c.get("measurement_date"))}',
           f'device_name: {yaml_scalar(c.get("device_name"))}',
           f'illumination: {yaml_scalar(c.get("illumination"))}',
           f'metadata_status: {cell(c.get("metadata_status"))}',
           f'metadata_review_required: {str(c.get("metadata_review_required",True)).lower()}',
           f'analysis_version: {cell(summary.get("version"))}',
           f'job_id: {cell(summary.get("job_id"))}',f'qc: {cell(summary.get("qc",{}).get("overall"))}','---',
           '# '+cell(summary.get('source_filename','측정 기록')),'',
           '## ① 연구 질문','',QUESTIONS[axis],'','## ② 조건 한 줄','',conditions(summary,g),'',
           '## ③ 현재 판단','', '**'+' · '.join(usability(summary))+'**','',judgment,'',
           '## ④ 대표 근거 그림','']
    if figure:
        lines += [f'![[{assets}/{figure}|640]]',f'[[{assets}/{figure}|원본 해상도로 보기]]','']
    else:lines+=['현재 보관된 근거에서 표시할 수 있는 그림이 없습니다.','']
    lines += [('원래 획득 순서의 전압과 부호를 보존한 드레인 전류를 그렸습니다.' if axis=='vd' else
               '위에는 부호를 보존한 Id–Vg 곡선, 아래에는 raw 미분과 가능한 평활 미분 gm을 그렸습니다.'),
              ('같은 크기의 양·음 전압에서 전류를 비교하되, 단위 미확인 시 눈금은 V/A 가정이며 정량 결론은 보류합니다.' if axis=='vd' else
               'raw 끝점 ×와 내부 후보 ○를 구별하고, Local 2 V/4 V는 주변 전압 구간의 전체 폭이므로 peak 위치가 유지되는지 보세요.'),
              '', '**대표 선택:** 첫 획득 블록·방향 → 고정 전압이 0에 가장 가까운 조건 → 동률이면 먼저 기록된 곡선.',
              group_condition(g)+(' · 고정 전압도 V 가정 · 미확인' if held else ' · 원본 열에서 인식한 조건'),'',
              '## ⑤ 핵심 수치 (최대 3개)','']
    if items:
        lines+=['| 항목 | 값·단위·상태 | 평가 전압·조건 |','|---|---|---|']
        lines += [f'| {cell(a)} | {cell(b)} | {cell(c)} |' for a,b,c in items]
    else:lines+=['사용 가능한 수치가 없습니다.']
    if held:lines+=['','공통 보류 이유: 전압·전류 단위 미확인. 아래 가정값은 확정 지표가 아닙니다.']
    if assumptions:lines+=['','> [!warning] V/A 가정 시 참고값 · 정량 사용 보류',
                           '> '+group_condition(g)]+['> - '+a for a in assumptions]
    lines+=['','## ⑥ 의미와 한계','',
            '- **측정에서 관측한 것:** '+(f'{len(summary.get("groups",[]))}개 개별 곡선을 기록했습니다. 개별 곡선은 통계적으로 독립된 반복 측정임을 뜻하지 않습니다.' if g else '파일 읽기 실패로 관측을 요약할 근거가 없습니다.'),
            '- **모델로 추정한 것:** '+('실제로 수행된 피팅과 계수는 접힌 상세에 있습니다. 수렴은 물리적 원인 확인을 뜻하지 않습니다.' if any(x.get('fits') for x in summary.get('groups',[])) else '이번 노트에서는 모델 피팅을 수행하지 않았습니다.'),
            '- **아직 확인되지 않은 해석:** 저장된 관측만으로 전도 메커니즘이나 광응답의 원인을 확정하지 않았습니다.']
    rs=any('rs' in str(k).lower() for x in summary.get('groups',[]) for m in x.get('rectifier_models',{}).get('models',[]) for ps in m.get('parameters',{}).values() if isinstance(ps,dict) for k in ps)
    if not rs:lines+=['','이번 노트에서는 Rs를 추출하지 않았습니다.']
    if axis=='vg':
        lines+=['','gm은 게이트 전압을 조금 바꿨을 때 전류가 얼마나 변하는지를 보여줍니다. 서로 다른 미분 구간에서 peak 위치가 유지되는지 함께 확인합니다.',
                '여기서는 signed gm과 |gm|의 크기를 구별합니다. gm/max|gm| (무차원)과 gm/Vd (A/V²)는 접힌 상세의 별도 정의·그래프로 구별합니다.']
    elif axis=='vd':lines+=['','RR은 동일한 |Vd|에서 양·음 전류 크기의 비입니다. 한계값은 상한/하한이며, 참고 후보는 검증 전 값, 모호함은 단일 값으로 판단 불가, 보류는 정량 사용 불가를 뜻합니다.']
    lines+=['','## ⑦ 다음 확인 한 가지','',next_action(summary),'','## ⑧ 접힌 상세 정보','']
    lines+=details(summary,assets,directory)
    return '\n'.join(lines)+'\n'
