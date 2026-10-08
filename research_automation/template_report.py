"""Bridge to an externally supplied formatting-only FET template.

No extraction, QC changes, date confirmations or comparison approvals occur here.
The production writer uses the supplied bundle over a small read-only view.
"""
import copy
import hashlib
import json
from .naming_metadata import condition_source
import math
from pathlib import Path

from .metric_contract import validate_records
from .metric_store import read_metric_json
from .research_panels import verify_png


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def local_file(root, relative):
    """Resolve report-local artifacts, never URLs, absolute paths or escapes."""
    if not isinstance(relative, str) or not relative or ':' in relative or '\x00' in relative:
        return None
    path = Path(relative)
    if path.is_absolute():
        return None
    root = Path(root).resolve()
    candidate = (root / path).resolve()
    return candidate if candidate.is_relative_to(root) and candidate.is_file() else None


def _digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load_native_records(path, collection):
    """Resolve v1/v2/v3 through the existing lossless reader, without writes."""
    document = read_metric_json(Path(path))
    records = document.get(collection)
    if not isinstance(records, list):
        raise ValueError('기존 계산 결과의 지표 배열을 찾지 못했습니다: ' + str(collection))
    validate_records(records)
    return records


def _local_schema(schema):
    if isinstance(schema, dict):
        for key in ('$ref', '$dynamicRef', '$recursiveRef'):
            if key in schema and not schema[key].startswith('#/'):
                raise ValueError('보고서 스키마는 내부 참조만 사용해야 합니다.')
        for value in schema.values():
            _local_schema(value)
    elif isinstance(schema, list):
        for value in schema:
            _local_schema(value)


class TemplateBundle:
    def __init__(self, root):
        root = Path(root)
        self.root = root / 'automation' if (root / 'automation').is_dir() else root
        required = ['report.md.j2', 'report.schema.json', 'empty_report.json']
        missing = [name for name in required if not (self.root / name).is_file()]
        if missing:
            raise FileNotFoundError('실제 템플릿 묶음이 필요합니다: ' + ', '.join(missing))
        self.template = (self.root / 'report.md.j2').read_text(encoding='utf-8')
        self.schema = json.loads((self.root / 'report.schema.json').read_text(encoding='utf-8'))
        self.empty = json.loads((self.root / 'empty_report.json').read_text(encoding='utf-8'))
        _local_schema(self.schema)
        from jsonschema import Draft202012Validator
        Draft202012Validator.check_schema(self.schema)
        self.validator = Draft202012Validator(self.schema)
        self.validator.validate(self.empty)

    def render(self, context, artifact_root, png_proofs=None, link_prefix=None):
        """Recompute read-only display flags before executing formatting."""
        from jinja2 import StrictUndefined
        from jinja2.sandbox import ImmutableSandboxedEnvironment
        checked = derive_display_flags(context, artifact_root, png_proofs or {})
        self.validator.validate(checked)
        display = copy.deepcopy(checked)
        if link_prefix is not None:
            def prefixed(value):
                return str(link_prefix).rstrip('/') + '/' + value if value else value
            for source in display['sources'].values():
                source['raw_path'] = prefixed(source.get('raw_path'))
            for figure in display['figures'].values():
                for key in ('image_path', 'plot_data_path'):
                    figure[key] = prefixed(figure.get(key))
            for module in display['modules'].values():
                for record in module.get('results', {}).values():
                    record['extraction']['point_lineage_path'] = prefixed(record['extraction'].get('point_lineage_path'))
            for link in display.get('report', {}).get('audit_links', []):
                link['path'] = prefixed(link['path'])
        environment = ImmutableSandboxedEnvironment(undefined=StrictUndefined, autoescape=False)
        environment.policies['json.dumps_kwargs'] = {'sort_keys': True, 'ensure_ascii': False}
        text = environment.from_string(self.template).render(**display)
        if '{{' in text or '{%' in text:
            raise ValueError('완성 보고서에 미해결 템플릿 변수가 있습니다.')
        if len(text.encode('utf-8')) > 1_000_000:
            raise ValueError('보고서가 너무 큽니다. 전체 배열은 근거 파일로 연결하세요.')
        return text, checked


def derive_display_flags(context, artifact_root, png_proofs):
    """Ignore supplied approval booleans; verify each result's own evidence.

PNG proofs are generated separately from actual exported images. They attest
decoding/hash checks, not a human pixel inspection or scientific validity.
"""
    result = copy.deepcopy(context)
    for link in result.get('report', {}).get('audit_links', []):
        if local_file(artifact_root, link.get('path')) is None:
            raise ValueError('전체 계산 근거 파일을 찾지 못했습니다: ' + str(link.get('path')))
    sources = result['sources']
    runs = result['runs']
    figures = result['figures']
    comparisons = result['comparisons']
    for source in sources.values():
        path = local_file(artifact_root, source.get('raw_path'))
        expected = source.get('sha256')
        source['link_validated'] = bool(path and expected and _digest(path) == expected)
        if source.get('confirmed_measurement_date') and not (
                source.get('date_confirmation_scope') and source.get('date_confirmation_evidence')):
            raise ValueError('실제 측정일 확인에는 해당 파일의 확인 범위와 근거가 필요합니다.')
    for fid, figure in figures.items():
        proof = png_proofs.get(fid, {})
        image = local_file(artifact_root, figure.get('image_path'))
        data = local_file(artifact_root, figure.get('plot_data_path'))
        refs = figure.get('source_refs', [])
        good = bool(figure.get('state') == 'ready' and image and data and data.stat().st_size
                    and refs and all(sid in sources and sources[sid]['link_validated'] for sid in refs))
        if good:
            try:
                actual = verify_png(image)
                good = (proof.get('decoded') is True and proof.get('sha256') == actual['sha256']
                        and proof.get('pixels') == actual['pixels'])
            except (OSError, ValueError):
                good = False
        figure['render_verified'] = bool(good)
        if figure.get('state') == 'ready' and not good:
            figure['state'] = 'failed'
            figure['failure_reason'] = '그림·데이터·원본의 실제 파일과 검증 기록을 확인하지 못했습니다.'
            figure['failure_stage'] = 'report_evidence_check'
    anchors = set()
    for mid, module in result['modules'].items():
        displayed = []
        for record in module.get('results', {}).values():
            anchor = record['detail_anchor']
            if anchor in anchors:
                raise ValueError('추출 근거 앵커가 중복되었습니다.')
            anchors.add(anchor)
            refs = record.get('source_refs', [])
            run_refs = record.get('evaluation', {}).get('run_refs', [])
            cids = set(module.get('comparison_refs', [])) | set(record.get('evaluation', {}).get('comparison_refs', []))
            figure_ids = record.get('figure_ids', [])
            record['display_value'] = None
            own_figures = [fid for fid in figure_ids if fid in figures and figures[fid]['render_verified']
                           and record['id'] in figures[fid].get('result_refs', [])]
            method = record.get('extraction', {}).get('method')
            approved = bool(record.get('status') in ('candidate', 'confirmed') and finite(record.get('value'))
                            and refs and all(sid in sources and sources[sid]['link_validated'] for sid in refs)
                            and run_refs and all(rid in runs and runs[rid].get('source_refs')
                                and all(sid in sources and sources[sid]['link_validated']
                                        for sid in runs[rid]['source_refs']) for rid in run_refs)
                            and method and own_figures)
            for cid in cids:
                check = comparisons.get(cid, {})
                approved &= (check.get('status') == 'approved_for_scope'
                             and mid in check.get('approved_module_ids', [])
                             and bool(check.get('checks'))
                             and set(run_refs) <= set(check.get('run_refs', []))
                             and bool(check.get('original_domains'))
                             and not any(q.get('verdict') in ('unknown', 'different') for q in check.get('checks', [])))
                approved &= all(q.get('reference') not in (None, '') and q.get('test') not in (None, '')
                                and (q.get('verdict') != 'matched' or q['reference'] == q['test'])
                                for q in check.get('checks', []))
            if len(run_refs) > 1 or mid in ('rectification', 'conductance_asymmetry', 'polarity_current',
                                           'gm_polarity', 'dibl', 'hysteresis', 'tlm'):
                approved &= bool(cids)
            if record.get('status') == 'confirmed':
                approved &= all(record['validation'].get(key) is True for key in (
                    'inputs_complete', 'method_checked', 'conditions_checked', 'qc_passed'))
            if record.get('value_kind') in ('lower_bound', 'upper_bound'):
                floors = record.get('floor_refs', [])
                approved &= bool(floors and record.get('bound_reason'))
                for floor_id in floors:
                    floor = result['floors'].get(floor_id, {})
                    approved &= bool(floor.get('verified') is True and finite(floor.get('value_A'))
                                     and floor['value_A'] > 0 and floor.get('method')
                                     and floor.get('bias_domain') and floor.get('source_refs')
                                     and set(run_refs) <= set(floor.get('run_refs', []))
                                     and all(sid in sources and sources[sid]['link_validated']
                                             for sid in floor.get('source_refs', [])))
            record['display_approved'] = bool(approved)
            if approved:
                displayed.append(record)
        module['display_approved'] = bool(displayed and module.get('status') in ('candidate', 'confirmed'))
    if not any(m['display_approved'] for m in result['modules'].values()):
        ready = any(f.get('render_verified') for f in figures.values())
        result['summary']['unresolved_statement'] = (
            '정량 지표의 확인 조건과 근거가 부족합니다. '
            + ('생성·검증된 원본 곡선은 아래에서 열람할 수 있습니다. ' if ready else
               '원본 곡선 그림도 현재 표시할 수 없습니다. 파일·그림 생성 상태를 확인하세요. ')
            + '숫자가 보이지 않는 이유는 접힌 생략 항목에서 확인할 수 있습니다.')
    return result


def native_result(record, *, result_id, label, source_id, run_id, figure_ids, lineage_path, evidence_reference):
    """Map the existing seven-field metric contract without calculating a value."""
    validate_records([record])
    provenance = record['provenance']
    conversions = provenance['unit_conversion']
    method = record['extraction_method']
    usable = (record['availability'] in ('available', 'candidate') and finite(record['value'])
              and conversions.get('units_confirmed') is True and conversions.get('SI_assumption') is not True
              and provenance.get('source_file') and provenance.get('source_sheet')
              and provenance.get('source_rows') and provenance.get('source_cells')
              and isinstance(record.get('unit'), str) and bool(record['unit']) and bool(method.get('formula')))
    status = 'candidate' if usable else 'on_hold'
    bias = record['bias_condition']
    formula = method.get('formula')
    rows = provenance.get('source_rows', [])
    window = provenance.get('evaluation_window_v')
    evaluation = bias.get('evaluation_voltage_v')
    fixed = bias.get('fixed_voltages_v', {})
    return {
        'id': result_id, 'label': label, 'value': record['value'] if usable else None,
        'unit': record['unit'], 'display_value': None, 'value_kind': 'exact' if usable else 'unavailable',
        'relation': '=' if usable else None, 'status': status, 'display_approved': False,
        'source_refs': [source_id], 'figure_ids': list(figure_ids), 'detail_anchor': result_id.replace('_', '-'),
        'evaluation': {'summary': f'평가 전압 {evaluation}; 고정 전압 {fixed}; 원래 방향 {bias.get("direction")}',
                       'run_refs': [run_id], 'comparison_refs': [], 'original_domain': str(bias.get('original_sweep')),
                       'direction_block': str((bias.get('direction'), bias.get('gate_block_id')))},
        'extraction': {'summary': formula or '계산법 확인 전', 'method': formula, 'formula': formula,
                       'settings': {'evidence_reference': evidence_reference, 'native_reason': record['reason'],
                                    'native_availability': record['availability'], 'row_count': len(rows),
                                    'source_rows': rows if len(rows) <= 12 else {'count': len(rows)},
                                    'source_cells': provenance.get('source_cells') if len(provenance.get('source_cells', [])) <= 12 else {'count': len(provenance['source_cells'])},
                                    'unit_conversion': conversions,
                                    'derivative_settings': method.get('derivative_settings'),
                                    'endpoint': method.get('endpoint')},
                       'included_ranges': [str(window)] if window else [], 'excluded_points': [],
                       'point_lineage_path': lineage_path, 'assumptions': list(method.get('assumptions') or [])},
        'validation': {'inputs_complete': usable, 'method_checked': False, 'conditions_checked': False,
                       'qc_passed': False, 'model_validated': False, 'reason': record['reason']}
    }


METRIC_MODULES = {
    'gm': ('gm', 'evaluated', 'Signed gm'),
    'gds': ('gds', 'evaluated', 'Signed gds'),
    'conductance': ('conductance', 'evaluated', 'Signed G=Id/Vds'),
    'normalized_gm': ('gm_normalized', 'signed', 'gm/max|gm|'),
    'normalized_abs_gm': ('gm_normalized', 'absolute', '|gm|/max|gm|'),
    'ss_min': ('ss', 'minimum', 'SS 최소 후보'),
    'ss_average': ('ss', 'interval_mean', 'SS 구간 평균 후보'),
    'vth_additional': ('vt', 'threshold', 'VT 후보'),
    'vth_yfm': ('y_function', 'threshold_candidate', 'Y-function 문턱 후보'),
    'mobility_linear': ('mu_fe', 'evaluated', 'Signed 유효 μFE 후보'),
    'on_off_ratio': ('on_off', 'ratio', '지정 동작점 전류비'),
}


def adapt_records(empty_context, summary, records, *, raw_path, lineage_path, figures, evidence_document):
    """Create a small canonical view; the native records stay in their store.

The first recorded result per parameter in the representative acquisition group
is used as an evaluated example, never renamed a maximum or averaged with other
blocks. All other points remain reachable through the original CSV/evidence.
"""
    from .note_presentation import representative, conditions, next_action
    result = copy.deepcopy(empty_context)
    group = representative(summary)
    if not group:
        raise ValueError('원본 획득 그룹이 없어 보고서 연결을 보류합니다.')
    context = summary.get('research_context', {})
    fields = context.get('fields', {})
    date = fields.get('measurement_date', {})
    date_confirmed = date.get('status') == 'confirmed' and date.get('value') and date.get('source')
    source_id = 'source-1'
    run_id = 'run-' + str(group['group_id'])
    result['report'].update(
        title=summary.get('source_filename'), profile='id_vg' if group['axis'] == 'vg' else 'id_vd',
        purpose='원래 측정 곡선과 조건을 확인하고 재현 가능한 후보 수치의 근거를 검토합니다.',
        measurement_date_display=str(date.get('value'))+' · 이름 규칙 자동 입력 · 사람의 실측 확인 아님' if date.get('verification')=='naming_rule' else str(date.get('value')) if date_confirmed else (
            str(date['value']) + ' · ' + {'inferred':'추정', 'conflict':'충돌', 'missing':'확인 전'}.get(date.get('status'), '확인 전') + ' · 사용자 확인 전'
            if date.get('value') else '실제 측정일 확인 전'),
        measurement_date_source_display=condition_source(date),
        conditions_summary=conditions(summary, group), generated_at=summary.get('created_at'),
        analysis_version=summary.get('version'), internal_id=summary.get('job_id'))
    result['device']['name'] = context.get('device_name')
    result['device']['analysis_context'] = 'unknown'
    result['summary'].update(headline_metrics=[], observations=[
        '획득 순서·방향·블록을 보존한 측정 곡선입니다. 반복 통계나 수송 경로를 증명하지 않습니다.'])
    result['sources'] = {source_id: {
        'id': source_id, 'label': summary.get('source_filename') or '원본 측정 파일',
        'raw_path': raw_path, 'link_validated': False,
        'kind': 'csv' if Path(raw_path).suffix.lower() == '.csv' else 'spreadsheet',
        'confirmed_measurement_date': str(date['value']) if date_confirmed else None,
        'date_confirmation_scope': summary.get('source_relative_path') if date_confirmed else None,
        'date_confirmation_evidence': str(date['source']) if date_confirmed else None,
        'instrument_saved_at': summary.get('instrument_settings', {}).get('measurement_timestamp_raw'),
        'sheet': group.get('source_sheet') or group.get('sheet'), 'cell_ranges': [],
        'sha256': summary.get('source_sha256')}}
    sweep = group.get('original_sweep', {})
    def confirmed_value(name):
        item = fields.get(name, {})
        value = item.get('value') if item.get('status') == 'confirmed' else None
        if name in ('sweep_delay_s', 'hold_s') and not finite(value):
            return None
        return value
    result['runs'] = {run_id: {
        'id': run_id, 'label': str(group['group_id']), 'source_refs': [source_id],
        'kind': 'transfer' if group['axis'] == 'vg' else 'output',
        'protocol': {'swept_variable': 'Vg' if group['axis'] == 'vg' else 'Vds',
                     'start_V': sweep.get('first_v', sweep.get('start_v')),
                     'stop_V': sweep.get('last_v', sweep.get('end_v', sweep.get('stop_v'))),
                     'minimum_V': sweep.get('min_v'), 'maximum_V': sweep.get('max_v'),
                     'fixed_vg_V': group.get('conditions', {}).get('vg'),
                     'fixed_vds_V': group.get('conditions', {}).get('vd'),
                     'original_order_path': lineage_path,
                     'direction': group.get('direction'), 'block_label': group.get('gate_block_id'),
                     'sweep_delay_s': confirmed_value('sweep_delay_s'), 'hold_s': confirmed_value('hold_s'),
                     'light_state': confirmed_value('illumination') or 'unknown',
                     'history': confirmed_value('history')},
        'notes': json.dumps({'original_sweep': sweep, 'original_conditions': group.get('conditions'),
                             'trace_id': group.get('trace_id'), 'branch_index': group.get('branch_index'),
                             'metadata_fields': {k: fields.get(k) for k in (
                                 'illumination', 'sweep_delay_s', 'hold_s', 'history', 'measurement_time')}},
                            ensure_ascii=False, allow_nan=False)}}
    result['figures'] = copy.deepcopy(figures)
    result['summary']['hero_figure_id'] = next(iter(figures), None)
    result['layout']['raw_figure_ids'] = list(figures)
    result['next_actions'] = [{'action': next_action(summary),
                              'condition_and_decision': '해당 파일의 실제 조건을 확인한 뒤 수치 사용 여부를 검토하세요.'}]
    seen = set()
    for index, record in enumerate(records):
        parameter = record.get('parameter')
        if (parameter not in METRIC_MODULES or parameter in seen
                or record.get('group_id') != group['group_id']):
            continue
        seen.add(parameter)
        mid, key, label = METRIC_MODULES[parameter]
        if mid not in result['modules']:
            continue
        figure_ids = [fid for fid, figure in figures.items()
                      if parameter in figure.get('supported_parameters', [])]
        item = native_result(record, result_id=f'result-{mid}-{key}', label=label,
                             source_id=source_id, run_id=run_id, figure_ids=figure_ids,
                             lineage_path=lineage_path, evidence_reference=f'{evidence_document} / logical record {index}')
        if item['status'] == 'candidate' and not figure_ids:
            item.update(status='on_hold', value=None, value_kind='unavailable', relation=None)
            item['validation'].update(inputs_complete=False, reason='해당 수치의 생성된 근거 그림이 없어 표시 보류')
        module = result['modules'][mid]
        module['results'][key] = item
        module['status'] = 'candidate' if any(r['status'] == 'candidate' for r in module['results'].values()) else 'on_hold'
        module['omit_reason'] = None if item['status'] == 'candidate' else record['reason']
        module['figure_ids'] = list(dict.fromkeys(module['figure_ids'] + figure_ids))
        for fid in figure_ids:
            result['figures'][fid].setdefault('result_refs', []).append(item['id'])
        category = 'candidates' if item['status'] == 'candidate' else 'on_hold'
        result['availability'][category].append(label + ' · ' + item['validation']['reason'])
    # supported_parameters is adapter-only proof input, outside the template schema.
    for figure in result['figures'].values():
        figure.pop('supported_parameters', None)
    return result
