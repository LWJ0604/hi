"""Local research context from the source hierarchy; retain evidence and ambiguity."""
from datetime import date
from pathlib import PurePosixPath
import re
from .util import filename_hints

FOLD = re.compile(r"(?<![a-z])(drain|center|centre|source)[\s_-]*fold(?![a-z])", re.I)
MATERIALS = re.compile(r"(?<![a-z0-9])(ReS2|MoS2|MoSe2|WS2|WSe2|ReSe2|TFET|FET)(?![a-z0-9])", re.I)
GENERIC = {"원본", "raw", "data", "original", "측정", "측정 데이터", "data_inbox", "측정일 미확인", "날짜 미상", "날짜 미상 루트 파일", "날짜 미상_루트 파일", "측정 조건", "조건", "소자", "devices", "device", "dark", "light", "with light", "암조건", "광조사"}
DATE = re.compile(r"(?<!\d)(20\d{2})\s*(?:[-./_]|년)\s*(\d{1,2})\s*(?:[-./_]|월)\s*(\d{1,2})(?:일)?(?!\d)|(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)")


def dates_in(value, instrument=False):
    found = []
    for match in DATE.finditer(str(value)):
        parts = match.groups()[:3] if match.group(1) else match.groups()[3:]
        try:
            found.append(date(*map(int, parts)).isoformat())
        except ValueError:
            pass
    # Keithley Last Executed uses US month/day/year. Other ambiguous short
    # dates, file mtimes and the processing clock are deliberately not guessed.
    if instrument and not found:
        match = re.match(r"\s*(\d{1,2})/(\d{1,2})/(20\d{2})(?!\d)", str(value))
        if match:
            month, day, year = map(int, match.groups())
            try:
                found.append(date(year, month, day).isoformat())
            except ValueError:
                pass
    return found


def lighting_in(value):
    text = str(value).replace("_", " ").replace("-", " ").casefold()
    values = []
    if re.search(r"\bdark\b|암조건|암실", text):
        values.append("dark")
    if re.search(r"\b(?:with\s*light|light)\b|광조사|조명", text):
        values.append("light")
    return values


def fold_name(value):
    match = FOLD.search(str(value))
    if match:
        return ("center" if match.group(1).lower() == "centre" else match.group(1).lower()) + " fold"
    return str(value).strip()


def component(value, limit=48):
    """Portable Windows filename and unambiguous Obsidian wikilink component."""
    value = re.sub(r'[\\/:*?"<>|\[\]#\x00-\x1f]', "_", str(value))
    value = re.sub(r"\s+", " ", value).strip(" .")[:limit].rstrip(" .") or "미확인"
    if re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", value):
        value = "_" + value
    return value


def condition_folder(value):
    text = value.strip().casefold()
    return bool(re.fullmatch(r"(?:dark|light|with[ _-]+light|암조건|광조사)(?:[ _-]+\d+(?:\.\d+)?\s*(?:nm|mw|uw))?", text) or re.fullmatch(r"(?:\d+(?:\.\d+)?\s*(?:k|°c|nm|mw|uw|hz|pa|torr)|vacuum|air|ambient|진공)", text))


def identify(relative, metadata, instrument, summary, cfg):
    """Priority: configured captures, explicit filename keys, directories, file,
    instrument timestamp. Every selected field keeps its provenance.
    """
    relative = str(relative).replace("\\", "/")
    path = PurePosixPath(relative)
    folders = list(path.parent.parts)
    filename = path.stem
    candidates = {key: [] for key in ("measurement_date", "device_name", "device_type", "fold", "condition", "illumination")}
    warnings = []

    def add(key, value, source, rank):
        if value is not None and str(value).strip():
            candidates[key].append({"value": str(value).strip(), "source": source, "priority": rank})

    for index, rule in enumerate(cfg.data["organization"]["path_rules"]):
        match = re.search(rule, relative, re.I)
        if match:
            for key, value in match.groupdict().items():
                if value:
                    if key == "measurement_date":
                        parsed = dates_in(value)
                        if len(set(parsed)) != 1:
                            warnings.append(f"path_rules[{index}] 측정 날짜를 해석하지 못함: {value}")
                            continue
                        value = parsed[0]
                    elif key == "fold":
                        value = fold_name(value)
                    elif key == "illumination":
                        parsed = lighting_in(value)
                        if len(parsed) != 1:
                            warnings.append(f"path_rules[{index}] 조명 조건을 확정하지 못함: {value}")
                            continue
                        value = parsed[0]
                    add(key, value, f"path_rules[{index}]", 0)
            break

    aliases = {"measurement_date": ("measurement_date", "date", "측정일"), "device_name": ("device_name", "device", "소자", "소자명"), "device_type": ("device_type", "material", "소자종류"), "fold": ("fold",), "condition": ("condition",), "illumination": ("illumination",)}
    for key, keys in aliases.items():
        for alias in keys:
            if alias not in metadata:
                continue
            value = metadata[alias]
            if key == "measurement_date":
                parsed = dates_in(value)
                if len(set(parsed)) != 1:
                    warnings.append(f"파일명 {alias}의 날짜 확인 필요: {value}")
                    continue
                value = parsed[0]
            elif key == "fold":
                value = fold_name(value)
            elif key == "illumination":
                parsed = lighting_in(value)
                if len(parsed) != 1:
                    continue
                value = parsed[0]
            add(key, value, f"filename/{alias}=", 1)

    # Date-only folders and known condition/administrative folders are not devices.
    device_candidates = []
    for index, folder in enumerate(folders):
        rank = 2 + (len(folders) - index) / 1000
        source = "folder/" + "/".join(folders[:index + 1])
        for value in dates_in(folder):
            add("measurement_date", value, source, rank)
        for match in FOLD.finditer(folder):
            add("fold", fold_name(match.group()), source, rank)
        if condition_folder(folder):
            for value in lighting_in(folder):
                # The user's naming policy makes the filename authoritative.
                # Folder lighting remains evidence but cannot override it.
                add("illumination", value, source, 4 + rank / 1000)
            if not re.fullmatch(r"(?i)dark|light|with[ _-]+light|암조건|광조사", folder.strip()):
                add("condition", folder, source, rank)
        # The user's device folders themselves are named drain-fold/center-fold.
        # Keep the original device label instead of treating fold as a condition.
        candidate = DATE.sub("", folder).strip(" _-./()")
        if candidate.casefold() not in GENERIC and candidate and not condition_folder(folder) and not re.search(r"(?:측정|미확인|미상|원본)$", candidate) and not re.fullmatch(r"\d{1,4}", candidate):
            device_candidates.append({"value": candidate, "source": source, "priority": rank})
            material = MATERIALS.search(candidate.replace("_", " "))
            if material:
                add("device_type", material.group(), source, rank)
    # A YYYY/MM/DD hierarchy is recognizable as well.
    for value in dates_in("/".join(folders)):
        add("measurement_date", value, "source_folder_path", 2.999)
    if device_candidates:
        selected = min(device_candidates, key=lambda value: value["priority"])
        add("device_name", selected["value"], selected["source"], selected["priority"])
        if len(device_candidates) > 1:
            warnings.append("소자 이름은 파일에 가장 가까운 소자 폴더를 사용하고, 상위 소자 폴더 계층도 저장 경로에 보존합니다. device_hierarchy를 확인하거나 path_rules로 지정하세요.")
    for value in dates_in(filename):
        add("measurement_date", value, "filename", 3)
    for match in FOLD.finditer(filename):
        add("fold", fold_name(match.group()), "filename", 3)
    for value in lighting_in(filename):
        add("illumination", value, "filename", 3)
    material = MATERIALS.search(filename.replace("_", " "))
    if material:
        add("device_type", material.group(), "filename/material_token", 3)
        # A material token alone cannot identify an individual device.
    timestamp = instrument.get("measurement_timestamp_raw")
    # Instrument clock is an equipment record, not an actual measurement date.

    result = {"source_folders": folders, "source_relative_path": relative, "device_hierarchy": [item["value"] for item in device_candidates], "warnings": warnings}
    for key, options in candidates.items():
        ordered = sorted(options, key=lambda item: item["priority"])
        picked = ordered[0] if ordered else {"value": None, "source": "unavailable"}
        result[key] = picked["value"]
        result[key + "_source"] = picked["source"]
        distinct = {item["value"].casefold() for item in ordered}
        if len(distinct) > 1:
            warnings.append(f"{key} 후보 불일치: " + "; ".join(f"{item['value']} ({item['source']})" for item in ordered) + f". 선택: {picked['value']}")
    result["evidence"] = candidates
    lighting = {item["value"] for item in candidates["illumination"]}
    marked=any(item["source"].startswith(("filename","path_rules")) for item in candidates["illumination"])
    result["illumination"] = "conflict" if len(lighting) > 1 else (result["illumination"] or "unknown") if marked else "unknown"
    if not marked:result["illumination_source"]="unavailable/unmarked_filename"
    result["instrument_timestamp_raw"] = timestamp
    axes = sorted({group["axis"] for group in summary["groups"]}) or [summary["axis"]]
    result["measurement_type"] = "+".join("I-Vd" if axis == "vd" else "Id-Vg" for axis in axes)
    ranges = {}
    for group in summary["groups"]:
        axis = group["axis"]
        entry = ranges.setdefault(axis, {"min_v": group["x_min_v"], "max_v": group["x_max_v"]})
        entry["min_v"] = min(entry["min_v"], group["x_min_v"])
        entry["max_v"] = max(entry["max_v"], group["x_max_v"])
    biases = {}
    for group in summary["groups"]:
        for key, value in group["conditions"].items():
            if isinstance(value, (int, float)):
                biases.setdefault(key, set()).add(value)
    result["sweep_ranges_v"] = ranges
    result["fixed_conditions_v"] = {key: sorted(values) for key, values in biases.items()}
    hints = filename_hints(path.name)
    result["filename_hints"] = hints
    if hints.get("measurement_type") and hints["measurement_type"] != result["measurement_type"]:
        warnings.append(f"파일명 유형 {hints['measurement_type']}와 실제 컬럼/Settings 유형 {result['measurement_type']}이 다릅니다. 실제 분석 축을 사용했습니다.")
    if "vd" in hints and result["fixed_conditions_v"].get("vd") and result["fixed_conditions_v"]["vd"] != [hints["vd"]]:
        warnings.append(f"파일명 Vd={hints['vd']:g} V와 데이터/Settings 조건 {result['fixed_conditions_v']['vd']} V가 다릅니다. 데이터/Settings 조건을 사용했습니다.")
    label = [result["measurement_type"], result["illumination"]]
    for key, values in result["fixed_conditions_v"].items():
        value_label = f"{values[0]:g}" if len(values) == 1 else f"{min(values):g}to{max(values):g}"
        label.append(f"{key.capitalize()}={value_label}V")
    if "vg" in axes and "vd" not in result["fixed_conditions_v"]:
        label.append("Vd=unknown")
    if result["condition"]:
        label.append(result["condition"])
    result["condition_label"] = "__".join(label)
    device = result["device_name"] or (result["device_type"] + "_소자명 미확인" if result["device_type"] else "소자 미확인")
    automatic_name = result["device_name_source"].startswith("folder/")
    hierarchy = result["device_hierarchy"] if automatic_name else [device]
    # A filename-only fold still separates measurements of one named device.
    if result["fold"] and not any(FOLD.search(part) for part in hierarchy):
        hierarchy = [*hierarchy, result["fold"]]
    result["device_path"] = "/".join(component(part, 40) for part in hierarchy)
    parts = [result["device_path"], result["measurement_date"] or "측정일 미확인", component(result["condition_label"], 48)]
    result["vault_subfolder"] = "/".join(parts)
    if not result["measurement_date"]:
        warnings.append("측정 날짜 미확인: 처리 날짜나 파일 수정 날짜로 대체하지 않았습니다.")
    if not result["device_name"]:
        warnings.append("개별 소자 이름 미확인: 원본 소자 폴더 또는 path_rules를 확인하세요.")
    return result


def csv_context(context):
    return {key: context.get(key) for key in ("measurement_date", "device_name", "device_type", "fold", "illumination", "measurement_type", "condition_label", "source_relative_path", "metadata_status")} | {"voltage_unit":"V","current_unit":"A","gm_unit":"A/V","normalized_gm_unit":"1","gm_over_vd_unit":"A/V^2"}
