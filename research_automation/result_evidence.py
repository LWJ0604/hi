"""Read cached scientific support without recalculating or confirming metadata."""
import json
from pathlib import Path


def evidence_items(summary):
    items = []
    for group in summary.get('groups', []):
        base = {key: group.get(key) for key in ('group_id', 'direction', 'gate_block_id', 'conditions', 'original_sweep', 'metadata_status')}
        for metric in group.get('rr_series', []):
            items.append({**base, 'metric': 'RR', 'support': metric})
        for name, metric in group.get('transfer_metrics', {}).items():
            if isinstance(metric, dict) and ('value' in metric or 'source_points' in metric):
                transfer = group['transfer_metrics']
                items.append({**base, 'metric': name, 'support': metric,
                              'raw_method': transfer.get('raw_method'),
                              'smoothing_settings': transfer.get('smoothing_settings'),
                              'original_range_v': transfer.get('original_range_v')})
    return items


def support_text(item):
    metric = item['support']
    intro = ['조건과 블록·방향은 원본 획득 순서를 따릅니다.',
             'RR: |I(+u)| / |I(−u)|. 평가 전압과 두 극성의 원본점을 함께 확인하세요.'
             if item['metric'] == 'RR' else
             ('gm: 끝점 최대값과 내부 피크를 구분하고 평활 폭·단위 민감도를 확인하세요.'
              if item['metric'] in ('raw_peak_abs', 'internal_peak_abs') else
              '후보 지표: 사용한 구간·단위·조건과 보류 이유를 함께 확인하세요.'),
             'null은 미확인/보류입니다. QC PASS만으로 연구 사용이 확정되지 않습니다.',
             '원본 행·셀, 보간 여부, 계산 구간과 제외 사유는 아래 저장된 근거를 확인하세요.']
    intro += [f"값: {metric.get('value') if metric.get('value') is not None else '보류 (null)'} {metric.get('unit') or ''}",
              f"평가 전압: {metric.get('evaluation_abs_vd_v', metric.get('vg_v', '저장된 상세 참조'))} V",
              f"보류/평가 사유: {metric.get('reason') or '저장된 상세 참조'}"]
    if item['metric'] == 'RR':
        for key, label in (('positive_current', '+u'), ('negative_current', '−u')):
            point = metric.get(key, {})
            intro.append(f"{label}: {point.get('value')} A · 원본 행 {[p.get('source_row') for p in point.get('source_points', [])]} · 보간 {point.get('interpolated', '미확인')}")
    return '\n'.join(intro) + '\n\n저장된 전체 근거\n' + json.dumps(item, ensure_ascii=False, indent=2)


def load_evidence(path):
    return evidence_items(json.loads(Path(path).read_text(encoding='utf-8-sig')))
