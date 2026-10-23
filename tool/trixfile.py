"""Writing a show back out as a `.trix`, the show editor's own file.

The rule is that a show read and written with no edit in between comes out
the same file, byte for byte -- measured on every show in `D:\\Content\\_SHOW`
(64 files with `previous-good-show`). The model in `show.py` is far too small
for that: it drops the black backdrop, reads `level: true` as 1, has no idea
which clips carried a `transform` and which did not, or in which order their
keys were written. So the export does not build a file out of the model. It
takes the file as it was read (`Show.raw`) and writes into it only what the
model says has changed:

  an entry a clip came from   each field the editor can change is compared
                              with what the reader made of it, and only one
                              that differs is written. `true` stays `true`,
                              `1.0` stays `1.0`, a key that was never there
                              stays away.
  an entry with no clip       deleted in the editor, so left out -- except
                              the backdrops, which the reader never made
                              clips of and the editor cannot touch.
  a clip with no entry        made in the editor: written at the end of its
                              section under the next id of the file, in the
                              shape the show editor writes, keys in its order.

And the file is put down the way the show editor writes it: one line, ASCII
with `\\u` escapes, `", "` and `": "` between things, no newline at the end --
which is exactly `json.dumps` with nothing set. All 64 match that.

Loops are the one thing this cannot write. In a show file a loop is a clip
with `loop` set, standing from its tx until the next clip arrives; a loop
drawn in the editor over the middle of a song has no such clip to be. The
clips' own `loop` goes out as it came in, and a show whose loops were moved
says so (`export` returns it as a note) rather than writing something else.
"""
from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path

import show as showfile
from lang import tr

# The sections a clip of each kind lives in.
SECTIONS = {"audio": "audio", "kinetic": "jsons", "cue": "cue"}
VIDEO_OF_ROW = {row: canvas for canvas, row in showfile.CANVASES.items()}

# What the show editor writes for a clip it has just made, keys in its order.
# Taken from the files: these are the shapes 1700 of 1800 entries have.
IDENTITY = {"x": 0, "y": 0, "scale": 1, "rotation": 0, "flip_x": 0,
            "flip_y": 0, "opacity": 1.0, "seamless": 0}


def _int(value) -> int:
    return int(value or 0)


def _path(value) -> str:
    return str(value)


def _range(value) -> tuple:
    return tuple(value or (0, 100))


# Per section: (key in the file, field of the clip, how the reader read it,
# what it was before the reader had it). Only these are written back; the
# reader reads nothing else, so nothing else can have been edited.
FIELDS = {
    "video": [("path", "path", _path, None), ("tx", "tx", _int, None),
              ("crop_start", "crop_start", _int, 0),
              ("crop_end", "crop_end", _int, 0),
              ("level", "level", _int, 0),
              ("fade_start", "fade_start", _int, 0),
              ("fade_end", "fade_end", _int, 0),
              ("loop", "loop", bool, False),
              ("loop_custom_range", "loop_range", _range, None)],
    "audio": [("path", "path", _path, None), ("tx", "tx", _int, None),
              ("level", "level", _int, 0)],
    "jsons": [("path", "path", _path, None), ("tx", "tx", _int, None)],
    "cue": [("frame", "tx", _int, None), ("channel", "channel", _int, 0),
            ("universe", "universe", _int, 0), ("value", "value", _int, 0),
            ("level", "level", _int, 0)],
}


class ExportError(Exception):
    """The show cannot be written where it was asked to go."""


def section_of(clip) -> str:
    """Where in the file a clip goes: a canvas name, or audio/jsons/cue."""
    if clip.kind == "video":
        return VIDEO_OF_ROW.get(clip.row, "")
    return SECTIONS.get(clip.kind, "")


def _entries(raw: dict, section: str) -> dict:
    """A section's entries, made if the file had none: the canvases under
    `video`, the rest at the top."""
    if section in VIDEO_OF_ROW.values():
        return raw.setdefault("video", {}).setdefault(section, {})
    return raw.setdefault(section, {})


def _skeleton() -> dict:
    """A file for a show that never was one, in the order every file has."""
    return {"video": {canvas: {} for canvas in showfile.CANVASES},
            "audio": {}, "cue": {}, "jsons": {}}


def _value(clip, attr: str, key: str):
    """A clip's field as it goes into the file."""
    value = getattr(clip, attr)
    if key == "path":
        # The show editor writes D:/Content/..., and a file dropped from
        # Explorer comes as D:\Content\...
        return str(value).replace("\\", "/")
    if key == "loop":
        return bool(value)
    if key == "loop_custom_range":
        return [int(one) for one in value]
    return int(value)


def _fresh(clip, kind: str) -> dict:
    """A new entry, the way the show editor writes one."""
    value = lambda key, attr=None: _value(clip, attr or key, key)  # noqa: E731
    if kind == "video":
        return {"path": value("path"), "tx": value("tx"),
                "crop_start": value("crop_start"),
                "crop_end": value("crop_end"), "level": value("level"),
                "fade_start": value("fade_start"),
                "fade_end": value("fade_end"), "loop": value("loop"),
                "loop_custom_range": value("loop_custom_range", "loop_range"),
                "transform": dict(clip.transform or IDENTITY)}
    if kind == "audio":
        return {"path": value("path"), "tx": value("tx"),
                "level": value("level")}
    if kind == "jsons":
        return {"path": value("path"), "tx": value("tx"),
                "prepare_enabled": False, "prepare_offset": 0,
                "prepare_interval": 0}
    return {"frame": value("frame", "tx"), "channel": value("channel"),
            "universe": value("universe"), "value": value("value"),
            "level": value("level")}


def _write_into(entry: dict, clip, kind: str) -> None:
    """Into an entry the clip came from, the fields it no longer agrees on."""
    for key, attr, read, absent in FIELDS[kind]:
        had = entry.get(key, absent)
        if had is not None and read(had) == read(getattr(clip, attr)):
            continue
        entry[key] = _value(clip, attr, key)


def _ids(raw: dict) -> list:
    found = []
    for entries in (raw.get("video") or {}).values():
        found += [int(one) for one in entries or {}]
    for section in ("audio", "jsons", "cue"):
        found += [int(one) for one in raw.get(section) or {}]
    return found


def to_raw(show) -> dict:
    """The show as the show file's JSON: its own file with the edits in."""
    raw = copy.deepcopy(show.raw) if show.raw is not None else _skeleton()

    # What the clips came from, and what of the file is left without a clip.
    kept = {}
    for clip in show.clips:
        if clip.origin and clip.origin.partition(":")[0] == section_of(clip):
            kept[clip.origin] = clip
    for canvas, entries in list((raw.get("video") or {}).items()):
        for ident in list(entries or {}):
            entry = entries[ident]
            backdrop = (Path(str(entry.get("path", ""))).name.lower()
                        in showfile.BACKDROPS)
            if f"{canvas}:{ident}" not in kept and not backdrop:
                del entries[ident]
    for section in ("audio", "jsons", "cue"):
        entries = raw.get(section) or {}
        for ident in list(entries):
            if f"{section}:{ident}" not in kept:
                del entries[ident]

    # A new clip keeps the id the editor gave it while that is past every id
    # the file has -- the backdrops' too, which the editor never saw -- and
    # past every one given out here; otherwise it takes the next after them.
    # Never one the file used, deleted or not, and always at the end of its
    # section, where the show editor puts one.
    used = set(_ids(show.raw or {}))
    for clip in show.clips:
        if clip.origin in kept:
            used.add(clip.ident)
    for clip in sorted(show.clips, key=lambda one: one.ident):
        section = section_of(clip)
        if not section:
            continue
        kind = "video" if clip.kind == "video" else section
        where, _, ident = clip.origin.partition(":")
        entries = _entries(raw, section)
        if clip.origin in kept and ident in entries:
            _write_into(entries[ident], clip, kind)
        else:
            # A clip made here, or one taken to another screen: a new entry,
            # and one the file has not used.
            highest = max(used | {0})
            ident = clip.ident if clip.ident > highest else highest + 1
            entries[str(ident)] = _fresh(clip, kind)
            used.add(ident)

    project = raw.get("project")
    name = show.name or (Path(show.path).stem if show.path else "")
    if project is None:
        # Only a file that had no project before keeps having none, and only
        # while nothing in it has been changed.
        if show.raw is None or name != Path(show.path).stem \
                or show.length != showfile.LENGTH:
            raw["project"] = {"length": int(show.length), "name": name,
                              "version": int(show.version or 1)}
    else:
        if str(project.get("name") or Path(show.path).stem) != name:
            project["name"] = name
        if int(project.get("length") or showfile.LENGTH) != int(show.length):
            project["length"] = int(show.length)
    return raw


def dumps(show) -> str:
    """The text of the file, as the show editor writes it."""
    return json.dumps(to_raw(show))


def notes(show, file_loops) -> list:
    """What the file will not carry of the show as it is in the editor."""
    said = []
    if [tuple(one) for one in show.loops] != [tuple(one) for one in file_loops]:
        said.append(tr("лупы из редактора в .trix не пишутся: в файле "
                       "остаются лупы клипов, как были"))
    return said


def next_version(path: str | Path) -> Path:
    """Beside the show it came from, one version on: -v001 to -v002, keeping
    the number's width; a name with no version gets -v002. The first such
    name that is free."""
    path = Path(path)
    found = re.search(r"([-_. ]v)(\d+)$", path.stem, re.IGNORECASE)
    if found:
        head, number, width = (path.stem[:found.start(2)],
                               int(found.group(2)), len(found.group(2)))
    else:
        head, number, width = path.stem + "-v", 1, 3
    while True:
        number += 1
        candidate = path.with_name(f"{head}{number:0{width}d}{path.suffix}")
        if not candidate.exists():
            return candidate


def export(show, target: str | Path, source: str | Path = "") -> Path:
    """Write the show to `target`. Never over the file it was read from, and
    never half a file: written beside it and put in place in one move."""
    target = Path(target)
    for one in (source, show.path):
        if one and Path(one).exists() and target.exists() \
                and os.path.samefile(one, target):
            raise ExportError(tr("{0} — это исходный файл шоу; экспорт пишет "
                                 "новый файл рядом", target.name))
    text = dumps(show)
    spare = target.with_name(target.name + ".writing")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        spare.write_bytes(text.encode("ascii"))
        os.replace(spare, target)
    except OSError as error:
        spare.unlink(missing_ok=True)
        raise ExportError(f"{target.name}: {error}") from error
    return target
