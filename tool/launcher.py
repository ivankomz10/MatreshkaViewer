"""The installer behind MatreshkaViewer.exe on Windows: the program laid out
once, beside the door.

The door itself is door.c, which starts in milliseconds and runs this only
when bin\<build> is not laid out yet (as bin\install-<build>.exe --from
<the door>). Built without a C compiler, this is the door.

A one-file build unpacks its whole archive into a temporary folder on every
start -- two seconds before Python is even running, every time. This is that
file's place instead: a small door with the program packed on its end (a zip
after the executable, see binpack.py). The first start lays the program out
in bin/<build> beside this file and runs it from there; every start after
finds it laid out and runs it straight away.

A new build is a new folder. Files it shares with the build already there
are hard links to that build's (a copy where a link cannot be made), so an
update writes only what changed, and a copy of the old build that is still
running is never written under. Old builds are cleared away once nothing
runs from them.

Everything the program keeps beside itself -- settings, logs, OUT, drafts --
stays beside this file: it is told so in MATRESHKA_HOME.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

MANIFEST = "bin-manifest.json"
COMPLETE = ".complete"
TARGET = "MatreshkaViewer.exe"
TITLE = "Matreshka Viewer"


def _say(text: str) -> None:
    try:
        import pyi_splash
        pyi_splash.update_text(text)
    except Exception:  # noqa: BLE001 -- no splash, nothing to say it on
        pass


def _close_splash() -> None:
    try:
        import pyi_splash
        pyi_splash.close()
    except Exception:  # noqa: BLE001
        pass


def _fail(text: str) -> int:
    _close_splash()
    import ctypes
    ctypes.windll.user32.MessageBoxW(None, text, TITLE, 0x10)
    return 1


def _manifest_of(folder: Path) -> dict | None:
    try:
        if (folder / COMPLETE).is_file():
            return json.loads((folder / MANIFEST).read_text("utf-8"))
    except (OSError, ValueError):
        pass
    return None


def _base(bins: Path, wanted: str) -> tuple[Path | None, dict]:
    """The newest build laid out already, to take unchanged files from."""
    best, best_time, best_files = None, -1.0, {}
    if bins.is_dir():
        for folder in bins.iterdir():
            if not folder.is_dir() or folder.name == wanted:
                continue
            said = _manifest_of(folder)
            if said is None:
                continue
            when = (folder / COMPLETE).stat().st_mtime
            if when > best_time:
                best, best_time, best_files = folder, when, said.get("files", {})
    return best, best_files


def lay_out(archive: zipfile.ZipFile, said: dict, root: Path) -> tuple[int, int]:
    """The build in `root`, its files linked from the last build where they
    are the same and unpacked where not. (linked, unpacked)."""
    bins = root.parent
    bins.mkdir(parents=True, exist_ok=True)
    staging = root.with_name(root.name + ".part")
    shutil.rmtree(staging, ignore_errors=True)
    base, base_files = _base(bins, root.name)
    files = said["files"]
    linked = unpacked = 0
    total = max(1, sum(size for size, _ in files.values()))
    done = 0
    shown = -1
    for rel, (size, digest) in files.items():
        target = staging / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        old = base_files.get(rel)
        if base is not None and old is not None and old[1] == digest:
            try:
                os.link(base / rel, target)
            except OSError:
                shutil.copy2(base / rel, target)
            linked += 1
        else:
            with archive.open("app/" + rel) as source, open(target, "wb") as out:
                shutil.copyfileobj(source, out, 1 << 20)
            unpacked += 1
        done += size
        percent = int(100 * done / total)
        if percent != shown:
            shown = percent
            _say(f"Matreshka Viewer {said.get('version', '')}: "
                 f"{'обновление' if base is not None else 'установка'} {percent} %")
    (staging / MANIFEST).write_text(json.dumps(said), "utf-8")
    try:
        staging.rename(root)
    except OSError:
        # Another start of the same build got there first.
        if _manifest_of(root) is None:
            raise
        shutil.rmtree(staging, ignore_errors=True)
        return linked, unpacked
    (root / COMPLETE).write_text(said["id"], "utf-8")
    return linked, unpacked


def clear_old(bins: Path, keep: str) -> None:
    """Builds other than this one, unless something still runs from them --
    a running program cannot be removed, and that is the test."""
    if not bins.is_dir():
        return
    for folder in bins.iterdir():
        if folder.is_file() and folder.name.startswith("install-")                 and folder.name != f"install-{keep}.exe":
            try:
                folder.unlink()             # an older build's installer
            except OSError:
                pass
            continue
        if not folder.is_dir() or folder.name == keep:
            continue
        program = folder / TARGET
        try:
            if program.exists():
                program.unlink()
        except OSError:
            continue                      # running: leave it for next time
        shutil.rmtree(folder, ignore_errors=True)


def main() -> int:
    # Started by the C door (door.c) as bin\install-<build>.exe --from <door>:
    # the program is packed on the door, not on this file. Started on its
    # own -- the door when no compiler was there for the C one -- it is.
    arguments = sys.argv[1:]
    here = Path(sys.executable).resolve()
    if arguments[:1] == ["--from"] and len(arguments) >= 2:
        here = Path(arguments[1]).resolve()
        arguments = arguments[2:]
    home = here.parent
    try:
        archive = zipfile.ZipFile(here)
        said = json.loads(archive.read(MANIFEST))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as error:
        return _fail(f"The program inside {here.name} cannot be read: {error}\n"
                     f"Программу внутри {here.name} не прочитать: {error}")
    bins = home / "bin"
    root = bins / said["id"]
    if _manifest_of(root) is None:
        try:
            lay_out(archive, said, root)
        except OSError as error:
            return _fail(f"Could not lay the program out in {bins}: {error}\n"
                         f"Не получилось разложить программу в {bins}: {error}")
    program = root / TARGET
    environment = dict(os.environ, MATRESHKA_HOME=str(home))
    _close_splash()
    subprocess.Popen([str(program), *arguments], cwd=str(home), env=environment,
                     close_fds=True)
    clear_old(bins, root.name)
    return 0


def digest(path: Path) -> str:
    hashed = hashlib.sha256()
    with open(path, "rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            hashed.update(block)
    return hashed.hexdigest()


if __name__ == "__main__":
    sys.exit(main())
