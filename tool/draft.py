"""A show being edited: what it is as data, its history, and its draft on disk.

The editor works on a `show.Show` in memory. Three things are kept about it
here, and none of them knows anything about windows:

  as data     a show and back again, as plain JSON -- every clip with every
              field, the loops, the name, the length. Lengths of media are
              kept rather than asked again, so going back through history or
              opening a draft touches no movie.
  history     a snapshot before every change, for Ctrl+Z and Ctrl+Y. A show
              is a few dozen clips; a snapshot is a few kilobytes, and a
              whole copy is the one kind of undo that cannot get out of step.
  the draft   the working file. Written by itself after every change, a
              moment after the last one, into `drafts` beside the program:
              not %TEMP%, which Windows clears on its own, and a working file
              has to last the week. The show file it came from is never
              written; what goes to the site is exported, later, as a new
              version beside it.

A draft remembers the show file it came from and how that file stood -- its
size and time -- so that opening the same file again can say whether it has
changed since the draft was begun.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import shutil
import time
from pathlib import Path

import show as showfile

FORMAT = "matreshka-show-draft"
VERSION = 1
UNDO_DEPTH = 200
# Changes to one thing this close together are one step back: typing 1, 2, 0
# into a field is one change to 120, not three.
TOGETHER = 1.5


# -- a show as data ------------------------------------------------------------

_FIELDS = [one.name for one in dataclasses.fields(showfile.Clip)]


def clip_to_dict(clip) -> dict:
    out = {name: getattr(clip, name) for name in _FIELDS}
    out["loop_range"] = list(out["loop_range"])
    out["transform"] = dict(out["transform"])
    return out


def clip_from_dict(raw: dict):
    known = {name: raw[name] for name in _FIELDS if name in raw}
    known["loop_range"] = tuple(known.get("loop_range") or (0, 100))
    known["transform"] = dict(known.get("transform") or {})
    return showfile.Clip(**known)


def show_to_dict(show) -> dict:
    return {"name": show.name, "version": show.version,
            "length": show.length, "path": show.path,
            "loops": [list(one) for one in show.loops],
            "clips": [clip_to_dict(one) for one in show.clips]}


def show_from_dict(raw: dict):
    show = showfile.Show(name=str(raw.get("name") or ""),
                         version=int(raw.get("version") or 1),
                         length=int(raw.get("length") or showfile.LENGTH),
                         path=str(raw.get("path") or ""))
    show.clips = [clip_from_dict(one) for one in raw.get("clips") or []]
    show.loops = [(int(low), int(high)) for low, high in raw.get("loops") or []]
    return show


def put_back(show, raw: dict) -> None:
    """Make `show` what `raw` says, in place: everything that holds the show
    object goes on holding it."""
    other = show_from_dict(raw)
    show.name, show.version, show.length = other.name, other.version, other.length
    show.clips[:] = other.clips
    show.loops[:] = other.loops


def next_ident(show) -> int:
    return max([one.ident for one in show.clips] or [0]) + 1


def settle(show) -> None:
    """What follows from the clips once they have been moved about.

    A still stands until the next clip on its own track, as it does in the
    show editor. And the show is long enough to hold everything on it: a
    clip dropped past the end takes the end with it.
    """
    for clip in show.clips:
        if clip.still:
            clip.until = 0
    for row in {one.row for one in show.clips}:
        for level in show.levels(row):
            track = show.on(row, level)
            for index, clip in enumerate(track):
                if clip.still:
                    later = [one.first for one in track[index + 1:]
                             if one.first > clip.first]
                    clip.until = min(later) if later else show.length
    furthest = max([one.last for one in show.clips
                    if one.frames or one.kind == "cue"] or [0])
    if furthest > show.length:
        show.length = int(furthest)
        for clip in show.clips:
            if clip.still and clip.until > show.length:
                clip.until = show.length


# -- history -----------------------------------------------------------------

class History:
    """Snapshots, taken before each change: back and forward through them."""

    def __init__(self, depth: int = UNDO_DEPTH) -> None:
        self.depth = depth
        self.back: list = []           # (label, snapshot) before each change
        self.ahead: list = []
        self._last = None              # (label, key, when) of the last change

    def clear(self) -> None:
        self.back.clear()
        self.ahead.clear()
        self._last = None

    def before(self, show, label: str, key=None) -> bool:
        """Remember the show as it is, about to change. False when this
        change is one with the change before it, and nothing was taken."""
        now = time.monotonic()
        if (key is not None and self._last is not None
                and self._last[:2] == (label, key)
                and now - self._last[2] < TOGETHER and self.back):
            self._last = (label, key, now)
            return False
        self.back.append((label, show_to_dict(show)))
        del self.back[:-self.depth]
        self.ahead.clear()
        self._last = (label, key, now)
        return True

    def forget_last(self) -> None:
        """The change that was about to happen did not: a click, not a drag."""
        if self.back:
            self.back.pop()
        self._last = None

    def undo(self, show):
        """Step back. The label of what was undone, or None."""
        if not self.back:
            return None
        label, was = self.back.pop()
        self.ahead.append((label, show_to_dict(show)))
        put_back(show, was)
        self._last = None
        return label

    def redo(self, show):
        if not self.ahead:
            return None
        label, will = self.ahead.pop()
        self.back.append((label, show_to_dict(show)))
        put_back(show, will)
        self._last = None
        return label


# -- the draft on disk ---------------------------------------------------------

def folder(home: Path) -> Path:
    return Path(home) / "drafts"


def stamp(path: str) -> dict:
    """How a file stands: enough to know whether it has been written since."""
    try:
        facts = Path(path).stat()
    except OSError:
        return {}
    return {"size": facts.st_size, "mtime_ns": facts.st_mtime_ns}


def path_for(home: Path, source: str) -> Path:
    """Where the draft of a show file lives. By the file's whole path, not
    its name: two shows called the same in two folders are two drafts."""
    if source:
        stem = Path(source).stem
        tag = hashlib.sha1(str(Path(source).resolve()).lower()
                           .encode("utf-8")).hexdigest()[:8]
        return folder(home) / f"{stem}-{tag}.json"
    return folder(home) / f"new-{time.strftime('%Y%m%d-%H%M%S')}.json"


class Draft:
    """One working file: which show it is of, and the show as edited."""

    def __init__(self, where: Path, source: str = "",
                 source_stamp: dict | None = None) -> None:
        self.where = Path(where)
        self.source = source
        self.source_stamp = dict(source_stamp or {})
        self.started = time.strftime("%Y-%m-%d %H:%M:%S")
        self.saved = ""
        self.changes = 0
        self.file_loops: list = []     # the loops the show file came with

    def save(self, show) -> Path:
        """Written whole to a file beside it and put in place in one move, so
        a crash in the middle leaves the last good draft and not half of one."""
        self.where.parent.mkdir(parents=True, exist_ok=True)
        self.saved = time.strftime("%Y-%m-%d %H:%M:%S")
        body = {"format": FORMAT, "version": VERSION,
                "source": self.source, "source_stamp": self.source_stamp,
                "started": self.started, "saved": self.saved,
                "changes": self.changes,
                "file_loops": [list(one) for one in self.file_loops],
                "show": show_to_dict(show)}
        spare = self.where.with_suffix(".writing")
        spare.write_text(json.dumps(body, ensure_ascii=False, indent=1),
                         encoding="utf-8")
        os.replace(spare, self.where)
        return self.where

    @classmethod
    def load(cls, where: Path):
        """(Draft, Show) from a working file. Raises ValueError if it is not
        one. Whether each file is here is asked again: a draft can be opened
        on a day the drive with half the media on it is not plugged in."""
        where = Path(where)
        try:
            body = json.loads(where.read_text(encoding="utf-8"))
        except Exception as error:  # noqa: BLE001 -- said to whoever opened it
            raise ValueError(f"{where.name}: {error}") from error
        if not isinstance(body, dict) or body.get("format") != FORMAT:
            raise ValueError(f"{where.name} is not a draft of a show")
        draft = cls(where, str(body.get("source") or ""),
                    body.get("source_stamp") or {})
        draft.started = str(body.get("started") or "")
        draft.saved = str(body.get("saved") or "")
        draft.changes = int(body.get("changes") or 0)
        draft.file_loops = [(int(low), int(high))
                            for low, high in body.get("file_loops") or []]
        show = show_from_dict(body.get("show") or {})
        for clip in show.clips:
            if clip.kind != "cue":
                clip.missing = not Path(clip.path).exists()
        return draft, show

    def source_changed(self) -> bool:
        """Whether the show file has been written since this draft began."""
        if not self.source:
            return False
        return stamp(self.source) != self.source_stamp

    def put_aside(self) -> Path | None:
        """Out of the way, not deleted: into `old`, with the time on it."""
        if not self.where.exists():
            return None
        aside = self.where.parent / "old"
        aside.mkdir(parents=True, exist_ok=True)
        target = aside / f"{self.where.stem}-{time.strftime('%Y%m%d-%H%M%S')}.json"
        shutil.move(str(self.where), str(target))
        return target
