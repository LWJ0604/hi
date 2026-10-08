import copy
import hashlib
import json
import os
import math
import re
from pathlib import Path
from pathlib import PureWindowsPath
from zoneinfo import ZoneInfo

DEFAULT = {
    "paths": {"inbox": "data_inbox", "analysis": "analysis", "vault": "vault", "state": "state", "logs": "logs", "backups": "backups"},
    "timezone": "Asia/Seoul",
    "ingest": {"recursive": True, "stable_seconds": 2, "poll_seconds": 10, "header_row": "auto", "sheet_names": "all", "encoding": "auto", "separator": "auto", "max_bytes": 52428800, "max_attempts": 3, "retry_seconds": 60, "extensions": [".csv", ".xls", ".xlsx"], "exclude_globs": []},
    "columns": {"mapping": {}, "scales": {"vd": 1, "vg": 1, "id": 1, "ig": 1}, "assume_si_for_unitless": True},
    "analysis": {"x": "vd", "y": "id", "group_by": ["vg"], "min_points": 6, "max_groups": 200, "models": ["linear", "sinh"], "rr_voltage": 1.0, "current_floor_a": 1e-14, "auto_detect_axis": True, "transfer_models": ["linear"]},
    "qc": {"gate_leakage_a": 1e-7, "zero_offset_a": 1e-7, "zero_voltage_tolerance_v": 1e-9, "current_jump_a": 5e-8, "hysteresis_mean_difference_a": 1e-7, "max_invalid_fraction": 0.05},
    "ai": {"enabled": False, "model": "gpt-4.1-mini", "timeout_seconds": 45, "max_attempts": 3, "max_output_tokens": 1800, "max_groups": 20, "include_filename": False},
    "organization": {"path_rules": []},
    "measurement_profile": {"voltage_unit": None, "current_unit": None, "confirmed": False, "source": None},
    "benchmark": {"enabled": True, "metadata_root": None, "electrode_pair": None,
        "fit_range_v": [0.6, 2.0], "gm_windows_v": [2.0, 4.0, 8.0], "min_fit_points": 5},
    "science": {
        "rr_voltages_v": [0.5, 1.0, 1.5, 2.0],
        "detection_limit_a": None, "detection_limit_evidence": None,
        "local_jump_sigma": None, "leakage_ratio_limit": None,
        "compliance_proximity_ratio": 0.98,
        "zero_slope_window_v": 0.2,
        "gm_windows_v": [1.0, 2.0, 4.0], "gm_polynomial_order": 2,
        "gm_min_points": 5, "gm_peak_tolerance_v": 2.0,
        "vth": None, "ss": None, "mobility": None,
        "rectifier_models_enabled": False, "rectifier_range_v": [0.6, 2.0],
        "rectifier_models": ["exponential", "independent", "shared_a_j0", "shared_a"],
        "knee_axis": "linear", "knee_min_side_points": 4,
        "offline": True,
    },
}


class Config:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.root = self.path.parent
        self.data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        for section in ("measurement_profile", "benchmark"):
            self.data.setdefault(section, copy.deepcopy(DEFAULT[section]))
            for key,value in DEFAULT[section].items():self.data[section].setdefault(key,copy.deepcopy(value))
        self.data.setdefault("organization", copy.deepcopy(DEFAULT["organization"]))
        self.data.setdefault("science", copy.deepcopy(DEFAULT["science"]))
        for key, value in DEFAULT["science"].items():
            self.data["science"].setdefault(key, copy.deepcopy(value))
        # Existing 1.0.0 configurations remain valid and retain their input policy.
        for key in ("extensions", "exclude_globs"):
            self.data.get("ingest", {}).setdefault(key, copy.deepcopy(DEFAULT["ingest"][key]))
        for key in ("auto_detect_axis", "transfer_models"):
            self.data.get("analysis", {}).setdefault(key, copy.deepcopy(DEFAULT["analysis"][key]))
        self.validate()
        if os.name != "nt" and any(PureWindowsPath(value).is_absolute() for value in self.data["paths"].values()):
            raise ValueError("Windows 경로가 들어 있는 설정은 Windows에서 실행하세요. Linux 데모는 config.example.json을 사용하세요.")
        self.paths = {key: (self.root / value).resolve() for key, value in self.data["paths"].items()}
        # Ingest and output trees must never overlap, including through symlinks.
        for key, path in self.paths.items():
            for other, candidate in self.paths.items():
                allowed = key == "vault" and other == "inbox" and path != candidate
                if key != other and not allowed and (path == candidate or path in candidate.parents):
                    raise ValueError(f"paths.{key} and paths.{other} overlap")
        for generated in ("Experiments", "Attachments", "Weekly"):
            output = self.paths["vault"] / generated
            inbox = self.paths["inbox"]
            if inbox == output or inbox in output.parents or output in inbox.parents:
                raise ValueError("inbox는 Vault의 자동 생성 폴더와 겹칠 수 없습니다.")

    def validate(self):
        d = self.data
        if set(d) != set(DEFAULT):
            raise ValueError("설정의 최상위 필드는 config.example.json과 같아야 합니다.")
        if set(d["paths"]) != set(DEFAULT["paths"]):
            raise ValueError("설정에 필요한 paths 필드가 누락되었습니다.")
        for section in ("ingest", "columns", "analysis", "qc", "ai", "organization", "science", "measurement_profile", "benchmark"):
            if set(d[section]) != set(DEFAULT[section]):
                raise ValueError(f"{section}의 필드는 config.example.json과 같아야 합니다.")
        profile=d['measurement_profile']
        if not isinstance(profile['confirmed'],bool):raise ValueError('measurement_profile.confirmed: true/false required')
        if profile['confirmed'] and (profile['voltage_unit'] not in ('V','mV','uV') or profile['current_unit'] not in ('A','mA','uA','nA','pA') or not isinstance(profile['source'],str) or not profile['source'].strip()):
            raise ValueError('확인된 단위 프로필에는 전압·전류 단위와 확인 출처가 필요합니다.')
        bench=d['benchmark']
        if not isinstance(bench['enabled'],bool):raise ValueError('benchmark.enabled: true/false required')
        for key in ('metadata_root','electrode_pair'):
            if bench[key] is not None and (not isinstance(bench[key],str) or not bench[key].strip()):raise ValueError('benchmark.'+key+': string or null required')
        limits=bench['fit_range_v']
        if not isinstance(limits,list) or len(limits)!=2 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in limits) or not 0<limits[0]<limits[1]:raise ValueError('benchmark.fit_range_v: positive ascending range required')
        if not isinstance(bench['gm_windows_v'],list) or not bench['gm_windows_v'] or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0 for v in bench['gm_windows_v']):raise ValueError('benchmark.gm_windows_v: positive finite widths required')
        if not isinstance(bench['min_fit_points'],int) or isinstance(bench['min_fit_points'],bool) or bench['min_fit_points']<5:raise ValueError('benchmark.min_fit_points: integer >=5 required')
        rules = d["organization"]["path_rules"]
        if not isinstance(rules, list):
            raise ValueError("organization.path_rules must be a list")
        supported = {"measurement_date", "device_name", "device_type", "fold", "condition", "illumination"}
        for rule in rules:
            if not isinstance(rule, str) or not rule.strip():
                raise ValueError("path_rules는 named capture가 있는 정규식 문자열 목록입니다.")
            try:
                pattern = re.compile(rule, re.IGNORECASE)
            except re.error as error:
                raise ValueError(f"path_rules 정규식 오류: {error}") from error
            if not pattern.groupindex or not set(pattern.groupindex) <= supported:
                raise ValueError(f"path_rules capture 지원 필드: {sorted(supported)}")
        for key, value in d["paths"].items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"paths.{key} must be a non-empty path")
        ZoneInfo(d["timezone"])
        extensions = d["ingest"]["extensions"]
        if not isinstance(extensions, list) or not extensions or any(not isinstance(ext, str) or ext.lower() not in (".csv", ".xls", ".xlsx") for ext in extensions):
            raise ValueError("ingest.extensions는 .csv/.xls/.xlsx 중 하나 이상의 목록이어야 합니다.")
        patterns = d["ingest"]["exclude_globs"]
        if not isinstance(patterns, list) or any(not isinstance(pattern, str) or not pattern.strip() for pattern in patterns):
            raise ValueError("ingest.exclude_globs는 비어 있지 않은 파일명 패턴 문자열의 목록이어야 합니다.")
        if d["analysis"]["x"] not in ("vd", "vg") or d["analysis"]["y"] != "id":
            raise ValueError("analysis.x는 vd/vg, y는 id를 사용합니다.")
        if not set(d["analysis"]["models"]) <= {"linear", "sinh"}:
            raise ValueError("지원 모델: linear, sinh")
        if not isinstance(d["analysis"]["auto_detect_axis"], bool):
            raise ValueError("auto_detect_axis must be true/false")
        if not isinstance(d["analysis"]["transfer_models"], list) or not set(d["analysis"]["transfer_models"]) <= {"linear"}:
            raise ValueError("Id–Vg transfer_models 지원: linear (경험적 추세 기준선)")
        if d["analysis"]["x"] in d["analysis"]["group_by"]:
            raise ValueError("독립변수는 group_by에 포함할 수 없습니다.")
        for section, keys in {"ingest": ["stable_seconds", "poll_seconds", "max_bytes", "max_attempts", "retry_seconds"], "analysis": ["min_points", "max_groups", "current_floor_a"], "ai": ["timeout_seconds", "max_attempts", "max_output_tokens", "max_groups"]}.items():
            for key in keys:
                if not isinstance(d[section][key], (int, float)) or not math.isfinite(d[section][key]) or d[section][key] <= 0:
                    raise ValueError(f"{section}.{key} must be positive")
        for key, value in d["qc"].items():
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"qc.{key} must be non-negative")
        if not 0 <= d["qc"]["max_invalid_fraction"] <= 1:
            raise ValueError("max_invalid_fraction must be in [0,1]")
        if d["ingest"]["header_row"] != "auto" and (not isinstance(d["ingest"]["header_row"], int) or d["ingest"]["header_row"] < 0):
            raise ValueError("header_row must be auto or a zero-based integer")
        if d["ingest"]["sheet_names"] != "all" and not isinstance(d["ingest"]["sheet_names"], list):
            raise ValueError("sheet_names must be all or a list of names")
        if any(not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in d["columns"]["scales"].values()):
            raise ValueError("column scales must be positive")
        for section, key in (("ingest", "max_bytes"), ("ingest", "max_attempts"), ("analysis", "min_points"), ("analysis", "max_groups"), ("ai", "max_attempts"), ("ai", "max_output_tokens"), ("ai", "max_groups")):
            if not isinstance(d[section][key], int):
                raise ValueError(f"{section}.{key} must be an integer")
        if d["analysis"]["min_points"] < 3:
            raise ValueError("min_points must be at least 3")
        science = d["science"]
        for key in ("rr_voltages_v", "gm_windows_v"):
            if not isinstance(science[key], list) or not science[key] or any(
                isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in science[key]):
                raise ValueError(f"science.{key}: positive finite values required")
        for key in ("detection_limit_a", "local_jump_sigma", "leakage_ratio_limit", "zero_slope_window_v"):
            value = science[key]
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0):
                raise ValueError(f"science.{key}: positive number or null required")
        if science["zero_slope_window_v"] is None:
            raise ValueError("zero_slope_window_v: positive number required")
        for key in ("gm_polynomial_order", "gm_min_points", "knee_min_side_points"):
            if not isinstance(science[key], int) or science[key] < 2:
                raise ValueError(f"science.{key}: integer >=2 required")
        if science["gm_min_points"] <= science["gm_polynomial_order"]:
            raise ValueError("gm_min_points must exceed polynomial order")
        if science["knee_axis"] not in ("linear", "log"):
            raise ValueError("knee_axis must be linear/log")
        if not 0 < science["compliance_proximity_ratio"] <= 1 or science["gm_peak_tolerance_v"] <= 0:
            raise ValueError("science: invalid proximity/peak tolerance")
        limits = science["rectifier_range_v"]
        if not isinstance(limits, list) or len(limits) != 2 or not 0 < limits[0] < limits[1]:
            raise ValueError("rectifier_range_v: positive ascending range required")
        if not isinstance(science["offline"], bool) or not isinstance(science["rectifier_models_enabled"], bool):
            raise ValueError("science toggles must be boolean")
        if not isinstance(science["rectifier_models"], list) or not set(science["rectifier_models"]) <= {"exponential", "independent", "shared_a_j0", "shared_a"}:
            raise ValueError("unknown rectifier model")
        for key in ("vth", "ss", "mobility"):
            if science[key] is not None and not isinstance(science[key], dict):
                raise ValueError(f"science.{key}: object or null required")

    def ensure_dirs(self):
        for path in self.paths.values():
            path.mkdir(parents=True, exist_ok=True)

    @property
    def fingerprint(self):
        # Paths do not change science, but changing the output destination must rerun.
        # Selection changes decide WHICH files run; they do not change a file's
        # analysis. Strip new fields to preserve 1.0.0 configuration hashes.
        payload = copy.deepcopy(self.data)
        for key in ("extensions", "exclude_globs"):
            payload["ingest"].pop(key, None)
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def initialize(path):
    target = Path(path)
    if target.exists():
        raise FileExistsError(f"설정이 이미 있습니다: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(copy.deepcopy(DEFAULT), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    cfg = Config(target)
    cfg.ensure_dirs()
    return cfg
