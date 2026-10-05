import hashlib
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def now(cfg):
    return datetime.now(ZoneInfo(cfg.data["timezone"]))


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path, value):
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def parse_filename(filename):
    result = {}
    for part in Path(filename).stem.split("_"):
        if "=" in part:
            key, value = part.split("=", 1)
            try:
                number = float(value)
                if not __import__("math").isfinite(number):
                    raise ValueError()
                value = number
            except ValueError:
                pass
            result[key.lower()] = value
    return result


def filename_hints(filename):
    stem = Path(filename).stem
    kind = re.search(r"(?i)(?<![a-z])(?:id|i)[ _-]*v([dg])(?![a-z])", stem)
    result = {"measurement_type": "Id-Vg" if kind and kind.group(1).lower() == "g" else "I-Vd" if kind else None}
    # @2V denotes Vd only on an explicitly named transfer measurement. @1
    # on an I-Vd file may be an acquisition label rather than a fixed bias.
    if result["measurement_type"] == "Id-Vg":
        explicit = re.search(r"(?i)(?<![a-z])vds?\s*[=_-]?\s*([+-]?\d+(?:\.\d+)?)\s*V(?![a-z])", stem)
        at = re.search(r"@\s*([+-]?\d+(?:\.\d+)?)\s*[vV](?![a-z])", stem)
        match = explicit or at
        if match:
            result.update({"vd": float(match.group(1)), "vd_source": "filename/" + match.group()})
    return result


def slug(value):
    return re.sub(r"[^\w.-]+", "_", str(value), flags=re.UNICODE)[:80].strip("._") or "measurement"
