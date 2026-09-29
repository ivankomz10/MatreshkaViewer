"""The motors' own movement: what the machine will do with the keys.

Keys say where a motor is to be and when. The motor has its own pace and its
own habits, and this works out what it actually does -- Cinema 4D's motor
model (screen_0.6.0.c4d, `get_field_data` and `save_field_data_to_json`),
chosen by the technical director as the machine's:

  a move      goes from where the motor is to where it is told, as fast as
              its pace allows and no faster: a full travel takes `travel`
              seconds, so half of one takes half as long. Keys asking for a
              slower move get it; keys asking for a faster one get the motor
              arriving late
  a rest      follows every move: `rest` seconds in which the motor will not
              start another
  a command   that arrives while the motor is moving or resting is dropped,
              as Cinema 4D drops it -- and marked, as it marks it. The motor
              stays where it was and takes the next command from there

A command is what the export would send: a motor's move from one of its keys
to its next. Distances are Cinema 4D's own: a pusher's 0..1, a tilt's value
(its field is the tilt plus a half), and a jack's four places at 0, 0.25,
0.5 and 1 of its travel -- 1300 mm is the whole of it, and 330 a quarter.

What comes out is a piece of the same kind as what went in: keys where each
move starts and ends. So it is drawn, checked and exported by the same code,
and putting it onto the timeline is handing its tracks over.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

import kin_model as km
from kinetic import PER_ROW, ROWS

# Cinema 4D's Moving Time and Delay Time, seconds, by family.
PACE = {"lift": (15.0, 0.5), "push": (4.0, 0.5), "tilt": (1.25, 0.2)}

# Where a jack's four places are along its travel, as Cinema 4D snaps its
# field: 0, a quarter, a half and all of it.
LIFT_TRAVEL = (0.0, 0.25, 0.5, 1.0)

# How often the finished motion is looked at for a tilt past its gaps, in
# frames, between the moves' own ends, which are always looked at.
LOOK_EVERY = 3

# A move this many frames over is not called late: the files Cinema 4D wrote
# at its own pace come out a frame over on thousands of moves, the way its
# lengths and its values were rounded, and a sixtieth of a second is not
# something anyone will see.
LATE_SLACK = 1


def travel(family: str, value) -> np.ndarray:
    """A value as a distance along the motor's travel, 0..1."""
    value = np.asarray(value, np.float64)
    if family == "lift":
        return np.interp(value, [0, 1, 2, 3], LIFT_TRAVEL)
    return value


@dataclass
class Dropped:
    family: str
    motor: int
    frame: int            # when the command came
    target: float
    busy_until: int       # when the motor would have taken it


@dataclass
class Late:
    family: str
    motor: int
    frame: int            # when the move began
    due: int              # when the keys wanted it there
    arrives: int          # when it got there


@dataclass
class Result:
    project: km.Project                 # the motion, as keys
    dropped: list = field(default_factory=list)
    late: list = field(default_factory=list)
    clashes: list = field(default_factory=list)     # (frame, cells) past gaps
    pace: dict = field(default_factory=dict)

    def worst_late(self):
        """The move that arrived latest after it was due, or None."""
        return max(self.late, key=lambda one: one.arrives - one.due, default=None)

    def problems(self) -> list[int]:
        """Every frame something went wrong, in order: a command dropped, a
        move arriving late, a tilt past its gaps."""
        found = {one.frame for one in self.dropped}
        found |= {one.due for one in self.late}
        found |= {frame for frame, _ in self.clashes}
        return sorted(found)

    def by_family(self) -> dict:
        counts = {family: {"dropped": 0, "late": 0} for family in km.FAMILIES}
        for one in self.dropped:
            counts[one.family]["dropped"] += 1
        for one in self.late:
            counts[one.family]["late"] += 1
        return counts


def simulate(project: km.Project, pace: dict | None = None) -> Result:
    """The keys as the motors carry them out."""
    pace = dict(PACE if pace is None else pace)
    out = km.Project(project.length, empty=True)
    out.name = project.name
    result = Result(out, pace=pace)
    for family in km.FAMILIES:
        track = project.tracks[family]
        full, rest = pace[family]
        full_frames = max(1e-6, full * km.FPS)
        rest_frames = rest * km.FPS
        ends: list[dict] = []           # per motor: frame -> value
        for motor in range(track.size):
            first, moves = track.segments(motor)
            here = float(first)
            mine = {0: here}
            free_at = -math.inf
            for frame, _start, dest, length in moves:
                if frame < free_at:
                    result.dropped.append(Dropped(family, motor, frame, dest,
                                                  int(math.ceil(free_at))))
                    continue
                # Off the values as the file writes them, four places: a key
                # kept in single precision is otherwise a hair off, and a
                # hair is a frame late.
                distance = abs(float(travel(family, round(dest, 4))
                                     - travel(family, round(here, 4))))
                if distance < 1e-6:
                    continue
                # Whole frames the way Cinema 4D counts them, the fraction
                # dropped: its own files then run exactly at pace.
                needed = max(1, int(distance * full_frames + 1e-6))
                took = max(int(length), needed)
                arrives = frame + took
                if took > length + LATE_SLACK:
                    result.late.append(Late(family, motor, frame,
                                            frame + int(length), arrives))
                mine[frame] = here
                mine[arrives] = float(dest)
                here = float(dest)
                free_at = arrives + rest_frames
            ends.append(mine)
        _as_keys(out.tracks[family], ends, project.length)
    result.clashes = _clashes(out)
    return result


def _as_keys(track: km.Track, ends: list, length: int) -> None:
    """Each motor's move ends as its keys, all of them on one track."""
    frames = sorted({frame for mine in ends for frame in mine})
    index = {frame: at for at, frame in enumerate(frames)}
    values = np.zeros((len(frames), track.size), np.float32)
    keyed = np.zeros((len(frames), track.size), bool)
    for motor, mine in enumerate(ends):
        for frame, value in mine.items():
            values[index[frame], motor] = value
            keyed[index[frame], motor] = True
    # Unkeyed slots hold what the motor holds there, so a key looked at on
    # its own says the truth; the curve never reads them.
    for at in range(1, len(frames)):
        values[at] = np.where(keyed[at], values[at], values[at - 1])
    track.frames = frames
    track.values = [values[at] for at in range(len(frames))]
    track.keyed = [keyed[at] for at in range(len(frames))]
    track._changed()


def _clashes(project: km.Project) -> list:
    """(frame, cells) wherever a cell tilts past what its gaps allow now --
    a jack closing under a tilted ring, or a tilt arriving before the jack
    has opened -- looked at through the whole motion, not only at keys."""
    looked = set(range(0, project.length, LOOK_EVERY))
    for track in project.tracks.values():
        looked.update(track.frames)
    found = []
    tilt, lift = project.tracks["tilt"], project.tracks["lift"]
    push = project.tracks["push"]
    for frame in sorted(f for f in looked if f < project.length):
        over = km.over_limit(tilt.at(frame), lift.at(frame), push.at(frame))
        count = int(over.sum())
        if count:
            found.append((frame, count))
    return found


def differs(source: km.Project, motion: km.Project, frame: int,
            family: str | None = None) -> np.ndarray:
    """Which cells stand somewhere else in the motion than the keys want
    them at this frame, (ROWS, PER_ROW): the ones running late or left
    behind by a dropped command."""
    lag = np.zeros((ROWS, PER_ROW), bool)
    for one in (km.FAMILIES if family is None else (family,)):
        want = source.tracks[one].at(frame)
        got = motion.tracks[one].at(frame)
        gap = np.abs(travel(one, got) - travel(one, want)) > 0.02
        lag |= km.spread(one, gap.astype(np.float32)) > 0.5
    return lag
