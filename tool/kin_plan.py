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
    """Whether the machine carries out a motor's commands as they are."""
    here, free_at = float(first), -math.inf
    for frame, _start, dest, length in moves:
        if frame < free_at:
            return False
        if abs(_travel(family, dest) - _travel(family, here)) < 1e-6:
            continue
        took = max(int(length), _needed(family, here, dest, full_frames))
        if took > length + kin_sim.LATE_SLACK:
            return False
        here = float(dest)
        free_at = frame + took + rest_frames
    return True


def pieces(frames, values, family: str, tolerance: float = TOLERANCE):
    """A motor's keys as runs and holds: [("run", f0, v0, f1, v1) or
    ("hold", f0, f1, v)], in order. Keys within FLAT of each other stand; a
    run smaller than the tolerance is swallowed."""
    frames = [int(f) for f in frames]
    values = [float(v) for v in values]
    items = []
    for k in range(len(frames) - 1):
        a, b = values[k], values[k + 1]
        if abs(_travel(family, b) - _travel(family, a)) <= FLAT:
            kind, sign = "hold", 0
        else:
            kind, sign = "run", 1 if b > a else -1
        last = items[-1] if items else None
        if last is not None and last[0] == kind and last[5] == sign:
            items[-1] = (kind, last[1], last[2], frames[k + 1], b, sign)
        else:
            items.append((kind, frames[k], a, frames[k + 1], b, sign))
    # A wiggle under the tolerance: one of three runs going there and back
    # joins them; alone between holds it is part of the hold.
    changed = True
    while changed:
        changed = False
        for n, item in enumerate(items):
            if item[0] != "run":
                continue
            if abs(_travel(family, item[4]) - _travel(family, item[2])) >= tolerance:
                continue
            before = items[n - 1] if n > 0 else None
            after = items[n + 1] if n + 1 < len(items) else None
            if (before and after and before[0] == after[0] == "run"
                    and before[5] == after[5] != item[5]):
                items[n - 1:n + 2] = [("run", before[1], before[2], after[3], after[4],
                                       before[5])]
            else:
                items[n] = ("hold", item[1], item[2], item[3], item[2], 0)
            changed = True
            break
    # Holds side by side are one.
    out = []
    for item in items:
        if out and out[-1][0] == item[0] == "hold":
            out[-1] = ("hold", out[-1][1], out[-1][2], item[3], out[-1][4], 0)
        else:
            out.append(item)
    return out


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
        target = out.tracks[family]
        for frame in sorted(written):
            values_at, mask = written[frame]
            target.write(frame, values_at, mask)
    out.planned = touched
    return out
