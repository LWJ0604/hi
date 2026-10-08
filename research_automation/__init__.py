__version__ = "1.9.1"

from functools import lru_cache
import hashlib
from pathlib import Path


@lru_cache(maxsize=1)
def code_fingerprint():
    """One fingerprint per process; restart watch after editing source files."""
    root = Path(__file__).resolve().parent
    fingerprint = hashlib.sha256()
    files=[*root.rglob('*.py'), *root.joinpath('report_templates').rglob('*')]
    for file in sorted(p for p in files if p.is_file()):
        fingerprint.update(file.relative_to(root).as_posix().encode())
        fingerprint.update(b"\0")
        fingerprint.update(file.read_bytes())
    return fingerprint.hexdigest()
