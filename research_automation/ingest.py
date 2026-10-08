"""Keithley exports: explicit mapping, header discovery, SI normalization."""
import csv
import io
import re
from pathlib import Path

import numpy as np
import pandas as pd

ALIASES = {
    "vd": {"vd", "vds", "drainv", "drainvoltage", "voltage", "voltagev", "volt"},
    "vg": {"vg", "vgs", "gatev", "gatevoltage"},
    "id": {"id", "ids", "draini", "draincurrent", "current", "currenta", "amps"},
    "ig": {"ig", "igs", "gatei", "gatecurrent"},
}
UNITS = {"V": ("voltage", 1), "mV": ("voltage", 1e-3), "uV": ("voltage", 1e-6),
         "A": ("current", 1), "mA": ("current", 1e-3), "uA": ("current", 1e-6), "nA": ("current", 1e-9), "pA": ("current", 1e-12)}


class NoMeasurementHeader(ValueError):
    pass


def trace_number(header):
    clean=re.sub(r'\s*\{col:\d+\}$','',str(header)).strip()
    match = re.search(r"\((\d+)\)\s*$", clean)
    return int(match.group(1)) if match else None


def column_info(header, cfg):
    original = re.sub(r"\s*\{col:\d+\}$", "", str(header)).strip().replace("µ", "u").replace("μ", "u")
    # Keithley (1), (2), ... are trace indices, not current/voltage units.
    if trace_number(original) is not None:
        original = re.sub(r"\(\d+\)\s*$", "", original).strip()
    unit = None
    match = re.search(r"\s*[\[(]([^\])]+)[\])]\s*$", original)
    base = original
    if match:
        unit = match.group(1).strip()
        base = original[:match.start()]
    elif " " in original:
        parts = original.rsplit(" ", 1)
        if parts[1] in UNITS:
            base, unit = parts
    token = re.sub(r"[^a-z0-9]", "", base.lower())
    explicit = [canonical for canonical, source in cfg.data["columns"]["mapping"].items() if str(source).strip() == str(header).strip()]
    canonical = explicit[0] if explicit else next((key for key, options in ALIASES.items() if token in options), None)
    if canonical is None:
        return None
    if canonical not in ALIASES:
        raise ValueError(f"지원하지 않는 정규화 컬럼: {canonical}")
    factor = 1.0
    assumption = None
    if unit:
        if unit not in UNITS:
            raise ValueError(f"{header}: 지원하지 않는 단위 {unit}")
        expected = "voltage" if canonical in ("vd", "vg") else "current"
        if UNITS[unit][0] != expected:
            raise ValueError(f"{header}: 전압/전류 단위가 맞지 않습니다.")
        factor = UNITS[unit][1]
    elif cfg.data.get('measurement_profile',{}).get('confirmed'):
        profile=cfg.data['measurement_profile']
        default=profile['voltage_unit' if canonical in ('vd','vg') else 'current_unit']
        expected='voltage' if canonical in ('vd','vg') else 'current'
        if default not in UNITS or UNITS[default][0]!=expected:raise ValueError('확인된 측정 단위 프로필을 확인하세요.')
        factor=UNITS[default][1]
    elif not cfg.data["columns"]["assume_si_for_unitless"]:
        raise ValueError(f"{header}: 단위가 없습니다. mapping/scales와 SI 가정 정책을 확인하세요.")
    else:
        assumption = f"{header}: 단위 없는 컬럼을 V/A로 가정; 추가 scale={cfg.data['columns']['scales'].get(canonical, 1)}"
    return canonical, factor * cfg.data["columns"]["scales"].get(canonical, 1), assumption


def header_unit(header):
    text=re.sub(r'\s*\{col:\d+\}$','',str(header)).strip().replace('µ','u').replace('μ','u')
    text=re.sub(r'\(\d+\)\s*$','',text).strip()
    match=re.search(r'\s*[\[(]([^\])]+)[\])]\s*$',text)
    return match.group(1).strip() if match else text.rsplit(' ',1)[-1] if ' ' in text and text.rsplit(' ',1)[-1] in UNITS else None


def header_index(rows, cfg):
    chosen = cfg.data["ingest"]["header_row"]
    if chosen != "auto":
        return chosen
    automatic = cfg.data["analysis"]["auto_detect_axis"]
    required = {cfg.data["analysis"]["x"], cfg.data["analysis"]["y"]}
    for index, row in enumerate(rows[:50]):
        found = set()
        for cell in row:
            info = column_info(cell, cfg)
            if info:
                found.add(info[0])
        if (automatic and "id" in found and bool({"vd", "vg"} & found)) or (not automatic and required <= found):
            return index
    raise NoMeasurementHeader(f"첫 50행에서 {sorted(required)} 헤더를 찾을 수 없습니다. columns.mapping/header_row를 설정하세요.")


def read_csv(path, cfg):
    encodings = [cfg.data["ingest"]["encoding"]]
    if encodings[0] == "auto":
        encodings = ["utf-16"] if path.read_bytes()[:2] in (b"\xff\xfe", b"\xfe\xff") else ["utf-8-sig", "cp949"]
    raw = None
    for encoding in encodings:
        try:
            raw = path.read_text(encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
    if raw is None:
        raise ValueError("CSV 문자 인코딩을 확인하세요 (utf-8/cp949/utf-16).")
    separator = cfg.data["ingest"]["separator"]
    candidates = [separator] if separator != "auto" else [",", "\t", ";"]
    selected = None
    for candidate in candidates:
        rows = list(csv.reader(io.StringIO("\n".join(raw.splitlines()[:55])), delimiter=candidate))
        try:
            index = header_index(rows, cfg)
            if len(rows[index]) > 1:
                selected = candidate, index
                break
        except NoMeasurementHeader:
            pass
    if selected is None:
        raise NoMeasurementHeader("CSV 구분자 또는 컬럼명을 확인하세요.")
    separator, index = selected
    raw_rows=list(csv.reader(io.StringIO(raw),delimiter=separator))
    headers=raw_rows[index]
    unique=[str(c)+f" {{col:{i+1}}}" if headers.count(c)>1 else str(c) for i,c in enumerate(headers)]
    frame=pd.read_csv(io.StringIO(raw),sep=separator,skiprows=index+1,header=None,names=unique,dtype=object,skip_blank_lines=False)
    frame.attrs['source_columns']={col:i+1 for i,col in enumerate(frame.columns)}
    frame.attrs['upper_conditions']={col:[(r+1,raw_rows[r][i] if i<len(raw_rows[r]) else None) for r in range(index)] for i,col in enumerate(unique)}
    return frame, index


def normalize(frame, sheet, header, cfg, metadata, settings=None, source_sheet=None, trace_id=None):
    settings = settings or {}
    columns = {}
    warnings = []
    mapping = {}
    for source in frame.columns:
        info = column_info(source, cfg)
        if info:
            canonical, factor, assumption = info
            if canonical in columns:
                raise ValueError(f"{sheet}: {canonical}에 대응하는 컬럼이 여러 개입니다.")
            # Preserve Excel's numeric cells directly; converting float → text →
            # numeric can unnecessarily round low-current readings.
            values = frame[source].map(lambda value: value.strip().replace("−", "-") if isinstance(value, str) else value)
            columns[canonical] = pd.to_numeric(values, errors="coerce") * factor
            mapping[canonical] = {"source": str(source), "factor_to_si": factor}
            position = frame.attrs.get("source_columns", {}).get(source)
            mapping[canonical].update({"source_column": position,
                "header_cell": cell_address(position, header + 1) if position else None,
                "unit_status": "inferred" if assumption else "confirmed",
                "origin": frame.attrs.get("voltage_origins", {}).get(canonical, "exported_voltage" if canonical in ("vd", "vg") else "measured_current")})
            profile=cfg.data.get('measurement_profile',{})
            declared=header_unit(source)
            mapping[canonical]['unit_source']='file_header' if declared else 'user_profile' if profile.get('confirmed') else 'SI_assumption'
            mapping[canonical]['declared_unit']=declared
            if profile.get('confirmed'):
                expected=profile['voltage_unit' if canonical in ('vd','vg') else 'current_unit']
                mapping[canonical]['profile_source']=profile.get('source')
                if declared and declared!=expected:
                    warnings.append(f'{source}: 파일 단위 {declared}가 사용자 기본 {expected}와 달라 파일 단위로 환산했습니다.')
                    mapping[canonical]['unit_conflict']=True
            if assumption:
                warnings.append(assumption)
    for key, bias in settings.get("fixed_bias_v", {}).items():
        if key not in columns:
            columns[key] = pd.Series(bias, index=frame.index)
            mapping[key] = {"source": f"Settings/{key}/Start/Level", "factor_to_si": 1, "origin": "programmed_bias", "unit_status":"confirmed", "unit_source":"instrument_program_V"}
            warnings.append(f"{key}={bias:g} V: Settings의 고정 설정값 사용; 실측 전압이 아님")
    axis = cfg.data["analysis"]["x"]
    axis_source = "configuration"
    if cfg.data["analysis"]["auto_detect_axis"]:
        if settings.get("sweep_axis"):
            axis, axis_source = settings["sweep_axis"], "Settings/Forcing Function"
        else:
            varying = [key for key in ("vd", "vg") if key in columns and columns[key].dropna().nunique() > 1]
            available = [key for key in ("vd", "vg") if key in columns]
            if len(varying) == 1:
                axis, axis_source = varying[0], "varying_voltage_column"
            elif len(available) == 1:
                axis, axis_source = available[0], "available_voltage_column"
            else:
                warnings.append(f"단일 스윕 축을 자동 확정할 수 없어 설정의 {axis} 사용; 조건 확인 필요")
    keys = (["vg"] if axis == "vd" else ["vd"]) if cfg.data["analysis"]["auto_detect_axis"] else cfg.data["analysis"]["group_by"]
    required = [axis, cfg.data["analysis"]["y"]]
    if any(key not in columns for key in required):
        raise NoMeasurementHeader(f"{sheet}: 필수 컬럼 {required}가 없습니다.")
    for key in keys:
        fallback_key = {"vg": "vgs", "vd": "vds"}.get(key, key)
        metadata_value = metadata.get(key, metadata.get(fallback_key))
        hint = metadata.get("_filename_hints", {})
        hint_used = axis == "vg" and key == "vd" and not isinstance(metadata_value, (float, int)) and "vd" in hint
        if hint_used:
            metadata_value = hint["vd"]
        if key not in columns and isinstance(metadata_value, (float, int)):
            columns[key] = pd.Series(metadata_value, index=frame.index)
            mapping[key] = {"source": hint["vd_source"] if hint_used else f"filename/{key}=", "factor_to_si": 1, "origin": "filename_bias"}
            warnings.append(f"{key}: 파일명 메타데이터의 고정값 사용")
        elif key not in columns:
            warnings.append(f"고정 조건 {key} 없음: 단일 조건 측정인지 연구자가 확인해야 함")
    data = pd.DataFrame(columns)
    needed = required + [key for key in keys if key in data]
    valid = np.isfinite(data[needed].to_numpy(dtype=float)).all(axis=1)
    data.insert(0, "source_row", frame.index.to_numpy() + header + 2)
    data.insert(0, "sheet", sheet)
    data.insert(0, "acquisition_order", frame.index.to_numpy())
    data["source_sheet"] = source_sheet or sheet
    data["source_id_cell"] = [cell_address(mapping["id"].get("source_column"), row) for row in data["source_row"]]
    data["source_x_cell"] = [cell_address(mapping[axis].get("source_column"), row) for row in data["source_row"]]
    data['raw_id_cell_value']=frame[mapping['id']['source']].to_numpy() if mapping['id']['source'] in frame else None
    data['raw_x_cell_value']=frame[mapping[axis]['source']].to_numpy() if mapping[axis]['source'] in frame else None
    data["compliance_flag"] = False
    data["compliance_flag_recorded"] = False
    for source in frame.columns:
        if re.search(r"(?i)compliance.*(?:flag|status)|(?:flag|status).*compliance", str(source)):
            data["compliance_flag_recorded"] = True
            data["compliance_flag"] |= frame[source].astype(str).str.casefold().isin(["1", "true", "compliance", "limit"])
    data["point_valid"] = valid
    # Only a contiguous suffix of fully empty/placeholder measurement cells is
    # padding. An internal placeholder remains a real missing measurement.
    measurement_columns = [col for col in frame.columns if column_info(col, cfg)]
    empty = frame[measurement_columns].map(lambda v: pd.isna(v) or (isinstance(v, str) and v.strip() in ("", "--", "—"))).all(axis=1)
    padding = np.zeros(len(frame), dtype=bool)
    for pos in range(len(frame)-1, -1, -1):
        if not empty.iloc[pos]:
            break
        padding[pos] = True
    data["row_kind"] = np.where(padding, "trailing_padding", np.where(valid, "measurement", "missing_measurement"))
    data["segment_id"] = pd.Series((~valid & ~padding).astype(int), index=data.index).cumsum()
    if trace_id is not None:
        data.insert(0, "trace_id", trace_id)
    invalid = int((~valid & ~padding).sum())
    for optional in ("ig",):
        if optional in data and not np.isfinite(data[optional]).all():
            warnings.append(f"{optional}: 비수치/비유한 값이 있어 해당 QC는 부분값으로 판정할 수 없음")
    if invalid:
        warnings.append(f"필수값 비수치/비유한 {invalid}/{len(data)}행 제외; 원본 파일 보존")
    clean = data.loc[valid].reset_index(drop=True)
    if clean.empty:
        raise ValueError(f"{sheet}: 유효한 측정 행이 없습니다.")
    derived = [str(column) for column in frame.columns if re.sub(r"[^a-z0-9]", "", str(column).lower()) in ("gm", "gm2")]
    if derived:
        warnings.append("장비 계산 컬럼 " + ", ".join(derived) + " 제외; GM은 유효한 Id/Vg에서 별도 계산")
    return {"name": sheet, "source_sheet": source_sheet or sheet, "trace_id": trace_id, "axis": axis, "axis_source": axis_source, "group_by": keys, "data": clean, "points": data, "raw_rows": len(data) - int(padding.sum()), "padding_rows": int(padding.sum()), "invalid_rows": invalid, "warnings": warnings, "column_mapping": mapping, "ignored_derived_columns": derived, "sweep_program": settings.get("terminals", {}).get(axis, {}), "compliance_a": settings.get("compliance_a", {}), "parse_status": {"status": "parsed_with_gaps" if invalid else "parsed", "header_row": header+1, "source_sheet": source_sheet or sheet, "ignored_columns": [str(c) for c in frame.columns if not column_info(c,cfg)], "padding_rows": int(padding.sum()), "missing_source_rows": data.loc[~valid & ~padding, "source_row"].astype(int).tolist()}}


def cell_address(column, row):
    if column is None:
        return None
    letters, number = "", int(column)
    while number:
        number, remainder = divmod(number - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters + str(row)


def read_settings(book):
    """Read values from the Keithley table. Never execute sheet formulas/text."""
    result = {"fixed_bias_v": {}, "compliance_a": {}, "terminals": {}}
    name = next((sheet for sheet in book.sheet_names if sheet.casefold() == "settings"), None)
    if name is None:
        return result
    table = pd.read_excel(book, sheet_name=name, header=None, dtype=object)
    rows = {}
    for _, row in table.iterrows():
        label = str(row.iloc[0]).strip().casefold() if len(row) else ""
        rows.setdefault(label, row)
    for label, key in (("last executed", "measurement_timestamp_raw"), ("test name", "test_name"), ("ktei version", "ktei_version"), ("sweep delay", "sweep_delay_s"), ("hold time", "hold_time_s")):
        if label in rows and len(rows[label]) > 1 and pd.notna(rows[label].iloc[1]):
            value = rows[label].iloc[1]
            result[key] = value.item() if isinstance(value, np.generic) else str(value) if not isinstance(value, (str, int, float)) else value
    names = rows.get("name")
    if names is None:
        return result
    for index in range(1, len(names)):
        token = re.sub(r"[^a-z]", "", str(names.iloc[index]).casefold())
        canonical = "vd" if token == "drainv" else "vg" if token == "gatev" else None
        if canonical is None:
            continue
        channel = {}
        for label in ("forcing function", "start/level", "stop", "step", "number of points", "compliance", "measure i", "measure v", "dual sweep mode"):
            value = rows[label].iloc[index] if label in rows and index < len(rows[label]) else None
            if value is not None and pd.notna(value):
                channel[label] = value.item() if isinstance(value, np.generic) else value
        result["terminals"][canonical] = channel
        forcing = str(channel.get("forcing function", "")).casefold().strip()
        if forcing == "voltage sweep":
            if result.get("sweep_axis") and result["sweep_axis"] != canonical:
                raise ValueError("Settings에 두 전압 Sweep 축이 있어 자동 분석 축을 확정할 수 없습니다.")
            result["sweep_axis"] = canonical
        for field, destination in (("compliance", "compliance_a"), ("start/level", "fixed_bias_v")):
            if field == "start/level" and forcing != "voltage bias":
                continue
            try:
                value = float(channel[field])
                if np.isfinite(value):
                    result[destination][canonical] = value
            except (KeyError, TypeError, ValueError):
                pass
    return result


def normalize_traces(frame, sheet, header, cfg, metadata, settings):
    indexed_copies=[];retained={};omit=[]
    for column in frame.columns:
        info=column_info(column,cfg);number=trace_number(column)
        if info is None or number is None:continue
        key=(info[0],number)
        if key in retained:
            original=retained[key]
            if column_info(original,cfg)[1]!=info[1] or not frame[column].equals(frame[original]):
                raise ValueError(f'{sheet}/{column}: same indexed channel has different values or unit scale')
            omit.append(column)
            indexed_copies.append({'header':column,'source_column':frame.attrs.get('source_columns',{}).get(column),
                'retained_header':original,'trace_id':number,'reason':'exact indexed chart copy; identical unit scale'})
        else:retained[key]=column
    if omit:frame=frame[[c for c in frame.columns if c not in omit]]
    # Repeated DrainI columns share GateV and a row of per-column Vds values.
    currents = [c for c in frame.columns if column_info(c,cfg) and column_info(c,cfg)[0] == "id"]
    if len(currents) > 1 and any("{col:" in str(c) for c in currents) and all(trace_number(c) is None for c in currents):
        common = [c for c in frame.columns if column_info(c,cfg) and column_info(c,cfg)[0] == "vg"]
        # KTEI workbooks may append an exact GateV/DrainI copy for a chart.
        # This is distinct from multiple biases with a Vds row above the header.
        # Collapse only demonstrably identical columns with identical scales,
        # a fixed drain bias in Settings, and no per-column Vds labels.
        upper_values=[str(text) for current in currents for _,text in frame.attrs.get('upper_conditions',{}).get(current,[])]
        labeled=any(re.search(r'(?i)vds?\s*=',text) for text in upper_values)
        def identical_full_or_prefix(column,original):
            if column_info(column,cfg)[1]!=column_info(original,cfg)[1]:return False
            if frame[column].equals(frame[original]):return True
            mask=frame[column].notna().to_numpy();positions=np.flatnonzero(mask)
            # A graph helper can contain just the forward prefix followed by
            # blank padding. Verify every populated cell at the same source row;
            # never replace the longer original or infer an unmeasured bias.
            return bool(len(positions)>=2 and np.array_equal(positions,np.arange(len(positions)))
                and frame.loc[mask,column].equals(frame.loc[mask,original]))
        same_ids=all(identical_full_or_prefix(c,currents[0]) for c in currents)
        same_gates=bool(common) and all(identical_full_or_prefix(c,common[0]) for c in common)
        paired_padding=len(currents)==len(common) and all(frame[c].notna().equals(frame[g].notna()) for c,g in zip(currents,common))
        if not labeled and same_ids and same_gates and paired_padding and settings.get('sweep_axis')=='vg' and 'vd' in settings.get('fixed_bias_v',{}):
            omitted=set(currents[1:]+common[1:])
            record=normalize(frame[[c for c in frame.columns if c not in omitted]],sheet,header,cfg,metadata,settings)
            record['duplicate_export_columns']=[{'source_column':frame.attrs.get('source_columns',{}).get(c),'header':c,
                'populated_cells':int(frame[c].notna().sum()),
                'reason':'exact full/prefix chart copy at same source rows; identical scale; longer original and reverse preserved'} for c in frame.columns if c in omitted]
            record['warnings'].append('동일 GateV/DrainI 그래프용 복사 열을 기록하고 원본 열만 사용했습니다. 다른 값/배율/조건 열은 합치지 않습니다.')
            return [record]
        records = []
        for index, current in enumerate(currents,1):
            upper = frame.attrs.get("upper_conditions", {}).get(current, [])
            found = []
            for row_number, text in upper:
                match = re.search(r"(?i)vds?\s*=\s*([+−-]?\d+(?:\.\d+)?)(?:\s*V\b)?", str(text))
                if match:
                    found.append((float(match.group(1).replace("−","-")), row_number))
            if len({v for v,_ in found}) != 1:
                raise ValueError(f"{sheet}/{current}: repeated current column has missing/conflicting Vds header condition")
            options = {**settings, "fixed_bias_v": {**settings.get("fixed_bias_v", {}), "vd": found[0][0]}, "sweep_axis": "vg"}
            record = normalize(frame[common+[current]],f"{sheet}/column-{index:03d}",header,cfg,metadata,options,sheet,index)
            record["column_mapping"]["vd"].update({"source":"upper_header/Vds", "origin":"programmed_header", "source_cell": cell_address(frame.attrs['source_columns'][current],found[0][1])})
            records.append(record)
        return records
    indexed, common = {}, []
    for column in frame.columns:
        info = column_info(column, cfg)
        if info is None:
            common.append(column)
            continue
        number = trace_number(column)
        if number is None:
            common.append(column)
        else:
            indexed.setdefault(number, []).append(column)
    if not indexed:
        return [normalize(frame, sheet, header, cfg, metadata, settings)]
    records = []
    for number, columns in sorted(indexed.items()):
        record=normalize(frame[common + columns], f"{sheet}/trace-{number:03d}", header, cfg, metadata, settings, sheet, number)
        record['duplicate_export_columns']=[item for item in indexed_copies if item['trace_id']==number]
        records.append(record)
    return records


def load_measurements(path, cfg, metadata):
    path = Path(path)
    if path.suffix.lower() == ".csv":
        frame, header = read_csv(path, cfg)
        return normalize_traces(frame, "CSV", header, cfg, metadata, {}), []
    sheets, ignored = [], []
    reader_log = io.StringIO()
    # BIFF files from these KTEI exports are readable despite OLE padding warnings.
    # Capture those warnings as provenance instead of mixing them into CLI JSON.
    legacy = path.read_bytes()[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    kwargs = {"engine": "xlrd", "engine_kwargs": {"logfile": reader_log}} if legacy else {}
    with pd.ExcelFile(path, **kwargs) as book:
        settings = read_settings(book)
        selected = cfg.data["ingest"]["sheet_names"]
        names = book.sheet_names if selected == "all" else selected
        for name in names:
            if name not in book.sheet_names:
                raise ValueError(f"워크북에 시트 {name}이 없습니다.")
            try:
                preview = pd.read_excel(book, sheet_name=name, header=None, nrows=50)
                header = header_index(preview.values.tolist(), cfg)
                table = pd.read_excel(book, sheet_name=name, header=None, dtype=object)
                headers = table.iloc[header].tolist()
                unique = [str(c)+f" {{col:{i+1}}}" if headers.count(c)>1 and pd.notna(c) else str(c) for i,c in enumerate(headers)]
                frame = table.iloc[header+1:].copy()
                frame.index = np.arange(len(frame))
                frame.columns = unique
                frame.attrs['source_columns'] = {c:i+1 for i,c in enumerate(unique)}
                frame.attrs['upper_conditions'] = {c:[(r+1, table.iloc[r,i]) for r in range(header)] for i,c in enumerate(unique)}
                frame.attrs['voltage_origins'] = {k: "programmed_voltage" if str(settings.get('terminals',{}).get(k,{}).get('measure v','')).casefold() in ('no','programmed') else "exported_voltage_unconfirmed" for k in ('vd','vg')}
                sheets.extend(normalize_traces(frame, name, header, cfg, metadata, settings))
            except NoMeasurementHeader as error:
                if selected != "all":
                    raise
                ignored.append({"sheet": name, "reason": str(error)})
    if not sheets:
        raise NoMeasurementHeader("분석 가능한 Excel 시트가 없습니다.")
    sheets[0]["instrument_settings"] = settings
    sheets[0]["reader_warnings"] = reader_log.getvalue().strip().splitlines()
    return sheets, ignored
