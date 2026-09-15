"""Render in Flat: one file per screen, named after its source, at its size.

"Its size" is the screen's, not the source file's -- a strip is a screen laid
out flat, so a small stand-in clip still writes a file the size of the wall.
The wall's own numbers are written down here, because they are the outside
truth this feature answers to: 2500x1150 across the top, 4608x1584 along the
bottom, 536x110 of lamels. Anything the code works out from them -- the
halves, the quarters, the rounding down to a multiple of four -- is checked
against them rather than against itself.
"""
from __future__ import annotations

import time

import look
from conftest import PREVIEW
import media
from test_render import render

# The screens themselves, in their own pixels.
SCREENS = {"top": 2500, "bottom": 4608, "lamels": 536}
TALL = {"top": 1150, "bottom": 1584, "lamels": 110}


def down4(side: float) -> int:
    """Every encoder here wants an even side and hap wants four."""
    return max(4, int(side) // 4 * 4)


def expected(row: str, scale: float) -> tuple[int, int]:
    return down4(SCREENS[row] * scale), down4(TALL[row] * scale)


def flat_name(row: str, suffix: str) -> str:
    return media.CLIPS[row][0].replace(".mov", f"_flat{suffix}")


def clear_out(app, suffix: str) -> None:
    for row in media.CLIPS:
        (app.out / flat_name(row, suffix)).unlink(missing_ok=True)


def test_a_quarter_is_a_quarter_of_the_screen(app):
    app.choose("qa_mode", "Flat")
    app.choose("qa_size", "Четверть")
    app.choose("qa_format", "H.264 mp4")
    app.type_into("qa_frame_first", "0")
    app.type_into("qa_frame_last", "3")
    clear_out(app, ".mp4")

    assert "frames in" in render(app)

    for row in media.CLIPS:
        made = app.out / flat_name(row, ".mp4")
        assert made.exists(), f"no {made.name}"
        facts = look.probe(made)
        assert (facts["width"], facts["height"]) == expected(row, 0.25), (
            f"{made.name} came out {facts['width']}x{facts['height']}, "
            f"expected {expected(row, 0.25)}")


def test_native_is_the_screen_itself(app):
    """Not the size of the clip: a stand-in clip writes the wall's own size."""
    app.choose("qa_mode", "Flat")
    app.choose("qa_size", "Родное")
    app.choose("qa_format", "H.264 mp4")
    app.type_into("qa_frame_first", "0")
    app.type_into("qa_frame_last", "1")
    clear_out(app, ".mp4")
    assert "frames in" in render(app)
    for row, (source, source_wide, _) in media.CLIPS.items():
        facts = look.probe(app.out / flat_name(row, ".mp4"))
        assert (facts["width"], facts["height"]) == expected(row, 1.0), (
            f"{source} came out {facts['width']}x{facts['height']}, "
            f"the screen is {expected(row, 1.0)}")
        assert facts["width"] != source_wide, (
            "the file was written at the source's size, not the screen's")


def test_it_refuses_when_the_files_are_already_there(app):
    """The same run twice writes nothing the second time."""
    made = app.out / flat_name("top", ".mp4")
    assert made.exists(), "the test before this one should have written it"
    stamp = made.stat().st_mtime
    said = render(app, within=30)
    assert "exists" in said, f"it did not refuse; it said {said!r}"
    assert made.stat().st_mtime == stamp, "it wrote over the file anyway"


def test_an_alpha_format_carries_the_alpha(app):
    """A quarter of every source frame is transparent, and must stay so."""
    app.choose("qa_mode", "Flat")
    app.choose("qa_size", "Четверть")
    app.choose("qa_format", "ProRes 4444 alpha")
    app.type_into("qa_frame_first", "0")
    app.type_into("qa_frame_last", "1")
    clear_out(app, ".mov")
    assert "frames in" in render(app)

    made = app.out / flat_name("top", ".mov")
    facts = look.probe(made)
    assert "yuva" in facts["pix_fmt"], f"no alpha in it: {facts}"
    assert (facts["width"], facts["height"]) == expected("top", 0.25), facts
    share = look.clear_share(made)
    assert 0.15 < share < 0.35, (
        f"{share * 100:.0f}% of the frame is transparent; a quarter of the "
        "source is, and the strip is drawn without its black backing")


def test_the_backing_comes_back_after_an_alpha_render(app):
    """Writing an alpha takes the backing off the strips; it must go back on."""
    assert app.at("qa_behind").value == "Calibration", (
        f"the backing was left on {app.at('qa_behind').value!r}")


def test_png_alpha_writes_a_folder_of_stills(app):
    app.choose("qa_mode", "Flat")
    app.choose("qa_size", "Четверть")
    app.choose("qa_format", "PNG alpha")
    # At the grid's own rate, so that three frames of range are three stills.
    app.choose("qa_fps", "60 fps")
    app.type_into("qa_frame_first", "0")
    app.type_into("qa_frame_last", "2")
    for row in media.CLIPS:
        folder = app.out / flat_name(row, "")
        if folder.exists():
            for old in folder.glob("*.png"):
                old.unlink()
            folder.rmdir()
    assert "frames in" in render(app)

    folder = app.out / flat_name("top", "")
    assert folder.is_dir(), f"{folder} is not a folder of stills"
    stills = sorted(folder.glob("*.png"))
    assert len(stills) == 3, f"{len(stills)} stills, asked for 3"

    import numpy as np
    from PIL import Image
    first = Image.open(stills[0]).convert("RGBA")
    assert first.size == expected("top", 0.25), first.size
    alpha = np.asarray(first)[..., 3]
    share = float((alpha < 8).sum()) / alpha.size
    assert 0.15 < share < 0.35, f"{share * 100:.0f}% of the still is transparent"


def test_geometry_still_writes_the_whole_frame(app):
    """The Flat branch sits in front of the ordinary render; it must not eat it."""
    app.choose("qa_mode", PREVIEW)
    app.choose("qa_size", "1080x1920")
    app.choose("qa_format", "H.264 mp4")
    app.type_into("qa_frame_first", "0")
    app.type_into("qa_frame_last", "1")
    app.type_into("qa_out_name", "qa_after_flat.mp4")
    (app.out / "qa_after_flat.mp4").unlink(missing_ok=True)
    assert "frames in" in render(app)
    facts = look.probe(app.out / "qa_after_flat.mp4")
    assert (facts["width"], facts["height"]) == (1080, 1920), facts
