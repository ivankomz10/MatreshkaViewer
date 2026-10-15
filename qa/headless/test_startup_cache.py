"""What the program prepares ahead so that it starts fast: wgpu's C
interface (wgpu_fast.py), the screens' measured cover (cache/cover.json),
and a loading window that does not wait to be seen."""
from __future__ import annotations

import json

from conftest import HOME


def test_wgpu_reads_the_prepared_interface_not_its_header(window):
    import main
    import wgpu_fast
    from wgpu.backends.wgpu_native import _ffi
    assert main.WGPU_INTERFACE in ("prepared", "made"), main.WGPU_INTERFACE
    assert type(_ffi.ffi).__name__ == "_Prepared"
    built = __import__(wgpu_fast.NAME)
    assert built.STAMP == wgpu_fast._stamp(wgpu_fast._header())


def test_the_cover_is_measured_once_and_kept(window):
    kept = HOME / "cache" / window.COVER_CACHE
    said = json.loads(kept.read_text("utf-8"))
    assert said["cover"] == {name: float(value) for name, value in window.cover.items()}
    assert set(window.cover) >= {"Screen_Bottom", "Screen_Top"}
    # Read back as it would be on the next start, without measuring.
    assert window._cover_remembered() == said["cover"]


def test_the_loading_window_does_not_wait_to_be_seen(window, tick):
    import time
    from PySide6.QtWidgets import QApplication
    import logfile
    started = time.perf_counter()
    logfile.raise_splash(QApplication.instance())
    took = time.perf_counter() - started
    logfile.say_while_loading("checking the loading window")
    logfile.loading_done()
    tick(0.1)
    assert took < 0.5, f"the loading window took {took:.2f} s to come up"
