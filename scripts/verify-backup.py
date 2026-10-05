"""Check every archived file against manifest without extracting anything."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

path = Path(sys.argv[1])
expected = Path(str(path) + ".sha256").read_text(encoding="utf-8").split()[0]
hasher = hashlib.sha256()
with path.open("rb") as source:
    for chunk in iter(lambda: source.read(1024 * 1024), b""):
        hasher.update(chunk)
if hasher.hexdigest() != expected:
    raise SystemExit("Archive checksum mismatch")
with zipfile.ZipFile(path) as archive:
    manifest = json.loads(archive.read("manifest.json"))
    for entry in manifest["files"]:
        value = archive.read(entry["path"])
        if len(value) != entry["bytes"] or hashlib.sha256(value).hexdigest() != entry["sha256"]:
            raise SystemExit("Invalid file: " + entry["path"])
print(f"Verified: {len(manifest['files'])} files")
