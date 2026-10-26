"""A show out as a new .trix, without a window.

The measure is the show editor's own files: every show in D:\\Content\\_SHOW
is read, written out as its next version into the test's own folder, and
compared with the file it came from -- unchanged, to the byte; edited, with
nothing changed but what was edited. Not one of those files is written:
each is checked afterwards to be what it was.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

import draft as drafts
import show as showfile
import trix_export

SHOWS = Path(r"D:\Content\_SHOW")
ALL = sorted(SHOWS.rglob("*.trix")) if SHOWS.exists() else []
needs_shows = pytest.mark.skipif(not ALL, reason="the show files are not here")


@pytest.fixture(autouse=True)
def no_media(monkeypatch):
    """No movie opened: how long things are is not in a show file."""
    monkeypatch.setattr(showfile, "media_frames", lambda path, strict=False: 600)
    monkeypatch.setattr(showfile, "sound_frames", lambda path: 600)
    monkeypatch.setattr(showfile, "motor_frames", lambda path: (600, 0))


def as_editor_holds_it(path):
    """Read, and through the draft's data, as the editor works on it."""
    show = showfile.read(path)
    return drafts.show_from_dict(json.loads(json.dumps(drafts.show_to_dict(show))))


def digest(path) -> str:
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()


def entries(raw) -> dict:
    """Every clip of a show file, by where it is and its ident."""
    out = {}
    for canvas, held in (raw.get("video") or {}).items():
        for key, entry in (held or {}).items():
            out[("video", canvas, key)] = entry
    for section in ("audio", "jsons", "cue"):
        for key, entry in (raw.get(section) or {}).items():
            out[(section, None, key)] = entry
    return out


def model(show) -> list:
    """What the viewer reads of a show, ident aside."""
    return sorted((one.kind, one.row, one.level, one.path.replace("\\", "/"), one.tx,
                   one.crop_start, one.crop_end, one.fade_start, one.fade_end,
                   one.loop, tuple(one.loop_range), one.universe, one.channel,
                   one.value) for one in show.clips)


# -- unchanged, it is the same file ---------------------------------------------------

@needs_shows
@pytest.mark.parametrize("path", ALL, ids=[one.name for one in ALL])
def test_a_show_written_out_unchanged_is_the_same_file(path, tmp_path):
    before = digest(path)
    show = as_editor_holds_it(path)
    target = trix_export.next_version(path, tmp_path)
    trix_export.export(show, target, str(path))
    assert target.read_bytes() == path.read_bytes()
    assert digest(path) == before


# -- edited, only the edits change ----------------------------------------------------

def edit(show):
    """One of each kind of change, on whatever the show has. What it did,
    by ident, to look for in the file."""
    did = {"moved": None, "gone": None, "new": 0}
    pictures = [one for one in show.clips if one.kind == "video"]
    if pictures:
        moved = pictures[len(pictures) // 2]
        moved.tx += 60
        moved.fade_end = -90
        moved.level = 2
        did["moved"] = moved.ident
    sounds = [one for one in show.clips if one.kind == "audio"]
    if sounds:
        gone = sounds[-1]
        show.clips.remove(gone)
        did["gone"] = gone.ident
    ident = drafts.next_ident(show)
    show.clips.append(showfile.Clip(
        kind="video", row="Bottom", level=1, path=r"D:\Content\qa\new_clip.mov",
        tx=5000, frames=600, fade_end=-120, ident=ident))
    show.clips.append(showfile.Clip(
        kind="cue", row="Cue", level=0, path="", tx=7000, universe=1,
        channel=12, value=255, ident=ident + 1))
    did["new"] = 2
    return did


@needs_shows
@pytest.mark.parametrize("path", ALL, ids=[one.name for one in ALL])
def test_an_edited_show_changes_only_what_was_edited(path, tmp_path):
    before = digest(path)
    old = json.loads(path.read_text(encoding="utf-8"))
    show = as_editor_holds_it(path)
    did = edit(show)
    target = trix_export.next_version(path, tmp_path)
    trix_export.export(show, target, str(path))
    new = json.loads(target.read_text(encoding="utf-8"))
    was, now = entries(old), entries(new)

    changed = {key for key in was.keys() & now.keys() if was[key] != now[key]}
    if did["moved"] is not None:
        assert [key[2] for key in changed] == [str(did["moved"])]
        entry = next(now[key] for key in changed)
        assert entry["level"] == 2 and entry["fade_end"] == -90
    else:
        assert not changed
    gone = was.keys() - now.keys()
    assert [key[2] for key in gone] == ([str(did["gone"])] if did["gone"] else [])
    added = now.keys() - was.keys()
    assert len(added) == did["new"]
    used = {int(key[2]) for key in was}
    assert all(int(key[2]) > max(used | {0}) for key in added)
    picture = next(now[key] for key in added if key[0] == "video")
    assert picture["path"] == "D:/Content/qa/new_clip.mov"
    assert list(picture) == ["path", "tx", "crop_start", "crop_end", "level",
                             "fade_start", "fade_end", "loop",
                             "loop_custom_range", "transform"]
    # What the viewer does not read went out as it came.
    for key in was.keys() & now.keys():
        if Path(str(was[key].get("path", ""))).name.lower() in showfile.BACKDROPS:
            assert now[key] == was[key]
    assert {k: v for k, v in new.items() if k not in ("video", "audio", "cue", "jsons")} \
        == {k: v for k, v in old.items() if k not in ("video", "audio", "cue", "jsons")}
    # And it reads back as the show that was written.
    assert model(showfile.read(target)) == model(show)
    assert digest(path) == before


# -- the version, and never over anything ----------------------------------------------

def test_the_next_version_is_past_every_version_there(tmp_path):
    source = tmp_path / "Show-v001.trix"
    source.write_text("{}", encoding="utf-8")
    assert trix_export.next_version(source).name == "Show-v002.trix"
    (tmp_path / "Show-v002.trix").write_text("{}", encoding="utf-8")
    (tmp_path / "show-v007.trix").write_text("{}", encoding="utf-8")
    (tmp_path / "Other-v040.trix").write_text("{}", encoding="utf-8")
    assert trix_export.next_version(source).name == "Show-v008.trix"
    assert trix_export.next_version(tmp_path / "Old-v01.trix").name == "Old-v02.trix"
    assert trix_export.next_version(tmp_path / "Special.trix").name == "Special-v001.trix"
    other = tmp_path / "elsewhere"
    other.mkdir()
    assert trix_export.next_version(source, other) == other / "Show-v002.trix"


def test_nothing_is_written_over(tmp_path):
    show = showfile.Show(name="проба", length=1000)
    source = tmp_path / "Show-v001.trix"
    trix_export.export(show, source)
    kept = source.read_bytes()
    with pytest.raises(trix_export.ExportError):
        trix_export.export(show, source, str(source))
    with pytest.raises(trix_export.ExportError):
        trix_export.export(show, source)
    assert source.read_bytes() == kept


def test_a_new_show_has_the_backdrops_and_reads_back(tmp_path):
    show = showfile.Show(name="Новое шоу", length=showfile.LENGTH)
    show.clips = [
        showfile.Clip(kind="video", row="Top", level=0, path="D:/Content/a.mov",
                      tx=1100, frames=600, ident=1),
        showfile.Clip(kind="audio", row="Sound", level=1, path="D:/Content/a.wav",
                      tx=1100, frames=600, ident=2),
        showfile.Clip(kind="kinetic", row="Kinetic", level=0, path="D:/Content/a.json",
                      tx=1100, frames=600, ident=3)]
    target = trix_export.export(show, tmp_path / "Новое шоу-v001.trix")
    raw = json.loads(target.read_text(encoding="utf-8"))
    assert list(raw) == ["video", "audio", "cue", "jsons", "project"]
    assert raw["project"] == {"length": 79200, "name": "Новое шоу", "version": 1}
    assert target.read_text(encoding="utf-8").isascii()      # as the editor writes it
    back = showfile.read(target)
    assert model(back) == model(show)
    assert back.loops == [(800, 1099)]
    assert raw["jsons"]["6"]["prepare_enabled"] is False
    assert trix_export.notes_for(show, None, "")


def test_a_loop_drawn_in_the_editor_is_said_not_written():
    show = showfile.Show(name="проба", length=1000)
    show.loops = [(800, 1099)]
    assert not trix_export.notes_for(show, [(800, 1099)], "x.trix")
    show.loops = [(800, 1099), (5000, 5300)]
    assert trix_export.notes_for(show, [(800, 1099)], "x.trix")


def test_an_old_show_with_a_word_for_a_version_reads(tmp_path):
    path = tmp_path / "old.trix"
    path.write_text(json.dumps({"video": {}, "audio": {}, "jsons": {},
                                "project": {"length": 100, "name": "old",
                                            "version": "v01"}}), encoding="utf-8")
    assert showfile.read(path).version == 1
    target = trix_export.export(showfile.read(path), tmp_path / "old-v02.trix", str(path))
    assert target.read_bytes() == path.read_bytes()
