"""Reviewable sidecar settings for NEW FET extraction; legacy config unchanged."""
import json
import math
from pathlib import Path
import shutil
from .util import now,write_json

FIELDS={'channel_length_m','channel_width_m','oxide_thickness_m','relative_permittivity','cox_f_per_m2','dielectric','linear_regime'}
METHODS={'yfm','ss_local','vth','ss','on_off'}


def validate_devices(data):
    if not isinstance(data,dict) or set(data)!={'devices'} or not isinstance(data['devices'],dict):raise ValueError('최상위에는 devices 객체만 사용합니다.')
    def scalar(value):return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)
    def window(values):return isinstance(values,list) and len(values)==2 and all(scalar(v) for v in values) and values[0]<values[1]
    for name,settings in data['devices'].items():
        if not isinstance(name,str) or not name.strip() or not isinstance(settings,dict):raise ValueError('소자 이름과 조건 객체가 필요합니다.')
        if set(settings)-FIELDS-METHODS-{'mobility_window_v'}:raise ValueError('지원하지 않는 FET 조건 키가 있습니다.')
        for key,value in settings.items():
            if key in FIELDS:
                if not isinstance(value,dict) or value.get('status') not in ('confirmed','assumed','missing'):raise ValueError('값에는 value/unit/status/source를 기록하세요.')
                if value.get('status') in ('confirmed','assumed') and not value.get('source'):raise ValueError('확인/가정 값에는 source 근거가 필요합니다.')
                if key not in ('dielectric','linear_regime') and value.get('value') is not None and (not scalar(value['value']) or value['value']<=0):raise ValueError('치수·용량·유전율은 양의 SI 값이어야 합니다.')
                if key=='linear_regime' and value.get('value') is not None and not isinstance(value['value'],bool):raise ValueError('linear_regime value는 true/false입니다.')
                expected={'channel_length_m':'m','channel_width_m':'m','oxide_thickness_m':'m','cox_f_per_m2':'F/m²'}.get(key)
                if expected and value.get('value') is not None and value.get('unit')!=expected:raise ValueError(f'{key} 단위는 {expected}를 사용하세요.')
            elif key=='mobility_window_v':
                if not window(value):raise ValueError('이동도 구간은 증가하는 [최소 V, 최대 V]입니다.')
            else:
                if not isinstance(value,dict):raise ValueError('추출 방법은 객체로 기록합니다.')
                if 'window_v' in value and not window(value['window_v']):raise ValueError('방법 구간은 증가하는 [최소 V, 최대 V]입니다.')
                if 'gm_window_v' in value and (not scalar(value['gm_window_v']) or value['gm_window_v']<=0):raise ValueError('gm 구간 전체 폭은 양수입니다.')
                if 'min_points' in value and (not isinstance(value['min_points'],int) or value['min_points']<3):raise ValueError('최소 점 수는 3 이상의 정수입니다.')
    return data


def save_settings(cfg,data):
    validate_devices(data)
    path=cfg.paths['vault']/'ResearchAutomation'/'fet-extraction-settings.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_file():shutil.copy2(path,path.with_name('fet-extraction-settings_preserved_'+now(cfg).strftime('%Y%m%d-%H%M%S-%f')+'.json'))
    write_json(path,data)
    return path
