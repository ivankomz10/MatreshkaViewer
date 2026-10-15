"""The build's second half on Windows: the program folder packed onto the
end of its door, launcher.py.

    door + zip( bin-manifest.json, app/<every file of the folder> )

A zip is read from its end, so it can follow an executable; PyInstaller's own
archive inside the door is found from the door's end in the same way and
does not mind what follows. The manifest names the build -- its version and a
hash of every file -- and gives each file's size and hash, which is what the
door compares an update against.
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from launcher import MANIFEST, digest

# Already packed; deflating them again buys nothing and costs time.
STORED = (".png", ".jpg", ".npz", ".zip", ".pyz")


def manifest(folder: Path, version: str) -> dict:
    files = {}
    whole = hashlib.sha256()
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        rel = path.relative_to(folder).as_posix()
        hashed = digest(path)
        files[rel] = [path.stat().st_size, hashed]
        whole.update(f"{rel}:{hashed}\n".encode())
    return {"id": f"{version}-{whole.hexdigest()[:10]}", "version": version,
            "files": files}


def pack(door: Path, folder: Path, version: str) -> dict:
    """Append the folder to the door; the door becomes the program.

    Written as a zip of its own first and then added on byte for byte: a zip
    read from the end finds its own records whatever stands before it, and
    nothing of the door's is ever taken for part of it."""
    said = manifest(folder, version)
    payload = door.with_name(door.stem + "_payload.zip")
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr(MANIFEST, json.dumps(said))
        for rel in said["files"]:
            how = zipfile.ZIP_STORED if rel.lower().endswith(STORED) else zipfile.ZIP_DEFLATED
            archive.write(folder / rel, "app/" + rel, compress_type=how)
    with open(door, "ab") as out, open(payload, "rb") as source:
        while block := source.read(1 << 22):
            out.write(block)
    payload.unlink()
    return said
