"""The keyboard: space plays, arrows step -- except where somebody is typing.

This went wrong twice. First the keys were caught by the window and whatever
widget had the focus ate them; then they were caught for good, and the
question became whether a field still gets its own space bar. Both halves are
here, and both are pressed on a real keyboard: a key handed straight to a
widget would prove neither.
"""
from __future__ import annotations

import time

import look
from conftest import PREVIEW


def canvas_click(app) -> None:
    """Put the keyboard somewhere harmless: on the picture itself."""
    picture = app.at("qa_canvas")
    app.click_at(picture.left + picture.wide // 2,
                 picture.top + picture.tall - 40)


def test_space_plays_and_stops(app):
    app.choose("qa_mode", PREVIEW)
    canvas_click(app)
    was, last = look.frame_now(app)
    assert last > 10, f"the clip is too short to play: {last} frames"

    app.key("space")
    time.sleep(1.2)
    playing, _ = look.frame_now(app)
    assert playing > was, f"space did not start it: {was} -> {playing}"

    app.key("space")
    time.sleep(0.4)
    stopped, _ = look.frame_now(app)
    time.sleep(0.8)
    still, _ = look.frame_now(app)
    assert still == stopped, f"space did not stop it: {stopped} -> {still}"


def test_arrows_step_one_frame(app):
    canvas_click(app)
    # From somewhere in the middle: at the end there is nowhere to step to,
    # and a test that happened to start there would pass for the wrong reason.
    app.key("left", "ctrl")
    app.key("right")
    was, _ = look.frame_now(app)
    app.key("right")
    on, _ = look.frame_now(app)
    assert on == was + 1, f"right went {was} -> {on}"
    app.key("left")
    back, _ = look.frame_now(app)
    assert back == was, f"left went {on} -> {back}"


def test_control_and_an_arrow_jump_to_the_ends(app):
    canvas_click(app)
    app.key("right", "ctrl")
    at_end, last = look.frame_now(app)
    assert at_end == last, f"ctrl-right stopped at {at_end} of {last}"
    app.key("left", "ctrl")
    at_start, _ = look.frame_now(app)
    assert at_start == 0, f"ctrl-left stopped at {at_start}"


def test_a_field_being_typed_in_keeps_its_own_space_bar(app):
    """The one exception: while a line is being edited, space is a space."""
    app.choose("qa_mode", PREVIEW)
    canvas_click(app)
    before, _ = look.frame_now(app)

    app.type_into("qa_out_name", "a b c.mp4", enter=False)
    typed = app.at("qa_out_name").value
    assert typed == "a b c.mp4", f"the field holds {typed!r}"
    after, _ = look.frame_now(app)
    assert after == before, f"the space bar played it anyway: {before} -> {after}"

    # And the arrows moved the cursor in the field rather than the timeline.
    app.key("left")
    app.key("left")
    moved, _ = look.frame_now(app)
    assert moved == before, f"an arrow moved the timeline from a field: {moved}"

    app.type_into("qa_out_name", "qa_render.mp4")


def test_the_keys_come_back_when_the_field_is_left(app):
    """Clicking away from a field gives the transport its keys again."""
    app.type_into("qa_out_name", "qa_render.mp4", enter=False)
    canvas_click(app)
    was, _ = look.frame_now(app)
    app.key("right")
    on, _ = look.frame_now(app)
    assert on == was + 1, f"the arrow did not come back: {was} -> {on}"


def test_a_transport_button_does_not_take_the_keyboard(app):
    """Clicking Step and then pressing space must still play, not re-step."""
    canvas_click(app)
    app.click("qa_on")
    was, _ = look.frame_now(app)
    app.key("space")
    time.sleep(1.0)
    playing, _ = look.frame_now(app)
    app.key("space")
    assert playing > was + 1, (f"space after a button click went {was} -> "
                               f"{playing}; the button kept the keyboard")


def test_dragging_the_timeline_moves_the_clip(app):
    """The slider is a slider: dragging it lands somewhere near the middle."""
    canvas_click(app)
    app.key("left", "ctrl")
    bar = app.at("qa_timeline")
    app.front()
    import winput
    winput.drag(bar.left + 4, bar.top + bar.tall // 2,
                bar.left + bar.wide // 2, bar.top + bar.tall // 2)
    time.sleep(0.4)
    at, last = look.frame_now(app)
    assert 0.25 * last < at < 0.75 * last, (
        f"dragging to the middle of the bar landed on {at} of {last}")
    app.key("left", "ctrl")
