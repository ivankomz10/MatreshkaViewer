"""The Windows door: the program packed onto its end, laid out once in
bin/<build>, and an update writing only what changed.

Built on a stand-in door (any bytes do: a zip read from its end does not
care what comes before it) and a stand-in program folder, in the sandbox.
"""
from __future__ import annotations

import json
import os
import shutil
import zipfile

import pytest

from conftest import HOME

import binpack
import launcher

ROOT = HOME / "binpack"


def _program(folder, files: dict):
    shutil.rmtree(folder, ignore_errors=True)
    for rel, text in files.items():
        path = folder / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text)


def _door(name: str, folder, version: str):
    door = ROOT / name
    door.write_bytes(b"MZ stand-in for the door's own executable" * 1000)
    said = binpack.pack(door, folder, version)
    return door, said


@pytest.fixture
def place():
    shutil.rmtree(ROOT, ignore_errors=True)
    ROOT.mkdir(parents=True)
    yield ROOT
    shutil.rmtree(ROOT, ignore_errors=True)


def test_the_door_carries_the_program_and_lays_it_out_once(place):
    folder = place / "built"
    _program(folder, {"MatreshkaViewer.exe": b"program one",
                      "_internal/python311.dll": b"x" * 5000,
                      "_internal/baked/scene_mesh.npz": b"scene"})
    door, said = _door("door1.exe", folder, "0.5")
    assert said["id"].startswith("0.5-") and len(said["files"]) == 3
    archive = zipfile.ZipFile(door)
    assert json.loads(archive.read(launcher.MANIFEST))["id"] == said["id"]
    root = place / "bin" / said["id"]
    linked, unpacked = launcher.lay_out(archive, said, root)
    assert (linked, unpacked) == (0, 3)
    assert (root / "MatreshkaViewer.exe").read_bytes() == b"program one"
    assert launcher._manifest_of(root)["id"] == said["id"]
    assert not root.with_name(root.name + ".part").exists()


def test_an_update_writes_only_what_changed_and_clears_the_old(place):
    folder = place / "built"
    _program(folder, {"MatreshkaViewer.exe": b"program one",
                      "_internal/python311.dll": b"x" * 5000,
                      "_internal/gone.txt": b"dropped in the next build"})
    door, first = _door("door1.exe", folder, "0.5")
    old = place / "bin" / first["id"]
    launcher.lay_out(zipfile.ZipFile(door), first, old)

    _program(folder, {"MatreshkaViewer.exe": b"program two",
                      "_internal/python311.dll": b"x" * 5000,
                      "_internal/new.txt": b"new in this build"})
    door2, second = _door("door2.exe", folder, "0.5")
    assert second["id"] != first["id"]
    new = place / "bin" / second["id"]
    linked, unpacked = launcher.lay_out(zipfile.ZipFile(door2), second, new)
    assert (linked, unpacked) == (1, 2), "only the changed and the new file are written"
    same = new / "_internal" / "python311.dll"
    assert os.stat(same).st_nlink >= 2 or same.read_bytes() == b"x" * 5000
    assert (new / "MatreshkaViewer.exe").read_bytes() == b"program two"
    assert not (new / "_internal" / "gone.txt").exists()
    # The old build is left exactly as it was until it is cleared.
    assert (old / "MatreshkaViewer.exe").read_bytes() == b"program one"
    launcher.clear_old(place / "bin", new.name)
    assert not old.exists()
    assert new.exists() and same.read_bytes() == b"x" * 5000


def test_a_build_still_running_is_not_cleared(place):
    folder = place / "built"
    _program(folder, {"MatreshkaViewer.exe": b"one"})
    door, first = _door("door1.exe", folder, "0.5")
    old = place / "bin" / first["id"]
    launcher.lay_out(zipfile.ZipFile(door), first, old)
    # Held open without sharing delete, as Windows holds a running program.
    import msvcrt  # noqa: F401 -- Windows only, as the door is
    import ctypes
    from ctypes import wintypes
    create = ctypes.windll.kernel32.CreateFileW
    create.restype = wintypes.HANDLE
    handle = create(str(old / "MatreshkaViewer.exe"), 0x80000000, 0x1, None, 3, 0, None)
    try:
        launcher.clear_old(place / "bin", "some-newer-build")
        assert (old / "MatreshkaViewer.exe").exists(), "a running build was taken away"
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)
    launcher.clear_old(place / "bin", "some-newer-build")
    assert not old.exists()


def test_the_program_keeps_its_things_beside_the_door(monkeypatch, tmp_path):
    """Settings, logs and OUT go beside MatreshkaViewer.exe, not into bin."""
    import importlib
    import sys
    import logfile as patched
    here = patched.app_dir
    real = importlib.util.spec_from_file_location("logfile_real", patched.__file__)
    module = importlib.util.module_from_spec(real)
    real.loader.exec_module(module)
    inner = tmp_path / "bin" / "0.5-abc" / "MatreshkaViewer.exe"
    inner.parent.mkdir(parents=True)
    (inner.parent / ".complete").write_text("0.5-abc")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(inner))
    monkeypatch.delenv("MATRESHKA_HOME", raising=False)
    assert module.app_dir() == tmp_path
    monkeypatch.setenv("MATRESHKA_HOME", str(tmp_path))
    assert module.app_dir() == tmp_path
    assert patched.app_dir is here


def test_the_native_door_carries_its_installer_and_says_where(place):
    """door.c reads one line at the very end of the file -- the zip's
    comment -- to find the build and the installer; the installer then reads
    the program out of the same file, past the door and itself."""
    folder = place / "built"
    _program(folder, {"MatreshkaViewer.exe": b"program", "_internal/a.dll": b"a" * 3000})
    door = place / "door_native.exe"
    door.write_bytes(b"MZ native door" * 500)
    installer = place / "installer.exe"
    installer.write_bytes(b"MZ the installer" * 700)
    out = place / "MatreshkaViewer.exe"
    said = binpack.pack_native(door, installer, folder, "0.5", out)
    whole = out.read_bytes()
    tail = whole[-8192:]
    line = tail[tail.rindex(b"MTRBIN1;"):].decode("ascii")
    fields = dict(part.split("=", 1) for part in line.split(";") if "=" in part)
    assert fields["id"] == said["id"]
    offset, length = (int(x) for x in fields["installer"].split(","))
    assert whole[offset:offset + length] == installer.read_bytes()
    assert whole[:len(door.read_bytes())] == door.read_bytes()
    archive = zipfile.ZipFile(out)
    assert json.loads(archive.read(launcher.MANIFEST))["id"] == said["id"]
    root = place / "bin" / said["id"]
    launcher.lay_out(archive, said, root)
    assert (root / "_internal" / "a.dll").read_bytes() == b"a" * 3000


def test_the_doors_compile_where_there_is_a_compiler(tmp_path):
    from pathlib import Path
    source = Path(binpack.__file__).with_name("door.c")
    if not binpack.compile_door(source, tmp_path / "door.exe"):
        pytest.skip("no Microsoft C compiler on this machine")
    assert binpack.compile_door(source, tmp_path / "kinetic.exe", kinetic=True)
    for name in ("door.exe", "kinetic.exe"):
        assert (tmp_path / name).read_bytes()[:2] == b"MZ"
        assert (tmp_path / name).stat().st_size < 400_000
