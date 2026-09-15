"""A log on disk, because a windowed application has nowhere else to speak.

Carried over deliberately from the renderer next door rather than rediscovered.
A frozen windowed build has no console: every print goes into a void, and an
unhandled exception takes the window with it and leaves nothing behind. That is
fine until something only happens on someone else's machine, and then it is the
whole problem.
"""
from __future__ import annotations

import datetime
import platform
import sys
import threading
import traceback
from pathlib import Path

DIR_NAME = "Logs"
KEEP = 10

# The splash the one-file build puts up while it unpacks itself. It exists
# only there: run from source, or as the folder build on a mac, there is
# nothing to import and nothing to say anything on.
try:
    import pyi_splash                     # noqa: F401 -- only when frozen
except Exception:                         # noqa: BLE001 -- absence is normal
    pyi_splash = None

# The splash line is one line wide. The log's are not.
SPLASH_WIDTH = 62

# Where the line goes on the picture, the same point the bootloader's splash
# is told to use in build.spec.
SPLASH_TEXT_AT = (30, 160)

# Our own loading window, for where the loader has none of its own, and the
# last thing said -- so that a window raised between two log lines does not
# stand there blank until the next one arrives.
_own = None
_own_app = None
_last_said = ""

_handle = None
_path: Path | None = None
_lock = threading.Lock()


def app_dir() -> Path:
    """Where this application lives, whether frozen or run from source."""
    if getattr(sys, "frozen", False):
        here = Path(sys.executable).resolve().parent
        # Out of a macOS bundle, so the folder beside the .app is used.
        for parent in [here] + list(here.parents):
            if parent.suffix == ".app":
                return parent.parent
        return here
    return Path(__file__).resolve().parent


def folder() -> Path:
    return app_dir() / DIR_NAME


SETTINGS = "settings.json"


def load_settings() -> dict:
    """The few things worth remembering between runs, or an empty answer.

    Beside the application, not in the registry or a user profile: the whole
    point of this build is that a folder can be copied to another machine and
    deleting it leaves nothing behind.
    """
    import json
    try:
        return json.loads((app_dir() / SETTINGS).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 -- absent or unreadable is the same answer
        return {}


def save_settings(values: dict) -> None:
    import json
    try:
        (app_dir() / SETTINGS).write_text(
            json.dumps(values, indent=2), encoding="utf-8")
    except Exception as error:  # noqa: BLE001 -- a read-only folder is allowed
        write(f"could not save settings: {error}")


def bundled(name: str) -> Path | None:
    """A file shipped with the application: inside the bundle, else beside it."""
    roots = []
    inside = getattr(sys, "_MEIPASS", None)
    if inside:
        roots.append(Path(inside))
    roots.append(app_dir())
    for root in roots:
        candidate = root / name
        if candidate.exists():
            return candidate
    return None


def path() -> Path | None:
    return _path


class _Tee:
    """A stream that writes to the log as well as wherever it went before."""

    def __init__(self, original, tag: str) -> None:
        self.original = original
        self.tag = tag
        self._partial = ""

    def write(self, text: str) -> int:
        if self.original is not None:
            try:
                self.original.write(text)
            except Exception:  # noqa: BLE001 -- the log still gets it
                pass
        self._partial += text
        while "\n" in self._partial:
            line, self._partial = self._partial.split("\n", 1)
            if line.strip():
                write(line.rstrip(), self.tag)
        return len(text)

    def flush(self) -> None:
        if self.original is not None:
            try:
                self.original.flush()
            except Exception:  # noqa: BLE001
                pass

    def isatty(self) -> bool:
        return False


def write(message: str, tag: str = "") -> None:
    """One timestamped line, on disk before the next one is composed."""
    if _handle is None:
        return
    stamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    prefix = f"{stamp}  {tag + '  ' if tag else ''}"
    with _lock:
        for line in str(message).splitlines() or [""]:
            _handle.write(f"{prefix}{line}\n")
        _handle.flush()
    say_while_loading(str(message).splitlines()[0] if str(message) else "")


def raise_splash(app) -> None:
    """Our own loading window, over whatever the loader put up.

    PyInstaller's splash is drawn by the bootloader, and the bootloader has
    none for macOS -- and the mac build is a folder rather than one file, so
    there was nothing on screen at all for the seconds the graphics device
    takes. This one is Qt's own, so it exists everywhere; on Windows it takes
    over from the loader's the moment Python is running.
    """
    global _own, _own_app
    picture = bundled("splash.png")
    if picture is None:
        return
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor, QPixmap
        from PySide6.QtWidgets import QSplashScreen
    except Exception:  # noqa: BLE001 -- no Qt, no splash, no matter
        return
    class Loading(QSplashScreen):
        """The same picture, with the line in the same place as the loader's.

        QSplashScreen puts its message against an edge of the picture. The
        bootloader's splash draws at a point, just under the rule. On Windows
        one of these replaces the other while the eye is on it, so the line
        had better not jump.
        """

        def drawContents(self, painter) -> None:  # noqa: N802 -- Qt naming
            painter.setPen(QColor("#b0b0b0"))
            font = painter.font()
            font.setPointSize(9)
            painter.setFont(font)
            painter.drawText(SPLASH_TEXT_AT[0], SPLASH_TEXT_AT[1],
                             self.message())

    _own_app = app
    _own = Loading(QPixmap(str(picture)))
    _own.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
    if _last_said:
        _own.showMessage(_last_said[:SPLASH_WIDTH])
    _own.show()
    app.processEvents()


def say_while_loading(line: str) -> None:
    """Put a line on whichever loading window is up."""
    global _last_said
    if not line:
        return
    _last_said = line
    if pyi_splash is not None:
        try:
            if pyi_splash.is_alive():
                pyi_splash.update_text(line[:SPLASH_WIDTH])
        except Exception:  # noqa: BLE001 -- a splash is never worth an exception
            pass
    # Widgets belong to the thread that made them, and this is written to from
    # the reading and writing threads as well.
    if _own is not None and threading.current_thread() is threading.main_thread():
        try:
            _own.showMessage(line[:SPLASH_WIDTH])
            if _own_app is not None:
                _own_app.processEvents()
        except Exception:  # noqa: BLE001 -- as above
            pass


def loading_done() -> None:
    """Take the loading window down; the real one is up."""
    global _own, _own_app
    if pyi_splash is not None:
        try:
            pyi_splash.close()
        except Exception:  # noqa: BLE001 -- as above
            pass
    if _own is not None:
        try:
            _own.close()
        except Exception:  # noqa: BLE001 -- as above
            pass
        _own = None
        _own_app = None


def _trim() -> None:
    try:
        existing = sorted(folder().glob("session_*.log"))
        for stale in existing[:-KEEP]:
            stale.unlink(missing_ok=True)
    except OSError:
        pass


def start(name: str = "Matreshka Viewer", version: str = "0.2") -> Path | None:
    """Open this session's file and start catching everything."""
    global _handle, _path

    if _handle is not None:
        return _path
    try:
        folder().mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        _path = folder() / f"session_{stamp}.log"
        _handle = _path.open("w", encoding="utf-8")
    except OSError:
        _handle, _path = None, None
        return None

    _trim()
    write(f"{name} {version}")
    write(f"{platform.platform()}   python {sys.version.split()[0]}   "
          f"{'frozen' if getattr(sys, 'frozen', False) else 'source'}")
    write(f"application  {app_dir()}")

    sys.stdout = _Tee(sys.stdout, "out")
    sys.stderr = _Tee(sys.stderr, "err")

    previous = sys.excepthook

    def catch(kind, value, tail) -> None:
        write("UNHANDLED\n" + "".join(traceback.format_exception(kind, value, tail)),
              "err")
        previous(kind, value, tail)

    sys.excepthook = catch

    def catch_thread(args) -> None:
        write(f"UNHANDLED in {args.thread.name if args.thread else '?'}\n"
              + "".join(traceback.format_exception(
                  args.exc_type, args.exc_value, args.exc_traceback)), "err")

    threading.excepthook = catch_thread
    return _path
