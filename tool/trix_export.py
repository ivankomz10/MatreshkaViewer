"""A show written out as a .trix -- always a new version, beside the old one.

The show editor on site writes its files with Python's `json.dumps` as it
comes: one line, ", " and ": " between things, everything past ASCII as
\\u escapes. All 68 files in `D:\\Content\\_SHOW` read back and written so
are the same file to the byte, and that is the measure here: a show opened
and written out with nothing changed is the file it came from.

So a show is not written from nothing. The file it came from is read again
and only what the editor changed is changed in it:

  kept        everything the viewer does not read -- the black backdrops,
              the perspective canvases of an old show, `transform`,
              `prepare_*`, whatever else a file has -- as it was, in its
              place, numbers as they were written (1 stays 1, not 1.0)
  matched     a clip of the file is the clip of the show with its ident, on
              the same canvas or section. Its fields are written only where
              they differ; a field the file did not have is added only when
              it is not what reading it had taken it to be
  gone        a clip of the file no longer in the show is taken out
  new         a clip of the show the file does not have goes in under a
              fresh ident, past every ident the file uses, written the way
              the editor writes one

Loops are not clips in a show file: a loop is the `loop` flag of a clip,
standing until whatever comes next. A loop drawn in the viewer's editor has
nothing to be written as, so it is said and not written; the file's own
loops go out as they came.

The file a show came from is never written. The new one is the next version
beside it -- `...-v001.trix` gives `...-v002.trix`, past any version already
there -- and is never written over either.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import show as showfile
from lang import tr

ROW_CANVAS = {row: canvas for canvas, row in showfile.CANVASES.items()}
SECTION = {"audio": "audio", "kinetic": "jsons", "cue": "cue"}
# Where the sections come in a show file, for one that has to be added.
ORDER = ("video", "audio", "cue", "jsons", "project")
TRANSFORM = {"x": 0, "y": 0, "scale": 1, "rotation": 0, "flip_x": 0,
             "flip_y": 0, "opacity": 1.0, "seamless": 0}
VERSION = re.compile(r"^(?P<base>.*)-v(?P<number>\d+)$", re.IGNORECASE)


class ExportError(Exception):
    """The show could not be written where it was asked to go."""


# -- where a clip lives in the file -------------------------------------------

def place_of(clip) -> tuple:
    """(section, canvas): the canvas for a picture, None for the rest."""
    if clip.kind == "video":
        return ("video", ROW_CANVAS[clip.row])
    return (SECTION[clip.kind], None)


def _container(raw: dict, place: tuple, make: bool = False):
    section, canvas = place
    if section not in raw:
        if not make:
            return None
        _insert(raw, section, {}, ORDER)
    held = raw[section]
    if canvas is None:
        return held
    if canvas not in held:
        if not make:
            return None
        _insert(held, canvas, {}, tuple(showfile.CANVASES))
    return held[canvas]


def _insert(into: dict, key: str, value, order: tuple) -> None:
    """A key added where it belongs among the others, not at the end."""
    rank = {name: index for index, name in enumerate(order)}
    items = list(into.items())
    at = len(items)
    for index, (name, _) in enumerate(items):
        if rank.get(name, -1) > rank.get(key, len(order)):
            at = index
            break
    items.insert(at, (key, value))
    into.clear()
    into.update(items)


def _backdrop(entry) -> bool:
    return (isinstance(entry, dict) and Path(str(entry.get("path", ""))).name.lower()
            in showfile.BACKDROPS)


def _places(raw: dict):
    """Every container the viewer reads, with its place."""
    for canvas in showfile.CANVASES:
        held = (raw.get("video") or {}).get(canvas)
        if isinstance(held, dict):
            yield ("video", canvas), held
    for section in ("audio", "jsons", "cue"):
        held = raw.get(section)
        if isinstance(held, dict):
            yield (section, None), held


def _idents(raw: dict) -> set:
    """Every ident the file uses, on any canvas at all."""
    found = set()
    for section in ("video",):
        for held in (raw.get(section) or {}).values():
            found.update(int(key) for key in (held or {}) if str(key).isdigit())
    for section in ("audio", "jsons", "cue"):
        found.update(int(key) for key in (raw.get(section) or {})
                     if str(key).isdigit())
    return found


# -- a clip's fields ------------------------------------------------------------

def _fields(clip) -> list:
    """(key, value, what reading takes it to be when the file says nothing)."""
    if clip.kind == "cue":
        return [("frame", int(clip.tx), None), ("channel", int(clip.channel), 0),
                ("universe", int(clip.universe), 0), ("value", int(clip.value), 0),
                ("level", int(clip.level), 0)]
    out = [("path", clip.path, None), ("tx", int(clip.tx), None)]
    if clip.kind == "video":
        out += [("crop_start", int(clip.crop_start), 0),
                ("crop_end", int(clip.crop_end), 0),
                ("level", int(clip.level), 0),
                ("fade_start", int(clip.fade_start), 0),
                ("fade_end", int(clip.fade_end), 0),
                ("loop", bool(clip.loop), False),
                ("loop_custom_range", [int(v) for v in clip.loop_range], [0, 100])]
    elif clip.kind == "audio":
        out.append(("level", int(clip.level), 0))
    return out


def _same_path(a: str, b: str) -> bool:
    return str(a).replace("\\", "/").lower() == str(b).replace("\\", "/").lower()


def _update(entry: dict, clip) -> None:
    for key, value, default in _fields(clip):
        if key in entry:
            if key == "path" and _same_path(entry[key], value):
                continue
            if entry[key] != value:
                entry[key] = value.replace("\\", "/") if key == "path" else value
        elif value != default:
            entry[key] = value
    if clip.kind == "video" and clip.transform and entry.get("transform") != clip.transform:
        entry["transform"] = dict(clip.transform)


def _new(clip) -> dict:
    """A clip as the show editor writes one."""
    entry = {key: (value.replace("\\", "/") if key == "path" else value)
             for key, value, _ in _fields(clip)}
    if clip.kind == "video":
        entry["transform"] = dict(clip.transform or TRANSFORM)
    elif clip.kind == "kinetic":
        entry.update(prepare_enabled=False, prepare_offset=0, prepare_interval=0)
    return entry


# -- the show -------------------------------------------------------------------

def blank(name: str, length: int) -> dict:
    """A show file with nothing on it but what every show has: the black
    backdrop behind each screen on level 3, the top one looped from frame
    800 -- the installation waiting to be started."""
    def black(path, loop):
        return {"path": path, "tx": 800, "crop_start": 0, "crop_end": 0,
                "level": 3, "fade_start": 0, "fade_end": 0, "loop": loop,
                "loop_custom_range": [0, 100], "transform": dict(TRANSFORM)}
    return {"video": {"Tiles-pixels": {"1": black("D:/Content/black.png", True)},
                      "Scene-pixels": {"2": black("D:/Content/black.png", False)},
                      "Lamel-pixels": {"3": black("D:/Content/black-lameli.png", False)}},
            "audio": {}, "cue": {}, "jsons": {},
            "project": {"length": int(length), "name": name, "version": 1}}


def to_raw(show, base: dict | None, stem: str = "") -> dict:
    """The show as a show file: `base`, the file it came from, with the
    editor's changes made in it; or a blank one."""
    raw = copy.deepcopy(base) if base is not None else blank(show.name, show.length)
    # Taken before anything is taken out: an ident a clip had is never given
    # to another one.
    used = _idents(raw)
    originals = {}
    for place, held in _places(raw):
        for key, entry in held.items():
            if not _backdrop(entry):
                originals[str(key)] = place
    matched, new = {}, []
    for clip in show.clips:
        key = str(clip.ident)
        if originals.get(key) == place_of(clip) and key not in matched:
            matched[key] = clip
        else:
            new.append(clip)
    for place, held in list(_places(raw)):
        for key in list(held):
            if str(key) not in originals:
                continue
            if str(key) in matched:
                _update(held[key], matched[str(key)])
            else:
                del held[key]
    ident = max(used | {int(key) for key in matched} | {0}) + 1
    for clip in sorted(new, key=lambda one: (one.tx, one.ident)):
        _container(raw, place_of(clip), make=True)[str(ident)] = _new(clip)
        ident += 1

    project = raw.get("project")
    if project is None:
        if show.name != (stem or show.name) or show.length != showfile.LENGTH:
            _insert(raw, "project", {"length": int(show.length), "name": show.name,
                                     "version": 1}, ORDER)
    else:
        if project.get("name", stem) != show.name:
            project["name"] = show.name
        if project.get("length", showfile.LENGTH) != show.length:
            project["length"] = int(show.length)
    return raw


def text_of(raw: dict) -> str:
    """As the show editor writes it (see the top of the file)."""
    return json.dumps(raw)


def next_version(source: str | Path, folder: str | Path | None = None) -> Path:
    """Where the next version of a show file goes: beside it, or in
    `folder`, numbered past every version of it already there."""
    source = Path(source)
    folder = Path(folder) if folder is not None else source.parent
    found = VERSION.match(source.stem)
    base = found.group("base") if found else source.stem
    width = len(found.group("number")) if found else 3
    number = int(found.group("number")) if found else 0
    pattern = re.compile(re.escape(base) + r"-v(\d+)$", re.IGNORECASE)
    for one in folder.glob("*.trix"):
        other = pattern.match(one.stem)
        if other:
            number = max(number, int(other.group(1)))
    return folder / f"{base}-v{number + 1:0{width}d}.trix"


def notes_for(show, file_loops=None, source: str = "") -> list:
    """What the new file will not say the way the viewer showed it."""
    notes = []
    if file_loops is not None and [tuple(one) for one in show.loops] \
            != [tuple(one) for one in file_loops]:
        notes.append(tr("Лупы, нарисованные в редакторе, в .trix не пишутся: в файле "
                        "луп — это флажок клипа. Ушли лупы, которые были в файле."))
    if not source:
        notes.append(tr("Шоу новое: в него положена чёрная подложка за каждым экраном "
                        "с лупом с 800-го кадра, как во всех шоу."))
    return notes


def export(show, target: str | Path, source: str = "") -> Path:
    """Write the show to `target`, a file that is not there yet. Based on
    `source`, the show file it came from, when there is one."""
    target = Path(target)
    if source and Path(source).exists() and target.resolve() == Path(source).resolve():
        raise ExportError(tr("{0}: в исходный файл шоу не пишется", target.name))
    base, stem = None, ""
    if source and Path(source).exists():
        try:
            base = json.loads(Path(source).read_text(encoding="utf-8"))
        except Exception as error:  # noqa: BLE001 -- said to whoever asked
            raise ExportError(f"{Path(source).name}: {error}") from error
        stem = Path(source).stem
    text = text_of(to_raw(show, base, stem))
    try:
        with open(target, "x", encoding="utf-8", newline="") as out:
            out.write(text)
    except FileExistsError as error:
        raise ExportError(tr("{0} уже есть, поверх не пишется", target.name)) from error
    except OSError as error:
        raise ExportError(f"{target.name}: {error}") from error
    return target
