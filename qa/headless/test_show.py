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


# How long each motor file is, measured in TouchDesigner, where the show
# editor lives: the length it gives each file on its timeline.
TOUCHDESIGNER = {
    "7Sisters_060_KIN_v004_1_of_1.json": 18470,
    "EDINSTVO_ALL_SHOW.v3.2025.12.26_1_of_1.json": 29699,
    "MosMetro_5798 Frames.json": 4754,
    "BrendMT_1_of_2.json": 3755,
    "BrendMT_2_of_2.json": 1831,
    "Carshering_all_animation_5_v1_2026_07_24_1_of_1.json": 1809,
    "CharCity_kinetic.json": 2325,
    "CosmoDay.v3.2026.04.11_1_of_1.json": 1979,
    "Den_Detei_060_sc_V001_1_of_1.json": 613,
    "DenGoroda.v1.2026.09.01_1_of_1.json": 5033,
    "znaniya.v2.2026.09.01_1_of_1.json": 4707,
    "Moscow_trans.v1.2026.07.06_1_of_1.json": 5865,
    "Easter.v1.2026.04.03_1_of_1.json": 2087,
    "Examples.v1.2026.06.17_1_of_1.json": 1197,
    "Electrobus.v1.2026.08.26_1_of_1.json": 1991,
    "Rus_Day.v6.2026.06.09_1_of_1.json": 25305,
}
# Where the ones no show here points at are.
ELSEWHERE = [
    r"D:\Content\DNE-daily\DNE_daily_kinetic\EDINSTVO_ALL_SHOW.v3.2025.12.26_1_of_1.json",
    r"D:\Content\2026-dates\BDmetro\MosMetro_5798 Frames.json",
    r"D:\Content\2026-dates\Cosmo\CosmoDay.v3.2026.04.11_1_of_1.json",
    r"D:\Content\2026-dates\Den_Detei\Den_Detei_060_sc_V001_1_of_1.json",
    r"D:\Content\2026-dates\Easter\Easter.v1.2026.04.03_1_of_1.json",
    r"D:\Content\2026-dates\Electro\Examples.v1.2026.06.17_1_of_1.json",
]


@needs_shows
def test_a_motor_file_is_as_long_as_the_show_editor_counts_it(every_show):
    """To the end of its last command, not the exporter's range -- and
    nothing hatched past it, because nothing moves past it."""
    found = {}
    for one in every_show:
        for clip in one.clips:
            if clip.kind == "kinetic" and not clip.missing:
                found[clip.name] = (clip.frames, clip.tail)
    for path in ELSEWHERE:
        if Path(path).exists():
            found[Path(path).name] = showfile.motor_frames(path)
    measured = {name: found[name] for name in TOUCHDESIGNER if name in found}
    assert len(measured) >= 10, f"only {sorted(measured)} are on this machine"
    wrong = {name: (got, TOUCHDESIGNER[name])
             for name, (got, _) in measured.items() if got != TOUCHDESIGNER[name]}
    assert not wrong, f"not the show editor's length (ours, its): {wrong}"
    assert all(tail == 0 for _, tail in found.values())


@needs_shows
def test_a_show_puts_part_two_where_part_one_ends(every_show):
    """The show files themselves say the same: BrendMT's second part stands
    exactly its first part's length after it."""
    checked = 0
    for one in every_show:
        parts = {clip.name: clip for clip in one.clips if clip.kind == "kinetic"}
        first = parts.get("BrendMT_1_of_2.json")
        second = parts.get("BrendMT_2_of_2.json")
        if first is None or second is None or first.missing:
            continue
        assert second.tx - first.tx == first.frames == 3755
        checked += 1
    assert checked, "no show here has both parts of BrendMT on this machine"


def test_the_keys_are_the_frames_the_commands_begin_on():
    path = Path(r"D:\Content\2026-dates\BrendMT\BrendMT_2_of_2.json")
    if not path.exists():
        pytest.skip("the two-part show is not on this machine")
    keys = showfile.motor_keys(str(path))
    assert keys and list(keys) == sorted(set(keys))
    assert keys[0] == 4, keys[:5]
    assert keys[-1] < showfile.motor_frames(str(path))[0]
    assert showfile.motor_keys(str(path.with_name("no_such.json"))) == ()


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
