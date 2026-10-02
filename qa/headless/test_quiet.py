"""Everything that can be asked without a hand on the mouse.

Same questions as the driven suite where they overlap -- the lists, the
sizes, the names, the refusals, the snapshot -- asked by calling what the
buttons call. Run this while somebody is working on the machine; run the
other one when nobody is.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import media
from conftest import HOME, PREVIEW, render_and_wait, wait_for

import look

# The screens themselves, in their own pixels: the outside truth Flat answers
# to. Written down in both suites on purpose -- if they disagree, one of them
# is wrong about the wall.
WIDE = {"top": 2500, "bottom": 4608, "lamels": 536}
TALL = {"top": 1150, "bottom": 1584, "lamels": 110}


def down4(side: float) -> int:
    return max(4, int(side) // 4 * 4)


def shape(row: str, scale: float) -> tuple[int, int]:
    return down4(WIDE[row] * scale), down4(TALL[row] * scale)


def items(box) -> list:
    return [box.itemText(n) for n in range(box.count())]


def out(window):
    return window.out_dir


# -- what the modes offer ----------------------------------------------------

def test_the_mode_is_called_preview(window):
    assert items(window.mode)[0] == PREVIEW, items(window.mode)
    assert window.mode.currentText() == PREVIEW


def test_an_old_settings_file_still_names_it(window, clips, tick):
    """`Geometry` in a settings file must still open this mode."""
    import main as viewer
    assert viewer.WAS_CALLED["Geometry"] == PREVIEW


def test_flat_swaps_the_lists_and_puts_them_back(window, tick):
    window.mode.setCurrentText("Flat")
    tick(0.4)
    assert items(window.size_choice) == ["Родное", "Половина", "Четверть"]
    formats = items(window.format_choice)
    assert "ProRes 4444 alpha" in formats and "PNG alpha" in formats
    assert not window.out_name.isEnabled()
    assert not window.bump_button.isEnabled()

    window.mode.setCurrentText(PREVIEW)
    tick(0.4)
    assert items(window.size_choice)[0] == "1080x1920"
    assert "PNG alpha" not in items(window.format_choice)
    assert window.out_name.isEnabled()


def test_rebake_raises_its_own_bar(window, tick):
    window.mode.setCurrentText("ReBake")
    tick(0.5)
    assert window.rebake_bar.isVisible()
    assert window.rebake_left_alpha.isVisible()
    assert window.rebake_right_alpha.isVisible()
    assert not window.matching.isVisible(), "a scene switch is up in ReBake"
    assert window.linked.isVisible(), "the link belongs to every mode"
    window.mode.setCurrentText(PREVIEW)
    tick(0.4)


def test_the_timeline_survives_a_mode_change(window, tick):
    window.mode.setCurrentText(PREVIEW)
    window._step(1)
    window._step(1)
    tick(0.3)
    was = window.frame_label.text()
    for mode in ("Flat", "Inspection", "ReBake", PREVIEW):
        window.mode.setCurrentText(mode)
        tick(0.3)
        assert window.frame_label.text() == was, (
            f"{mode} moved the timeline: {was!r} -> {window.frame_label.text()!r}")


# -- the framing line --------------------------------------------------------

def test_the_framing_line_follows_the_zoom(window, tick):
    window.mode.setCurrentText(PREVIEW)
    window.reset_view()
    tick(0.3)
    assert window.frame_edge.isVisible(), "no framing line at the whole frame"
    window.mesh.look_at_window(None, 0.5)          # in
    window._lay_frame_edge()
    tick(0.2)
    assert not window.frame_edge.isVisible(), "the line stayed while zoomed in"
    window.reset_view()
    tick(0.2)
    assert window.frame_edge.isVisible(), "the line did not come back"


# -- writing a file ----------------------------------------------------------

def test_it_writes_the_size_and_the_range_asked_for(window, tick):
    window.mode.setCurrentText(PREVIEW)
    window.size_choice.setCurrentText("1080x1920")
    window.format_choice.setCurrentText("H.264 mp4")
    window.fps_choice.setCurrentText("60 к/с")
    window.first_frame.setValue(0)
    window.last_frame.setValue(11)
    window.out_name.setText("quiet_render.mp4")
    (out(window) / "quiet_render.mp4").unlink(missing_ok=True)
    tick(0.3)

    said = render_and_wait(window, tick)
    assert "Записано" in said, said
    facts = look.probe(out(window) / "quiet_render.mp4")
    assert (facts["width"], facts["height"]) == (1080, 1920), facts
    assert facts["frames"] == 12, facts


def test_it_refuses_to_write_over_a_file(window, tick):
    made = out(window) / "quiet_render.mp4"
    stamp = made.stat().st_mtime
    said = render_and_wait(window, tick, within=30)
    assert "уже есть" in said, said
    assert made.stat().st_mtime == stamp


def test_the_snapshot_is_the_frame_the_render_writes(window, tick):
    """The one the squeezed snapshot fails.

    On screen the camera is opened out to fill the window; a picture taken
    through that and written into the frame's shape is the building made
    narrow. Compared against a PNG the render wrote, so the comparison is
    exact rather than lossy.
    """
    window.mode.setCurrentText(PREVIEW)
    window.size_choice.setCurrentText("1080x1920")
    window.reset_view()
    # On the frame the render writes. The tests before leave the playhead
    # two frames in, and a snapshot is of whatever the screens hold when it
    # is taken -- the render's last frame, or the playhead's once the readers
    # have caught up, depending on how soon it is asked.
    window._move(0.0)
    tick(0.5)
    window.first_frame.setValue(0)
    window.last_frame.setValue(0)
    window.format_choice.setCurrentText("PNG sequence")
    window.out_name.setText("quiet_frame.png")
    made = out(window) / "quiet_frame.png"
    if made.is_dir():
        for old in made.glob("*.png"):
            old.unlink()
    else:
        made.unlink(missing_ok=True)
    tick(0.3)
    assert "Записано" in render_and_wait(window, tick)
    written = (sorted(made.glob("*.png")) if made.is_dir()
               else [made] if made.exists() else [])
    assert written, "the render wrote no still"

    folder = out(window) / "snapshots"
    was = set(folder.glob("*.png")) if folder.exists() else set()
    window._snapshot()
    fresh = wait_for(tick,
                     lambda: sorted(set(folder.glob("*.png")) - was),
                     "the snapshot wrote nothing", within=60)
    assert "не записан" not in window.eta.text(), window.eta.text()

    from PIL import Image
    rendered = Image.open(written[0]).convert("RGB")
    snapped = Image.open(fresh[0]).convert("RGB")
    assert snapped.size == rendered.size == (1080, 1920), (
        f"snapshot {snapped.size}, render {rendered.size}")
    apart = look.difference(snapped, rendered)
    assert apart < 2.0, (
        f"the snapshot and the render differ by {apart:.1f} per pixel -- the "
        "snapshot is not the frame the render writes")


def test_the_folder_and_the_name_are_both_typed_into(window, tick):
    """The output field looks like one path and is typed like one."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    was_dir, was_name = window.out_dir, window.out_name.text()
    typed = HOME / "OUT" / "typed_here"
    try:
        folder = window.out_folder
        assert not folder.isReadOnly()
        folder.setFocus()
        folder.selectAll()
        QTest.keyClicks(folder, str(typed))
        QTest.keyClick(folder, Qt.Key.Key_Return)
        tick(0.1)
        assert window.out_dir == typed, window.out_dir
        assert folder.text().rstrip("\\/") == str(typed)

        # Half a path is not a folder: it is put back, and said.
        folder.setText("just_a_name")
        folder.editingFinished.emit()
        assert window.out_dir == typed
        assert "полный путь" in window.eta.text(), window.eta.text()

        # A whole path pasted into the name goes to both.
        whole = HOME / "OUT" / "pasted" / "piece_v3.mp4"
        window.out_name.setText(str(whole))
        window.out_name.editingFinished.emit()
        assert window.out_dir == whole.parent
        assert window.out_name.text() == "piece_v3.mp4"
    finally:
        window.out_dir = was_dir
        window.out_name.setText(was_name)
        window._note_output()
        window._remember(now=True)
        window.canvas.setFocus()
        tick(0.2)


def test_the_snapshot_leaves_the_window_as_it_was(window, tick):
    """Taking one must not leave the picture framed and letterboxed."""
    window.mode.setCurrentText(PREVIEW)
    window.reset_view()
    tick(0.4)
    before = window.mesh.spill
    window._snapshot()
    tick(0.5)
    assert window.mesh.spill == before, (
        f"the window was left opened out {window.mesh.spill} instead of "
        f"{before}")


def test_a_zoomed_snapshot_keeps_the_zoom(window, tick):
    """Zoomed in, the snapshot is that piece -- and the zoom stays put."""
    window.mode.setCurrentText(PREVIEW)
    window.reset_view()
    window.mesh.look_at_window(None, 0.5)
    tick(0.3)
    window._snapshot()
    tick(0.4)
    assert abs(window.mesh.zoom - 0.5) < 1e-6, (
        f"the snapshot reset the zoom to {window.mesh.zoom}")
    window.reset_view()
    tick(0.2)


# -- Flat --------------------------------------------------------------------

def test_flat_writes_one_file_per_screen_at_the_screen_size(window, tick):
    window.mode.setCurrentText("Flat")
    window.size_choice.setCurrentText("Четверть")
    window.format_choice.setCurrentText("H.264 mp4")
    window.fps_choice.setCurrentText("60 к/с")
    window.first_frame.setValue(0)
    window.last_frame.setValue(3)
    tick(0.4)
    for row in media.CLIPS:
        (out(window) / media.CLIPS[row][0].replace(".mov", "_flat.mp4")).unlink(
            missing_ok=True)

    assert "Записано" in render_and_wait(window, tick)
    for row in media.CLIPS:
        made = out(window) / media.CLIPS[row][0].replace(".mov", "_flat.mp4")
        facts = look.probe(made)
        assert (facts["width"], facts["height"]) == shape(row, 0.25), (
            f"{made.name} came out {facts['width']}x{facts['height']}, "
            f"expected {shape(row, 0.25)}")
    window.mode.setCurrentText(PREVIEW)
    tick(0.3)


def test_flat_alpha_carries_the_alpha(window, tick):
    window.mode.setCurrentText("Flat")
    window.size_choice.setCurrentText("Четверть")
    window.format_choice.setCurrentText("ProRes 4444 alpha")
    window.first_frame.setValue(0)
    window.last_frame.setValue(1)
    tick(0.4)
    made = out(window) / media.CLIPS["top"][0].replace(".mov", "_flat.mov")
    for row in media.CLIPS:
        (out(window) / media.CLIPS[row][0].replace(".mov", "_flat.mov")).unlink(
            missing_ok=True)

    assert "Записано" in render_and_wait(window, tick)
    facts = look.probe(made)
    assert "yuva" in facts["pix_fmt"], facts
    share = look.clear_share(made)
    assert 0.15 < share < 0.35, f"{share * 100:.0f}% transparent"
    assert window.backing.currentData() == "Calibration", (
        "the backing was left off after an alpha render")
    window.mode.setCurrentText(PREVIEW)
    tick(0.3)


def test_nothing_went_wrong_the_whole_time(window):
    bad = [line for line in (logfile_text() or "").splitlines()
           if "Traceback" in line or "FAILED" in line]
    assert not bad, "\n".join(bad)


def logfile_text() -> str:
    import logfile
    where = logfile.path()
    return where.read_text(encoding="utf-8", errors="replace") if where else ""


# -- the quick look: six rows, one fold, played through Track ----------------

PARTS = r"D:\Content\2026-dates\BrendMT\BrendMT_1_of_2.json"


def put_back(window, clips, tick) -> None:
    """The three clips on the three screens, as every other test expects."""
    for title, which in (("Top", "top"), ("Bottom", "bottom"),
                         ("Lamels", "lamels")):
        window.row_for(title).field.setText(str(clips[which]))
    for title in ("Frame", "Kinetic"):
        window.row_for(title).field.setText("")
    window._load()
    tick(0.4)


def test_there_are_six_rows_and_no_chains(window):
    from PySide6.QtWidgets import QWidget
    assert [row.title for row in window.rows] == [
        "Top", "Bottom", "Lamels", "Frame", "Sound", "Kinetic"]
    names = [one.objectName() for one in window.findChildren(QWidget)]
    for gone in ("qa_add_", "qa_less_", "qa_repeat_", "qa_spread_",
                 "qa_group", "qa_loops"):
        assert not [n for n in names if n.startswith(gone)], (
            f"something of the chains is still in the window: {gone}")


def test_every_screen_plays_through_a_track(window, clips, tick):
    """One way of playing things: the quick look is a show of one clip each."""
    import player
    put_back(window, clips, tick)
    assert window.streams, "nothing is loaded"
    assert all(isinstance(one, player.Track) for one in window.streams)
    shown = window.show_now
    assert sorted(clip.row for clip in shown.clips) == ["Bottom", "Lamels", "Top"]
    assert all(clip.tx == 0 for clip in shown.clips)
    # And the picture moves as it always did.
    window._move(0.2)
    tick(0.4)
    early = [held.index for held in window.held if held is not None]
    window._move(0.8)
    tick(0.4)
    late = [held.index for held in window.held if held is not None]
    assert early and late and min(late) > max(early), (early, late)


def test_a_still_stays_up_for_as_long_as_it_is_loaded(window, clips, tick,
                                                      tmp_path):
    """A picture has no length of its own, so it neither sets the timeline
    nor goes dark at the end of it."""
    from PIL import Image
    picture = tmp_path / "still.png"
    Image.new("RGBA", (64, 32), (200, 40, 40, 255)).save(picture)
    put_back(window, clips, tick)
    window.row_for("Top").field.setText(str(picture))
    window._load()
    tick(0.4)
    track = next(one for one, feeds in zip(window.streams, window.feeding)
                 if feeds == "Screen_Top")
    assert track.duration == 0.0, "a still gave the timeline a length"
    assert abs(window.clock.duration - 1.0) < 0.05, window.clock.duration
    assert track.showing(10_000_000) is not None, "the still went away"
    assert "fitted into" in window.row_for("Top").note.text() \
        or "64x32" in window.row_for("Top").note.text()
    put_back(window, clips, tick)


def test_a_file_that_will_not_open_says_why(window, clips, tick):
    put_back(window, clips, tick)
    window.row_for("Top").field.setText(r"E:\nowhere\at_all.mov")
    window._load()
    tick(0.3)
    said = window.row_for("Top").note.text()
    assert "at_all.mov" in said and "такого файла нет" in said, said
    assert "Screen_Top" not in window.feeding
    put_back(window, clips, tick)


def test_a_chain_from_0_3_is_kept_aside_not_lost(window, clips, tick):
    """The quick look plays one file a row. A settings file from 0.3 with a
    chain in it must not lose the chain the first time it is saved again."""
    import json

    import logfile
    from conftest import HOME, settings, write_settings
    chain = [str(clips["top"]), str(clips["bottom"]), str(clips["lamels"])]
    old = settings(clips)
    old["rows"]["Top"] = {"file": chain[0], "files": chain,
                          "repeats": [1, 6, 1], "gain": 100}
    write_settings(old)
    try:
        window._start_from_settings()
        tick(0.5)
        assert window.row_for("Top").field.text() == chain[0]
        window._remember(now=True)
        kept = json.loads((HOME / "settings.json").read_text("utf-8"))
        aside = kept.get("chains_0_3", {}).get("Top")
        assert aside == {"files": chain, "repeats": [1, 6, 1]}, aside
        # And it stays put across another save: nothing writes over it.
        window._remember(now=True)
        again = json.loads((HOME / "settings.json").read_text("utf-8"))
        assert again["chains_0_3"]["Top"]["files"] == chain
        assert "kept aside" in logfile.path().read_text("utf-8")
    finally:
        write_settings(settings(clips))
        window._start_from_settings()
        tick(0.5)


@pytest.mark.skipif(not Path(PARTS).exists(),
                    reason="the two-part show is not on this machine")
def test_a_lone_part_brings_its_siblings(window, clips, tick):
    """One row, and a show the exporter cut in two is still one show."""
    put_back(window, clips, tick)
    window.row_for("Kinetic").field.setText(PARTS)
    window._load()
    wait_for(tick, lambda: window.motors is not None, "nothing loaded",
             within=60)
    assert [part.name for part in window.motors.parts] == [
        "BrendMT_1_of_2.json", "BrendMT_2_of_2.json"]
    assert "части 1, 2 из 2" in window.row_for("Kinetic").note.text()
    assert "+1" in window.sources_summary()
    put_back(window, clips, tick)


def test_clicking_the_header_folds_and_unfolds(window, tick):
    """Through the signal, not the method.

    `clicked` hands its handler a bool, and connecting it straight at a
    method whose first argument decides the fold meant every click folded:
    the second one had nothing left to do. A test that called the method
    itself never saw it.
    """
    window._fold_sources(True)
    tick(0.2)
    assert window.sources_open

    window.sources_head.click()
    tick(0.2)
    assert not window.sources_open, "one click did not fold it"

    window.sources_head.click()
    tick(0.2)
    assert window.sources_open, "the second click did not unfold it"

    window.sources_head.click()
    window.sources_head.click()
    tick(0.2)
    assert window.sources_open, "two more clicks left it somewhere else"


def test_the_cards_fold_to_a_strip_of_marks(window, clips, tick):
    """Folded, the column gives the picture its width, and says what is
    loaded by which of its marks are lit -- and in full, in the hover."""
    put_back(window, clips, tick)
    window._fold_sources(True)
    tick(0.2)
    wide = window.sources.width()
    count = window.sources_count.text()
    loaded = [row for row in window.rows if row.field.text().strip()]
    assert count == f"{len(loaded)} из {len(window.rows)} загружено", count
    window._fold_sources(False)
    tick(0.2)
    assert not window.sources_open
    assert not window.sources_body.isVisible()
    assert window.sources_marks.isVisible()
    assert window.sources.width() < wide / 4, (
        f"folded, the column is still {window.sources.width()} px")
    said = window.sources_summary()
    for row in loaded:
        assert row.title in said, f"the summary does not name {row.title}"
    window._fold_sources(True)
    tick(0.2)
    assert window.sources.width() == wide


def test_the_link_stands_under_the_cards_it_ties(window, tick):
    """At the foot of the cards in the quick look; with the sliders in the
    show's Экраны in Шоу -- the same button, moved, not a second one."""
    assert window.level == "view"
    assert window.link_banner.isAncestorOf(window.linked)
    assert window.linked.isVisible()
    window.linked.setChecked(True)
    tick(0.1)
    assert window.linked.text() == "Разъединить"
    assert "связаны" in window.link_said.text()
    window.linked.setChecked(False)
    tick(0.1)
    assert window.linked.text() == "Связать"
    assert "не связаны" in window.link_said.text()


def test_the_link_still_ties_the_two_sliders(window, tick):
    top, bottom = window.row_for("Top"), window.row_for("Bottom")
    top.gain.setValue(120)
    bottom.gain.setValue(100)
    window.linked.setChecked(True)
    tick(0.2)
    top.gain.setValue(60)
    tick(0.2)
    assert bottom.gain.value() != 100, (
        "the other slider stayed put: the link is not tied to anything")
    window.linked.setChecked(False)
    top.gain.setValue(129)
    bottom.gain.setValue(129)
    tick(0.2)


# -- the reviewed interface ---------------------------------------------------

def test_the_modes_are_tabs_that_answer_like_the_list(window, tick):
    from conftest import PREVIEW
    assert [window.mode.itemText(i) for i in range(window.mode.count())] == [
        PREVIEW, "Flat", "Inspection", "ReBake"]
    labels = [window.mode.buttons[window.mode.itemText(i)].text()
              for i in range(window.mode.count())]
    assert labels == ["Превью", "Развертка", "Инспектор", "Перепечка"]
    window.mode.buttons["Flat"].click()
    tick(0.2)
    assert window.mode.currentText() == "Flat" and window.flat_mode()
    window.mode.setCurrentText(PREVIEW)
    tick(0.2)
    assert window.mode.buttons[PREVIEW].isChecked()


def test_the_layers_are_in_a_menu(window, tick):
    bar = window.mode.parentWidget()
    assert window.layers_button.menu() is not None
    boxes = [box.text() for box in window.toggles.values()]
    assert "Корпус" in boxes and "Оболочка" in boxes, boxes
    for box in window.toggles.values():
        assert not box.isVisible(), "a layer box is still on the bar"


def test_how_the_screens_look_is_one_bar_over_the_picture(window, tick):
    """The match, the top's back, the alpha, the backing, the frame and the
    whole monitor: one bar, over the picture, in the quick look."""
    from conftest import PREVIEW
    window.mode.setCurrentText(PREVIEW)
    tick(0.2)
    assert window.level == "view" and window.look_bar.isVisible()
    for widget in (window.matching, window.solid_top, window.alpha,
                   window.backing, window.frame_button, window.full_button,
                   window.reset_button):
        assert window.look_bar.isAncestorOf(widget), widget.objectName()
        assert widget.isVisible(), widget.objectName()
    assert window.look_bar.geometry().right() <= window.canvas.width()
    # The brightness is on each card, the frame's included.
    for title in ("Top", "Bottom", "Lamels", "Frame", "Sound"):
        row = window.row_for(title)
        assert row.gain is not None and row.isAncestorOf(row.gain), title
    assert window.row_for("Kinetic").gain is None
    window.mode.setCurrentText("Flat")
    tick(0.2)
    assert window.tile_button.isVisible() and not window.frame_button.isVisible()
    window.mode.setCurrentText(PREVIEW)
    tick(0.2)


def test_one_reading_of_time_and_it_counts_frames_of_the_whole(window, tick):
    window._move(0.5)
    tick(0.3)
    at, last = window._frame_now()
    assert window.frame_label.text() == f"кадр {at} из {last + 1}"
    assert window.time_label.text().count(":") == 3


def test_a_press_anywhere_on_the_slider_puts_the_playhead_there(window, tick):
    """The handle is a line two pixels wide: the press is what moves it."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    window._move(0.0)
    tick(0.2)
    slider = window.slider
    middle = QPoint(slider.width() // 2, slider.height() // 2)
    QTest.mousePress(slider, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, middle)
    QTest.mouseRelease(slider, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier, middle)
    tick(0.3)
    at, last = window._frame_now()
    assert 0.4 * last < at < 0.6 * last, f"a press in the middle landed on {at} of {last}"
    assert not slider.isSliderDown()
    window._move(0.0)
    tick(0.2)


def test_the_keys_are_the_keyboard_s_not_the_layout_s():
    """On a Russian layout I is Ш and Shift with / is a comma; the viewer
    answers the key, which Windows names the same on every layout."""
    import sys
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    import main
    if sys.platform != "win32":
        pytest.skip("the key's own code is read on Windows only")
    press = QEvent.Type.KeyPress
    sha = QKeyEvent(press, 0x428, Qt.KeyboardModifier.NoModifier, 0x17, 0x49,
                    0, "ш")
    assert main.layout_key(sha) == Qt.Key.Key_I
    comma = QKeyEvent(press, Qt.Key.Key_Comma, Qt.KeyboardModifier.ShiftModifier,
                      0x35, 0xBF, 0, ",")
    assert main.layout_key(comma) == Qt.Key.Key_Slash
    space = QKeyEvent(press, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier,
                      0x39, 0x20, 0, " ")
    assert main.layout_key(space) == Qt.Key.Key_Space


def test_shift_i_and_o_set_the_range_from_the_playhead(window, tick):
    window._move(10 / 60.0)
    window._range_here(False)
    window._move(40 / 60.0)
    window._range_here(True)
    assert (window.first_frame.value(), window.last_frame.value()) == (10, 40)
    assert window.slider._range is not None
    window._reset_range()
    assert window.slider._range is None


def test_an_empty_quick_look_offers_to_be_given_files(window, clips, tick):
    for row in window.rows:
        row.field.setText("")
    window._load()
    tick(0.3)
    assert window.empty_card.isVisible(), "nothing loaded and nothing offered"
    placed = window.put_files([str(clips["bottom"]), str(clips["top"]),
                               str(clips["lamels"])])
    assert placed == {"Bottom": str(clips["bottom"]), "Top": str(clips["top"]),
                      "Lamels": str(clips["lamels"])}, placed
    tick(0.3)
    assert not window.empty_card.isVisible()
    put_back(window, clips, tick)


def test_files_go_to_rows_by_their_names():
    import main
    got = main.assign_files(
        ["x/Show_top.mov", "x/Show_main.mov", "x/Show_lameli.mov",
         "x/music.wav", "x/motors.json", "x/other.mov"], {})
    assert got == {"Top": "x/Show_top.mov", "Bottom": "x/Show_main.mov",
                   "Lamels": "x/Show_lameli.mov", "Sound": "x/music.wav",
                   "Kinetic": "x/motors.json"}, got
    assert main.assign_files(["x/a.mov"], {"Top": "busy"}) == {"Bottom": "x/a.mov"}


def test_old_english_settings_still_open_on_what_they_say(window):
    import main
    main.choose_saved(window.backing, "Black")
    assert window.backing.currentData() == "Black"
    main.choose_saved(window.backing, "Калибровка")
    assert window.backing.currentData() == "Calibration"
    main.choose_saved(window.sync, "30 fps")
    assert window.sync.currentData() == 30.0
    main.choose_saved(window.sync, "60 fps")
    frame = window.row_for("Frame")
    main.choose_saved(frame.how, "Stretch")
    assert frame.how.currentData() == "Stretch"
    main.choose_saved(frame.how, "Fit")


def test_the_version_is_the_one_that_never_waits_for_a_share():
    import main
    assert main.APP_VERSION == "0.4.1"
