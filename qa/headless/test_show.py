"""The show files, read the way the viewer reads them.

No window and no graphics card: this is the model, asked about the forty real
shows in D:\\Content\\_SHOW. Everything it checks was measured across those
files first -- the numbers below are theirs, not the schema's.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import show as showfile

SHOWS = Path(r"D:\Content\_SHOW")
FILES = sorted(SHOWS.glob("*.trix")) if SHOWS.exists() else []
RUSDAY = SHOWS / "2026-Daily-RusDay-Matreshka_Day-MuzeyTransporta-v001.trix"

needs_shows = pytest.mark.skipif(len(FILES) < 40,
                                 reason="the forty show files are not here")


@pytest.fixture(scope="module")
def every_show():
    return [showfile.read(one) for one in FILES]


@needs_shows
def test_every_show_reads(every_show):
    assert len(every_show) == len(FILES)
    for one, path in zip(every_show, FILES):
        assert one.length == 79200, f"{path.name}: {one.length} frames"
        assert one.clips, f"{path.name} came out empty"


@needs_shows
def test_the_wait_before_every_show_is_800_to_1099(every_show):
    """The looped black still, from its own frame to the first real clip."""
    for one, path in zip(every_show, FILES):
        assert one.loops == [(800, 1099)], f"{path.name}: {one.loops}"


@needs_shows
def test_the_backdrop_is_not_a_clip(every_show):
    """It is the viewer's own backing that shows; the show's is only a loop."""
    for one, path in zip(every_show, FILES):
        names = {clip.name.lower() for clip in one.clips}
        assert not names & set(showfile.BACKDROPS), (
            f"{path.name} still has its backdrop as a clip")


@needs_shows
def test_levels_are_rows_zero_to_two(every_show):
    for one, path in zip(every_show, FILES):
        for clip in one.clips:
            if clip.kind == "video":
                assert 0 <= clip.level <= 2, (
                    f"{path.name}: {clip.name} on level {clip.level}")


@needs_shows
def test_the_motors_keep_moving_past_their_range(every_show):
    """A pusher told to move two frames from the end takes 154 more."""
    tails = {}
    for one in every_show:
        for clip in one.clips:
            if clip.kind == "kinetic" and not clip.missing:
                tails[clip.name] = clip.tail
    assert tails.get("BrendMT_1_of_2.json") == 154, tails.get("BrendMT_1_of_2.json")
    assert tails.get("7Sisters_060_KIN_v004_1_of_1.json") == 125
    # And the clip is that much longer for it.
    brend = next(clip for one in every_show for clip in one.clips
                 if clip.name == "BrendMT_1_of_2.json")
    assert brend.last == brend.tx + brend.frames + 154


@needs_shows
def test_nothing_missing_stops_a_show_opening(every_show):
    """Files on drives that are not here are clips marked missing, not errors."""
    missing = [clip for one in every_show for clip in one.missing()]
    assert missing, "expected some of the forty shows to point off this machine"
    for clip in missing:
        assert clip.frames == 0 and clip.path


@pytest.mark.skipif(not RUSDAY.exists(), reason="the RusDay show is not here")
def test_the_crossfade_on_the_top_screen():
    """Frame 11742: the podium clip fading out, RusDay already under it.

    The one window in that show where two real movies live on one screen at
    once, and the frame the show editor was checked at: level 1 on show, two
    seconds of fade, 22 frames of it gone.
    """
    one = showfile.read(RUSDAY)
    live = [clip for clip in one.live_at(11742) if clip.row == "Top"]
    names = sorted((clip.level, clip.name) for clip in live)
    assert names == [(0, "RusDay_SHOW_Top_v02_2026-06-09.mov"),
                     (1, "kinetic_screen_out_-100px.mov")], names
    leaving = next(clip for clip in live if clip.level == 1)
    assert leaving.last == 11840                     # 1100 + 10800 - 60
    assert abs(leaving.opacity_at(11742) - (11840 - 11742) / 120) < 1e-9
    arriving = next(clip for clip in live if clip.level == 0)
    assert arriving.opacity_at(11742) == 1.0
    assert arriving.local(11742) == 24


def test_a_fade_is_a_straight_line_at_both_ends():
    clip = showfile.Clip(kind="video", row="Top", level=0, path="x.mov",
                         tx=100, frames=1000, fade_start=10, fade_end=-20)
    assert clip.opacity_at(99) == 0.0
    assert abs(clip.opacity_at(100) - 0.1) < 1e-9
    assert clip.opacity_at(109) == 1.0
    assert clip.opacity_at(500) == 1.0
    assert abs(clip.opacity_at(1099) - 1 / 20) < 1e-9
    assert clip.opacity_at(1100) == 0.0


def test_a_cropped_tail_ends_the_clip_early():
    clip = showfile.Clip(kind="video", row="Top", level=0, path="x.mov",
                         tx=0, frames=600, crop_end=-60)
    assert clip.last == 540 and clip.covers(539) and not clip.covers(540)


def test_the_quick_look_is_a_show_as_well(clips):
    """One file per screen, all from frame zero, as long as the longest."""
    one = showfile.single({"Top": str(clips["top"]),
                           "Bottom": str(clips["bottom"]),
                           "Lamels": ""})
    assert [clip.row for clip in one.clips] == ["Top", "Bottom"]
    assert all(clip.tx == 0 for clip in one.clips)
    assert one.length == 60 and one.loops == []
