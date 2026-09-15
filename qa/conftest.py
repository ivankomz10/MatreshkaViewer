"""What every test needs: a built viewer, three small clips, and no strays.

Most tests share one running viewer for the file they are in. Starting it
costs about seven seconds, and a test that needed a clean one -- the ones
about starting up, about settings surviving a close, about a machine with no
ffmpeg on it -- asks for `fresh` instead and gets a launch of its own.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import media                            # noqa: E402
import viewer                           # noqa: E402

# The mode the building is framed in, named once here. It was called Geometry
# and the application still opens a settings file that says so.
PREVIEW = "Превью"


def pytest_addoption(parser) -> None:
    parser.addoption("--keep-open", action="store_true",
                     help="leave the viewer up after the tests, to look at it")


@pytest.fixture(scope="session", autouse=True)
def ready():
    """One built executable, three clips, and nothing left over from before."""
    viewer.keep_exe_fresh()
    clips = media.build()
    left = viewer.kill_strays()
    if left:
        print(f"\n{left} viewer(s) left from a previous run were closed")
    yield clips
    viewer.kill_strays()


def settings(clips: dict, **changed) -> dict:
    """The settings file a test starts from: the three clips, and defaults.

    Written before the launch rather than loaded through the window, because
    that is what the application does with a folder somebody has worked in --
    and it means a test about the timeline does not first have to be a test
    about the file dialog.
    """
    rows = {
        "Top": {"file": str(clips["top"]), "gain": 100},
        "Bottom": {"file": str(clips["bottom"]), "gain": 100},
        "Lamels": {"file": str(clips["lamels"]), "gain": 100},
        "Frame": {"file": "", "gain": 100, "how": "Fit"},
        "Sound": {"file": "", "gain": 10},
        "Kinetic": {"file": ""},
    }
    settled = {
        "checked_machine": True,        # no dependency window in the way
        "rows": rows,
        "match": True,
        "solid_top": True,
        "linked": False,
        "alpha": "Premultiplied",
        "behind": "Calibration",
        "sync": "60 fps",
        "mode": PREVIEW,
        "out_dir": str(viewer.SANDBOX / "OUT"),
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


@pytest.fixture(scope="module")
def app(ready, request):
    """A viewer with the three clips loaded, shared by one file's tests."""
    running = viewer.Viewer(settings=settings(ready),
                            name=request.module.__name__)
    try:
        running.start()
        running.log_has("log:", within=30)
    except Exception:                   # noqa: BLE001 -- and then say why
        # A failure here happens before the yield, so pytest runs no teardown
        # and the process would be left running for the next file to inherit.
        running.stop()
        raise
    yield running
    if not request.config.getoption("--keep-open"):
        running.stop()


@pytest.fixture
def fresh(ready, request):
    """A launch of this test's own, with whatever settings it asks for."""
    running: list = []

    def launch(**changed) -> viewer.Viewer:
        env = changed.pop("env", None)
        one = viewer.Viewer(settings=settings(ready, **changed), env=env,
                            name=request.node.name.replace("/", "_"))
        # On the list before it is started, so that a launch which fails half
        # way is still something the teardown knows to close.
        running.append(one)
        one.start()
        return one

    yield launch
    for one in running:
        one.stop()


@pytest.fixture(autouse=True)
def no_crash(request):
    """After any test that used a viewer, the log must hold no wreckage."""
    yield
    running = request.node.funcargs.get("app")
    if running is None:
        return
    bad = running.complaints()
    assert not bad, "the log complains:\n  " + "\n  ".join(bad)
