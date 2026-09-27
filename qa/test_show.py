"""The show mode, by hand: the switch, the strips under the mouse, the keys.

The quiet suite asks the window what it did; this asks what a hand does to
it. Which button a press is, what a drag on the ruler moves and what a drag
on the tracks must not, whether the keys arrive -- all of that is only true
of a real mouse and a real keyboard.

The show here is the three test clips as a show, a second long: the rows are
what the show mode shows when no .trix is open.
"""
from __future__ import annotations

import time
from pathlib import Path

import look

RUSDAY = Path(r"D:\Content\_SHOW"
              r"\2026-Daily-RusDay-Matreshka_Day-MuzeyTransporta-v001.trix")


def shown(app, qa: str) -> bool:
    node = app.maybe(qa)
    return node is not None and node.showing and node.wide > 0


def into_show(app) -> None:
    if not shown(app, "qa_show_tracks"):
        app.click("qa_level_show", settle=0.8)
    app.wait_until(lambda: shown(app, "qa_show_tracks"),
                   "the strips never came up", within=15)


def at_start(app) -> None:
    picture = app.at("qa_canvas")
    app.click_at(picture.left + picture.wide // 2,
                 picture.top + picture.tall - 40)
    app.key("left", "ctrl")


def test_the_switch_brings_the_strips_up_and_the_rows_down(app):
    into_show(app)
    assert shown(app, "qa_show_ruler") and shown(app, "qa_show_side")
    assert not shown(app, "qa_sources"), "the rows stayed up over the show"
    assert not shown(app, "qa_timeline"), "two timelines on one screen"
    canvas = app.at("qa_canvas")
    side = app.at("qa_show_side")
    tracks = app.at("qa_show_tracks")
    assert not canvas.overlaps(side), "the column is over the picture"
    assert not canvas.overlaps(tracks), "the strips are over the picture"


def test_the_ruler_is_where_the_playhead_is_dragged(app):
    into_show(app)
    at_start(app)
    ruler = app.at("qa_show_ruler")
    y = ruler.top + ruler.tall // 2
    app.drag(ruler.left + int(ruler.wide * 0.3), y,
             ruler.left + int(ruler.wide * 0.9), y)
    far, last = look.frame_now(app)
    assert far > last * 0.6, f"dragged to nine tenths, it stands at {far}/{last}"
    app.drag(ruler.left + int(ruler.wide * 0.9), y,
             ruler.left + int(ruler.wide * 0.35), y)
    near, _ = look.frame_now(app)
    assert near < far and near < last * 0.5, f"{far} -> {near} of {last}"


def test_the_middle_button_puts_the_playhead_there(app):
    into_show(app)
    at_start(app)
    tracks = app.at("qa_show_tracks")
    app.click_at(tracks.left + int(tracks.wide * 0.6), tracks.top + 60,
                 button="middle")
    time.sleep(0.3)
    here, last = look.frame_now(app)
    assert last * 0.35 < here < last * 0.8, f"middle at 0.6: {here}/{last}"


def test_left_and_right_on_the_tracks_leave_the_playhead_alone(app):
    into_show(app)
    at_start(app)
    tracks = app.at("qa_show_tracks")
    # The cue lane: nothing on it in these rows, so this is empty space.
    app.click_at(tracks.left + int(tracks.wide * 0.7), tracks.top + 8)
    time.sleep(0.2)
    after_left, _ = look.frame_now(app)
    y = tracks.top + 60
    app.drag(tracks.left + int(tracks.wide * 0.7), y,
             tracks.left + int(tracks.wide * 0.3), y, button="right")
    time.sleep(0.2)
    after_right, _ = look.frame_now(app)
    assert after_left == 0, f"a click on empty space moved it to {after_left}"
    assert after_right == 0, f"scrolling moved the playhead to {after_right}"


def test_the_keys_card_comes_and_goes_with_the_question_mark(app):
    into_show(app)
    at_start(app)
    assert not shown(app, "qa_keys")
    app.key("slash", "shift")
    app.wait_until(lambda: shown(app, "qa_keys"), "? raised nothing", 5)
    app.key("slash", "shift")
    app.wait_until(lambda: not shown(app, "qa_keys"), "? did not put it away", 5)


def test_shift_and_an_arrow_go_a_second(app):
    into_show(app)
    at_start(app)
    app.key("right", "shift")
    on, last = look.frame_now(app)
    # A second is sixty frames, and these rows are only a second long.
    assert on == min(60, last), f"shift-right went 0 -> {on} of {last}"
    app.key("left", "shift")
    back, _ = look.frame_now(app)
    assert back == 0, f"shift-left went {on} -> {back}"


def test_full_screen_from_the_show_keeps_the_picture(app):
    into_show(app)
    app.key("f11")
    try:
        app.wait_until(lambda: not shown(app, "qa_show_tracks"),
                       "full screen left the strips up", 10)
        assert shown(app, "qa_canvas"), "full screen hid the picture as well"
    finally:
        app.key("f11")
    app.wait_until(lambda: shown(app, "qa_show_tracks"),
                   "the strips did not come back", 10)


def test_back_to_the_quick_look(app):
    into_show(app)
    app.click("qa_level_view", settle=0.8)
    app.wait_until(lambda: shown(app, "qa_sources"),
                   "the rows did not come back", 10)
    assert not shown(app, "qa_show_tracks")
    assert shown(app, "qa_timeline")


def test_a_session_left_in_the_show_opens_in_it(fresh):
    extra = {"level": "show"}
    if RUSDAY.exists():
        extra["trix"] = str(RUSDAY)
    running = fresh(**extra)
    running.log_has("log:", within=30)
    running.wait_until(lambda: shown(running, "qa_show_tracks"),
                       "it opened in the quick look", 30)
    if RUSDAY.exists():
        said = running.says("qa_project")
        assert "RusDay" in said, said
        running.log_has("motor files placed", within=60)
