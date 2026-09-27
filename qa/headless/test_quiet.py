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
from conftest import PREVIEW, render_and_wait, wait_for

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
    window.fps_choice.setCurrentText("60 fps")
    window.first_frame.setValue(0)
    window.last_frame.setValue(11)
    window.out_name.setText("quiet_render.mp4")
    (out(window) / "quiet_render.mp4").unlink(missing_ok=True)
    tick(0.3)

    said = render_and_wait(window, tick)
    assert "frames in" in said, said
    facts = look.probe(out(window) / "quiet_render.mp4")
    assert (facts["width"], facts["height"]) == (1080, 1920), facts
    assert facts["frames"] == 12, facts


def test_it_refuses_to_write_over_a_file(window, tick):
    made = out(window) / "quiet_render.mp4"
    stamp = made.stat().st_mtime
    said = render_and_wait(window, tick, within=30)
    assert "exists" in said, said
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
    assert "frames in" in render_and_wait(window, tick)
    written = (sorted(made.glob("*.png")) if made.is_dir()
               else [made] if made.exists() else [])
    assert written, "the render wrote no still"

    folder = out(window) / "snapshots"
    was = set(folder.glob("*.png")) if folder.exists() else set()
    window._snapshot()
    fresh = wait_for(tick,
                     lambda: sorted(set(folder.glob("*.png")) - was),
                     "the snapshot wrote nothing", within=60)
    assert "failed" not in window.eta.text(), window.eta.text()

    from PIL import Image
    rendered = Image.open(written[0]).convert("RGB")
    snapped = Image.open(fresh[0]).convert("RGB")
    assert snapped.size == rendered.size == (1080, 1920), (
        f"snapshot {snapped.size}, render {rendered.size}")
    apart = look.difference(snapped, rendered)
    assert apart < 2.0, (
        f"the snapshot and the render differ by {apart:.1f} per pixel -- the "
        "snapshot is not the frame the render writes")


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
    window.fps_choice.setCurrentText("60 fps")
    window.first_frame.setValue(0)
    window.last_frame.setValue(3)
    tick(0.4)
    for row in media.CLIPS:
        (out(window) / media.CLIPS[row][0].replace(".mov", "_flat.mp4")).unlink(
            missing_ok=True)

    assert "frames in" in render_and_wait(window, tick)
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

    assert "frames in" in render_and_wait(window, tick)
    facts = look.probe(made)
    assert "yuva" in facts["pix_fmt"], facts
    share = look.clear_share(made)
    assert 0.15 < share < 0.35, f"{share * 100:.0f}% transparent"
    assert window.backing.currentText() == "Calibration", (
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
    assert "at_all.mov" in said and "not there" in said, said
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
    assert "+1" in window.sources_head.text()
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


def test_the_rows_fold_away(window, clips, tick):
    """One block, as before the timeline, and its line says what is in it."""
    put_back(window, clips, tick)
    window._fold_sources(True)
    tick(0.2)
    tall = window.sources_body.sizeHint().height()
    window._fold_sources(False)
    tick(0.2)
    assert not window.sources_open
    assert not window.sources_body.isVisible()
    line = window.sources_head.text()
    for row in window.rows:
        if row.field.text().strip():
            assert row.title in line, (
                f"the folded line does not name {row.title}: {line!r}")
    assert tall > 100, f"the rows are only {tall} px; folding buys nothing"
    window._fold_sources(True)
    tick(0.2)


def test_the_link_stands_in_the_panel_heading(window, tick):
    """A widget in a layout, beside the fold and not inside it.

    It used to float over the rows, placed by hand, and that cost three bugs.
    Now the layout owns it: it is in the heading's strip, beside the button
    that folds the panel -- a button within that button would be a click
    landing on the wrong one -- and it stays on show while the rows are
    folded, because it goes on tying the sliders whether or not anybody can
    see them.
    """
    window._fold_sources(True)
    tick(0.2)
    strip = window.sources_head.parentWidget()
    assert strip.objectName() == "qa_sources_strip"
    assert strip.isAncestorOf(window.linked), "the link is not in the heading"
    assert not window.sources_body.isAncestorOf(window.linked)
    assert not window.sources_head.isAncestorOf(window.linked)

    window._fold_sources(False)
    tick(0.2)
    assert window.linked.isVisible(), "the link went away with the rows"
    window._fold_sources(True)
    tick(0.2)


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
