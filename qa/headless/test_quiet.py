"""Everything that can be asked without a hand on the mouse.

Same questions as the driven suite where they overlap -- the lists, the
sizes, the names, the refusals, the snapshot -- asked by calling what the
buttons call. Run this while somebody is working on the machine; run the
other one when nobody is.
"""
from __future__ import annotations

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


# -- the chain of motor files ------------------------------------------------

BLOCKS = r"D:\Content\Dostizhenia\JSON"
PARTS = r"D:\Content\2026-dates\BrendMT\BrendMT_1_of_2.json"


def test_a_chain_of_blocks_plays_end_to_end(window, tick):
    """Seven blocks of a programme are one timeline, marked at every join."""
    from pathlib import Path
    import pytest
    blocks = sorted(Path(BLOCKS).glob("*.json"))
    if len(blocks) < 3:
        pytest.skip("the programme's blocks are not on this machine")

    window.mode.setCurrentText(PREVIEW)
    window._fill_chain("Kinetic", [(str(one), 1) for one in blocks])
    window._load()
    wait_for(tick, lambda: window.motors is not None,
             "the chain never loaded", within=60)

    assert len(window.kinetic_rows()) == len(blocks), (
        f"{len(window.kinetic_rows())} rows for {len(blocks)} files")
    assert len(window.motors.parts) == len(blocks)
    # Every join lands where the part before it ends, and the clock is the sum.
    at = 0
    for part in window.motors.parts:
        assert part.first == at, f"{part.name} starts at {part.first}, not {at}"
        at += part.length
    assert window.motors.frames == at + 1
    assert abs(window.clock.duration - at / window.motors.fps) < 0.05
    assert len(window.slider._marks) == len(blocks) - 1, "marks missing"


def test_nothing_jumps_where_two_files_meet(window, tick):
    """The exporter cuts a movement in half; the chain has to finish it."""
    import numpy as np
    from pathlib import Path
    import pytest
    if not Path(PARTS).exists():
        pytest.skip("the two-part show is not on this machine")
    window._fill_chain("Kinetic", [(PARTS, 1)])
    window._load()
    wait_for(tick, lambda: window.motors is not None and
             len(window.motors.parts) == 2,
             "the second part did not come with the first", within=60)
    motors = window.motors
    join = motors.parts[1].first
    for name, array in (("tilt", motors.tilt), ("pusher", motors.pusher),
                        ("jack", motors.jack)):
        step = float(np.abs(array[..., join] - array[..., join - 1]).max())
        # A frame of ordinary movement, not a jump: the fastest thing in
        # these files crosses its whole range in about a second.
        assert step < 0.02, (
            f"{name} jumps {step:.4f} at the join -- the movement the "
            "exporter cut in half was not carried across")


def test_a_lone_part_brings_its_siblings(window, tick):
    from pathlib import Path
    import pytest
    if not Path(PARTS).exists():
        pytest.skip("the two-part show is not on this machine")
    window._fill_chain("Kinetic", [(PARTS, 1)])
    window._load()
    wait_for(tick, lambda: window.motors is not None, "nothing loaded", within=60)
    names = [Path(r.field.text()).name for r in window.kinetic_rows()
             if r.field.text().strip()]
    assert names == ["BrendMT_1_of_2.json", "BrendMT_2_of_2.json"], names


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
    assert window.linked.isVisible(), "the link did not come back with the rows"

    window.sources_head.click()
    window.sources_head.click()
    tick(0.2)
    assert window.sources_open, "two more clicks left it somewhere else"


def test_the_rows_fold_away(window, tick):
    """The panel is why a chain of seven does not cost the picture its height."""
    window._fold_sources(True)
    tick(0.2)
    assert window.sources_open and window.linked.isVisible()
    tall = window.sources_body.sizeHint().height()
    window._fold_sources(False)
    tick(0.2)
    assert not window.sources_open
    assert not window.linked.isVisible(), "the link stayed over a folded panel"
    # The folded line has to say what is loaded -- that is the whole reason
    # it is allowed to hide the rows. Asked of whatever the rows hold at this
    # point rather than of one name, so the test does not depend on which
    # test ran before it.
    line = window.sources_head.text()
    for row in window.rows:
        if row.field.text().strip() and not row.motors:
            assert row.title in line, (
                f"the folded line does not name {row.title}: {line!r}")
    assert tall > 100, f"the rows are only {tall} px; folding buys nothing"
    window._fold_sources(True)
    tick(0.2)


def test_the_link_sits_between_the_two_rows_it_ties(window, tick):
    """It is placed by hand, so where it lands is worth measuring.

    Measured in the coordinates of its own parent, which is the panel of
    rows: `move` is relative to the parent, and computing the place against
    the window instead put the button a header's height too low and the
    layout's margin too far left.
    """
    window._fold_sources(True)
    tick(0.3)
    window._lay_link()
    tick(0.2)

    top, bottom = window.head_row("Top"), window.head_row("Bottom")
    holder = window.linked.parentWidget()
    from PySide6.QtCore import QPoint
    link = window.linked.geometry()
    middle = link.center()

    ends = top.mapTo(holder, QPoint(0, top.height())).y()
    starts = bottom.mapTo(holder, QPoint(0, 0)).y()
    assert ends - 4 <= middle.y() <= starts + 4, (
        f"the link's middle is at y={middle.y()}, and the two rows it ties "
        f"run from {ends} to {starts}")

    column = top.link_gap.geometry()
    left = top.mapTo(holder, column.topLeft()).x()
    assert left - 2 <= link.left() and \
        link.left() + link.width() <= left + column.width() + 2, (
        f"the link at x={link.left()}..{link.left() + link.width()} is "
        f"outside its column at {left}..{left + column.width()}")


# -- chains on the screens, and loops ----------------------------------------

def one_clip(window, group: str, clips, which: str, times: int = 1) -> None:
    """Put a single file in a chain, with nothing after it."""
    window._fill_chain(group, [(str(clips[which]), times)])


def no_motors(window) -> None:
    """Empty the kinetic chain, so the clock is the screens' own length.

    These tests share one window with every other test in the file, and a
    programme left loaded by one of them is longer than anything made here.
    """
    window._fill_chain("Kinetic", [("", 1)])


def stream_of(window, group: str):
    """The stream feeding one screen, whatever it is made of."""
    row = window.head_row(group)
    for index, feeds in enumerate(window.feeding):
        if feeds == row.screen and index < len(window.streams):
            return window.streams[index]
    return None


def test_two_files_on_one_screen_play_one_after_another(window, clips, tick):
    """A screen is a run of files now, and the clock is the sum of them."""
    window.mode.setCurrentText(PREVIEW)
    no_motors(window)
    window._fill_chain("Top", [(str(clips["top"]), 1),
                               (str(clips["top"]), 1)])
    window._load()
    tick(0.5)

    chained = stream_of(window, "Top")
    assert hasattr(chained, "links"), "two files did not make a chain"
    assert len(chained.links) == 2
    # Each clip is a second long, so the pair is two -- and the timeline runs
    # to the longest thing loaded, which is now this rather than the others.
    assert abs(chained.duration - 2.0) < 0.05, chained.describe()
    assert abs(window.clock.duration - 2.0) < 0.05
    assert any(abs(at - 1.0) < 0.05 for at, _ in window.slider._marks), (
        f"no mark where the two files meet: {window.slider._marks}")

    # And the pictures actually cross the join: the frame handed out at two
    # thirds of the way through is past the first file's last one.
    window._move(0.2)
    tick(0.4)
    early = window.held[window.streams.index(chained)]
    window._move(1.5)
    tick(0.4)
    late = window.held[window.streams.index(chained)]
    assert early is not None and late is not None, "no frames came out"
    assert late.index > early.index, (
        f"the chain went backwards at the join: {early.index} then {late.index}")

    one_clip(window, "Top", clips, "top")
    window._load()
    tick(0.4)


def test_a_loop_plays_the_same_file_that_many_times(window, clips, tick):
    """Thirty seconds and a five second loop is the whole point of the count."""
    window.mode.setCurrentText(PREVIEW)
    window.looping.setChecked(True)
    no_motors(window)
    one_clip(window, "Top", clips, "top", times=3)
    window._load()
    tick(0.5)

    chained = stream_of(window, "Top")
    assert abs(chained.duration - 3.0) < 0.05, chained.describe()
    assert abs(window.clock.duration - 3.0) < 0.05
    # A mark at the top of every pass but the first.
    passes = [at for at, _ in window.slider._marks if at < 3.0]
    assert len(passes) >= 2, f"the repeats are not marked: {window.slider._marks}"

    # The same frame of the file comes back round on the second pass.
    window._move(0.5)
    tick(0.4)
    first = window.held[window.streams.index(chained)]
    window._move(1.5)
    tick(0.4)
    second = window.held[window.streams.index(chained)]
    assert first is not None and second is not None
    assert second.index > first.index, "the second pass did not move the clock on"

    one_clip(window, "Top", clips, "top")
    window.looping.setChecked(False)
    window._load()
    tick(0.4)


def test_the_surface_is_remade_when_the_blocks_differ(window, clips, tick):
    """Blocks of a show need not agree on size or codec; the screen follows."""
    window.mode.setCurrentText(PREVIEW)
    window._fill_chain("Top", [(str(clips["top"]), 1),
                               (str(clips["bottom"]), 1)])
    window._load()
    tick(0.5)

    chained = stream_of(window, "Top")
    at = window.streams.index(chained)
    assert (window.screens[at].width, window.screens[at].height) == (256, 120)

    window._move(1.5)
    tick(0.6)
    assert (window.screens[at].width, window.screens[at].height) == (464, 160), (
        "the surface kept the first block's size after the join")
    assert "the surface was remade" in logfile_text()

    one_clip(window, "Top", clips, "top")
    window._load()
    tick(0.4)


def test_a_chain_renders_across_its_join(window, clips, tick):
    """The writer asks for exact frames, and a join is where it would miss."""
    window.mode.setCurrentText(PREVIEW)
    window._fill_chain("Top", [(str(clips["top"]), 1),
                               (str(clips["top"]), 1)])
    window._load()
    tick(0.5)
    window.size_choice.setCurrentText("1080x1920")
    window.format_choice.setCurrentText("H.264 mp4")
    window.fps_choice.setCurrentText("60 fps")
    window.first_frame.setValue(55)
    window.last_frame.setValue(66)
    window.out_name.setText("quiet_chain.mp4")
    (out(window) / "quiet_chain.mp4").unlink(missing_ok=True)
    tick(0.3)

    said = render_and_wait(window, tick)
    assert "frames in" in said, said
    facts = look.probe(out(window) / "quiet_chain.mp4")
    assert facts["frames"] == 12, facts

    one_clip(window, "Top", clips, "top")
    window._load()
    tick(0.4)


def test_the_count_spreads_down_the_column(window, clips, tick):
    """A five second insert is the same insert on every screen and the motors."""
    window.looping.setChecked(True)
    for group in ("Top", "Bottom", "Lamels"):
        which = {"Top": "top", "Bottom": "bottom", "Lamels": "lamels"}[group]
        window._fill_chain(group, [(str(clips[which]), 1),
                                   (str(clips[which]), 1)])
    tick(0.2)
    was = {group: len(window.chain_rows(group)) for group in window.CHAINS}

    second = window.chain_rows("Top")[1]
    second.repeat.setValue(4)
    window._spread(second)
    tick(0.2)
    for group in ("Bottom", "Lamels"):
        assert window.chain_rows(group)[1].times == 4, (
            f"{group} did not take the count")
    # Never up the column it came from, and never off the end of a shorter
    # one: a chain with no row in that place is left the length it was.
    assert window.chain_rows("Top")[0].times == 1
    assert {group: len(window.chain_rows(group)) for group in window.CHAINS} \
        == was, "spreading a count made rows"

    window.looping.setChecked(False)
    for group in ("Top", "Bottom", "Lamels"):
        which = {"Top": "top", "Bottom": "bottom", "Lamels": "lamels"}[group]
        window._fill_chain(group, [(str(clips[which]), 1)])
    window._load()
    tick(0.4)


def test_each_heading_folds_on_its_own(window, tick):
    """Twenty-one fields is the picture's whole height; one screen at a time."""
    window._fold_sources(True)
    for group in window.groups.values():
        group.fold(True)
    tick(0.3)

    window.groups["Top"].head.click()
    tick(0.3)
    assert not window.groups["Top"].open, "one click did not fold the heading"
    assert not window.groups["Top"].body.isVisible()
    for other in ("Bottom", "Lamels", "Sound", "Kinetic"):
        assert window.groups[other].open, f"{other} folded with Top"
        assert window.groups[other].body.isVisible()
    # The heading has to say what it is hiding -- that is what earns the fold.
    assert "Top" in window.groups["Top"].head.text()
    assert window.sources_open, "the whole panel went with one heading"

    window.groups["Top"].head.click()
    tick(0.3)
    assert window.groups["Top"].open, "the second click did not unfold it"


def test_a_chain_and_its_counts_are_written_down(window, clips, tick):
    """What is opened next time: every file of every chain, and every count."""
    window.looping.setChecked(True)
    window._fill_chain("Top", [(str(clips["top"]), 1),
                               (str(clips["top"]), 5)])
    window.groups["Lamels"].fold(False)
    tick(0.2)

    kept = window._settings_now()["rows"]["Top"]
    assert kept["files"] == [str(clips["top"]), str(clips["top"])], kept
    assert kept["repeats"] == [1, 5], kept
    # And the first of them under the old key, so a settings file written here
    # still opens in a version that knew one row per screen.
    assert kept["file"] == str(clips["top"])
    folds = window._settings_now()["groups_open"]
    assert folds["Lamels"] is False and folds["Top"] is True, folds
    assert window._settings_now()["loops"] is True

    window.groups["Lamels"].fold(True)
    window.looping.setChecked(False)
    one_clip(window, "Top", clips, "top")
    window._load()
    tick(0.4)


def test_the_motors_loop_with_the_picture(window, tick):
    """A looped block moves the screens the same way on every pass."""
    import numpy as np
    from pathlib import Path
    import pytest
    if not Path(PARTS).exists():
        pytest.skip("the two-part show is not on this machine")

    window.looping.setChecked(True)
    window._fill_chain("Kinetic", [(PARTS, 1)])
    window._load()
    wait_for(tick, lambda: window.motors is not None and
             len(window.motors.parts) == 2, "the parts did not load", within=60)
    plain = window.motors.frames

    window.chain_rows("Kinetic")[0].repeat.setValue(2)
    window._load()
    wait_for(tick, lambda: window.motors is not None and
             window.motors.parts[0].repeats == 2, "the loop did not take",
             within=60)
    motors = window.motors
    over = motors.parts[0].length
    assert motors.frames == plain + over, (
        f"{motors.frames} frames for a part played twice, not {plain + over}")
    assert np.allclose(motors.tilt[..., :over], motors.tilt[..., over:2 * over]), (
        "the second pass is not the first one again")

    window.chain_rows("Kinetic")[0].repeat.setValue(1)
    window.looping.setChecked(False)
    window._fill_chain("Kinetic", [("", 1)])
    window._load()
    tick(0.4)


def test_the_counters_are_not_there_until_they_are_asked_for(window, clips, tick):
    """A column of boxes reading "× 1" is four more things to wonder about."""
    window.looping.setChecked(False)
    no_motors(window)
    window._fill_chain("Top", [(str(clips["top"]), 1),
                               (str(clips["top"]), 1)])
    window._load()
    tick(0.4)
    for row in window.chain_rows("Top"):
        assert row.repeat is not None, "the counter was never built"
        assert not row.repeat.isVisible(), "the counter is on show with loops off"
        assert not row.spread_button.isVisible()

    # And a number left behind in a hidden box does not lengthen the piece.
    window.chain_rows("Top")[1].repeat.setValue(4)
    window._load()
    tick(0.4)
    assert abs(window.clock.duration - 2.0) < 0.05, (
        f"a hidden count made the timeline {window.clock.duration:.2f} s")

    window.looping.setChecked(True)
    tick(0.4)
    for row in window.chain_rows("Top"):
        assert row.repeat.isVisible(), "the counter did not come back"
    # The number was kept while it was away, and now it counts.
    assert window.chain_rows("Top")[1].times == 4
    assert abs(window.clock.duration - 5.0) < 0.05, (
        f"the kept count is not being played: {window.clock.duration:.2f} s")

    window.chain_rows("Top")[1].repeat.setValue(1)
    window.looping.setChecked(False)
    window._fill_chain("Top", [(str(clips["top"]), 1)])
    window._load()
    tick(0.4)
