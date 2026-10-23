"""The show written back out as a .trix: the same file, byte for byte, when
nothing was changed, and only what was changed when something was.

Most of it needs no window and no show drive: a small show is made here with
every odd thing the forty files on site have in them -- a clip with no
transform, keys in another order, `level: true`, a sound with no level, a
`"version": "v01"`, empty perspective canvases, a looped backdrop. The real
shows are read and written too, wherever they are on this machine:
`D:\\Content\\_SHOW`, or the folder MATRESHKA_SHOWS names (on a machine that
sees the share only through a copy of it).
"""
from __future__ import annotations

import copy
import json
import os
import shutil
from pathlib import Path

import pytest

import draft as drafts
import show as showfile
import trixfile
from conftest import HOME

SHOWS = Path(os.environ.get("MATRESHKA_SHOWS") or r"D:\Content\_SHOW")
FILES = sorted(SHOWS.rglob("*.trix")) if SHOWS.exists() else []
DRAFTS = HOME / "drafts"

TRANSFORM = {"x": 0, "y": 0, "scale": 1, "rotation": 0, "flip_x": 0,
             "flip_y": 0, "opacity": 1.0, "seamless": 0}


def video(path, tx, level, **rest):
    entry = {"path": path, "tx": tx, "crop_start": 0, "crop_end": 0,
             "level": level, "fade_start": 0, "fade_end": 0, "loop": False,
             "loop_custom_range": [0, 100], "transform": dict(TRANSFORM)}
    entry.update(rest)
    return entry


ODD = {
    "video": {
        "Tiles-pixels": {
            "1": video("D:/Content/black.png", 800, 3, loop=True),
            "2": video("D:/Content/A/intro_top.mov", 1100, 1, crop_end=-60,
                       fade_end=-120),
            # Keys in the other order the files have, and no transform.
            "7": {"path": "D:/Content/A/song_top.mov", "tx": 9000,
                  "crop_start": 0, "crop_end": 0, "fade_start": 0,
                  "fade_end": -120, "level": 0, "loop": False,
                  "loop_custom_range": [0, 100]},
        },
        "Tiles-perspective": {},
        "Scene-pixels": {
            "3": video("D:/Content/black.png", 800, 3, loop=True),
            "4": video("D:/Content/A/intro_main.mov", 1100, True),
        },
        "Scene-perspective": {},
        "Lamel-pixels": {
            "5": video("D:/Content/black-lameli.png", 800, 3, loop=True),
            "6": dict(video("D:/Content/A/intro_lamel.mov", 1100, 1),
                      transform=dict(TRANSFORM, opacity=1)),
        },
    },
    "audio": {"8": {"path": "D:/Content/A/intro.wav", "tx": 1100},
              "9": {"path": "D:/Content/A/song.wav", "tx": 9000, "level": 1}},
    "cue": {"10": {"frame": 1101, "channel": 44, "universe": 2, "value": 255,
                   "level": 0}},
    "jsons": {"11": {"path": "D:/Content/A/motors_1_of_1.json", "tx": 700,
                     "prepare_enabled": False, "prepare_offset": 0,
                     "prepare_interval": 0}},
    "project": {"length": 79200, "name": "Odd-Show-v001", "version": "v01"},
}


@pytest.fixture
def odd(tmp_path):
    """The odd show, as the show editor would have written it."""
    where = tmp_path / "Odd-Show-v001.trix"
    where.write_bytes(json.dumps(ODD).encode("ascii"))
    return where


def written(show) -> dict:
    return json.loads(trixfile.dumps(show))


def clip_from(show, origin):
    return next(one for one in show.clips if one.origin == origin)


# -- nothing changed: the same file ----------------------------------------------

def test_a_show_read_and_written_is_the_same_file(odd):
    assert trixfile.dumps(showfile.read(odd)).encode("ascii") == odd.read_bytes()


@pytest.mark.skipif(not FILES, reason="no show files on this machine")
@pytest.mark.parametrize("path", FILES, ids=lambda one: one.name)
def test_every_show_on_this_machine_comes_back_the_same(path):
    again = trixfile.dumps(showfile.read(path)).encode("ascii")
    assert again == path.read_bytes()


def test_the_same_through_a_draft(odd, tmp_path):
    """Saved into a draft and opened from it -- after the program was
    closed, say -- the show still writes the same file."""
    show = showfile.read(odd)
    keep = drafts.Draft(tmp_path / "drafts" / "odd.json", str(odd),
                        drafts.stamp(str(odd)))
    keep.save(show)
    _, again = drafts.Draft.load(keep.where)
    assert trixfile.dumps(again).encode("ascii") == odd.read_bytes()


def test_a_draft_from_before_finds_its_file_again(odd, tmp_path):
    """A draft begun before drafts kept their show file: the file is read
    again and the clips matched to their entries by id."""
    show = showfile.read(odd)
    keep = drafts.Draft(tmp_path / "drafts" / "odd.json", str(odd),
                        drafts.stamp(str(odd)))
    keep.save(show)
    body = json.loads(keep.where.read_text("utf-8"))
    body.pop("source_raw")
    for one in body["show"]["clips"]:
        one.pop("origin")
    keep.where.write_text(json.dumps(body), "utf-8")
    _, again = drafts.Draft.load(keep.where)
    assert trixfile.dumps(again).encode("ascii") == odd.read_bytes()


def test_the_reader_takes_a_version_that_is_not_a_number(odd):
    assert showfile.read(odd).version == 1


# -- something changed: that, and nothing else ------------------------------------

def test_a_moved_clip_changes_its_tx_and_nothing_else(odd):
    show = showfile.read(odd)
    clip_from(show, "Tiles-pixels:7").tx = 9300
    out = written(show)
    expected = copy.deepcopy(ODD)
    expected["video"]["Tiles-pixels"]["7"]["tx"] = 9300
    assert out == expected
    # The keys stay in their own order, the missing transform stays missing.
    assert list(out["video"]["Tiles-pixels"]["7"]) == \
        list(ODD["video"]["Tiles-pixels"]["7"])


def test_a_level_written_as_true_stays_true_until_it_is_changed(odd):
    show = showfile.read(odd)
    clip = clip_from(show, "Scene-pixels:4")
    assert clip.level == 1
    clip.fade_start = 60
    out = written(show)["video"]["Scene-pixels"]["4"]
    assert out["level"] is True and out["fade_start"] == 60
    clip.level = 2
    assert written(show)["video"]["Scene-pixels"]["4"]["level"] == 2


def test_a_sound_with_no_level_gets_one_only_when_it_is_given_one(odd):
    show = showfile.read(odd)
    clip = clip_from(show, "audio:8")
    clip.tx = 1200
    assert written(show)["audio"]["8"] == {"path": "D:/Content/A/intro.wav",
                                           "tx": 1200}
    clip.level = 1
    assert written(show)["audio"]["8"]["level"] == 1


def test_every_field_the_editor_has_goes_into_the_file(odd):
    show = showfile.read(odd)
    clip = clip_from(show, "Tiles-pixels:2")
    clip.crop_start, clip.crop_end = 30, -90
    clip.fade_start, clip.fade_end = 45, -60
    clip.level = 2
    cue = clip_from(show, "cue:10")
    cue.tx, cue.universe, cue.channel = 2000, 1, 7
    out = written(show)
    entry = out["video"]["Tiles-pixels"]["2"]
    assert (entry["crop_start"], entry["crop_end"], entry["fade_start"],
            entry["fade_end"], entry["level"]) == (30, -90, 45, -60, 2)
    assert out["cue"]["10"] == {"frame": 2000, "channel": 7, "universe": 1,
                                "value": 255, "level": 0}


def test_a_deleted_clip_is_gone_and_the_backdrops_stay(odd):
    show = showfile.read(odd)
    show.clips.remove(clip_from(show, "Tiles-pixels:2"))
    show.clips.remove(clip_from(show, "jsons:11"))
    out = written(show)
    assert list(out["video"]["Tiles-pixels"]) == ["1", "7"]
    assert out["jsons"] == {}
    assert out["video"]["Scene-pixels"]["3"]["path"] == "D:/Content/black.png"


def test_new_clips_take_the_next_ids_in_the_show_editors_shape(odd):
    show = showfile.read(odd)
    later = drafts.next_ident(show)
    show.clips.append(showfile.Clip(
        kind="video", row="Bottom", level=1, path=r"D:\Content\B\new_main.mov",
        tx=20000, frames=600, ident=later))
    show.clips.append(showfile.Clip(kind="cue", row="Cue", level=0, path="",
                                    tx=20001, ident=later + 1, universe=2,
                                    channel=45, value=255))
    show.clips.append(showfile.Clip(kind="kinetic", row="Kinetic", level=0,
                                    path=r"D:\Content\B\m_1_of_1.json",
                                    tx=19900, ident=later + 2))
    out = written(show)
    # After every id the file has, the backdrops' included.
    assert list(out["video"]["Scene-pixels"]) == ["3", "4", "12"]
    assert out["video"]["Scene-pixels"]["12"] == video(
        "D:/Content/B/new_main.mov", 20000, 1)
    assert list(out["video"]["Scene-pixels"]["12"]) == list(video("", 0, 0))
    assert out["cue"]["13"] == {"frame": 20001, "channel": 45, "universe": 2,
                                "value": 255, "level": 0}
    assert out["jsons"]["14"] == {"path": "D:/Content/B/m_1_of_1.json",
                                  "tx": 19900, "prepare_enabled": False,
                                  "prepare_offset": 0, "prepare_interval": 0}
    # And the file is still the show editor's: one line, nothing after it.
    text = trixfile.dumps(show)
    assert "\n" not in text and text == json.dumps(json.loads(text))


def test_a_new_name_and_length_go_into_the_project(odd):
    show = showfile.read(odd)
    show.name, show.length = "Odd-Show-v002", 80000
    assert written(show)["project"] == {"length": 80000,
                                        "name": "Odd-Show-v002",
                                        "version": "v01"}


def test_a_show_that_never_was_a_file_is_written_whole():
    show = showfile.Show(name="Fresh", length=showfile.LENGTH)
    show.clips.append(showfile.Clip(kind="audio", row="Sound", level=0,
                                    path="D:/Content/x.wav", tx=10, ident=1))
    assert written(show) == {
        "video": {"Tiles-pixels": {}, "Scene-pixels": {}, "Lamel-pixels": {}},
        "audio": {"1": {"path": "D:/Content/x.wav", "tx": 10, "level": 0}},
        "cue": {}, "jsons": {},
        "project": {"length": 79200, "name": "Fresh", "version": 1}}


def test_moved_loops_are_said_not_written(odd):
    show = showfile.read(odd)
    file_loops = list(show.loops)
    assert trixfile.notes(show, file_loops) == []
    show.loops.append((20000, 20300))
    assert trixfile.notes(show, file_loops)
    assert trixfile.dumps(show).encode("ascii") == odd.read_bytes()


# -- where it goes ----------------------------------------------------------------

def test_the_next_version_is_beside_the_show(tmp_path):
    one = tmp_path / "Show-v001.trix"
    assert trixfile.next_version(one).name == "Show-v002.trix"
    (tmp_path / "Show-v002.trix").write_text("{}")
    assert trixfile.next_version(one).name == "Show-v003.trix"
    assert trixfile.next_version(tmp_path / "NewYearShow_v024.trix").name \
        == "NewYearShow_v025.trix"
    assert trixfile.next_version(tmp_path / "RusDay_2_times.trix").name \
        == "RusDay_2_times-v002.trix"


def test_it_never_writes_over_the_show_it_came_from(odd):
    show = showfile.read(odd)
    before = odd.read_bytes()
    clip_from(show, "Tiles-pixels:7").tx = 1
    with pytest.raises(trixfile.ExportError):
        trixfile.export(show, odd, odd)
    assert odd.read_bytes() == before
    beside = trixfile.export(show, trixfile.next_version(odd), odd)
    assert beside.name == "Odd-Show-v002.trix"
    assert json.loads(beside.read_text("ascii"))["video"]["Tiles-pixels"]["7"]["tx"] == 1
    assert not list(odd.parent.glob("*.writing"))


# -- in the window ----------------------------------------------------------------

def test_the_window_exports_what_its_editor_changed(window, tick, odd):
    """Opened, exported as it is, then a field changed in the editor and
    exported again: the first is the file, the second the file with that."""
    shutil.rmtree(DRAFTS, ignore_errors=True)
    window.ask_resume = lambda found: "draft"
    try:
        window.open_show_file(str(odd))
        tick(0.3)
        assert window.show_open is not None
        same = window.export_show_file(str(odd.with_name("as-is.trix")))
        assert same.read_bytes() == odd.read_bytes()
        assert window.export_show_file(str(odd)) is None
        window._set_editing(True)
        tick(0.1)
        clip = next(one for one in window.show_open.clips
                    if one.origin == "Tiles-pixels:7")
        window.show_view.set_field(clip, "fade_end", -240)
        tick(0.1)
        changed = window.export_show_file(str(odd.with_name("edited.trix")))
        expected = copy.deepcopy(ODD)
        expected["video"]["Tiles-pixels"]["7"]["fade_end"] = -240
        assert json.loads(changed.read_text("ascii")) == expected
    finally:
        window._set_editing(False)
        window.draft = None
        window.trix_path = ""
        window.history.clear()
        window._set_level("view")
        shutil.rmtree(DRAFTS, ignore_errors=True)
