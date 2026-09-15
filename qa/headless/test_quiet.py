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
