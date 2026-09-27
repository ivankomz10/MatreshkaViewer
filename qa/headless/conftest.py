"""The same window, driven from inside the process instead of by hand.

Two suites, on purpose. The one upstairs drives the built executable with the
real mouse and the real keyboard: it is the only way to find out who gets a
key press, what a click lands on and whether a window has stopped answering,
and the price is that it owns the machine while it runs. This one asks
everything that does not need a hand -- what the lists hold, what gets
written, how large, under what name, what the labels say afterwards -- by
calling the window's own methods in this process. Nothing is taken from
whoever is using the computer.

What it costs: it runs the source in `tool`, not the built file, so it cannot
notice anything the build does to it (a missing icon, a file left out of the
spec, the loading window). Keep both.

The application keeps its settings and its log beside itself, which from
source means inside `tool`. `logfile.app_dir` is pointed at a sandbox before
the window is built, so a test run leaves nothing in the working folder.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
QA = HERE.parent
TOOL = QA.parent / "tool"
HOME = HERE / "sandbox"
sys.path.insert(0, str(TOOL))
sys.path.insert(0, str(QA))

import logfile                          # noqa: E402

# Before anything of the application's is built: everything it keeps beside
# itself -- settings, logs, the folder it writes into -- goes here instead.
#
# What it *reads* still comes from `tool`: the baked scene and the icons are
# found through `bundled`, which normally looks inside the built file and
# beside it, so that one keeps pointing where those things actually are.
HOME.mkdir(parents=True, exist_ok=True)
BESIDE = logfile.app_dir()


def _bundled(name: str):
    where = BESIDE / name
    return where if where.exists() else None


logfile.app_dir = lambda: HOME          # noqa: E731 -- the point is the patch
logfile.bundled = _bundled

import media                            # noqa: E402

PREVIEW = "Превью"


def write_settings(values: dict) -> None:
    (HOME / "settings.json").write_text(json.dumps(values, indent=2),
                                        encoding="utf-8")


def settings(clips: dict, **changed) -> dict:
    """The same starting point the driven suite uses, kept in step by hand."""
    settled = {
        "checked_machine": True,
        "rows": {
            "Top": {"file": str(clips["top"]), "gain": 100},
            "Bottom": {"file": str(clips["bottom"]), "gain": 100},
            "Lamels": {"file": str(clips["lamels"]), "gain": 100},
            "Frame": {"file": "", "gain": 100, "how": "Fit"},
            "Sound": {"file": "", "gain": 10},
            "Kinetic": {"file": ""},
        },
        "match": True,
        "solid_top": True,
        "linked": False,
        "alpha": "Premultiplied",
        "behind": "Calibration",
        "sync": "60 fps",
        "mode": PREVIEW,
        "out_dir": str(HOME / "OUT"),
        "out_name": "qa_render.mp4",
        "rebake": "Clean",
        "rebake_below": 8,
        "rebake_clamp": True,
        "rebake_colour": "Multiply",
        "rebake_left": "Premultiplied",
        "rebake_right": "Premultiplied",
        "rebake_format": "Hap Q Alpha",
        "frame_edge": True,
    }
    settled.update(changed)
    return settled


@pytest.fixture(scope="session")
def clips():
    return media.build()


@pytest.fixture(scope="session")
def window(clips):
    """One window, built once, for every test in this suite.

    Built rather than launched: there is no second process, no waiting for a
    file to unpack itself, and no focus to steal. It is shown because the
    picture goes through a real surface on the graphics card and there has to
    be something for that surface to be in -- but nothing ever clicks it.
    """
    for rubbish in ("Logs", "OUT"):
        shutil.rmtree(HOME / rubbish, ignore_errors=True)
    (HOME / "OUT").mkdir(parents=True, exist_ok=True)
    write_settings(settings(clips))

    from PySide6.QtWidgets import QApplication
    import main as viewer

    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(viewer.STYLESHEET)
    logfile.start(viewer.APP_NAME, viewer.APP_VERSION)
    one = viewer.Viewer()
    # Shown, because the picture needs a real surface on the graphics card to
    # be drawn into -- but not activated: whoever is typing somewhere else
    # keeps the keyboard.
    from PySide6.QtCore import Qt
    one.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
    one.show()
    settle(app, 2.0)
    yield one
    one.close()


def settle(app, seconds: float = 0.3) -> None:
    """Let the window get on with whatever it was told to do."""
    import time
    ends = time.perf_counter() + seconds
    while time.perf_counter() < ends:
        app.processEvents()
        time.sleep(0.01)


@pytest.fixture
def tick():
    """A way to let Qt breathe without a test knowing about QApplication."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    return lambda seconds=0.3: settle(app, seconds)


def wait_for(tick, what, why: str, within: float = 180.0):
    """Spin the window's own event loop until something becomes true."""
    import time
    ends = time.perf_counter() + within
    while time.perf_counter() < ends:
        tick(0.05)
        got = what()
        if got:
            return got
    raise AssertionError(f"{why} -- not in {within:.0f}s")


def render_and_wait(window, tick, within: float = 180.0) -> str:
    """Press RENDER the way the button does, and wait for the verdict."""
    was = window.eta.text()
    window.job = None
    window._start_export()
    if window.job is None:              # refused before it started
        tick(0.2)
        return window.eta.text()
    endings = ("frames in", "exists", "failed", "missing", "nothing")
    return wait_for(
        tick,
        lambda: (window.eta.text()
                 if window.eta.text() != was
                 and any(word in window.eta.text() for word in endings)
                 else ""),
        "the render never finished", within)
