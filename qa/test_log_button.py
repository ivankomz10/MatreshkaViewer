"""The Log button, which once stopped the window and Explorer with it.

It opened the folder through the shell, on this thread, and the shell answers
that by talking to every top-level window on the machine -- including the
half-dozen the graphics driver leaves lying about in this process on threads
that run no message loop. Everything waited on everything. The window froze,
Explorer froze with it, and only killing the process let go.

So this test does not ask whether a folder opened. It asks whether both are
still answering afterwards.
"""
from __future__ import annotations

import time

import winput
from conftest import PREVIEW


def explorer_windows() -> set:
    return {hwnd for hwnd, _, klass, _, showing in winput.top_windows()
            if showing and klass in ("CabinetWClass", "ExploreWClass")}


def test_the_log_button_freezes_nothing(app):
    before = explorer_windows()
    app.click("qa_log", settle=0.2)

    # Watched for several seconds, because the freeze was not instant: the
    # call went out and the answer never came back.
    began = time.time()
    while time.time() - began < 8:
        assert app.answering(1.5), (
            f"the window stopped answering {time.time() - began:.1f}s after "
            "the Log button was pressed")
        assert winput.shell_answers(1.5), (
            f"Explorer stopped answering {time.time() - began:.1f}s after "
            "the Log button was pressed")
        time.sleep(0.5)
    assert app.alive(), "the viewer died on the Log button"

    # Whatever it opened, this test opened, so this test closes it.
    for hwnd in explorer_windows() - before:
        winput.close_window(hwnd)
    time.sleep(0.5)


def test_the_window_still_works_afterwards(app):
    """Answering is not the same as working: it must still do as it is told."""
    app.choose("qa_mode", "Flat")
    assert app.at("qa_mode").value == "Flat"
    app.choose("qa_mode", PREVIEW)
    assert app.at("qa_mode").value == PREVIEW
    assert not app.complaints(), app.complaints()
