"""What sits on the picture: full screen, the framing line, and the link.

All three were reported by eye -- an icon that did not say whether it was on,
a button that covered its neighbours, a line that stayed up while the picture
was zoomed past it -- so all three are checked by where things actually are
on the screen rather than by what the code believes.
"""
from __future__ import annotations

import time

import look
from conftest import PREVIEW
import winput


def monitor_of(hwnd) -> tuple[int, int]:
    """The size of the screen this window is on."""
    import ctypes
    import ctypes.wintypes as wt

    class INFO(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("monitor", wt.RECT),
                    ("work", wt.RECT), ("flags", wt.DWORD)]

    user32 = ctypes.WinDLL("user32")
    handle = user32.MonitorFromWindow(wt.HWND(hwnd), 2)   # nearest
    info = INFO()
    info.cbSize = ctypes.sizeof(INFO)
    user32.GetMonitorInfoW(handle, ctypes.byref(info))
    box = info.monitor
    return box.right - box.left, box.bottom - box.top


# -- the whole monitor -------------------------------------------------------

def test_full_screen_takes_the_monitor_and_gives_it_back(app):
    app.choose("qa_mode", PREVIEW)
    was = winput.rect_of(app.hwnd)
    wide, tall = monitor_of(app.hwnd)

    app.click("qa_full")
    time.sleep(0.8)
    left, top, right, bottom = winput.rect_of(app.hwnd)
    assert (right - left, bottom - top) == (wide, tall), (
        f"full screen is {right - left}x{bottom - top}, the monitor is "
        f"{wide}x{tall}")
    # Everything the window laid out goes away; the picture keeps its own bar.
    assert app.maybe("qa_mode") is None, "the mode box is still up"
    assert app.maybe("qa_timeline") is None, "the window's timeline is still up"
    assert app.at("qa_full_bar").showing, "no timeline on the picture"
    for qa in ("qa_full_play", "qa_full_slider", "qa_full_time"):
        assert app.at(qa).showing, f"{qa} is missing from the full screen bar"
    # The link ties two sliders, and neither of them is on the screen here.
    assert app.maybe("qa_link") is None, "the link is still on the picture"

    app.key("escape")
    time.sleep(0.8)
    assert winput.rect_of(app.hwnd) == was, "it came back to a different place"
    assert app.at("qa_mode").showing, "the bars did not come back"
    assert app.at("qa_link").showing, "the link did not come back"
    assert app.maybe("qa_full_bar") is None, "the picture's bar stayed up"


def test_the_keys_still_work_in_full_screen(app):
    app.click("qa_full")
    time.sleep(0.8)
    try:
        said = app.says("qa_full_time")
        app.key("right")
        time.sleep(0.3)
        assert app.says("qa_full_time") != said, (
            f"the arrow did nothing; the label still says {said!r}")
    finally:
        app.key("escape")
        time.sleep(0.6)


# -- the line that says what will be written ---------------------------------

def test_the_framing_line_is_the_shape_of_the_render(app):
    app.choose("qa_mode", PREVIEW)
    app.choose("qa_size", "1080x1920")
    time.sleep(0.5)
    line = app.at("qa_frame_edge")
    shape = line.wide / line.tall
    assert abs(shape - 1080 / 1920) < 0.02, (
        f"the line is {line.wide}x{line.tall}, which is not 9:16")
    picture = app.at("qa_canvas")
    assert line.tall <= picture.tall + 2, "the line is taller than the picture"


def test_the_framing_line_can_be_switched_off(app):
    assert app.at("qa_frame_edge").showing
    app.click("qa_frame_edge_button")
    app.wait_gone("qa_frame_edge", within=5)
    app.click("qa_frame_edge_button")
    assert app.wait_for("qa_frame_edge", within=5).showing


def test_the_framing_line_goes_away_while_zoomed_in(app):
    """Zoomed in, the line would be marking a frame that is not on the screen."""
    app.choose("qa_mode", PREVIEW)
    app.click("qa_reset_view")
    assert app.wait_for("qa_frame_edge", within=5).showing
    picture = app.at("qa_canvas")
    app.front()
    winput.wheel(*picture.middle, 3)        # in
    time.sleep(0.5)
    assert app.maybe("qa_frame_edge") is None, "the line stayed while zoomed in"
    app.click("qa_reset_view")
    time.sleep(0.5)
    assert app.wait_for("qa_frame_edge", within=5).showing, (
        "the line did not come back when the view was reset")


def test_only_geometry_has_a_framing_line(app):
    app.choose("qa_mode", "Flat")
    assert app.maybe("qa_frame_edge") is None, "Flat has nothing to frame"
    app.choose("qa_mode", PREVIEW)
    assert app.wait_for("qa_frame_edge", within=5).showing


# -- the link between the two sliders ----------------------------------------

def test_the_link_says_whether_it_is_on(app):
    link = app.at("qa_link")
    was = link.checked
    before = app.picture_of("qa_link")
    app.click("qa_link")
    time.sleep(0.3)
    now = app.at("qa_link")
    assert now.checked is not was, f"the link did not change: {was} -> {now.checked}"
    after = app.picture_of("qa_link")
    assert look.difference(before, after) > 4, (
        "the button looks the same on as off")
    app.click("qa_link")


def test_the_link_covers_nothing_and_nothing_covers_it(app):
    """It is placed by hand between two rows, which is how it once overlapped."""
    link = app.at("qa_link")
    landed = app.desk.under(*link.middle)
    assert landed is not None and landed.qa == "qa_link", (
        f"a click on the link would land on {landed}")
    for qa in ("qa_clear_top", "qa_gain_top", "qa_clear_bottom", "qa_gain_bottom",
               "qa_path_top", "qa_path_bottom"):
        assert not link.overlaps(app.at(qa)), f"the link covers {qa}"
    # It sits in the gap every row leaves for it, not over a row's own widgets.
    gap = app.at("qa_linkgap_top")
    assert gap.left - 2 <= link.left and link.left + link.wide <= gap.left + gap.wide + 2, (
        f"the link at {link.rect} is outside its column at {gap.rect}")


def test_the_link_moves_with_the_window(app):
    """It is not in any layout, so it has to be put in its place by hand."""
    gap = app.at("qa_linkgap_top")
    app.front()
    left, top, right, _ = winput.rect_of(app.hwnd)
    winput.click(min(left + 200, right - 20), top + 8, count=2)   # maximise
    time.sleep(1.0)
    moved_gap = app.at("qa_linkgap_top")
    assert moved_gap.left != gap.left, "the window did not change shape"
    link = app.at("qa_link")
    assert (moved_gap.left - 2 <= link.left
            and link.left + link.wide <= moved_gap.left + moved_gap.wide + 2), (
        f"after the resize the link is at {link.rect}, its column at "
        f"{moved_gap.rect}")
    left, top, right, _ = winput.rect_of(app.hwnd)
    winput.click(min(left + 200, right - 20), top + 8, count=2)   # and back
    time.sleep(1.0)
