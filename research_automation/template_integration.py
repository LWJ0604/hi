"""Actual Template Creator report output over immutable native evidence."""
import copy
import json
import os
from pathlib import Path
import shutil

from .metric_store import read_metric_json
from .note_presentation import representative, group_condition, number
from .research_panels import verify_png
from .template_report import TemplateBundle, adapt_records, METRIC_MODULES
from .util import digest, atomic_text, write_json

ROOT = Path(__file__).parent / 'report_templates' / 'fet_v1'
TITLES = {'b': ('transfer_log', '전달 곡선 — |Id|와 누설'),
          'c': ('transfer_linear', '전달 곡선 — 부호를 보존한 Id'),
          'd': ('output', '실제 드레인 sweep — 부호를 보존한 Id'),
          'e': ('ss_current', '직접 로그 미분 SS — 추출 조건 검토'),
          'i': ('conductance', '기록된 전압에 대한 signed G'),
          'j': ('gm', '원시·평활 gm — 끝점과 창 폭'),
          'k': ('gm_normalized', 'gm/Vds와 부호·절댓값 정규화'),
          'l': ('rectification', 'RR·AG — 검증된 조건의 극성 비교'),
          'm': ('mu_fe', '유효 이동도 — 입력과 모델 검토')}
SUPPORTED = {'gm': ['gm'], 'conductance': ['conductance'], 'gm_normalized': ['normalized_gm', 'normalized_abs_gm'],
             'ss_current': ['ss_min', 'ss_average'], 'mu_fe': ['mobility_linear'], 'output': ['gds','conductance']}
AXES = {'transfer_log':('Vg (V)','|Id|·|Ig| (A; W 확인 시 A/μm)'),
        'transfer_linear':('Vg (V)','Signed Id (A; W 확인 시 A/μm)'),
        'output':('Vds (V)','Signed Id (A; W 확인 시 A/μm)'),
        'ss_current':('|Id| (A)','SS (mV/dec)'), 'conductance':('Vg (V)','Signed G (S)'),
        'gm':('Vg (V)','Signed gm (A/V)'), 'gm_normalized':('Vg (V)','gm/Vds (A/V²), 정규화 gm (1)'),
        'rectification':('Vg (V)','RR·AG (1)'), 'mu_fe':('Vg (V)','Signed μFE (cm²/(V s))')}


def audit_links(directory):
    labels={'result.json':'기존 결과·조건·QC', 'research_report.json':'전체 계산 기록·정규화 참조',
        'metric_evidence.json':'공유 원본점·단위 변환·provenance', 'research_metrics.csv':'전체 7필드 지표 CSV',
        'observable_metrics.csv':'기존 관측 지표 CSV', 'fet_parameters.json':'기존 FET 계산 기록',
        'fet_parameters.csv':'기존 FET 지표 CSV', 'fet_summary.csv':'기존 FET 요약 CSV',
        'parsed_points.csv':'원본 행·셀과 파싱 기록', 'normalized.csv':'정규화 원본점 CSV',
        'curves.csv':'원래 순서의 곡선·미분 CSV', 'fit_results.csv':'기존 적합 결과 CSV',
        'model_diagnostics.csv':'기존 모델 진단 CSV', 'rectifier_parameters.csv':'기존 유효 모델 계수 CSV',
        'figure2_manifest.json':'그림 manifest·범위·검증 기록', 'note_presentation.json':'미리보기 보존·생성 기록',
        'comparison.json':'전체 기존 비교 판정·원본점', 'photoresponse.csv':'기존 광 비교 계산 CSV',
        'source-1-curves.csv':'비교 결과 1의 원래 곡선', 'source-2-curves.csv':'비교 결과 2의 원래 곡선'}
    return [{'label':label,'path':name} for name,label in labels.items() if (Path(directory)/name).is_file()]


def native_view(summary, directory):
    """Select recorded examples without changing any scalar or native file."""
    report = read_metric_json(Path(directory) / 'research_report.json')
    records = report['metric_records']
    chosen = representative(summary)
    gid = chosen['group_id']
    selected = []
    for parameter in METRIC_MODULES:
        options = [(i, r) for i, r in enumerate(records) if r.get('parameter') == parameter and r.get('group_id') == gid]
        if not options:
            continue
        def key(item):
            _, record = item
            direct = parameter not in ('ss_min', 'ss_average') or str(record['extraction_method'].get('formula', '')).startswith('1000/abs(d(log10')
            endpoint = bool(record['extraction_method'].get('endpoint'))
            voltage = record.get('evaluation_voltage_v')
            return (not direct, endpoint, abs(voltage) if isinstance(voltage, (int, float)) else float('inf'), item[0])
        index, record = min(options, key=key)
        selected.append((index, record))
    return report, selected


def measurement_context(summary, directory, raw_name):
    directory = Path(directory)
    bundle = TemplateBundle(ROOT)
    report, selected = native_view(summary, directory)
    group = representative(summary)
    manifest = json.loads((directory / 'figure2_manifest.json').read_text(encoding='utf-8'))['panels']
    import pandas as pd
    # Copy recorded scalars, including explicitly labelled SI assumptions. No
    # derivative, interpolation, ratio or QC calculation is performed here.
    ss_rows=[{k:r.get(k) for k in ('group_id','parameter','evaluation_voltage_v','signed_current_a','value','candidate_value_assuming_si',
              'candidate_value_exploratory','unit','availability','reason','endpoint','summary_selected','source_row','source_x_cell','source_id_cell')}
             for r in report.get('direct_metrics',[]) if r.get('parameter')=='ss_direct' and not r.get('endpoint') and r.get('summary_selected')
             and r.get('group_id') in {g['group_id'] for g in summary['groups']}]
    if ss_rows:pd.DataFrame(ss_rows).to_csv(directory/'figure2_e_data.csv',index=False,encoding='utf-8-sig')
    figures, proofs = {}, {}
    for panel in manifest:
        if panel.get('panel') not in TITLES:
            continue
        fid, title = TITLES[panel['panel']]
        if panel.get('generation_status') != 'generated' or not panel.get('file'):
            continue
        proof = verify_png(directory / panel['file'])
        expected = panel.get('verification', {})
        if proof['sha256'] != expected.get('sha256'):
            raise ValueError('생성된 그림이 검증 기록과 달라졌습니다: ' + panel['file'])
        proofs[fid] = proof
        scope = panel.get('scope_group_ids', [])
        supports = SUPPORTED.get(fid, []) if group['group_id'] in scope else []
        if fid=='conductance' and group['axis']=='vd':
            supports=[]  # ±u gate slice does not support a G evaluated at another Vds.
        figures[fid] = {
            'id': fid, 'state': 'ready', 'title': title, 'x_axis': AXES[fid][0],
            'y_axis': AXES[fid][1], 'image_path': panel['file'], 'plot_data_path': (
                'figure2_e_data.csv' if panel['panel']=='e' and ss_rows else
                'fet_parameters.csv' if panel['panel'] in ('i','m') else
                'research_metrics.csv' if panel['panel']=='l' else 'curves.csv'),
            'source_refs': ['source-1'], 'run_refs': ['run-' + group['group_id']], 'result_refs': [],
            'caption': {'observation': panel.get('caption') or '저장된 측정 배열과 관측량을 그대로 표시했습니다.',
                        'conditions': panel.get('units_note') or '단위·원래 조건을 먼저 확인하세요.',
                        'limitation': ('실제 output에서 얻은 gate 단면이며 gate sweep이 아닙니다. ' if fid == 'conductance' and group['axis'] == 'vd' else '')
                                      + '곡선·QC PASS만으로 모델이나 연구 사용 가능성이 확인되지는 않습니다.'},
            'render_verified': False, 'error_bars': False, 'validated_repeat_refs': [],
            'data_scope': '원래 획득 block·방향의 저장된 배열; crop 또는 평균 없음',
            'supported_parameters': supports}
    context = adapt_records(bundle.empty, summary, [r for _, r in selected], raw_path=raw_name,
                            lineage_path='curves.csv', figures=figures, evidence_document='research_report.json')
    context['device']['analysis_context'] = 'general_fet'
    device_field=summary.get('research_context',{}).get('fields',{}).get('device_name',{})
    if context['device']['name'] and device_field.get('status')!='confirmed':
        context['device']['name'] += ' · 소자 이름 확인 전'
    context['layout']['fet_module_ids'] = ['gm', 'vt', 'y_function', 'ss', 'mu_fe', 'on_off', 'gds', 'conductance', 'gm_normalized']
    context['modules']['conductance'].update(title='평가점의 signed G = Id/Vds',
        meaning='기록된 원본 전류와 평가 전압의 직류 할선 전도도입니다. gds·접촉저항·극성 대칭을 뜻하지 않습니다.')
    date = summary.get('research_context', {}).get('fields', {}).get('measurement_date', {})
    context['report'].update(metadata_status=summary.get('research_context', {}).get('metadata_status', 'missing'),
                             metadata_review_required=summary.get('research_context', {}).get('metadata_review_required', True),
                             measurement_date=date.get('value') if date.get('status') == 'confirmed' else None)
    fields=summary.get('research_context',{}).get('fields',{})
    rows=[]
    statuses={'confirmed':'확인','inferred':'추정','conflict':'충돌','missing':'확인 전'}
    for key,label in [('measurement_date','실제 측정일'),('measurement_time','실제 측정 시각'),('device_name','소자 이름'),
                      ('illumination','광 조건'),('sweep_delay_s','delay'),('hold_s','hold'),('units_confirmed','단위 확인'),('history','측정 이력')]:
        field=fields.get(key,{})
        candidates=field.get('candidates',[])
        other=[str(c.get('value'))+' ('+str(c.get('source') or '출처 미상')+')' for c in candidates if c.get('value')!=field.get('value')]
        rows.append({'label':label,'value':str(field.get('value')) if field.get('value') is not None else '확인 전',
            'unit':str(field.get('unit') or ''),'source':str(field.get('source') or '근거 미확인'),
            'status':statuses.get(field.get('status'),'확인 전'), 'other_evidence':'; '.join(other[:4]) or '다른 값 기록 없음'})
    context['report']['metadata_rows']=rows
    context['report']['audit_links']=audit_links(directory)
    label = ('VD' if group['axis'] == 'vg' else 'VG') + '=' + number(group.get('conditions', {}).get('vd' if group['axis'] == 'vg' else 'vg'), 'V')
    label += ' · ' + {'forward': '증가 방향', 'reverse': '감소 방향'}.get(group.get('direction'), '방향 확인 전')
    context['report']['conditions_summary'] = context['report']['conditions_summary'].replace(group_condition(group), label)
    for module in context['modules'].values():
        for result_key, record in module['results'].items():
            parameter = next((p for p, (mid, key, _) in METRIC_MODULES.items() if mid == module['id'] and key == result_key), None)
            matching = next(((index, r) for index, r in selected if r.get('parameter') == parameter), None)
            if matching:
                record['extraction']['settings']['evidence_reference'] = 'research_report.json / metric_records/' + str(matching[0])
                record['extraction']['version'] = summary.get('version')
                native = matching[1]
                axis = native.get('axis') or group['axis']
                voltage = native.get('evaluation_voltage_v')
                record['evaluation']['summary'] = ('기록된 gate' if axis == 'vg' else '기록된 drain') + ' 전압 ' + number(voltage, 'V') + ' · ' + label
    context['summary']['hero_figure_id'] = next((fid for fid in ('transfer_linear', 'output', 'transfer_log') if fid in figures), None)
    # Derived evidence remains visible when numerical approval is on hold.
    context['layout']['raw_figure_ids'] = list(figures)
    context['summary']['observations'] = [
        '원래 측정 순서·블록·방향의 곡선을 볼 수 있습니다. 반복 통계나 물리적 경로 증명으로 해석하지 않습니다.',
        '숫자는 원본점·단위·조건과 근거 그림을 갖춘 후보만 표시합니다. 보류된 값은 0이나 확정값으로 채우지 않습니다.']
    context['quality']['review_summary'] = 'QC ' + str(summary.get('qc', {}).get('overall', '미실행')) + '는 데이터 점검 결과이며 연구 사용 가능 판정과 별개입니다.'
    context['quality']['uncertainty_note'] = '검증된 반복 측정의 불확도가 없어 오차 막대를 만들지 않았습니다.'
    context['report']['review_history'] = ['원래 수치·상태·날짜 확인 범위를 보존한 표시 형식 변환']
    context['availability']['no_measurement'] = ['TLM·접촉 분리 Rc/Rsh·nS·μcon: 필요한 길이별 또는 밀도 근거 없음']
    context['availability']['on_hold'].append('RR 전환점: 검증된 탐색 알고리즘·범위가 연결되지 않아 수치 생략; argmin과 구별')
    if group['axis']=='vd':
        context['availability']['on_hold'].append('RR 평가 |Vds|='+str(report.get('primary_evaluation_abs_vds_v'))+' V; ±원본점·조건 일치·검출한계 상태는 research_report.json의 polarity_pairs에서 확인하세요. RR=|I(+u)|/|I(−u)| 방향 고정.')
    return bundle, context, proofs


def render_measurement(summary, directory, assets, destination_relative):
    """Use a fresh asset directory; source snapshots are read-only."""
    directory = Path(directory)
    snapshot = Path(summary['raw_snapshot'])
    if not snapshot.is_file() or digest(snapshot) != summary['source_sha256']:
        raise ValueError('원본 스냅샷을 확인할 수 없습니다. 파일 상태를 확인한 뒤 재시도하세요.')
    raw_name = 'source_measurement' + snapshot.suffix.lower()
    shutil.copy2(snapshot, directory / raw_name)
    bundle, context, proofs = measurement_context(summary, directory, raw_name)
    prefix = os.path.relpath(Path(assets), Path(destination_relative).parent).replace('\\', '/')
    text, checked = bundle.render(context, directory, proofs, prefix)
    write_json(directory / 'report_context.json', checked)
    write_json(directory / 'report_validation.json', {'template_version': checked['report']['template_version'],
        'schema_validated': True, 'source_hash_validated': True, 'number_recalculation': False,
        'png_decoding_verified': True, 'human_pixel_review': False, 'native_metric_storage_changed': False})
    atomic_text(directory / 'report.md', text)
    return text


def render_comparison(entries, pairs, directory, assets, destination_relative, exclusions=None, date_pending=0):
    """Present stored comparison evidence; never compute or approve a new pair."""
    import pandas as pd
    import matplotlib.pyplot as plt
    from .plot_style import export_theme
    from .template_report import finite
    directory = Path(directory)
    bundle = TemplateBundle(ROOT)
    context = copy.deepcopy(bundle.empty)
    context['report'].update(title='선택 결과의 비교 검토', profile='comparison',
        purpose='두 결과의 원래 조건을 확인하고, 기존 비교 판정이 허용한 범위만 검토합니다.',
        analysis_version=entries[0][0].get('version') if entries else None,
        conditions_summary='원래 sweep·방향·블록·이력·단위 일치 확인이 먼저 필요합니다.',
        measurement_date_display='각 원본의 파일별 확인 상태를 아래에서 확인하세요.',
        measurement_date_source_display='파일별 원래 메타데이터; 저장 시각은 실제 측정일로 사용하지 않음')
    context['device']['analysis_context'] = 'general_fet'
    context['sources'], context['runs'], context['figures'], context['comparisons'] = {}, {}, {}, {}
    context['layout'].update(raw_figure_ids=[], fet_module_ids=['photoresponse'], drain_module_ids=[])
    eligible = next((p for p in pairs if p.get('metric_status') == 'candidate' and not p.get('reasons') and p.get('points')), None)
    # Existing pair order, then source order. Never choose by current/RR magnitude.
    chosen = []
    if eligible:
        for side in ('dark', 'light'):
            entry = next((e for e in entries if e[0]['job_id'] == eligible[side+'_job_id']), None)
            if entry:
                group = next((g for g in entry[0]['groups'] if g['group_id'] == eligible[side+'_group_id']), None)
                if group: chosen.append((entry, group))
    if len(chosen) != 2:
        eligible = None
        chosen = [(e, representative(e[0])) for e in entries[:2] if representative(e[0])]
    proofs = {}

    @export_theme
    def plot_source(frame, group, filename, label):
        fig, ax = plt.subplots(figsize=(7.6, 4.2))
        ax.plot(frame['x_v'], frame['id_a'], marker='.', markersize=3, linewidth=1, label=label)
        ax.set(xlabel=('Vg' if group['axis']=='vg' else 'Vds')+' (V)', ylabel='Signed Id (A)', title='Original acquisition order')
        ax.grid(True, alpha=.2); ax.legend(fontsize=8); fig.tight_layout(); fig.savefig(directory/filename); plt.close(fig)

    for index, (entry, group) in enumerate(chosen, 1):
        summary, source_dir = entry
        snapshot = Path(summary['raw_snapshot'])
        if not snapshot.is_file() or digest(snapshot) != summary['source_sha256']:
            raise ValueError('비교 원본 사본의 SHA-256을 확인하지 못했습니다.')
        raw_name = 'source-'+str(index)+snapshot.suffix.lower()
        shutil.copy2(snapshot, directory/raw_name)
        csv_name = 'source-'+str(index)+'-curves.csv'
        shutil.copy2(Path(source_dir)/'curves.csv', directory/csv_name)
        selected = dict(summary, groups=[group])
        view = adapt_records(bundle.empty, selected, [], raw_path=raw_name, lineage_path=csv_name, figures={}, evidence_document='comparison.json')
        sid, rid = 'source-'+str(index), 'run-'+str(index)
        source = next(iter(view['sources'].values())); source['id'] = sid
        run = next(iter(view['runs'].values())); run.update(id=rid, source_refs=[sid])
        context['sources'][sid], context['runs'][rid] = source, run
        frame = pd.read_csv(directory/csv_name, float_precision='round_trip')
        frame = frame[frame['group_id']==group['group_id']]
        if frame.empty: raise ValueError('비교 그림에 사용할 저장 곡선이 없습니다.')
        png_name, fid = 'comparison-source-'+str(index)+'.png', 'comparison-source-'+str(index)
        plot_source(frame, group, png_name, group_condition(group))
        context['figures'][fid] = {'id':fid, 'state':'ready', 'title':'결과 '+str(index)+' · 원래 측정 곡선',
            'x_axis':'Vg' if group['axis']=='vg' else 'Vds', 'y_axis':'Signed Id', 'image_path':png_name,
            'plot_data_path':csv_name, 'source_refs':[sid], 'run_refs':[rid], 'result_refs':[],
            'caption':{'observation':'원본 획득 순서의 signed Id를 보존했습니다.', 'conditions':group_condition(group),
                       'limitation':'V/A 가정 참고 곡선 · 단위 확인 전' if group.get('units_review_required',True) else '단위 확인; 반복 통계·수송 경로 증명 없음'},
            'render_verified':False, 'error_bars':False, 'validated_repeat_refs':[]}
        proofs[fid] = verify_png(directory/png_name)
        context['layout']['raw_figure_ids'].append(fid)
    run_refs = list(context['runs'])
    domains = [json.dumps(g.get('original_sweep',{}),ensure_ascii=False) for _,g in chosen]
    reasons = sorted({r for p in pairs for r in p.get('reasons',[])})
    checks=[]
    if len(chosen)==2:
        (left,lg),(right,rg)=chosen
        for key,label in [('axis','측정 축'),('conditions','고정 바이어스'),('direction','원래 방향'),
                          ('gate_block_id','원래 블록'),('original_sweep','원래 sweep 전체 범위')]:
            a,b=lg.get(key),rg.get(key)
            checks.append({'condition':label,'reference':json.dumps(a,ensure_ascii=False) if a is not None else None,
                'test':json.dumps(b,ensure_ascii=False) if b is not None else None,
                'verdict':'unknown' if a is None or b is None else 'matched' if a==b else 'different',
                'evidence':'원래 result.json; crop·재정렬 없이 읽음'})
        from .comparison import REQUIRED
        for key in (*REQUIRED,'illumination','units_confirmed'):
            a=left[0].get('research_context',{}).get('fields',{}).get(key,{})
            b=right[0].get('research_context',{}).get('fields',{}).get(key,{})
            av=a.get('value') if a.get('status')=='confirmed' else None
            bv=b.get('value') if b.get('status')=='confirmed' else None
            checks.append({'condition':key,'reference':str(av) if av is not None else None,
                'test':str(bv) if bv is not None else None,
                'verdict':'unknown' if av is None or bv is None else 'intentionally_varied' if key=='illumination' else 'matched' if av==bv else 'different',
                'evidence':'파일별 원래 메타데이터 확인 상태'})
    if eligible:
        # Legacy comparison fixtures/results can lack the newer explicit unit
        # field. Their existing engine check still needs confirmed curve units.
        checks=[q for q in checks if q['condition']!='units_confirmed']
        checks.append({'condition':'기존 비교 엔진 단위·조건 판정','reference':'passed','test':'passed',
                       'verdict':'matched','evidence':'comparison.json; 기존 compare_reasons 결과'})
    if not checks:
        checks=[{'condition':'비교 원본 선택','reference':None,'test':None,'verdict':'unknown','evidence':'두 저장 결과가 필요합니다.'}]
    context['comparisons']['selected'] = {'id':'selected', 'question':'광 조건 변화에 따른 전류 차이를 비교할 수 있나요?',
        'run_refs':run_refs, 'status':'approved_for_scope' if eligible else 'unverified',
        'varied_dimensions':['광 조건 dark/light'], 'approved_module_ids':['photoresponse'] if eligible else [],
        'checks':checks,
        'original_domains':domains, 'common_domain':None,
        'reason':'기존 비교 엔진이 해당 쌍의 후보 계산을 허용했습니다.' if eligible else ('; '.join(reasons[:8]) or '확인된 비교 쌍이 없습니다. 원본 조건부터 확인하세요.'),
        'limitations':'원래 범위를 crop하여 스트레스 차이를 없애지 않습니다. 광 파워·반복 오차·메커니즘 확인은 별도입니다.'}
    if eligible and len(run_refs)==2:
        points = eligible['points']
        fig, ax = plt.subplots(figsize=(7.6,4.2))
        ax.plot([p['evaluation_voltage_v'] for p in points], [p['signed_delta_id_a'] for p in points], marker='.', markersize=3)
        ax.set(xlabel=points[0]['axis']+' (V)',ylabel='Signed delta Id (A)',title='Stored light - dark current difference')
        ax.grid(True,alpha=.2);fig.tight_layout();fig.savefig(directory/'photoresponse.png');plt.close(fig)
        fid='photoresponse'
        context['figures'][fid] = {'id':fid,'state':'ready','title':'기록된 signed ΔId = Id(light)−Id(dark)',
            'x_axis':points[0]['axis'],'y_axis':'Signed ΔId (A)','image_path':'photoresponse.png','plot_data_path':'photoresponse.csv',
            'source_refs':list(context['sources']),'run_refs':run_refs,'result_refs':[],
            'caption':{'observation':'기존 비교 결과의 평가점과 전류 차이를 그대로 그렸습니다.',
                       'conditions':eligible.get('presentation_conditions','선택한 원래 쌍'),
                       'limitation':'새 보간·평균·정량 승인 없음; signed ΔId와 Δ|Id|는 다른 값입니다.'},
            'render_verified':False,'error_bars':False,'validated_repeat_refs':[]}
        proofs[fid] = verify_png(directory/'photoresponse.png')
        module=context['modules']['photoresponse'];module.update(status='candidate',figure_ids=[fid],comparison_refs=['selected'],omit_reason=None)
        # A single recorded evaluation point is an example, not a peak or average.
        point=points[0]
        for key,label in [('signed_delta_id_a','Signed ΔId'),('delta_abs_id_a','Δ|Id|')]:
            if not finite(point.get(key)):continue
            rid='result-photoresponse-'+key.replace('_','-')
            module['results'][key]={'id':rid,'label':label,'value':point[key],'unit':'A','display_value':None,
                'value_kind':'exact','relation':'=','status':'candidate','display_approved':False,
                'evaluation':{'summary':'기록된 평가 전압 '+str(point['evaluation_voltage_v'])+' V', 'run_refs':run_refs,
                              'comparison_refs':['selected'],'original_domain':' / '.join(domains)},
                'extraction':{'summary':'기존 비교 결과를 그대로 읽음; '+label,'method':'stored photo_difference',
                              'formula':'Id(light)-Id(dark)' if key=='signed_delta_id_a' else '|Id(light)|-|Id(dark)|',
                              'included_ranges':domains,'excluded_points':[], 'point_lineage_path':'photoresponse.csv',
                              'settings':{'evidence_reference':'comparison.json / first eligible pair / points/0',
                                          'source_points_dark':point.get('source_points_dark'), 'source_points_light':point.get('source_points_light')}},
                'source_refs':list(context['sources']),'figure_ids':[fid],'detail_anchor':rid,
                'validation':{'inputs_complete':True,'method_checked':False,'conditions_checked':False,'qc_passed':False,'model_validated':False,'reason':'기존 후보 계산; 인간 확인·모델 검증으로 승격하지 않음'}}
            context['figures'][fid]['result_refs'].append(rid)
        context['summary']['hero_figure_id']=fid
    else:
        context['summary']['hero_figure_id']=next(iter(context['figures']),None)
    context['summary']['observations']=['선택된 결과 '+str(len(entries))+'개 중 원래 조건을 보존한 대표 '+str(len(chosen))+'개를 표시했습니다.',
        '전체 비교 후보 '+str(len(pairs))+'개, 날짜 선택 보류 '+str(date_pending)+'개; 전체 기록은 첨부 comparison.json과 photoresponse.csv에 보존했습니다.']
    if any(p.get('cross_date_explicitly_selected') for p in pairs):
        context['summary']['observations'].append('다른 날짜를 사용자가 선택했습니다(명시적 선택). 이 선택은 이력·원래 조건 차이를 해소하지 않습니다.')
    context['availability']['on_hold'].append('원래 sweep·gate step·장비 설정 불일치는 crop으로 해결 안 됨; '+str(sum((exclusions or {}).values()))+'개 제외')
    context['next_actions']=[{'action':'두 파일의 실제 광 조건·단위·원래 sweep과 이력을 확인하세요.',
                              'condition_and_decision':'같다고 확인되지 않은 조건은 보류를 유지합니다.'}]
    context['quality']['review_summary']='QC PASS는 연구 비교 사용 가능 판정과 별개입니다.'
    context['availability']['on_hold'] += reasons[:8]+[k+' '+str(v)+'개 제외' for k,v in (exclusions or {}).items()]
    context['report']['audit_links']=audit_links(directory)
    prefix=os.path.relpath(Path(assets),Path(destination_relative).parent).replace('\\','/')
    text,checked=bundle.render(context,directory,proofs,prefix)
    write_json(directory/'report_context.json',checked)
    write_json(directory/'report_validation.json',{'schema_validated':True,'number_recalculation':False,
        'comparison_recomputed':False,'human_pixel_review':False,'source_hash_validated':True})
    atomic_text(directory/'report.md',text)
    return text
