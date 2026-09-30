"""Keys the machine carries out: a plan of moves made from what the piece wants.

The machine runs a motor one command at a time -- a move from one key to
the next -- no faster than the motor goes, then rests; a command that comes
while it moves or rests is dropped (`kin_sim`, Cinema 4D's rule). Keys laid
one after another with no rest between them -- a solid sampled every so many
frames, noise, a fade -- so lose every other command, and the motor is left
standing half way, short of the shape the piece ends on.

A plan looks at each motor's whole curve and makes moves of it that the
machine takes:

  1  the curve in runs and holds: where it goes up, where down, where it
     stands; a wiggle smaller than the tolerance is no run of its own
  2  a run is one move, start to end -- the motor's own ease between -- so
     a slope made of many keys is one smooth command, not a stutter
  3  a move longer than the curve's own is centred on it -- half early,
     half late, the plan knows what comes -- so the motor's move and the
     curve's go together; never before the motor is free, with its rest
     after the move before
  4  a peak the curve only turns at goes as far as there is time for,
     turning back no later than half its own length after the curve does;
     a shape the curve stands at -- held for a while, or the last -- is
     reached in full, late if it must be. A jack's places are all shapes

Motors whose own keys the machine already carries out -- nothing dropped,
nothing late -- keep them exactly: a plan is for what it cannot.
"""
from __future__ import annotations

import math

import numpy as np

import kin_model as km
import kin_sim

TOLERANCE = km.PLAN_TOLERANCE   # of a motor's travel: 20 mm of push, 1.8 degrees of tilt
HOLD = 30             # frames a value has to stand to be a shape to reach
FLAT = 1e-4           # keys this close are the same place


def _travel(family: str, value: float) -> float:
    return float(kin_sim.travel(family, round(float(value), 4)))


def _needed(family: str, a: float, b: float, full_frames: float) -> int:
    """Frames a move takes, as the machine counts them."""
    distance = abs(_travel(family, b) - _travel(family, a))
    return max(1, int(distance * full_frames + 1e-6))


def carried(family: str, first: float, moves: list, full_frames: float,
            rest_frames: float) -> bool:
    """Whether the machine carries out a motor's commands as they are:
    none of them late, none coming before the motor is free. With nothing
    dropped, each move starts where the one before ended, so all of it is
    read at once."""
    if not moves:
        return True
    frame, start, dest, length = np.asarray(moves, np.float64).T
    distance = np.abs(np.asarray(kin_sim.travel(family, np.round(dest, 4)))
                      - np.asarray(kin_sim.travel(family, np.round(start, 4))))
    live = distance >= 1e-6
    frame, length, distance = frame[live], length[live], distance[live]
    if not len(frame):
        return True
    needed = np.maximum(1, (distance * full_frames + 1e-6).astype(np.int64))
    took = np.maximum(length.astype(np.int64), needed)
    if (took > length + kin_sim.LATE_SLACK).any():
        return False
    return not (frame[1:] < (frame + took + rest_frames)[:-1]).any()


def _travels(family: str, values) -> list:
    """Many values as distances along the travel, as plain numbers."""
    values = np.round(np.asarray(values, np.float64), 4)
    return np.asarray(kin_sim.travel(family, values), np.float64).tolist()


def pieces(frames, values, family: str, tolerance: float = TOLERANCE):
    """A motor's keys as runs and holds: [("run", f0, v0, f1, v1) or
    ("hold", f0, f1, v)], in order. Keys within FLAT of each other stand; a
    run smaller than the tolerance is swallowed."""
    frames = np.asarray(frames, np.int64)
    values = np.asarray(values, np.float64)
    if len(frames) < 2:
        return []
    along = np.asarray(_travels(family, values))
    step = np.diff(along)
    kinds = np.where(np.abs(step) <= FLAT, 0, np.sign(step)).astype(np.int64)
    # Each stretch of one kind -- standing, going up, going down -- is one.
    cuts = np.nonzero(np.diff(kinds))[0] + 1
    firsts = np.concatenate([[0], cuts]).tolist()
    lasts = np.concatenate([cuts, [len(kinds)]]).tolist()
    frame_list, value_list, along_list = frames.tolist(), values.tolist(), along.tolist()
    kinds = kinds.tolist()

    def small(item) -> bool:
        return item[0] == "run" and abs(item[6] - item[7]) < tolerance

    def join_holds(out) -> None:
        while len(out) >= 2 and out[-1][0] == out[-2][0] == "hold":
            last = out.pop()
            out[-1] = ("hold", out[-1][1], out[-1][2], last[3], out[-1][4], 0,
                       out[-1][6], last[7])

    def settle(out) -> None:
        """The one before the last now has both its neighbours: a wiggle
        under the tolerance joins a run there and back, or stands."""
        if len(out) < 2 or not small(out[-2]):
            return
        middle, after = out[-2], out[-1]
        before = out[-3] if len(out) >= 3 else None
        if (before is not None and before[0] == after[0] == "run"
                and before[5] == after[5] != middle[5]):
            del out[-3:]
            out.append(("run", before[1], before[2], after[3], after[4], before[5],
                        before[6], after[7]))
        else:
            out[-2] = ("hold", middle[1], middle[2], middle[3], middle[2], 0,
                       middle[6], middle[6])
            last = out.pop()
            join_holds(out)
            out.append(last)
            join_holds(out)

    out: list = []
    for first, last in zip(firsts, lasts):
        kind = kinds[first]
        item = ("hold" if kind == 0 else "run", frame_list[first], value_list[first],
                frame_list[last], value_list[last], kind, along_list[first],
                along_list[last])
        out.append(item)
        join_holds(out)
        settle(out)
    if out and small(out[-1]):
        end = out[-1]
        out[-1] = ("hold", end[1], end[2], end[3], end[2], 0, end[6], end[6])
        join_holds(out)
    return [one[:6] for one in out]


def plan_motor(family: str, frames, values, full_frames: float, rest_frames: float,
               tolerance: float = TOLERANCE, hold: int = HOLD) -> list:
    """(frame, value) keys the machine carries out, as near the curve as it
    goes: see the module's story."""
    if not len(frames):
        return []
    items = pieces(frames, values, family, tolerance)
    rest = int(math.ceil(rest_frames))
    here = float(values[0])
    keys = [(int(frames[0]), here)]
    free_at = -10 ** 9
    for n, item in enumerate(items):
        if item[0] != "run":
            continue
        _, start_at, _, end_at, target, _ = item
        after = items[n + 1] if n + 1 < len(items) else None
        firm = (after is None or family == "lift"
                or (after[0] == "hold" and (after[3] - after[1] >= hold
                                            or n + 2 >= len(items))))
        if abs(_travel(family, target) - _travel(family, here)) <= FLAT:
            continue
        need = _needed(family, here, target, full_frames)
        earliest = max(free_at, 0)
        if end_at - start_at >= need:
            start = max(start_at, earliest)      # the curve's own time is enough
        else:
            # Longer than the curve takes: centred on it, half early, half
            # late, so the motor's move and the curve's go together.
            start = max(earliest, int(round((start_at + end_at - need) / 2.0)))
        end = max(end_at, start + need)
        deadline = end_at + (end_at - start_at) // 2
        if end > deadline and not firm:
            # A peak the curve only turns at: as far as there is time for,
            # turning back no later than half its own length after it.
            room = deadline - start
            if room < 1:
                continue
            reach = room / full_frames
            there = _travel(family, target) - _travel(family, here)
            got = math.copysign(min(abs(there), reach), there)
            target = here + got
            need = _needed(family, here, target, full_frames)
            end = max(end_at, start + need)
        if len(keys) == 1 and keys[0][0] >= start:
            keys[0] = (start, here)          # before its first key it stood there anyway
        elif keys[-1][0] < start:
            keys.append((start, here))
        elif keys[-1][0] > start:
            start = keys[-1][0]
            end = max(end, start + need)
        keys.append((end, target))
        here = target
        free_at = end + rest
    return keys


def plan(project, pace: dict | None = None, tolerance: float = TOLERANCE):
    """The piece's keys as the machine can carry them out; `project` is
    left as it is. Motors the machine already carries out keep their keys."""
    pace = dict(kin_sim.PACE if pace is None else pace)
    out = km.Project(project.length, empty=True)
    out.name, out.video, out.sound = project.name, project.video, project.sound
    out.masks, out.primitives, out.prim_step = (project.masks, [], project.prim_step)
    touched = 0
    for family in km.FAMILIES:
        track = project.tracks[family]
        full, rest = pace[family]
        full_frames, rest_frames = max(1e-6, full * km.FPS), rest * km.FPS
        frames, values, keyed, _, _ = track._stacked()
        written: dict = {}
        for motor in range(track.size):
            mine = np.nonzero(keyed[:, motor])[0] if len(frames) else []
            if not len(mine):
                continue
            first, moves = track.segments(motor)
            if carried(family, first, moves, full_frames, rest_frames):
                got = [(int(frames[k]), float(values[k, motor])) for k in mine]
            else:
                got = plan_motor(family, frames[mine], values[mine, motor],
                                 full_frames, rest_frames, tolerance)
                touched += 1
            for frame, value in got:
                slot = written.setdefault(frame, (np.zeros(track.size, np.float32),
                                                  np.zeros(track.size, bool)))
                slot[0][motor] = value
                slot[1][motor] = True
        if written:
            when = sorted(written)
            out.tracks[family].merge(when, [written[f][0] for f in when],
                                     [written[f][1] for f in when])
    out.planned = touched
    return out
