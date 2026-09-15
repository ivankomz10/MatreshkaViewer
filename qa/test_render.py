"""Writing a file out of Превью: the size asked for, the range asked for.

Short ranges on small clips, so that a test writes a whole file and then
looks at it. What comes back is read with ffprobe rather than believed off
the label, because the label has been right about a file that was wrong.
"""
from __future__ import annotations

import time

import pytest

import look
from conftest import PREVIEW

PREVIEW = PREVIEW        # about to be renamed; here for the failure demo


def set_range(app, first: int, last: int) -> None:
    app.type_into("qa_frame_first", str(first))
    app.type_into("qa_frame_last", str(last))


ENDINGS = ("frames in", "exists", "failed", "missing", "nothing")


def render(app, within: float = 180.0) -> str:
    """Press Render, wait for it to finish, and answer with what it said.

    The pressing and the waiting together, because the label keeps the last
    render's words until this one has some of its own: a test that only
    waited for words would read the words from the run before.
    """
    was = app.says("qa_eta")
    app.click("qa_render")

    def done(one):
        said = one.says("qa_eta")
        if said == was:
            return ""
        return said if any(word in said for word in ENDINGS) else ""

    return app.wait_until(done, "the render never finished", within=within)


def test_it_writes_the_size_it_was_asked_for(app):
    app.choose("qa_mode", PREVIEW)
    app.choose("qa_size", "1080x1920")
    app.choose("qa_format", "H.264 mp4")
    app.choose("qa_fps", "60 fps")          # the grid the range is counted on
    set_range(app, 0, 11)
    app.type_into("qa_out_name", "qa_render.mp4")
    (app.out / "qa_render.mp4").unlink(missing_ok=True)

    said = render(app)
    assert "frames in" in said, f"the render said {said!r}"

    made = app.out / "qa_render.mp4"
    assert made.exists(), f"nothing at {made}"
    facts = look.probe(made)
    assert (facts["width"], facts["height"]) == (1080, 1920), facts
    assert facts["frames"] == 12, f"asked for 12 frames, got {facts['frames']}"
    assert app.log_has("saved:", within=10)


def test_writing_at_half_the_grid_writes_half_the_frames(app):
    """The range is counted on Sync; what is written comes out at its own rate.

    Six frames of a sixty-a-second grid are a tenth of a second, and a tenth
    of a second at thirty is three frames. Worth pinning down: it is the one
    place where the number typed in and the number written differ on purpose.
    """
    app.choose("qa_sync", "60 fps")
    app.choose("qa_fps", "30 fps")
    set_range(app, 0, 5)
    app.type_into("qa_out_name", "qa_half_rate.mp4")
    (app.out / "qa_half_rate.mp4").unlink(missing_ok=True)
    assert "frames in" in render(app)
    facts = look.probe(app.out / "qa_half_rate.mp4")
    assert facts["frames"] == 3, f"six frames at half the rate gave {facts}"
    app.choose("qa_fps", "60 fps")


def test_it_refuses_to_write_over_a_file(app):
    """Nothing is ever overwritten; the name has to be changed first."""
    made = app.out / "qa_render.mp4"
    assert made.exists(), "the test before this one should have written it"
    stamp = made.stat().st_mtime
    said = render(app, within=30)
    assert "exists" in said, f"it did not refuse; it said {said!r}"
    assert made.stat().st_mtime == stamp, "it wrote over the file anyway"


def test_the_version_button_finds_the_next_name(app):
    app.type_into("qa_out_name", "qa_render.mp4")
    app.click("qa_bump")
    assert app.at("qa_out_name").value == "qa_render_v2.mp4", (
        f"the name became {app.at('qa_out_name').value!r}")
    app.click("qa_bump")
    assert app.at("qa_out_name").value == "qa_render_v3.mp4"


def test_a_snapshot_writes_one_frame(app):
    app.choose("qa_mode", PREVIEW)
    app.choose("qa_size", "1080x1920")
    folder = app.out / "snapshots"
    was = set(folder.glob("*.png")) if folder.exists() else set()
    app.click("qa_snapshot")
    app.wait_until(lambda one: "->" in one.says("qa_eta")
                   or "failed" in one.says("qa_eta"),
                   "the snapshot said nothing", within=60)
    said = app.says("qa_eta")
    assert "failed" not in said, said
    now = set(folder.glob("*.png"))
    fresh = now - was
    assert fresh, f"no new picture in {folder}"
    from PIL import Image
    picture = Image.open(fresh.pop())
    assert picture.size == (1080, 1920), f"the snapshot is {picture.size}"


def test_a_smaller_size_is_written_smaller(app):
    app.choose("qa_size", "Quarter 1024x1024")
    app.choose("qa_format", "H.264 mp4")
    set_range(app, 0, 1)
    app.type_into("qa_out_name", "qa_quarter.mp4")
    (app.out / "qa_quarter.mp4").unlink(missing_ok=True)
    said = render(app)
    assert "frames in" in said, said
    facts = look.probe(app.out / "qa_quarter.mp4")
    assert (facts["width"], facts["height"]) == (1024, 1024), facts
    app.choose("qa_size", "1080x1920")


def test_the_picture_comes_back_after_a_render(app):
    """The render takes the view to the whole frame; it must not stay off."""
    assert app.answering(), "the window is not answering after a render"
    assert app.at("qa_render").enabled, "the render button is still down"
    assert not app.at("qa_cancel").enabled, "the cancel button is still live"
    picture = app.picture_of("qa_canvas")
    assert look.spread(picture) > 6, "the picture is blank after a render"


@pytest.mark.xfail(reason="the hardware encoder loses the last of exactly six "
                          "frames; five, seven and everything longer are whole",
                   strict=False)
def test_a_six_frame_range_is_six_frames(app):
    """A range of six comes out one short, and only a range of six does.

    Found by these tests and reproduced without the window: 1080x1920 at
    sixty, six frames in, five in the file. Four, five, seven, eight, nine,
    eleven, twelve and thirty are all whole, and the same six through
    libx264 are whole, so it is the hardware encoder and not the writer.
    Left standing rather than worked around: if it is fixed, this passes and
    pytest says so.
    """
    app.choose("qa_mode", PREVIEW)
    app.choose("qa_size", "1080x1920")
    app.choose("qa_format", "H.264 mp4")
    app.choose("qa_fps", "60 fps")
    set_range(app, 0, 5)
    app.type_into("qa_out_name", "qa_six.mp4")
    (app.out / "qa_six.mp4").unlink(missing_ok=True)
    assert "frames in" in render(app)
    facts = look.probe(app.out / "qa_six.mp4")
    assert facts["frames"] == 6, (
        f"six frames were asked for and {facts['frames']} were written "
        f"({facts['codec']})")


def test_a_snapshot_is_the_frame_the_render_writes(app):
    """The same picture, to the pixel -- that is what a snapshot is for.

    Compared against a PNG sequence rather than against an mp4, because a
    lossless file makes the comparison exact: the two are either the same
    picture or they are not.

    This is the one that catches a squeezed snapshot. On screen the camera is
    opened out to fill the window, and a picture taken through that and then
    squeezed into the written shape is the whole building made narrow.
    """
    app.choose("qa_mode", PREVIEW)
    app.choose("qa_size", "1080x1920")
    app.click("qa_reset_view")
    set_range(app, 0, 0)

    app.type_into("qa_out_name", "qa_frame.png")
    made = app.out / "qa_frame.png"
    if made.is_dir():
        for old in made.glob("*.png"):
            old.unlink()
    else:
        made.unlink(missing_ok=True)
    app.choose("qa_format", "PNG sequence")
    assert "frames in" in render(app)
    # One frame of a sequence is written as the file itself rather than as a
    # folder with one still in it.
    written = (sorted(made.glob("*.png")) if made.is_dir()
               else [made] if made.exists() else [])
    assert written, f"the render wrote no stills: {list(app.out.iterdir())}"

    folder = app.out / "snapshots"
    was = set(folder.glob("*.png")) if folder.exists() else set()
    app.click("qa_snapshot")
    app.wait_until(lambda one: "->" in one.says("qa_eta")
                   or "failed" in one.says("qa_eta"),
                   "the snapshot said nothing", within=60)
    fresh = sorted(set(folder.glob("*.png")) - was)
    assert fresh, "the snapshot wrote nothing"

    from PIL import Image
    rendered = Image.open(written[0]).convert("RGB")
    snapped = Image.open(fresh[0]).convert("RGB")
    assert snapped.size == rendered.size == (1080, 1920), (
        f"the snapshot is {snapped.size}, the render {rendered.size}")
    apart = look.difference(snapped, rendered)
    assert apart < 2.0, (
        f"the snapshot and the render differ by {apart:.1f} per pixel -- the "
        "snapshot is not the frame the render writes")
