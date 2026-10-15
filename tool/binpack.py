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


MARK = "MTRBIN1"


def pack_native(door: Path, installer: Path, folder: Path, version: str,
                out: Path) -> dict:
    """The C door, the installer behind it and the program, as one file:

        [door.c built] [installer: launcher.py, one file] [zip of the program]

    with the zip's comment -- the last bytes of the file -- saying where the
    installer is and which build this is, for the door to read in a moment.
    """
    said = manifest(folder, version)
    door_bytes = door.read_bytes()
    installer_bytes = installer.read_bytes()
    payload = out.with_name(out.stem + "_payload.zip")
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr(MANIFEST, json.dumps(said))
        for rel in said["files"]:
            how = zipfile.ZIP_STORED if rel.lower().endswith(STORED) else zipfile.ZIP_DEFLATED
            archive.write(folder / rel, "app/" + rel, compress_type=how)
        archive.comment = (f"{MARK};id={said['id']};installer={len(door_bytes)},"
                           f"{len(installer_bytes)};").encode("ascii")
    with open(out, "wb") as target:
        target.write(door_bytes)
        target.write(installer_bytes)
        with open(payload, "rb") as source:
            while block := source.read(1 << 22):
                target.write(block)
    payload.unlink()
    return said


def compile_door(source: Path, out: Path, kinetic: bool = False) -> bool:
    """door.c built with Microsoft's compiler, found through vswhere. False if
    there is none -- the build then keeps the Python door."""
    import os
    import subprocess
    where = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) \
        / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if not where.is_file():
        return False
    found = subprocess.run([str(where), "-latest", "-products", "*", "-requires",
                            "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                            "-property", "installationPath"],
                           capture_output=True, text=True)
    root = found.stdout.strip().splitlines()[0] if found.stdout.strip() else ""
    setup = Path(root) / "VC" / "Auxiliary" / "Build" / "vcvars64.bat"
    if not setup.is_file():
        return False
    work = out.parent / f"{out.stem}_obj"
    work.mkdir(parents=True, exist_ok=True)
    flags = "/nologo /O1 /MT /W3 /DUNICODE /D_UNICODE"
    if kinetic:
        flags += " /DKINETIC_DOOR"
    # Through a batch file: cmd reads quotes its own way, not the way a
    # quoted argument would be handed to it.
    script = work / "build_door.bat"
    # vcvars looks for vswhere on the PATH; and a quote after a backslash is
    # read by cl as a quote in the name, hence the forward slash.
    lines = [f'@set "PATH={where.parent};%PATH%"',
             f'@call "{setup}" >nul',
             f'@cl {flags} /Fo"{work.as_posix()}/" "{source}" /link /SUBSYSTEM:WINDOWS '
             f'user32.lib /OUT:"{out}"']
    script.write_text("\r\n".join(lines) + "\r\n", encoding="ascii")
    built = subprocess.run(["cmd", "/c", str(script)], capture_output=True, text=True)
    if built.returncode != 0 or not out.is_file():
        print(built.stdout[-2000:], built.stderr[-2000:])
        return False
    return True
