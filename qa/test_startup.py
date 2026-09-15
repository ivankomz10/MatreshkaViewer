"""Starting up: the window arrives, says what machine it is on, and loads.

One launch answers most of this, so these all share the file's viewer rather
than starting six of their own -- starting one is the slowest thing in the
suite. Only the last test, which closes the window, needs its own.
"""
from __future__ import annotations

import viewer


def test_window_arrives(app):
    assert app.started_in < 90, f"took {app.started_in:.1f}s to put a window up"
    print(f"\nwindow up in {app.started_in:.1f}s")
    assert app.answering(), "the window is up but not answering"


def test_loading_window_comes_first(app):
    """The one-file build unpacks itself for seconds before it can draw."""
    assert app.splash_seen, ("no loading window while it started -- "
                             f"it was up in {app.started_in:.1f}s")


def test_says_what_it_found(app):
    line = app.log_has("GPU:", within=40)
    assert "GPU: ok" in line, line
    assert "ffmpeg" in line, line
    shown = app.says("qa_stats")
    assert "GPU" in shown or "ok" in shown, f"the footer says {shown!r}"


def test_carries_the_last_session_over(app):
    """Three clips named in the settings file are three clips loaded."""
    for row in ("top", "bottom", "lamels"):
        path = app.at(f"qa_path_{row}").value
        assert path.endswith(f"qa_{row}.mov"), f"{row} holds {path!r}"
        note = app.says(f"qa_note_{row}")
        assert "x" in note, f"{row} says nothing about its file: {note!r}"
    assert "frame" in app.says("qa_frame_label").lower()


def test_the_whole_window_is_there(app):
    """Every control a test will reach for, on the screen and reachable."""
    for qa in ("qa_mode", "qa_timeline", "qa_play", "qa_render", "qa_snapshot",
               "qa_log", "qa_size", "qa_format", "qa_out_name", "qa_full",
               "qa_frame_edge_button", "qa_link", "qa_stats"):
        found = app.at(qa)
        assert found.showing, f"{qa} is not showing"
        assert found.wide > 0 and found.tall > 0, f"{qa} has no size"


def test_nothing_went_wrong(app):
    app.log_has("GPU:", within=40)
    assert not app.complaints(), app.complaints()


def test_closing_leaves_nothing_running(fresh):
    """A closed viewer leaves no process behind, or the next test inherits it."""
    one = fresh()
    assert one.quit(), "the window did not close on Alt+F4"
    assert not viewer.stray_viewers(), "a sandbox viewer is still running"
    assert (viewer.SANDBOX / "settings.json").exists(), "it saved no settings"
