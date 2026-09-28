"""A show: what plays on which screen, from which frame, for how long.

The show editor that runs the building on site keeps a show as a `.trix` --
JSON, one file per show, forty of them in `D:\\Content\\_SHOW`. This reads one
into the least model the viewer needs, and never writes one back.

Everything about the format below was measured across all forty files rather
than read off the schema, because the schema allows far more than anybody
uses (see `docs/timeline.md`):

  tx          where a clip starts on the show's own timeline, in frames. The
              core of it: clips are placed, not chained, and may overlap.
  level       which track of its screen a clip is on. Not a depth -- the
              layers add, they do not stack -- so here it is only a row.
  crop/fade   only ever used from the tail: one second trimmed, two seconds
              faded. The heads are always zero, because the editor has no
              field to set them with; they are read all the same.
  loop        set on exactly one clip per show, a black still behind
              everything, from its own tx until the first real clip arrives.
              That span is the installation waiting to be started, and it is
              read here as a loop: 800..1099 in every one of the forty.
  transform   never anything but identity. Kept, not applied.
  prepare_*   on the kinetic files, never switched on. Ignored.

The viewer's own quick look -- one file per screen, all from frame zero -- is
a show as well (`single`), so that there is one way of playing things and
not two.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from lang import tr

FPS = 60.0
LENGTH = 79200                  # every show file here: exactly 22 minutes
# How long a still stands in the quick look: for as long as it is loaded,
# which is what dropping a picture on a screen has always meant.
FOREVER = 1 << 40

# The show file's canvases, and what the viewer calls the same screens.
CANVASES = {"Tiles-pixels": "Top", "Scene-pixels": "Bottom",
            "Lamel-pixels": "Lamels"}
# And the baked screen each of those is drawn on.
SCREENS = {"Top": "Screen_Top", "Bottom": "Screen_Bottom",
           "Lamels": "Lamel_screen"}

# Every show carries an opaque black still on the level behind the content,
# looped for the whole show. It is a backdrop, not a clip: the viewer chooses
# its own backing, black or the calibration picture, and a second answer read
# out of the show would only be a way for the two to disagree. So it is kept
# as a loop and nothing else.
BACKDROPS = ("black.png", "black-lameli.png")


class ShowError(Exception):
    """The file is not a show this can read."""


def timecode(frame: float, fps: float = FPS) -> str:
    """hh:mm:ss:ff on the show's grid -- the way the show editor counts."""
    frame = max(0, int(frame))
    whole = int(fps) or 60
    seconds, part = divmod(frame, whole)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{part:02d}"


@dataclass
class Clip:
    """One thing on one track, at one place in time."""

    kind: str                   # video | audio | kinetic | cue
    row: str                    # Top | Bottom | Lamels | Sound | Kinetic | Cue
    level: int
    path: str
    tx: int
    # Its length in frames of the show's own grid -- not of its file. The
    # same number for everything in the show files, which are all 60 fps;
    # not for a 30 fps movie dropped on the quick look.
    frames: int = 0             # 0 for a still, or when it is not here
    crop_start: int = 0
    crop_end: int = 0           # negative: frames taken off the tail
    fade_start: int = 0
    fade_end: int = 0           # negative: frames of fade before the tail
    loop: bool = False
    loop_range: tuple = (0, 100)
    ident: int = 0
    # Kinetic only: how long past its declared range the last command given
    # to a motor is still being carried out. A pusher told to move two frames
    # before the part ends and taking 156 more is still moving; those frames
    # are in no file, and cutting the clip at its range cuts the move off.
    tail: int = 0
    # A still has no length of its own. It stands until the next clip on its
    # track arrives, which is filled in once the track is known.
    until: int = 0
    universe: int = 0           # cue only
    channel: int = 0
    value: int = 0
    missing: bool = False
    transform: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return Path(self.path).name if self.path else f"cue {self.channel}"

    @property
    def still(self) -> bool:
        return self.kind == "video" and not self.frames and not self.missing

    @property
    def first(self) -> int:
        """The first show frame it is seen on. A cropped head is trimmed in
        place: the rest of the clip does not move up to fill it."""
        return self.tx + max(0, self.crop_start)

    @property
    def last(self) -> int:
        """One past the last show frame it is seen on."""
        if self.kind == "cue":
            return self.tx + 1
        if self.still:
            return max(self.first + 1, self.until or self.first + 1)
        return self.tx + self.frames + min(0, self.crop_end) + self.tail

    @property
    def span(self) -> int:
        return max(1, self.last - self.first)

    def covers(self, frame: float) -> bool:
        return self.first <= frame < self.last

    def local(self, frame: float) -> int:
        """Which frame of its own file is on show at this show frame."""
        if self.still or not self.frames:
            return 0
        return max(0, min(self.frames - 1, int(frame) - self.tx))

    def opacity_at(self, frame: float) -> float:
        """The fade, as a factor on everything this clip emits.

        Straight lines, head and tail. The show editor's own curve is not in
        its files; linear is what a fade field of a length in frames reads as,
        and every fade in all forty shows is the plain two seconds.
        """
        if not self.covers(frame):
            return 0.0
        level = 1.0
        head = abs(self.fade_start)
        if head:
            level = min(level, (frame - self.first + 1) / head)
        tail = abs(self.fade_end)
        if tail:
            # Measured from where the picture stops, not from where the motor
            # stops: a kinetic clip's follow-through is not a thing to fade.
            ends = self.last - self.tail
            level = min(level, (ends - frame) / tail)
        return max(0.0, min(1.0, level))


@dataclass
class Show:
    """A show, as far as the viewer needs one."""

    name: str = ""
    version: int = 1
    length: int = LENGTH
    path: str = ""
    clips: list = field(default_factory=list)
    # Where the show waits: one (first, last) per looped clip, `last` being
    # the frame before whatever arrives next. A show cut into blocks waits at
    # every join, so there can be several.
    loops: list = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.length / FPS

    def on(self, row: str, level: int | None = None) -> list:
        """The clips of one row, and of one level of it if asked, in order."""
        return sorted((one for one in self.clips
                       if one.row == row and (level is None
                                              or one.level == level)),
                      key=lambda one: (one.tx, one.ident))

    def levels(self, row: str) -> list:
        return sorted({one.level for one in self.clips if one.row == row})

    def live_at(self, frame: float) -> list:
        return [one for one in self.clips
                if one.kind != "cue" and one.covers(frame)]

    def loop_at(self, frame: float):
        for first, last in self.loops:
            if first <= frame < last:
                return (first, last)
        return None

    def missing(self) -> list:
        return [one for one in self.clips if one.missing]

    def describe(self) -> str:
        kinds = {}
        for one in self.clips:
            kinds[one.kind] = kinds.get(one.kind, 0) + 1
        words = {"video": tr("видео"), "audio": tr("звук"), "kinetic": tr("моторы"),
                 "cue": tr("кью")}
        said = " · ".join(f"{words[k]} {kinds[k]}" for k in
                          ("video", "audio", "kinetic", "cue") if k in kinds)
        lost = len(self.missing())
        return (tr("{0}  {1} · лупы {2}", self.name, said, len(self.loops))
                + (tr(" · нет на машине {0}", lost) if lost else ""))


# -- how long things are -----------------------------------------------------

def media_frames(path: str, strict: bool = False) -> int | None:
    """How long a movie is on the show's grid, 0 for a still, None when it
    is not here to ask.

    The show file does not say how long anything is -- the editor asks the
    media -- so neither can this. Strict, a file that is missing or will not
    open says why instead of answering None: somebody who dropped it on a
    row wants the reason, where a show with a clip on another drive does not.
    """
    import videofile
    where = Path(path)
    if not where.exists():
        if strict:
            raise ShowError(tr("{0}: такого файла нет", where.name))
        return None
    if videofile.is_still(path):
        return 0
    try:
        import hapfile
        try:
            movie, container = hapfile.open_movie(path)
        except Exception:  # noqa: BLE001 -- not HAP is not an error
            movie, container = videofile.open_movie(path)
        container.close()
    except Exception as error:  # noqa: BLE001 -- as good as missing here
        if strict:
            raise ShowError(f"{where.name}: {error}") from error
        return None
    rate = float(getattr(movie, "rate", 0.0) or FPS)
    return max(1, int(round(movie.frames * FPS / rate)))


def sound_frames(path: str) -> int | None:
    """A WAV's length in show frames, off its header alone."""
    import wave
    where = Path(path)
    if not where.exists():
        return None
    try:
        with wave.open(str(where), "rb") as opened:
            return int(round(opened.getnframes() / opened.getframerate() * FPS))
    except Exception:  # noqa: BLE001
        return None


_MOTOR_FRAMES: dict = {}


def commands_of(data) -> tuple:
    """(length, keys) of a motor file's `data`: how long it is, and the
    frames its commands begin on.

    The length is how the show editor counts it -- to the end of the last
    command, the last frame included: the largest `frame + length` of any
    segment, plus one. Measured in TouchDesigner on sixteen files, from 613
    frames to 29 699, and not one frame out on any of them. It is not the
    exporter's `export_range`, which runs on about thirty frames past the
    last command, and a show places the next file at this length: part two
    of BrendMT stands 3755 frames after part one, which is where part one's
    last pusher arrives.
    """
    furthest, keys = 0, set()
    for groups in (data or {}).values():
        if not isinstance(groups, dict):
            continue
        for ids in groups.values():
            if not isinstance(ids, dict):
                continue
            for segments in ids.values():
                for one in segments or []:
                    if isinstance(one, dict):
                        at = int(one.get("frame", 0))
                        keys.add(at)
                        furthest = max(furthest,
                                       at + max(0, int(one.get("length", 0))))
    return furthest + 1, tuple(sorted(keys))


def motor_frames(path: str) -> tuple:
    """A motor file's length, as the show editor counts it (see
    `commands_of`), and a run-on past it, which is always nothing now.

    The run-on was the part of a clip after the exporter's range where a
    motor was still arriving. Counted the show editor's way, the length
    already goes to the end of the last command, and there is none; it is
    kept as a number so a clip and a draft keep the shape they had.

    Off the JSON itself rather than by building the motors: sampling 1829
    tracks to learn a length is a second per file, and a show has a handful.
    None for the length when the file is not here. Kept by the file's size
    and time: reading five of them was two thirds of a second of opening a
    show, every time the show mode was gone into.
    """
    found = _motor_facts(path)
    return (None, 0) if found is None else (found[0], 0)


def motor_keys(path: str) -> tuple:
    """The frames a motor file's commands begin on, from its own start --
    drawn on its clip as keys, the way the show editor draws them."""
    found = _motor_facts(path)
    return () if found is None else found[1]


def _motor_facts(path: str):
    where = Path(path)
    if not where.exists():
        return None
    try:
        facts = where.stat()
        key = (str(where), facts.st_size, facts.st_mtime_ns)
    except OSError:
        return None
    if key not in _MOTOR_FRAMES:
        try:
            raw = json.loads(where.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            raw = None
        data = raw.get("data") if isinstance(raw, dict) else None
        # A JSON with no motor data in it is not a motor file, whatever it
        # is called.
        _MOTOR_FRAMES[key] = (commands_of(data) if isinstance(data, dict)
                              and data else None)
    return _MOTOR_FRAMES[key]


# -- reading a show file -----------------------------------------------------

def loops_of(raw: dict, length: int) -> list:
    """Every wait the show file describes, in order.

    A clip with `loop` set stands from its own tx until the next clip arrives,
    on any row -- that is the installation waiting. In all forty files there
    is one, the black still before the show starts, and it comes to 800..1099.
    """
    looped, others = [], []
    for layers in (raw.get("video") or {}).values():
        for clip in (layers or {}).values():
            (looped if clip.get("loop") else others).append(int(clip["tx"]))
    for section in ("audio", "jsons"):
        for clip in (raw.get(section) or {}).values():
            others.append(int(clip["tx"]))
    starts = sorted(set(looped))
    edges = sorted(set(others))
    found = []
    for first in starts:
        after = [one for one in edges if one > first] \
            + [one for one in starts if one > first]
        last = min(after) - 1 if after else length
        if last > first:
            found.append((first, last))
    return found


def _stills_until_next(show: Show) -> None:
    """A still stands until the next clip on its own track, or the end."""
    for row in set(one.row for one in show.clips):
        for level in show.levels(row):
            track = show.on(row, level)
            for index, clip in enumerate(track):
                if clip.kind == "video" and not clip.frames:
                    later = [one.first for one in track[index + 1:]]
                    clip.until = (min(later) if later else show.length)


def read(path: str | Path) -> Show:
    """One show file, with every clip's length found out from its media."""
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:  # noqa: BLE001 -- said to whoever opened it
        raise ShowError(f"{path.name}: {error}") from error
    if not isinstance(raw, dict) or "video" not in raw:
        raise ShowError(tr("{0} — это не файл шоу", path.name))

    project = raw.get("project") or {}
    show = Show(name=str(project.get("name") or path.stem),
                version=int(project.get("version") or 1),
                length=int(project.get("length") or LENGTH),
                path=str(path))

    for canvas, row in CANVASES.items():
        for ident, clip in ((raw.get("video") or {}).get(canvas) or {}).items():
            if Path(clip.get("path", "")).name.lower() in BACKDROPS:
                continue
            got = media_frames(clip["path"])
            show.clips.append(Clip(
                kind="video", row=row, level=int(clip.get("level", 0)),
                path=str(clip["path"]), tx=int(clip["tx"]), frames=got or 0,
                crop_start=int(clip.get("crop_start", 0)),
                crop_end=int(clip.get("crop_end", 0)),
                fade_start=int(clip.get("fade_start", 0)),
                fade_end=int(clip.get("fade_end", 0)),
                loop=bool(clip.get("loop")),
                loop_range=tuple(clip.get("loop_custom_range") or (0, 100)),
                ident=int(ident), missing=got is None,
                transform=dict(clip.get("transform") or {})))
    for ident, clip in (raw.get("audio") or {}).items():
        got = sound_frames(clip["path"])
        show.clips.append(Clip(
            kind="audio", row="Sound", level=int(clip.get("level", 0)),
            path=str(clip["path"]), tx=int(clip["tx"]), frames=got or 0,
            ident=int(ident), missing=got is None))
    for ident, clip in (raw.get("jsons") or {}).items():
        declared, tail = motor_frames(clip["path"])
        show.clips.append(Clip(
            kind="kinetic", row="Kinetic", level=0, path=str(clip["path"]),
            tx=int(clip["tx"]), frames=declared or 0, tail=tail,
            ident=int(ident), missing=declared is None))
    for ident, clip in (raw.get("cue") or {}).items():
        show.clips.append(Clip(
            kind="cue", row="Cue", level=int(clip.get("level", 0)), path="",
            tx=int(clip["frame"]), universe=int(clip.get("universe", 0)),
            channel=int(clip.get("channel", 0)),
            value=int(clip.get("value", 0)), ident=int(ident)))

    show.loops = loops_of(raw, show.length)
    _stills_until_next(show)
    return show


def single(files: dict, length: int = 0, strict: bool = False) -> Show:
    """The quick look as a show: one file per screen, all from frame zero.

    `files` maps a row -- Top, Bottom, Lamels, Frame, Sound, Kinetic -- to a
    path. Nothing loops. A still stands for as long as it is loaded, as a
    picture dropped on a screen always has. The show is as long as the
    longest thing in it that has a length, unless one is given. Strict, a
    screen file that will not open raises with the reason.
    """
    show = Show(name="", length=length or 0)
    for ident, (row, path) in enumerate(files.items(), start=1):
        if not str(path).strip():
            continue
        if row == "Sound":
            got, kind, tail = sound_frames(path), "audio", 0
        elif row == "Kinetic":
            got, tail = motor_frames(path)
            kind = "kinetic"
        else:
            got, kind, tail = media_frames(path, strict), "video", 0
        show.clips.append(Clip(kind=kind, row=row, level=0, path=str(path),
                               tx=0, frames=got or 0, tail=tail, ident=ident,
                               missing=got is None))
    if not length:
        show.length = max([one.last for one in show.clips
                           if one.frames] or [1])
    for clip in show.clips:
        if clip.still:
            clip.until = FOREVER
    return show


def chained(rows: dict) -> Show:
    """The rows as a show, a chain of 0.3 laid end to end where there is one.

    `rows` maps a row to a list of (path, repeats). A movie played over is
    that many copies of it, one after another -- the same length the chain
    had. A picture has nothing to play twice, so its count was read as
    seconds, and still is. Motor files follow each other where the one
    before ends, not where its motors stop: the chain was laid out that way,
    and the next part picks the movement up from where it was cut.

    A picture alone on its row, as dropped on the quick look, stands for the
    whole show, the same as it did there.
    """
    show = Show(name="", length=0)
    ident = 0
    for row, entries in rows.items():
        at = 0
        entries = [one for one in entries if str(one[0]).strip()]
        for path, repeats in entries:
            times = max(1, int(repeats or 1))
            if row == "Sound":
                got, kind, tail = sound_frames(path), "audio", 0
            elif row == "Kinetic":
                got, tail = motor_frames(path)
                kind = "kinetic"
            else:
                got, kind, tail = media_frames(path), "video", 0
            still = kind == "video" and got == 0
            for _ in range(1 if still else times):
                ident += 1
                clip = Clip(kind=kind, row=row, level=0, path=str(path),
                            tx=at, frames=got or 0, tail=tail, ident=ident,
                            missing=got is None)
                show.clips.append(clip)
                if still:
                    clip.until = (FOREVER if len(entries) == 1
                                  else at + max(1, int(round(times * FPS))))
                    at = clip.until
                else:
                    # A motor file's length is where the show editor puts the
                    # next one (see commands_of), so it chains like the rest.
                    at += max(1, got or 0)
    show.length = max([one.last for one in show.clips
                       if one.frames or (one.still and one.until < FOREVER)]
                      or [1])
    return show
