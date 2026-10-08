"""Read-only measurement naming rules; automatic labels are never human confirmations."""
import copy
from datetime import date
from pathlib import Path
import re

RULE_DEFAULTS = {'date_from_folder': True, 'excel_light_from_filename': True}
RAW_FOLDERS = {'원본', 'raw', 'original'}
OUTPUT_FOLDERS = {'분석', 'analysis', 'runs', 'benchmarks', 'observations', 'experiments', 'attachments', 'weekly'}
DATE_FOLDER = re.compile(r'(\d{4})([-._])(\d{1,2})\2(\d{1,2})')


def naming_rules(cfg):
    return {**RULE_DEFAULTS, **cfg.data.get('organization', {}).get('naming_rules', {})}


def condition_source(record):
    evidence=record.get('evidence',{})
    if record.get('verification')=='naming_rule':
        if record.get('source')=='folder_name':return '날짜 폴더 '+str(evidence.get('folder_name',''))
        return 'Excel 파일명 '+str(evidence.get('filename',''))
    return str(record.get('source') or '출처 미기록')


def condition_status(record):
    if record.get('verification')=='naming_rule':return '이름 규칙 자동 입력 · 사람의 실측 확인 아님'
    return {'confirmed':'확인','inferred':'추정','conflict':'충돌','missing':'확인 전'}.get(record.get('status'),'확인 전')


def valid_date(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed.isoformat() if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value.strip()) else None


def _folder_date(name):
    match = DATE_FOLDER.fullmatch(name.strip())
    if not match:
        return None
    try:
        return date(int(match[1]), int(match[3]), int(match[4])).isoformat()
    except ValueError:
        return None


def _root(cfg):
    inbox = cfg.paths['inbox'].resolve()
    explicit = cfg.data.get('benchmark', {}).get('metadata_root')
    root = (cfg.root / explicit).resolve() if explicit else inbox
    # Only folder names are consulted outside a selected raw Inbox. Device
    # inheritance itself keeps its existing bounded file-reading policy.
    if not explicit and inbox.name.casefold() in RAW_FOLDERS:
        root = inbox.parent
    return root


def automatic_conditions(source, cfg):
    source = Path(source).resolve()
    root = _root(cfg)
    fields = {}
    policy = naming_rules(cfg)
    if policy['date_from_folder'] and root in source.parents:
        directories = []
        current = source.parent
        while True:
            directories.append(current)
            if current == root:
                break
            current = current.parent
        directories.reverse()
        # The outer raw/output marker ends measurement classification. Dates
        # in nested raw exports and generated report folders are not run dates.
        boundary = next((i for i, p in enumerate(directories)
                         if p.name.casefold() in RAW_FOLDERS | OUTPUT_FOLDERS), len(directories))
        classification = directories[:boundary]
        candidates = []
        for i, folder in enumerate(classification):
            value = _folder_date(folder.name)
            label = folder.name
            if value is None and i >= 2:
                names = [p.name for p in classification[i-2:i+1]]
                if re.fullmatch(r'\d{4}/\d{1,2}/\d{1,2}', '/'.join(names)):
                    try:
                        value = date(*map(int, names)).isoformat()
                        label = '/'.join(names)
                    except ValueError:
                        pass
            if value is not None:
                candidates.append((folder, value, label))
        if candidates:
            folder, value, label = candidates[-1]
            fields['measurement_date'] = {
                'value': value, 'source': 'folder_name', 'verification': 'naming_rule',
                'status': 'inferred', 'history': [],
                'evidence': {'folder_name': label,
                             'classification_folder': folder.relative_to(root).as_posix(),
                             'rule': 'nearest valid complete date before raw/output folders'},
                'candidates': [{'value': v, 'source': 'folder_name', 'folder_name': label}
                               for p, v, label in candidates]}
    if policy['excel_light_from_filename'] and source.suffix.casefold() in ('.xls', '.xlsx'):
        fields['illumination'] = {
            'value': 'light' if 'light' in source.stem.casefold() else 'dark',
            'source': 'filename', 'verification': 'naming_rule', 'status': 'inferred', 'history': [],
            'evidence': {'filename': source.name, 'rule': 'case-insensitive light substring; otherwise dark'}}
    return fields


def _explicit(field, record):
    if not isinstance(record, dict):
        return False
    value = record.get('value')
    if field == 'measurement_date':
        return valid_date(value) is not None
    return isinstance(value, str) and value.strip().casefold() in ('light', 'dark')


def resolve_conditions(source, cfg, declared, overrides=None):
    """Prefer valid per-file overrides/device values; null/unknown falls back.

    Concrete unconfirmed declarations retain that state. Automatic naming never
    supplies missing units, physical conditions, or fabricated confirmation history.
    """
    conditions = copy.deepcopy(declared)
    automatic = automatic_conditions(source, cfg)
    notices = []
    for field in ('measurement_date', 'illumination'):
        selected = conditions.get(field)
        override = (overrides or {}).get(field)
        if _explicit(field, override):
            selected = copy.deepcopy(override)
            selected['source'] = 'user_override'
            selected['verification'] = 'user_confirmed' if override.get('status') == 'confirmed' else 'unconfirmed'
        elif not _explicit(field, selected):
            selected = None
        auto = automatic.get(field)
        if selected is None:
            if auto is not None:
                conditions[field] = copy.deepcopy(auto)
            elif field in conditions:
                conditions[field] = {'value':None,'source':None,'verification':'unconfirmed',
                                     'unapplied_declaration':copy.deepcopy(conditions[field])}
            continue
        selected = copy.deepcopy(selected)
        selected.setdefault('verification', 'unconfirmed')
        if field == 'measurement_date':
            selected['value'] = valid_date(selected['value'])
        else:
            selected['value'] = selected['value'].strip().casefold()
        if auto is not None and selected['value'] != auto['value']:
            selected['naming_rule_candidate'] = copy.deepcopy(auto)
            label = '측정일' if field == 'measurement_date' else '광 조건'
            origin = '사용자 확인 이력' if selected.get('source') == 'user_override' else 'device.md'
            basis = '날짜 폴더' if field == 'measurement_date' else 'Excel 파일명'
            notices.append(f"{label}은 {origin}의 {selected['value']} 값을 유지했습니다. "
                           f"{basis} 규칙의 {auto['value']}와 달라 이름 또는 명시 정보를 확인하세요.")
        conditions[field] = selected
    return conditions, notices
