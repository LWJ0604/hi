__version__ = "1.6.0"

from functools import lru_cache
import hashlib
from pathlib import Path


@lru_cache(maxsize=1)
def code_fingerprint():
    """One fingerprint per process; restart watch after editing source files."""
    root = Path(__file__).resolve().parent
    fingerprint = hashlib.sha256()
    for file in sorted(root.rglob("*.py")):
        fingerprint.update(file.relative_to(root).as_posix().encode())
        fingerprint.update(b"\0")
        fingerprint.update(file.read_bytes())
    return fingerprint.hexdigest()
