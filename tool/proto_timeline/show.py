"""PROTOTYPE -- throwaway. A show file, read into the least model that will do.

Only what the three variants in `proto.py` need: what the clips are, where
they sit, how long they are. No validation, no error handling beyond staying
runnable, and no writing anything back.

Clip lengths are not in the show file -- the editor probes the media -- so they
are probed here once and cached in `lengths.PROTOTYPE.json` beside this file.
Delete that file and it is rebuilt.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent
sys.path.insert(0, str(TOOL))

SHOWS = Path(r"D:\Content\_SHOW")
CACHE = HERE / "lengths.PROTOTYPE.json"

FPS = 60.0

# The show file's canvases, in the order the building stacks them, and what the
# viewer calls the same screens.
CANVASES = [("Tiles-pixels", "Top"),
            ("Scene-pixels", "Bottom"),
            ("Lamel-pixels", "Lamels")]
CALLED = dict(CANVASES)

# Every show file carries one opaque black still, looped across the whole 22
# minutes, on the level behind the content. It is a backdrop, not a clip: the
# viewer already chooses its own backing -- black or the calibration picture --
# and reading a second answer out of the show file only gives the two a way to
# disagree. So it never reaches the timeline.
BACKDROPS = ("black.png", "black-lameli.png")


def is_backdrop(clip: dict) -> bool:
    return Path(clip.get("path", "")).name.lower() in BACKDROPS


@dataclass
class Clip:
    """One thing on one track, at one place in time."""

    kind: str                 # video | audio | kinetic | cue
    row: str                  # Top | Bottom | Lamels | Sound | Kinetic | Cue
    level: int
    path: str
    tx: int
    frames: int = 0           # its own length, probed; 0 for a still
    crop_start: int = 0
    crop_end: int = 0
    fade_start: int = 0
    fade_end: int = 0
    loop: bool = False
    loop_range: tuple = (0, 100)
    ident: int = 0
    # Cue only
    universe: int = 0
    channel: int = 0
    value: int = 0
    missing: bool = False

    @property
    def name(self) -> str:
        return Path(self.path).name if self.path else f"cue {self.channel}"

    @property
    def first(self) -> int:
        return self.tx + self.crop_start

    @property
    def last(self) -> int:
        """Where it stops. A looped still runs to the end of the show."""
        if self.kind == "cue":
            return self.tx + 1
        if not self.frames:
            return self.tx + (79200 if self.loop else 60)
        return self.tx + self.frames + self.crop_end

    @property
    def span(self) -> int:
        return max(1, self.last - self.first)

    def says(self) -> str:
        """Everything about it, for the state line at the bottom."""
        if self.kind == "cue":
            return (f"cue  frame {self.tx}  universe {self.universe}  "
                    f"channel {self.channel}  value {self.value}")
        bits = [f"{self.row}", f"L{self.level}", f"{self.name}",
                f"tx {self.tx}", f"len {self.frames}",
                f"{self.first}..{self.last}"]
        if self.crop_start or self.crop_end:
            bits.append(f"crop {self.crop_start}/{self.crop_end}")
        if self.fade_start or self.fade_end:
            bits.append(f"fade {self.fade_start}/{self.fade_end}")
        if self.loop:
            bits.append(f"loop {list(self.loop_range)}")
        if self.missing:
            bits.append("FILE MISSING")
        return "   ".join(bits)


@dataclass
class Show:
    name: str = ""
    length: int = 79200
    clips: list = field(default_factory=list)

    def rows(self) -> dict:
        out: dict = {}
        for clip in self.clips:
            out.setdefault(clip.row, []).append(clip)
        for holds in out.values():
            holds.sort(key=lambda one: (one.level, one.tx))
        return out

    def live_at(self, frame: int) -> list:
        return [one for one in self.clips
                if one.kind != "cue" and one.first <= frame < one.last]

    def sections(self) -> list:
        """The instants the show is cut at, with what starts there.

        The shows turn out to be cut in the same places on every row -- the
        same section arrives on Top, Bottom, Lamels, Sound and Kinetic within
        a frame or two of each other -- so a section is a column, and this is
        what variant C is built on.
        """
        marks: list = []
        for clip in sorted(self.clips, key=lambda one: one.tx):
            for at in marks:
                if abs(at[0] - clip.tx) <= 120:      # two seconds of slack
                    at[1].append(clip)
                    break
            else:
                marks.append([clip.tx, [clip]])
        return [(at, holds) for at, holds in marks]


# -- probing -----------------------------------------------------------------

def _cache() -> dict:
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save(known: dict) -> None:
    CACHE.write_text(json.dumps(known, indent=1), encoding="utf-8")


def frames_of(path: str, known: dict) -> int | None:
    """How many frames a media file holds. None when it is not on this machine."""
    if path in known:
        return known[path]
    where = Path(path)
    if not where.exists():
        known[path] = None
        return None
    try:
        import videofile
        if videofile.is_still(path):
            known[path] = 0
            return 0
        if where.suffix.lower() == ".wav":
            import wave
            with wave.open(str(where)) as opened:
                known[path] = int(opened.getnframes()
                                  / opened.getframerate() * FPS)
            return known[path]
        if where.suffix.lower() == ".json":
            import kinetic
            known[path] = int(kinetic.Motors([where]).frames)
            return known[path]
        import hapfile
        try:
            movie, container = hapfile.open_movie(path)
        except Exception:
            movie, container = videofile.open_movie(path)
        container.close()
        known[path] = int(movie.frames)
    except Exception:
        known[path] = None
    return known[path]


def listing() -> list:
    return sorted(SHOWS.glob("*.trix"))


def read(path: Path) -> Show:
    """One show file, with every clip's length filled in."""
    known = _cache()
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    show = Show(name=raw.get("project", {}).get("name", Path(path).stem),
                length=int(raw.get("project", {}).get("length") or 79200))

    for canvas, row in CANVASES:
        for ident, clip in (raw.get("video", {}).get(canvas) or {}).items():
            if is_backdrop(clip):
                continue
            got = frames_of(clip["path"], known)
            show.clips.append(Clip(
                kind="video", row=row, level=int(clip.get("level", 0)),
                path=clip["path"], tx=int(clip["tx"]), frames=got or 0,
                crop_start=int(clip.get("crop_start", 0)),
                crop_end=int(clip.get("crop_end", 0)),
                fade_start=int(clip.get("fade_start", 0)),
                fade_end=int(clip.get("fade_end", 0)),
                loop=bool(clip.get("loop")),
                loop_range=tuple(clip.get("loop_custom_range") or (0, 100)),
                ident=int(ident), missing=got is None))
    for ident, clip in (raw.get("audio") or {}).items():
        got = frames_of(clip["path"], known)
        show.clips.append(Clip(kind="audio", row="Sound",
                               level=int(clip.get("level", 0)),
                               path=clip["path"], tx=int(clip["tx"]),
                               frames=got or 0, ident=int(ident),
                               missing=got is None))
    for ident, clip in (raw.get("jsons") or {}).items():
        got = frames_of(clip["path"], known)
        show.clips.append(Clip(kind="kinetic", row="Kinetic", level=0,
                               path=clip["path"], tx=int(clip["tx"]),
                               frames=got or 0, ident=int(ident),
                               missing=got is None))
    for ident, clip in (raw.get("cue") or {}).items():
        show.clips.append(Clip(kind="cue", row="Cue", level=0, path="",
                               tx=int(clip["frame"]),
                               universe=int(clip.get("universe", 0)),
                               channel=int(clip.get("channel", 0)),
                               value=int(clip.get("value", 0)),
                               ident=int(ident)))
    _save(known)
    return show


def timecode(frame: int) -> str:
    frame = max(0, int(frame))
    whole, rest = divmod(frame, int(FPS))
    minutes, seconds = divmod(whole, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}:{rest:02}"


if __name__ == "__main__":
    for one in listing():
        show = read(one)
        print(f"{show.name[:50]:52} {len(show.clips):3} clips  "
              f"{show.length} frames")
