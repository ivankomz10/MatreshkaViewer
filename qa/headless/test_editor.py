"""The editor, in the window: every kind of change, its undo, its draft.

The mouse here is Qt events sent to the widget itself -- a press, moves and
a release on the tracks -- which is the widget's own code path without the
machine's pointer moving. The show file is never written: every draft goes
into the sandbox, and each test starts with none.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

import draft as drafts
import timeline
from conftest import HOME, wait_for
from test_quiet import put_back

RUSDAY = Path(r"D:\Content\_SHOW"
              r"\2026-Daily-RusDay-Matreshka_Day-MuzeyTransporta-v001.trix")
needs_rusday = pytest.mark.skipif(not RUSDAY.exists(),
                                  reason="the RusDay show is not here")
DRAFTS = HOME / "drafts"


@pytest.fixture
def editor(window, clips, tick):
    """In Шоу over the three test clips, the editor on, no draft anywhere."""
    shutil.rmtree(DRAFTS, ignore_errors=True)
    window.ask_resume = lambda found: "draft"
    window.draft = None
    window.trix_path = ""
    window._set_level("view")
    put_back(window, clips, tick)
    window._set_level("show")
    tick(0.3)
    window._set_editing(True)
    tick(0.1)
    yield window
    if window.player is not None:
        window.player.set_volume(0.0)
    if window.clock.playing:
        window._toggle()
    window._set_editing(False)
    window.draft = None
    window.trix_path = ""
    window.history.clear()
    window._set_level("view")
    put_back(window, clips, tick)
    shutil.rmtree(DRAFTS, ignore_errors=True)


def top_clip(window):
    return window.show_open.on("Top")[0]


def send(widget, kind, x, y, button=Qt.MouseButton.LeftButton,
         held=Qt.MouseButton.LeftButton, keys=Qt.KeyboardModifier.NoModifier):
    point = QPointF(x, y)
    event = QMouseEvent(kind, point, widget.mapToGlobal(point), button, held,
                        keys)
    QApplication.sendEvent(widget, event)


def drag(widget, start, end, steps=8, keys=Qt.KeyboardModifier.NoModifier):
    (x1, y1), (x2, y2) = start, end
    send(widget, QEvent.Type.MouseButtonPress, x1, y1, keys=keys)
    for step in range(1, steps + 1):
        send(widget, QEvent.Type.MouseMove, x1 + (x2 - x1) * step / steps,
             y1 + (y2 - y1) * step / steps, button=Qt.MouseButton.NoButton,
             keys=keys)
    send(widget, QEvent.Type.MouseButtonRelease, x2, y2,
         held=Qt.MouseButton.NoButton, keys=keys)


# -- read only means read only ---------------------------------------------------

def test_without_the_editor_nothing_changes(editor, tick):
    window = editor
    window._set_editing(False)
    view = window.show_view
    view.pick(top_clip(window))
    view.set_frame(20)
    view.put_clip(True)
    view.delete_chosen()
    view.add_cue()
    assert top_clip(window).tx == 0 and not window.history.back
    assert window.draft is None, "a draft was begun without the editor"
    assert window.project_name.isReadOnly(), "the name is typed into outside the editor"


# -- clips -------------------------------------------------------------------------

def test_a_clip_dragged_on_the_tracks_moves_and_plays_from_there(editor, tick):
    window = editor
    tracks = window.show_pane.tracks
    view = window.show_view
    view.axis.fit()
    band = tracks.band_of(top_clip(window))
    start = (band.center().x(), band.center().y())
    # Down a level as well: Top L0 to Top L1, and along.
    drag(tracks, start, (start[0] + 200, start[1] + tracks.LANE))
    clip = top_clip(window)
    assert clip.tx > 0 and clip.level == 1, (clip.tx, clip.level)
    assert len(window.history.back) == 1
    playing = [track for track in window.streams
               if any(one.ident == clip.ident for one in track.clips)]
    assert playing and playing[0].clips[0].tx == clip.tx, (
        "the screen still plays the clip where it was")


def test_the_right_hand_moves_the_lanes_up_and_down_and_the_time_across(
        editor, tick):
    """A drag with the right button carries the field of lanes both ways, and
    changes nothing in the show."""
    window = editor
    pane = window.show_pane
    tracks, bar = pane.tracks, pane.scroller.verticalScrollBar()
    pane.scroller.setFixedHeight(80)          # fewer lanes fit than there are
    tick(0.3)
    try:
        assert bar.maximum() > 40, f"nothing to scroll: {bar.maximum()}"
        bar.setValue(0)
        # A second of show fits whole at any zoom; a longer axis has room to
        # slide along.
        axis = window.show_view.axis
        axis.stretch(6000)
        axis.fit()
        axis.zoom_at(tracks.width() / 2, 8.0)
        left_was = axis.left
        right = Qt.MouseButton.RightButton
        still = pane.scroller.viewport()      # what does not move as it scrolls

        def hand(kind, x, y, button, held):
            # Where a real hand is: on the screen. The lanes slide under it,
            # so where that is on them changes as they scroll.
            spot = still.mapToGlobal(QPointF(x, y))
            QApplication.sendEvent(tracks, QMouseEvent(
                kind, tracks.mapFromGlobal(spot), spot, button, held,
                Qt.KeyboardModifier.NoModifier))

        x = tracks.width() * 0.6
        hand(QEvent.Type.MouseButtonPress, x, 60, right, right)
        for step in range(1, 9):
            # Up by forty and left by eighty, in steps.
            hand(QEvent.Type.MouseMove, x - 10 * step, 60 - 5 * step,
                 Qt.MouseButton.NoButton, right)
        hand(QEvent.Type.MouseButtonRelease, x - 80, 20, right,
             Qt.MouseButton.NoButton)
        tick(0.1)
        assert 30 <= bar.value() <= 50, f"the lanes moved by {bar.value()}"
        assert window.show_view.axis.left > left_was, "the time did not move"
        assert tracks.panning is None
        assert not window.history.back, "a look around became a change"
    finally:
        pane.scroller.setMinimumHeight(60)
        pane.scroller.setMaximumHeight(16777215)
        bar.setValue(0)
        window.show_view.axis.stretch(window.show_open.length)
        window.show_view.axis.fit()
        tick(0.2)


def test_a_click_on_a_clip_is_not_a_change(editor, tick):
    window = editor
    tracks = window.show_pane.tracks
    band = tracks.band_of(top_clip(window))
    drag(tracks, (band.center().x(), band.center().y()),
         (band.center().x(), band.center().y()), steps=1)
    assert window.show_view.chosen is top_clip(window)
    assert not window.history.back, "choosing a clip went into the history"


def test_a_dragged_clip_meets_the_edges(editor, tick):
    window = editor
    view = window.show_view
    view.axis.fit()
    clip = top_clip(window)
    other = window.show_open.on("Bottom")[0]
    close = int(3 / view.axis.scale)
    assert view.snap(clip, other.last + close) == other.last
    far = other.last + int(40 / view.axis.scale)
    assert view.snap(clip, far) == far, "it snapped to an edge nowhere near"


def test_brackets_put_a_clip_against_the_playhead_and_undo_puts_it_back(
        editor, tick):
    window = editor
    view = window.show_view
    view.pick(top_clip(window))
    window._move(40 / 60.0)
    view.put_clip(True)
    assert top_clip(window).tx == 40
    window._undo()
    assert top_clip(window).tx == 0
    assert view.chosen is not None and view.chosen.ident == top_clip(window).ident
    window._redo()
    assert top_clip(window).tx == 40


def test_typing_a_fade_is_one_step_back(editor, tick):
    window = editor
    view = window.show_view
    view.pick(top_clip(window))
    field = window.show_side.inspector.body["fade_end"]
    assert not field.isReadOnly()
    for value in (-5, -20):
        field.setValue(value)
    assert top_clip(window).fade_end == -20
    assert len(window.history.back) == 1
    window._undo()
    assert top_clip(window).fade_end == 0


def test_deleting_and_bringing_back(editor, tick):
    window = editor
    view = window.show_view
    view.pick(window.show_open.on("Bottom")[0])
    view.delete_chosen()
    assert not window.show_open.on("Bottom")
    assert "Screen_Bottom" in window.composers
    assert not window.composers["Screen_Bottom"][1], "a deleted clip still plays"
    window._undo()
    assert len(window.show_open.on("Bottom")) == 1
    assert window.composers["Screen_Bottom"][1]


def test_files_dropped_on_a_lane_land_there(editor, clips, tick):
    window = editor
    before = len(window.show_open.clips)
    window._drop_files([str(clips["lamels"]), str(clips["top"])],
                       "Bottom", 2, 90)
    placed = [one for one in window.show_open.on("Bottom", 2)]
    assert [(one.name, one.tx) for one in placed] == [
        ("qa_lamels.mov", 90), ("qa_top.mov", 90 + placed[0].frames)]
    assert len(window.show_open.clips) == before + 2
    assert window.show_open.length >= placed[-1].last
    assert len(window.history.back) == 1, "two files were two steps"


def test_a_file_a_lane_will_not_open_changes_nothing(editor, tmp_path, tick):
    window = editor
    broken = tmp_path / "not_a_movie.mov"
    broken.write_bytes(b"nothing like a movie")
    window._drop_files([str(broken)], "Top", 0, 10)
    assert not window.history.back
    assert "not_a_movie" in window.show_pane.note.text()
    assert not timeline.row_takes("Sound", str(broken))
    assert timeline.row_takes("Kinetic", "x.json")


def test_a_cue_at_the_playhead(editor, tick):
    window = editor
    window._move(25 / 60.0)
    window.show_view.add_cue()
    cue = window.show_view.chosen
    assert cue.kind == "cue" and cue.tx == 25 and cue in window.show_open.clips
    field = window.show_side.inspector.body["universe"]
    field.setValue(7)
    assert cue.universe == 7


def test_the_name_is_typed_in_the_editor(editor, tick):
    window = editor
    window.project_name.setText("Моё шоу")
    window.project_name.editingFinished.emit()
    assert window.show_open.name == "Моё шоу"
    window._flush_draft()
    _, read = drafts.Draft.load(window.draft.where)
    assert read.name == "Моё шоу"


# -- loops ---------------------------------------------------------------------------

def test_loops_are_drawn_only_unlocked(editor, tick):
    window = editor
    bar = window.show_pane.loopbar
    view = window.show_view
    view.axis.fit()
    assert bar.lock.isVisible() and view.locked
    y = bar.height() // 2
    drag(bar, (bar.width() * 0.3, y), (bar.width() * 0.5, y))
    assert not view.loops, "a loop was drawn through the lock"
    view.set_locked(False)
    drag(bar, (bar.width() * 0.3, y), (bar.width() * 0.5, y))
    assert len(view.loops) == 1 and view.loops is window.show_open.loops
    low, high = view.loops[0]
    assert high - low > 5
    window.show_side.loops.high.setValue(high + 3)
    assert view.loops[0] == (low, high + 3)
    view.drop_loop()
    assert not view.loops
    window._undo()
    assert view.loops == [(low, high + 3)]


def test_a_loop_over_the_whole_clip_holds(editor, tick):
    window = editor
    view = window.show_view
    clip = top_clip(window)
    view.pick(clip)
    view.loop_the_clip()
    assert view.loops == [(clip.first, clip.last)]
    assert view.looping


# -- the draft -------------------------------------------------------------------------

def test_the_first_change_begins_a_draft_and_it_is_written(editor, tick):
    window = editor
    assert window.draft is None
    window.show_view.pick(top_clip(window))
    window._move(10 / 60.0)
    window.show_view.put_clip(True)
    assert window.draft is not None and window.draft.where.parent == DRAFTS
    wait_for(tick, lambda: window.draft.where.exists(),
             "the draft was never written", 5)
    _, read = drafts.Draft.load(window.draft.where)
    assert read.on("Top")[0].tx == 10
    assert window._settings_now()["draft"] == str(window.draft.where)


def test_the_history_survives_going_to_the_quick_look_and_back(editor, tick):
    window = editor
    window.show_view.pick(top_clip(window))
    window._move(12 / 60.0)
    window.show_view.put_clip(True)
    window._set_level("view")
    tick(0.2)
    window._set_level("show")
    window._set_editing(True)
    tick(0.2)
    assert top_clip(window).tx == 12, "the edit was lost going to the quick look"
    window._undo()
    assert top_clip(window).tx == 0


def test_a_new_show_is_empty_and_edited(editor, tick):
    window = editor
    window._new_show()
    tick(0.2)
    show = window.show_open
    assert not show.clips and show.length == 79200 and show.name == "Новое шоу"
    assert window.show_view.editing and window.draft.where.exists()


@needs_rusday
def test_opening_a_show_with_a_draft_asks(editor, tick):
    window = editor
    window.open_show_file(str(RUSDAY))
    tick(0.3)
    assert window.draft is None and not window.show_view.editing
    window._set_editing(True)
    first = window.show_open.on("Top")[0]
    window.show_view.pick(first)
    window._move(2000 / 60.0)
    window.show_view.put_clip(True)
    window._flush_draft()
    where = window.draft.where
    asked = []

    def answer(what):
        def ask(found):
            asked.append(found)
            return what
        return ask

    # Neither: nothing moves.
    window.ask_resume = answer(None)
    window.open_show_file(str(RUSDAY))
    assert asked and window.draft is not None
    # Carry on: the edit is there, the editor on.
    window.ask_resume = answer("draft")
    window.open_show_file(str(RUSDAY))
    tick(0.3)
    assert window.show_view.editing
    assert any(one.tx == 2000 for one in window.show_open.on("Top"))
    assert not asked[-1].source_changed()
    # Afresh: the file as it is, the draft kept aside.
    window.ask_resume = answer("file")
    window.open_show_file(str(RUSDAY))
    tick(0.3)
    assert not where.exists() and list((DRAFTS / "old").glob("*.json"))
    assert window.draft is None and not window.show_view.editing
    assert all(one.tx != 2000 for one in window.show_open.on("Top"))


@needs_rusday
def test_a_draft_says_when_its_show_file_has_changed(editor, tick):
    window = editor
    window.open_show_file(str(RUSDAY))
    window._set_editing(True)
    window.show_view.add_cue()
    window._flush_draft()
    kept = drafts.Draft.load(window.draft.where)[0]
    kept.source_stamp = {"size": 1, "mtime_ns": 1}     # as if written since
    kept.save(drafts.Draft.load(window.draft.where)[1])
    seen = []
    window.ask_resume = lambda found: (seen.append(found.source_changed()),
                                       "draft")[1]
    window.open_show_file(str(RUSDAY))
    assert seen == [True]


@needs_rusday
def test_giving_the_draft_up_opens_the_file(editor, tick):
    window = editor
    window.open_show_file(str(RUSDAY))
    window._set_editing(True)
    window.show_view.add_cue()
    cues = len([one for one in window.show_open.clips if one.kind == "cue"])
    window._revert()
    tick(0.3)
    assert window.draft is None and not window.show_view.editing
    assert len([one for one in window.show_open.clips
                if one.kind == "cue"]) == cues - 1
    assert RUSDAY.exists()


@needs_rusday
def test_moving_a_motor_file_does_not_build_its_motors_again(editor, tick):
    window = editor
    window.open_show_file(str(RUSDAY))
    window._set_editing(True)
    moving = [one for one in window.show_open.clips
              if one.kind == "kinetic" and not one.missing]
    if not moving:
        pytest.skip("no motor file of this show is on this machine")
    wait_for(tick, lambda: window.show_motors is not None
             and len(window.show_motors.placed) == len(moving),
             "the motors never arrived", 90)
    clip = max(moving, key=lambda one: one.frames)
    before = {id(motors) for _, motors in window.show_motors.placed}
    window.show_view.pick(clip)
    window._move((clip.tx + 600) / 60.0)
    window.show_view.put_clip(True)
    assert window.motors_job is None, "the motors were sent to be built again"
    after = {id(motors) for _, motors in window.show_motors.placed}
    assert after == before
    assert clip.tx in [start for start, _ in window.show_motors.placed]


@needs_rusday
def test_moving_a_sound_moves_it_in_the_mix(editor, tick):
    window = editor
    window.open_show_file(str(RUSDAY))
    if window.player is not None:
        window.player.set_volume(0.0)
    window._set_editing(True)
    heard = [one for one in window.show_open.clips
             if one.kind == "audio" and not one.missing]
    if not heard:
        pytest.skip("no sound of this show is on this machine")
    clip = heard[0]
    window.show_view.pick(clip)
    window._move((clip.tx + 300) / 60.0)
    window.show_view.put_clip(True)
    if window.player is not None:
        window.player.set_volume(0.0)
    offsets = [offset for _, offset, _ in window.mix._pieces]
    assert round(clip.tx / 60.0 * window.mix.rate) in offsets
