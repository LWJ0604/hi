"""Portable, append-only metadata confirmations; never edit measurement files."""
from datetime import date
import copy
import hashlib
import json
from pathlib import Path
import re

from .organization import identify
from .util import now, write_json
from .store import lock

UNITS = {"illumination": None, "measurement_date": "date", "measurement_time": "time",
    "device_name": None, "device_type": None, "electrodes": None, "polarity": None,
    "sweep_delay_s": "s", "hold_s": "s", "pre_bias": "V/s sequence",
    "environment": None, "history": None, "optical_power_w": "W", "units_confirmed": None}


def override_path(cfg):
    return cfg.paths["vault"] / "ResearchAutomation" / "metadata-overrides.json"


def source_key(relative, source_hash):
    return hashlib.sha256((relative.replace("\\", "/")+"\n"+source_hash).encode()).hexdigest()


def load_override(cfg, relative, source_hash):
    path = override_path(cfg)
    book = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"entries": {}}
    return book["entries"].get(source_key(relative,source_hash), {"fields": {}})


def save_override(cfg, relative, source_hash, updates, reason, researcher="researcher"):
    if not reason.strip():
        raise ValueError("확인 근거 또는 수정 이유를 입력하세요.")
    if not set(updates) <= set(UNITS):
        raise ValueError("지원하지 않는 메타데이터 필드")
    for field, value in updates.items():
        if field == "illumination" and value not in ("dark", "light", "unknown"):
            raise ValueError("광 조건: dark/light/unknown")
        if field == "measurement_date" and value is not None:
            date.fromisoformat(value)
        if field in ("sweep_delay_s", "hold_s", "optical_power_w") and value is not None:
            import math
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{field}: 유한한 0 이상의 수치 필요")
        if field == "units_confirmed" and not isinstance(value,bool):
            raise ValueError("units_confirmed must be boolean")
    with lock(cfg):
        path = override_path(cfg)
        book = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"schema_version":1,"entries":{}}
        entry = book["entries"].setdefault(source_key(relative,source_hash),
            {"source_relative_path":relative,"source_sha256":source_hash,"fields":{}})
        for key,value in updates.items():
            old = entry['fields'].get(key, {})
            history = old.get('history', []) + [{"previous_value":old.get('value'),"value":value,
                "reason":reason,"researcher":researcher,"confirmed_at":now(cfg).isoformat()}]
            entry['fields'][key] = {"value":value,"unit":UNITS[key],"source":"user_override",
                "status":"confirmed" if value is not None and value != "unknown" else "missing", "history":history}
        write_json(path,book)
    return entry


def fingerprint(cfg, relative, source_hash):
    return hashlib.sha256(json.dumps(load_override(cfg,relative,source_hash),sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def build_context(relative, metadata, instrument, summary, cfg, source_hash):
    context = identify(relative,metadata,instrument,summary,cfg)
    override = load_override(cfg,relative,source_hash)
    from .device_metadata import context_for,resolved_run_conditions
    source=cfg.paths['inbox']/relative
    device_context=context_for(source,cfg)
    _,resolved,notices=resolved_run_conditions(source,device_context,cfg,override.get('fields',{}))
    context['condition_notices']=notices
    context['resolved_conditions']=resolved
    fields = {}
    for key,unit in UNITS.items():
        candidates = list(context.get('evidence',{}).get(key,[]))
        if key == 'sweep_delay_s':
            match = re.search(r"(?i)(?:sweep[ _-]*)?delay[ _=:-]*(\d+(?:\.\d+)?)\s*s",relative)
            if match:
                candidates.append({'value':float(match[1]),'source':'filename/delay'})
            if instrument.get('sweep_delay_s') is not None:
                try:candidates.append({'value':float(instrument['sweep_delay_s']),'source':'Settings/Sweep Delay'})
                except (ValueError,TypeError):pass
        if key == 'hold_s' and instrument.get('hold_time_s') is not None:
            try:candidates.append({'value':float(instrument['hold_time_s']),'source':'Settings/Hold Time'})
            except (ValueError,TypeError):pass
        selected = context.get(key)
        selected_source = context.get(key+'_source','unavailable')
        if selected is None and candidates:
            selected=candidates[0]['value']
            selected_source=candidates[0]['source']
        item = {'value':None if selected in ('unknown','conflict') else selected, 'unit':unit,
            'source':selected_source, 'status':'inferred' if selected is not None and selected not in ('unknown','conflict') else 'missing',
            'candidates':candidates,'history':[]}
        declaration=resolved.get(key) if key in ('measurement_date','illumination') else None
        explicit=False
        if isinstance(declaration,dict) and declaration.get('value') is not None:
            item.update(copy.deepcopy(declaration))
            item['source']=declaration.get('source') or 'device.md / 출처 미기록'
            item['status']=declaration.get('status') or ('confirmed' if declaration.get('verification')=='user_confirmed' else 'inferred')
            explicit=declaration.get('verification')!='naming_rule'
            auto=declaration.get('naming_rule_candidate')
            item['candidates']=([{'value':auto['value'],'source':auto['source']}] if auto else candidates)+[{'value':item['value'],'source':item['source']}]
        if key in override['fields'] and key not in ('measurement_date','illumination'):
            item.update(override['fields'][key])
            item['candidates'] = candidates + [{'value':item['value'],'source':'user_override'}]
        # User choosing a timing value does not silently resolve an instrument disagreement.
        distinct = {json.dumps(c['value'],sort_keys=True) for c in item['candidates']}
        if key in ('illumination','sweep_delay_s','hold_s') and len(distinct)>1:
            item['candidate_disagreement']=True
            if key=='illumination' and explicit:
                item['resolution_reason']=item['history'][-1]['reason'] if item.get('history') else '명시한 측정 조건을 유지; 이름 규칙과 차이는 별도 안내'
            else:item['status']='conflict'
        if key == 'units_confirmed' and item['value'] is False:item['status']='missing'
        fields[key]=item
        if key in context:
            context[key] = 'conflict' if key=='illumination' and item['status']=='conflict' else item['value'] or ('unknown' if key=='illumination' else None)
            context[key+'_source']=item['source']
    context['fields']=fields
    context['actual_measurement_date']=fields['measurement_date']
    context['actual_measurement_time']=fields['measurement_time']
    context['equipment_record_time']={'value':instrument.get('measurement_timestamp_raw'),'unit':'instrument clock/timezone unknown','source':'Settings/Last Executed','status':'inferred' if instrument.get('measurement_timestamp_raw') else 'missing','candidates':[{'value':instrument.get('measurement_timestamp_raw'),'source':'Settings/Last Executed'}],'history':[]}
    context['acquisition_metadata']=[{'group_id':g.get('group_id'),'original_sweep':{'value':g.get('original_sweep'),'unit':'V','source':'uncropped source trace','status':'inferred','candidates':[g.get('original_sweep')],'history':[]},'fixed_voltages':{'value':g['conditions'],'unit':'V','source':'normalized columns / programmed header / Settings','status':'inferred','history':[]},'direction':{'value':g.get('direction'),'unit':None,'source':'source acquisition order','status':'inferred','history':[]},'sweep_id':g.get('sweep_id'),'gate_block_id':g.get('gate_block_id'),'branch_id':g.get('branch_id')} for g in summary['groups']]
    context['metadata_status']='conflict' if any(v['status']=='conflict' for v in fields.values()) else 'missing' if any(v['status']=='missing' for k,v in fields.items() if k!='optical_power_w') else 'confirmed' if all(v['status']=='confirmed' for v in fields.values()) else 'inferred'
    context['metadata_review_required']=context['metadata_status']!='confirmed'
    context['override_fingerprint']=fingerprint(cfg,relative,source_hash)
    # Rebuild labels/paths from selected confirmations without reinterpreting raw cells.
    parts=context['condition_label'].split('__')
    parts[1]=context['illumination']
    context['condition_label']='__'.join(parts)
    if fields['device_name']['source']=='user_override':
        from .organization import component
        context['device_path']=component(context['device_name'] or '소자 미확인')
    from .organization import component
    context['vault_subfolder']='/'.join([context['device_path'],context['measurement_date'] or '측정일 미확인',component(context['condition_label'])])
    return context
