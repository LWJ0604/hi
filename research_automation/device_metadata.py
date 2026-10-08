"""Read-only, bounded device.md inheritance and explicitly scoped run links."""
import copy
from datetime import date
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace

import yaml

MAX_BYTES=262144
ROOT_KEYS={'schema_version','device_name','structure','electrode_pairs','active_electrode_pair',
           'run_conditions','reference_inputs'}


class DeviceLoader(yaml.SafeLoader):
    pass


def _mapping(loader,node,deep=False):
    result={}
    for key_node,value_node in node.value:
        key=loader.construct_object(key_node,deep=deep)
        if not isinstance(key,str) or key in result:raise ValueError('device.md에는 중복 없는 문자열 키를 사용하세요.')
        result[key]=loader.construct_object(value_node,deep=deep)
    return result


DeviceLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,_mapping)


def _bounded(value,depth=0,ancestors=None):
    ancestors=set() if ancestors is None else ancestors
    if depth>12:raise ValueError('device.md의 중첩 깊이가 너무 큽니다.')
    if isinstance(value,(dict,list)):
        if id(value) in ancestors or len(value)>1000:raise ValueError('device.md의 순환 참조나 큰 목록은 지원하지 않습니다.')
        ancestors=ancestors|{id(value)}
        return {k:_bounded(v,depth+1,ancestors) for k,v in value.items()} if isinstance(value,dict) else [_bounded(v,depth+1,ancestors) for v in value]
    if isinstance(value,date):return value.isoformat()
    if isinstance(value,float) and not math.isfinite(value):raise ValueError('device.md에 무한대나 NaN을 넣을 수 없습니다.')
    if value is None or isinstance(value,(str,bool,int,float)):return value
    raise ValueError('device.md에는 일반 값과 안전한 YAML만 사용하세요.')


def _schema(value):
    """Quarantine malformed fields, retaining unrelated conditions and raw data."""
    warnings=[];invalid=set()

    def reject(parent,key,path,empty):
        parent[key]=empty;invalid.add(path)
        warnings.append('조건 필드 '+path+'의 형식이 잘못되어 해당 조건 계산을 보류합니다.')

    def mapping(parent,key,path):
        if key not in parent:return {}
        if not isinstance(parent[key],dict):reject(parent,key,path,{})
        return parent[key]

    def scalar(parent,key,path,kind):
        if key not in parent or parent[key] is None:return
        item=parent[key]
        if kind=='number':
            try:valid=isinstance(item,(int,float)) and not isinstance(item,bool) and math.isfinite(float(item))
            except OverflowError:valid=False
        else:valid=isinstance(item,kind)
        if not valid:reject(parent,key,path,None)

    def field(parent,key,path,kind='number',nullable=False):
        if key not in parent or nullable and parent[key] is None:return
        item=mapping(parent,key,path)
        before=len(invalid)
        scalar(item,'value',path+'.value',kind)
        for attr in ('unit','source','verification','confirmed_at'):
            scalar(item,attr,path+'.'+attr,str)
        if len(invalid)>before:reject(parent,key,path,{})

    field(value,'device_name','device_name',str)
    selection=value.get('active_electrode_pair')
    if isinstance(selection,dict):field(value,'active_electrode_pair','active_electrode_pair',str)
    elif selection is not None and (not isinstance(selection,str) or not selection.strip()):
        reject(value,'active_electrode_pair','active_electrode_pair',{'value':None})
    structure=mapping(value,'structure','structure')
    for key in ('material','gate_geometry'):
        if isinstance(structure.get(key),dict):field(structure,key,'structure.'+key,str)
        else:scalar(structure,key,'structure.'+key,str)
    field(structure,'thickness','structure.thickness')
    dielectric=mapping(structure,'gate_dielectric','structure.gate_dielectric')
    for key in ('thickness','relative_permittivity'):field(dielectric,key,'structure.gate_dielectric.'+key)
    if isinstance(dielectric.get('material'),dict):field(dielectric,'material','structure.gate_dielectric.material',str)
    else:scalar(dielectric,'material','structure.gate_dielectric.material',str)
    electrodes=mapping(structure,'electrodes','structure.electrodes')
    for key in ('metal','adhesion_layer','source','verification'):scalar(electrodes,key,'structure.electrodes.'+key,str)
    pairs=mapping(value,'electrode_pairs','electrode_pairs')
    for name in pairs:
        pair=mapping(pairs,name,'electrode_pairs.'+name)
        for axis in ('L','W'):field(pair,axis,'electrode_pairs.'+name+'.'+axis)
        field(pair,'wiring','electrode_pairs.'+name+'.wiring',str,nullable=True)
    runs=mapping(value,'run_conditions','run_conditions')
    field(runs,'temperature','run_conditions.temperature',nullable=True)
    for role in ('IdVd','IdVg'):
        run=mapping(runs,role,'run_conditions.'+role)
        scalar(run,'file','run_conditions.'+role+'.file',str)
        for key in ('measurement_date','measurement_time','illumination'):
            field(run,key,'run_conditions.'+role+'.'+key,str,nullable=True)
        for key in ('sweep_delay_user_s','sweep_delay_settings_s','hold_time_settings_s'):
            scalar(run,key,'run_conditions.'+role+'.'+key,'number')
        scalar(run,'linear_region_confirmed','run_conditions.'+role+'.linear_region_confirmed',bool)
        scalar(run,'delay_verification','run_conditions.'+role+'.delay_verification',str)
    units=mapping(runs,'units','run_conditions.units')
    for key in ('voltage','current','source','verification','confirmed_at','applies_to'):
        scalar(units,key,'run_conditions.units.'+key,str)
    if any(p.startswith('run_conditions.units.') for p in invalid):reject(runs,'units','run_conditions.units',{})
    pair_check=mapping(runs,'pair_verification','run_conditions.pair_verification')
    for key in pair_check:scalar(pair_check,key,'run_conditions.pair_verification.'+key,str)
    scalar(runs,'measured_noise_floor_A','run_conditions.measured_noise_floor_A','number')
    reference=mapping(value,'reference_inputs','reference_inputs')
    field(reference,'mobility_cm2_Vs','reference_inputs.mobility_cm2_Vs',nullable=True)
    return warnings,invalid


def read_device(path):
    path=Path(path)
    if path.is_symlink() or path.stat().st_size>MAX_BYTES:raise ValueError('device.md는 256 KiB 이하의 일반 파일이어야 합니다.')
    raw=path.read_bytes();text=raw.decode('utf-8-sig');lines=text.splitlines()
    if not lines or lines[0]!='---':raise ValueError('device.md 첫 줄에 YAML 구분선 ---가 필요합니다.')
    try:end=lines.index('---',1)
    except ValueError:raise ValueError('device.md의 YAML 닫는 구분선 ---가 없습니다.') from None
    front='\n'.join(lines[1:end])
    if sum(isinstance(token,yaml.tokens.AliasToken) for token in yaml.scan(front))>20:raise ValueError('device.md의 별칭이 너무 많습니다.')
    value=_bounded(yaml.load(front,Loader=DeviceLoader))
    if not isinstance(value,dict) or type(value.get('schema_version')) is not int or value['schema_version']!=1:raise ValueError('device.md는 schema_version: 1인 정보 객체여야 합니다.')
    unknown=set(value)-ROOT_KEYS
    if unknown:raise ValueError('device.md의 지원하지 않는 최상위 항목: '+', '.join(sorted(unknown)))
    warnings,invalid=_schema(value)
    return value,{'path':str(path.resolve()),'sha256':hashlib.sha256(raw).hexdigest(),
                  'warnings':warnings,'invalid_fields':sorted(invalid)},'\n'.join(lines[end+1:])


def _origins(value,origin,provenance,prefix):
    if isinstance(value,dict) and value:
        for key,item in value.items():_origins(item,origin,provenance,prefix+'.'+key)
    else:provenance[prefix]=origin


def _merge(base,value,origin,provenance,prefix='',invalid=(),warnings=None):
    """Value/evidence records replace atomically; units are never borrowed."""
    for key,item in value.items():
        name=prefix+'.'+key if prefix else key
        previous=base.get(key)
        atomic=name in invalid or name in ('run_conditions.units','structure.electrodes')
        field=isinstance(item,dict) and ('value' in item or isinstance(previous,dict) and 'value' in previous)
        # Re-declaring a file establishes a fresh scope for all its conditions.
        scoped=name in ('run_conditions.IdVd','run_conditions.IdVg') and isinstance(item,dict) and 'file' in item
        if atomic or field or scoped:
            for old in list(provenance):
                if old==name or old.startswith(name+'.'):provenance.pop(old)
            replacement=copy.deepcopy(item)
            if isinstance(replacement,dict) and (field or name in ('run_conditions.units','structure.electrodes')):
                replacement.setdefault('source',None);replacement.setdefault('verification','unconfirmed')
                if field:replacement.setdefault('value',None)
            base[key]=replacement;_origins(replacement,origin,provenance,name)
            if warnings is not None and isinstance(previous,dict) and (field or name=='run_conditions.units') and any(attr not in item for attr in previous):
                warnings.append('하위 조건 '+name+'는 전체 교체되었습니다. 이전 단위·출처·확인 상태를 상속하지 않습니다.')
            continue
        if isinstance(item,dict):
            if not isinstance(base.get(key),dict):base[key]={}
            _merge(base[key],item,origin,provenance,name,invalid,warnings)
        else:
            for old in list(provenance):
                if old==name or old.startswith(name+'.'):provenance.pop(old)
            base[key]=copy.deepcopy(item);provenance[name]=origin


def _root(cfg):
    explicit=cfg.data.get('benchmark',{}).get('metadata_root')
    inbox=cfg.paths['inbox'].resolve()
    if explicit:
        root=(cfg.root/explicit).resolve()
        if root!=inbox and root not in inbox.parents:raise ValueError('metadata_root는 선택한 입력 폴더를 포함해야 합니다.')
        return root
    if inbox.name.casefold() in ('원본','raw') and (inbox.parent/'device.md').is_file():return inbox.parent
    return inbox


def _resolve_run_file(name,note,root):
    if not isinstance(name,str) or not name.strip():return None
    relative=Path(name)
    if relative.is_absolute() or '..' in relative.parts:raise ValueError('device.md의 측정 file은 정보 폴더 안의 상대 경로여야 합니다.')
    base=Path(note).parent
    candidates=[base/relative] if len(relative.parts)>1 else [base/relative,base/'원본'/relative,base/'raw'/relative]
    matches=[]
    for candidate in candidates:
        resolved=candidate.resolve()
        if resolved!=root and root not in resolved.parents:raise ValueError('device.md의 측정 연결이 입력 정보 범위를 벗어납니다.')
        if candidate.is_symlink():raise ValueError('측정 연결은 심볼릭 링크를 사용할 수 없습니다.')
        if candidate.is_file():matches.append(resolved)
    return matches[0] if len(set(matches))==1 else None


def context_for(source,cfg):
    source=Path(source).resolve();root=_root(cfg)
    if root not in source.parents:raise ValueError('원본이 metadata_root 범위를 벗어납니다.')
    directories=[];current=source.parent
    while True:
        directories.append(current)
        if current==root:break
        current=current.parent
    data={};provenance={};sources=[];warnings=[]
    for directory in reversed(directories):
        path=directory/'device.md'
        if not path.exists():continue
        try:
            value,receipt,_=read_device(path)
            old_name=data.get('device_name',{});new_name=value.get('device_name',{})
            changed_identity=isinstance(new_name,dict) and new_name.get('value') and isinstance(old_name,dict) and old_name.get('value') and new_name['value']!=old_name['value']
            if changed_identity or 'device_name' in receipt['invalid_fields']:
                for key in ('structure','electrode_pairs','active_electrode_pair','reference_inputs'):data.pop(key,None)
                for key in list(provenance):
                    if key.split('.')[0] in ('structure','electrode_pairs','active_electrode_pair','reference_inputs'):provenance.pop(key)
            _merge(data,value,str(path.resolve()),provenance,invalid=receipt['invalid_fields'],warnings=warnings)
            warnings.extend(receipt['warnings']);sources.append(receipt)
        except (OSError,ValueError,UnicodeError,yaml.YAMLError) as error:
            warnings.append('소자 정보 파일을 적용하지 못했습니다: '+path.name+' ('+str(error)+')')
    runs={}
    for role in ('IdVd','IdVg'):
        record=data.get('run_conditions',{}).get(role,{})
        if not isinstance(record,dict):continue
        owner=provenance.get('run_conditions.'+role+'.file')
        if owner:
            try:runs[role]=_resolve_run_file(record.get('file'),owner,root)
            except ValueError as error:warnings.append(str(error))
    return {'data':data,'sources':sources,'provenance':provenance,'warnings':warnings,
            'root':str(root),'resolved_runs':runs}


def fingerprint(context):
    payload={'data':context['data'],'sources':context['sources'],'warnings':context['warnings']}
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode('utf-8')).hexdigest()


def units_profile(context,cfg):
    profile=copy.deepcopy(cfg.data.get('measurement_profile',{}))
    units=context['data'].get('run_conditions',{}).get('units',{})
    if isinstance(units,dict) and units.get('verification')=='user_confirmed' and units.get('voltage') and units.get('current'):
        if units['voltage'] in ('V','mV','uV') and units['current'] in ('A','mA','uA','nA','pA'):
            profile={'voltage_unit':units['voltage'],'current_unit':units['current'],'confirmed':True,'source':'device.md / '+str(units.get('source','사용자 확인'))}
        else:
            warning='device.md의 확인 단위를 읽지 못해 사용자 설정 또는 미확인 기본값을 사용했습니다.'
            if warning not in context['warnings']:context['warnings'].append(warning)
    return profile


def measurement_config(context,cfg):
    data=copy.deepcopy(cfg.data);data['measurement_profile']=units_profile(context,cfg)
    return SimpleNamespace(data=data,paths=cfg.paths,root=cfg.root,path=cfg.path)


def declared_pair(source,context):
    runs=context['resolved_runs'];a,b=runs.get('IdVd'),runs.get('IdVg')
    source=Path(source).resolve()
    return [a,b] if a and b and a!=b and source in (a,b) else [source]


def run_conditions(source,context):
    source=Path(source).resolve()
    for role,resolved in context['resolved_runs'].items():
        if resolved==source:return role,context['data'].get('run_conditions',{}).get(role,{})
    return None,{}


def value(item,unit=None,*,confirmed=False,positive=False):
    if not isinstance(item,dict) or item.get('value') is None:return None
    if confirmed and item.get('verification')!='user_confirmed':return None
    if unit is not None and item.get('unit')!=unit:return None
    number=item['value']
    if isinstance(number,bool):return None
    try:number=float(number)
    except (ValueError,TypeError,OverflowError):return None
    return number if math.isfinite(number) and (not positive or number>0) else None
