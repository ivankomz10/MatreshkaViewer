"""The show mode, in the window: the timeline under the picture, read only.

What has to hold. Going into Шоу and back loses nothing, and the rows shown
as a show are the same picture as the rows themselves. A real show opens with
its loops, its layers are added on each screen, and a render goes through the
gaps between clips instead of stopping at the first one. The motors of a show
arrive off the window's thread. Full screen still leaves the picture.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtWidgets import QWidget

import look
from conftest import HOME, PREVIEW, render_and_wait, wait_for
from test_quiet import put_back

SHOWS = Path(r"D:\Content\_SHOW")
RUSDAY = SHOWS / "2026-Daily-RusDay-Matreshka_Day-MuzeyTransporta-v001.trix"
needs_rusday = pytest.mark.skipif(not RUSDAY.exists(),
                                  reason="the RusDay show is not here")
# One layer composed against one bound directly differs by where the
# filtering happens -- never more than a code of 255 in the compositor's own
# test. Here one more: the test clips are a tenth of the wall's size, and a
# screen is composed at the wall's size, so they are stretched once before the
# scene filters them again. Measured on an RTX 3080: composed at the clip's
# own size the worst is 1, at the wall's 3, mean 0.014, in 20 000 of 518 400
# pixels. Real content is made at the wall's size and has no such stretch.
MOST, MEAN = 3, 0.02


@pytest.fixture
def quick_look(window, clips, tick):
    """In Просмотр with the three test clips, before and after."""
    window.trix_path = ""
    window._set_level("view")
    put_back(window, clips, tick)
    yield window
    if window.player is not None:
        window.player.set_volume(0.0)
    if window.clock.playing:
        window._toggle()
    window.trix_path = ""
    window._set_level("view")
    put_back(window, clips, tick)


def opened(window, tick, path=RUSDAY):
    window.open_show_file(str(path))
    tick(0.5)
    if window.player is not None:
        window.player.set_volume(0.0)       # nobody asked to hear it
    return window.show_open


def settled_at(window, tick, frame: int) -> None:
    """There, with every track that has a clip there holding a frame of it."""
    window._move(frame / 60.0)
    # That frame, not merely a frame: the test clips change by four codes of
    # blue from one frame to the next, and a picture a frame behind is a
    # difference the comparison would blame on the compositing.
    wait_for(tick, lambda: all(
        held is not None and held.index >= frame
        for track, held in zip(window.streams, window.held)
        if track.showing(frame) is not None) or not window.streams,
        "the tracks never gave that frame", 30)
    window.touch()
    tick(0.4)


def framed(window, wide: int = 960, tall: int = 540):
    """The picture as the render and the snapshot take it: through the frame,
    not opened out to whatever shape the canvas is -- which in Шоу is
    narrower, with the column beside it."""
    spilled = window.mesh.spill
    window.solid.show_around(1.0, 1.0)
    try:
        return window.solid.to_array(wide, tall)
    finally:
        window.solid.show_around(*spilled)


def layers_on(window, screen: str, frame: float) -> int:
    composer, members = window.composers[screen]
    count = 0
    for index in members:
        clip = window.streams[index].showing(frame)
        if clip is not None and clip.opacity_at(frame) > 0:
            count += 1
    return count


# -- the rows as a show ------------------------------------------------------

def test_into_the_show_and_back_loses_nothing(quick_look, tick):
    window = quick_look
    rows = [row.field.text() for row in window.rows]
    window._set_level("show")
    tick(0.4)
    assert window.level == "show"
    assert window.show_pane.isVisible() and window.show_side.isVisible()
    assert not window.sources.isVisible(), "the rows stayed up over the show"
    assert not window.slider.isVisible(), "two timelines: the ruler is the one"
    assert sorted(window.composers) == ["Lamel_screen", "Screen_Bottom",
                                        "Screen_Top"]
    names = {clip.name for clip in window.show_open.clips}
    assert names == {"qa_top.mov", "qa_bottom.mov", "qa_lamels.mov"}
    assert all(clip.tx == 0 for clip in window.show_open.clips)
    assert "строки Просмотра" in window.project.text()

    window._set_level("view")
    tick(0.4)
    assert [row.field.text() for row in window.rows] == rows
    assert window.sources.isVisible() and not window.show_pane.isVisible()
    assert not window.composers and len(window.streams) == 3


def test_the_rows_as_a_show_are_the_same_picture(quick_look, tick):
    """The same three clips, each the only layer of its screen: the show's
    composed screens have to come out as the rows' bound directly."""
    window = quick_look
    # At 1.00: the brightness multiplies every difference with the rest, and
    # the tests before may have left the two big screens at 1.29.
    for title in ("Top", "Bottom", "Lamels"):
        window.row_for(title).gain.setValue(100)
    settled_at(window, tick, 30)
    direct = framed(window).astype(np.int32)
    window._set_level("show")
    settled_at(window, tick, 30)
    composed = framed(window).astype(np.int32)
    apart = np.abs(direct[..., :3] - composed[..., :3])
    assert direct[..., :3].max() > 20, "nothing was drawn to compare"
    assert int(apart.max()) <= MOST and float(apart.mean()) <= MEAN, (
        f"worst {int(apart.max())}, mean {float(apart.mean()):.4f}")


def test_rebake_is_not_offered_in_a_show(quick_look, tick):
    """ReBake is about one source file; a show's screen is several added."""
    window = quick_look
    window.mode.setCurrentText("ReBake")
    tick(0.2)
    window._set_level("show")
    tick(0.3)
    assert window.mode.currentText() == PREVIEW
    for index in range(window.mode.count()):
        name = window.mode.itemText(index)
        assert window.mode.is_offered(name) == (name != "ReBake"), name
    window._set_level("view")
    tick(0.3)
    assert all(window.mode.is_offered(window.mode.itemText(index))
               for index in range(window.mode.count()))


def test_flat_in_a_show_is_the_rows_flat(quick_look, tick):
    """Each strip is the show's composed screen, and for the rows as a show
    that is the same strip the rows draw."""
    window = quick_look
    for title in ("Top", "Bottom", "Lamels"):
        window.row_for(title).gain.setValue(100)
    window.mode.setCurrentText("Flat")
    settled_at(window, tick, 30)
    across, down = window._pixels("Screen_Top")
    direct = window._screen_to_array("Screen_Top", across, down).astype(int)
    window._set_level("show")
    tick(0.2)
    assert window.mode.currentText() == "Flat", "Flat was taken away"
    settled_at(window, tick, 30)
    composed = window._screen_to_array("Screen_Top", across, down).astype(int)
    window.mode.setCurrentText(PREVIEW)
    apart = np.abs(direct[..., :3] - composed[..., :3])
    assert direct[..., :3].max() > 20, "nothing was drawn to compare"
    # Pixel for pixel, at the strip's own size, so no filtering differs and
    # the worst is one code: what is left is the composed screen passing
    # through half floats, and that rounds a great many pixels by one --
    # measured 0.021 on average, which is a mean the scene's test would not
    # allow, and a worst it would.
    assert int(apart.max()) <= 1 and float(apart.mean()) <= 0.05, (
        f"worst {int(apart.max())}, mean {float(apart.mean()):.4f}")


def test_a_seek_does_not_put_the_screens_out(quick_look, tick):
    """Scrubbing blinked: a seek hands the held frames back, and a layer was
    only composed while a frame was held. What counts is the card."""
    window = quick_look
    window._set_level("show")
    settled_at(window, tick, 30)
    window._move(45 / 60.0)
    assert all(held is None for held in window.held), "the seek kept frames"
    for _composer, members in window.composers.values():
        assert all(index in window._on_card for index in members), (
            "right after a seek a screen had nothing to show")


def test_what_is_on_the_screens_does_not_widen_the_window(quick_look, tick):
    window = quick_look
    window._set_level("show")
    tick(0.4)
    wide = window.width()
    window.show_pane.state.setText("на экранах: " + "очень_длинное_имя.mov | " * 60)
    window.project.setText("имя проекта " * 60)
    tick(0.4)
    assert window.width() == wide, f"the window went from {wide} to {window.width()}"


def test_the_switch_is_small_and_the_show_line_is_the_show_s(quick_look, tick):
    window = quick_look
    for button in window.level_buttons.values():
        assert button.width() < 160, f"{button.text()} is {button.width()} wide"
    assert not window.show_bar.isVisible(), "the show's line in the quick look"
    window._set_level("show")
    tick(0.3)
    assert window.show_bar.isVisible() and window.open_show_button.isVisible()
    for button in window.level_buttons.values():
        assert button.width() < 160


def test_the_screens_column_moves_the_cards_own_sliders(quick_look, tick):
    """The show's Экраны: sliders that are the cards' own values, with the
    match and the link moved in under them, and moved back on the way out."""
    window = quick_look
    window._set_level("show")
    tick(0.3)
    column = window.findChild(QWidget, "qa_show_screens")
    assert column is not None and column.isVisible()
    assert set(window.levels_sliders) == {"Top", "Bottom", "Lamels", "Sound"}, \
        "a frame's brightness in a show, which has no frame"
    for slider in window.levels_sliders.values():
        assert column.isAncestorOf(slider) and slider.isVisible()
    window.levels_sliders["Top"].setValue(150)
    assert window.row_for("Top").gain.value() == 150
    window.row_for("Bottom").gain.setValue(80)
    assert window.levels_sliders["Bottom"].value() == 80
    for widget in (window.matching, window.linked):
        assert column.isAncestorOf(widget), widget.objectName()
        assert widget.isVisible(), widget.objectName()
    assert window.linked.text() == "Top \u21c4 Bottom"
    # The transport's buttons stand beside the show's time.
    assert window.show_pane.head.isAncestorOf(window.play_button)
    assert window.play_button.isVisible()
    assert not window.transport_bar.isVisible()
    window._set_level("view")
    tick(0.3)
    assert window.look_bar.isAncestorOf(window.matching)
    assert window.link_banner.isAncestorOf(window.linked)
    assert window.transport_bar.isAncestorOf(window.play_button)
    assert window.play_button.isVisible() and window.matching.isVisible()
    assert window.look_bar.width() >= window.look_bar.sizeHint().width()
    for title in ("Top", "Bottom"):
        window.row_for(title).gain.setValue(100)


def test_going_back_to_the_quick_look_does_not_wait_on_the_readers(quick_look,
                                                                   tick):
    """Six readers stopped one after another were a third of a second."""
    import time
    window = quick_look
    window._set_level("show")
    settled_at(window, tick, 30)
    started = time.perf_counter()
    window._set_level("view")
    took = time.perf_counter() - started
    assert took < 0.25, f"back to the quick look took {took:.2f} s"


def test_full_screen_keeps_the_picture(quick_look, tick):
    window = quick_look
    window._set_level("show")
    tick(0.3)
    hidden = window._beside_canvas()
    assert window.split not in hidden and window.canvas not in hidden
    assert window.canvas.parent() not in hidden
    assert window.show_pane in hidden and window.show_side in hidden


def test_the_keys_come_up_over_the_picture(quick_look, tick):
    """In both levels, each with its own keys."""
    window = quick_look
    assert window.keys_button.isVisible(), "no keys in the quick look"
    window._toggle_keys()
    tick(0.1)
    assert window.keys_card.isVisible()
    assert "F11" in window.keys_card.text() and "луп" not in window.keys_card.text()
    window._toggle_keys()
    window._set_level("show")
    tick(0.3)
    assert window.keys_button.isVisible() and not window.keys_card.isVisible()
    window._toggle_keys()
    tick(0.1)
    assert window.keys_card.isVisible()
    assert "играть" in window.keys_card.text() and "луп" in window.keys_card.text()
    window._toggle_keys()
    tick(0.1)
    assert not window.keys_card.isVisible()


def test_a_0_3_chain_opens_laid_out(quick_look, clips, tick):
    """The chain put aside in the quick look is the show mode's to open."""
    import logfile
    window = quick_look
    kept = logfile.load_settings()
    kept["chains_0_3"] = {"Top": {"files": [str(clips["top"]),
                                            str(clips["bottom"])],
                                  "repeats": [2, 1]}}
    logfile.save_settings(kept)
    try:
        window._set_level("show")
        tick(0.4)
        top = window.show_open.on("Top")
        assert [clip.name for clip in top] == ["qa_top.mov", "qa_top.mov",
                                               "qa_bottom.mov"]
        assert top[1].tx == top[0].last and top[2].tx == top[1].last
    finally:
        kept.pop("chains_0_3", None)
        logfile.save_settings(kept)


def test_the_show_mode_is_remembered(quick_look, tick):
    window = quick_look
    window._set_level("show")
    tick(0.2)
    now = window._settings_now()
    assert now["level"] == "show"
    window._set_level("view")
    tick(0.2)
    assert window._settings_now()["level"] == "view"


# -- a real show ---------------------------------------------------------------

@needs_rusday
def test_a_show_opens_with_its_loops_and_its_levels(quick_look, tick):
    window = quick_look
    show = opened(window, tick)
    assert window.level == "show"
    assert show.loops == [(800, 1099)]
    assert window.show_view.loops == [(800, 1099)]
    assert window.project_name.text() == show.name
    assert sorted(window.composers) == ["Lamel_screen", "Screen_Bottom",
                                        "Screen_Top"]
    assert window.clock.duration == pytest.approx(79200 / 60.0)
    # A track a level, and at most two readers open on any of them.
    assert len(window.streams) == sum(len(show.levels(row))
                                      for row in ("Top", "Bottom", "Lamels"))
    assert all(track.open_now <= 2 for track in window.streams)


@needs_rusday
def test_the_crossfade_is_two_layers_added(quick_look, tick):
    """Frame 11742: the section leaving still fading, the next begun."""
    window = quick_look
    opened(window, tick)
    settled_at(window, tick, 11742)
    assert layers_on(window, "Screen_Top", 11742) == 2
    picture = framed(window, 480, 270)
    assert picture[..., :3].max() > 10, "the building came out black"


@needs_rusday
def test_the_playhead_driving_into_the_wait_lights_loop(quick_look, tick):
    window = quick_look
    opened(window, tick)
    window._move(780 / 60.0)
    assert not window.show_view.looping
    window._toggle()
    wait_for(tick, lambda: window.show_view.frame > 830,
             "the playhead never got into the loop", 10)
    assert window.show_view.looping, "LOOP stayed dark"
    assert window.show_pane.ruler.switch.isChecked()
    # The hand on the switch: the loop lets go, and the show goes on.
    window.show_pane.ruler.switch.click()
    assert not window.show_view.looping
    assert window.show_view.let_go == (800, 1099)
    window._toggle()


@needs_rusday
def test_the_motors_arrive_and_move_the_cells(quick_look, tick):
    window = quick_look
    show = opened(window, tick)
    moving = [clip for clip in show.clips
              if clip.kind == "kinetic" and not clip.missing]
    if not moving:
        pytest.skip("no motor file of this show is on this machine")
    wait_for(tick, lambda: window.show_motors is not None,
             "the motors never arrived", 60)
    assert window.solid is not None
    first = min(clip.tx for clip in moving)
    if first >= 30:
        settled_at(window, tick, first - 30)
        assert window._moved_to is None, "the cells moved before any file began"
    # Well inside the longest file, and counted from whichever file began
    # last before there: that one is in charge.
    longest = max(moving, key=lambda clip: clip.frames)
    target = longest.tx + 120
    began = max(clip.tx for clip in moving if clip.tx <= target)
    settled_at(window, tick, target)
    assert isinstance(window._moved_to, tuple), "the cells never moved"
    assert window._moved_to[1] == target - began


@needs_rusday
def test_the_motors_are_kept_for_coming_back(quick_look, tick):
    """Four seconds and a third of a gigabyte, not spent again for going
    into the quick look and back."""
    window = quick_look
    opened(window, tick)
    if not any(clip.kind == "kinetic" and not clip.missing
               for clip in window.show_open.clips):
        pytest.skip("no motor file of this show is on this machine")
    wait_for(tick, lambda: window.show_motors is not None,
             "the motors never arrived", 60)
    first = [motors for _, motors in window.show_motors.placed]
    window._set_level("view")
    tick(0.3)
    window._set_level("show")
    assert window.show_motors is not None, "the motors were not there at once"
    again = [motors for _, motors in window.show_motors.placed]
    assert all(one is other for one, other in zip(first, again))         and len(first) == len(again), "the motors were built again"


@needs_rusday
def test_a_render_goes_through_the_gaps(quick_look, tick):
    """Across the end of the wait, where every track is still between clips:
    that used to stop the render at its first frame."""
    window = quick_look
    opened(window, tick)
    target = HOME / "OUT" / "qa_show_gap.mp4"
    target.unlink(missing_ok=True)
    window.out_name.setText(target.name)
    window.first_frame.setValue(1080)
    window.last_frame.setValue(1139)
    said = render_and_wait(window, tick, within=240)
    assert "Записано" in said, said
    written = look.probe(target)
    rate = float(window.fps_choice.currentData())
    assert written["frames"] == round(60 / 60.0 * rate), written
    temp = HOME / "temp"
    assert not list(temp.glob("show_mix_*.wav")), "the show's mix was left"


def test_the_counts_over_the_status_line_fold_away(quick_look, tick):
    """The status line stays; the file by file counts over it go."""
    window = quick_look
    window._fold_stats(True)
    tick(0.3)
    assert window.stats.isVisible() and "qa_top.mov" in window.stats.text()
    assert window.stats_head.text() == "Статистика декодера \u25be"
    window.stats_head.click()
    tick(0.3)
    assert not window.stats.isVisible(), "the counts stayed up"
    assert window.stats_head.isVisible()
    assert window.stats_head.text() == "Статистика декодера \u25b4"
    assert "файлы: 3" in window.status_files.text()
    assert "\u25cf" in window.status.text()
    assert window._settings_now()["stats_open"] is False
    window._fold_stats(True)
    tick(0.2)
    assert window.stats.isVisible()
