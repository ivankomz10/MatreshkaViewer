"""The kinetic editor's model: three tracks of keys, and what they make.

The honeycomb on top of the building has three families of motor behind it
(see `kinetic`): thirty jacks that set the gap between rings, three hundred
pushers that drive a group of five cells straight out, and fifteen hundred
tilts that swing one cell each. An artist works on them here the way the
motors themselves work -- a motor is told where to be and when, and gets
there -- so the whole piece is keys:

  a key     is a frame and, for some of the motors of one family, where
            they are to be at that frame
  a track   is one family's keys, in time order

Keys are sparse per motor. A brush stroke over three cells keys those three
and leaves the other 1497 of the family to carry on through it, which is what
makes a stroke at one moment not freeze the rest of the ring there too, and
what lets a motor JSON come in as keys and go back out as the same commands.
Between two keys of its own a motor eases the way the exporter's segments do
(`kinetic.smoothstep`); before its first it waits at that value, after its
last it stays.

What a value is, per family -- the numbers the motor JSON carries, so nothing
is converted on the way out:

  lift  the jack's state, 0..3 (0, 330, 660, 1300 mm of gap); whole numbers
        at keys, because a jack has no position between its states
  push  the pusher, 0..1, times 1000 mm outward
  tilt  the tilt, -0.5..0.5, times 90 degrees -- the sign the viewer reads,
        which is the Houdini exporter's own (it inverts on the way out)

The tilt limits are Houdini's (anim_simple, `rotate_clamp`), chosen by the
show's technical director: by the direction of the tilt. A cell turning its
face down swings into the gap under its ring, face up into the gap over it,
and each gap allows

  0 mm (state 0)       2 degrees
  330 mm (state 1)     10 degrees
  660 mm and up        45 degrees        -- straight between, as a jack moves

-- and then the beam: with its pusher out less than 0.1 a cell tilts 30
degrees at most, from 0.2 out the whole 45. Cinema 4D's rule -- the narrower
gap, both ways, 0, 10 or 30 -- is kept beside it (`TILT_RULE`).
Which gap is beside which ring is the machine's (kinetic.JACK_READING): the
lowest ring stands on the base and the jacks are between the others, so row
1 has no jack and row N opens the gap under ring N -- Cinema 4D's numbering.
Houdini's exporter and the rig number them one lower; a file made there comes
in with its row 1 moving, and the editor says so.
"""
from __future__ import annotations

import json
import math
import time
from bisect import bisect_left, bisect_right
from pathlib import Path

import numpy as np

import kinetic
from kinetic import PER_PUSHER, PER_ROW, ROWS, smoothstep
from lang import tr

FPS = 60
GROUPS = PER_ROW // PER_PUSHER            # pushers round one ring
CELLS = ROWS * PER_ROW

FAMILIES = ("lift", "push", "tilt")
SHAPE = {"lift": (ROWS,), "push": (ROWS, GROUPS), "tilt": (ROWS, PER_ROW)}
JSON_GROUP = {"lift": "jack", "push": "pusher", "tilt": "tilt"}
FAMILY_OF = {group: family for family, group in JSON_GROUP.items()}

# Where a new piece starts. The jacks at state 1 because the rigged geometry
# was modelled there (kinetic.JACK_REST_STATE) and because at state 0 no cell
# could tilt at all.
REST = {"lift": float(kinetic.JACK_REST_STATE), "push": 0.0, "tilt": 0.0}
RANGE = {"lift": (0.0, 3.0), "push": (0.0, 1.0), "tilt": (-0.5, 0.5)}

# Tilt allowed by the narrower gap beside a ring, by its state: Cinema 4D's
# 0, 10 and 30 degrees. Its code clamps a field to 0.4..0.6 for the middle
# one, which is 9; its comment, Houdini's ramp and the files themselves all
# say 10 -- 0.111 is the commonest tilt in the shows made at state 1.
TILT_REACH = (0.0, 10.0 / 90.0, 30.0 / 90.0)

# The rule in force (see `tilt_bounds`): Houdini's, by the direction of the
# tilt, chosen by the technical director over Cinema 4D's on 2026-09-29.
TILT_RULE = "houdini"
# Houdini's ramp, both of its remaps the same: the gap as millimetres over the
# jack's whole travel (0, 33, 66, 130 of the rig's 130) to a fraction of 45
# degrees (2, 10, 45, 45).
HOUDINI_RAMP = ((0.0, 33.0 / 130.0, 66.0 / 130.0, 1.0),
                (2.0 / 45.0, 10.0 / 45.0, 1.0, 1.0))
# And the beam: pushed out this far, a cell clears it and may tilt this much.
BEAM_PUSH = (0.1, 0.2)
BEAM_DEGREES = (30.0, 45.0)

# Houdini's reading of a painted lift, mask 0..1 to a state: the thresholds
# are the midpoints between 0, 33, 66 and 130 mm (anim_simple, `discrete`).
LIFT_THRESHOLDS = (16.5 / 130.0, 49.5 / 130.0, 98.0 / 130.0)

FORMAT = "matreshka-kinetic"
VERSION = 1

# The machine's numbering of the jacks (see kinetic.JACK_READING): row 1's is
# not there, and nothing the tools do moves it.
READING = "machine"
NO_JACK = 0

# A moving primitive is looked at this often, in frames, when it is turned
# into keys; the plan of moves (`kin_plan`) then makes of that what the
# motors can carry out.
PRIM_STEP = 10
# The plan's tolerance: a wiggle smaller than this, of a motor's travel, is
# no move of its own.
PLAN_TOLERANCE = 0.02


class ModelError(Exception):
    """A project or motor file this cannot read."""


def motor_address(family: str, index: int) -> tuple[int, int]:
    """(row, id), both from zero, of the motor at a flat index."""
    if family == "lift":
        return index, 0
    per = GROUPS if family == "push" else PER_ROW
    return divmod(index, per)


# -- one family's keys -------------------------------------------------------

class Track:
    """One family's keys, and the curve every motor of it follows.

    A key's arrays are never changed in place: an edit puts new ones in its
    slot. That is what makes an undo step three shallow list copies rather
    than a copy of every key -- see `state` and `restore`.
    """

    def __init__(self, family: str) -> None:
        self.family = family
        self.shape = SHAPE[family]
        self.size = int(np.prod(self.shape))
        self.frames: list[int] = []
        self.values: list[np.ndarray] = []     # flat float32, one per key
        self.keyed: list[np.ndarray] = []      # flat bool: which it keys
        self.version = 0
        self._cache = None
        self._any = None

    # -- undo --------------------------------------------------------------

    def state(self):
        return (list(self.frames), list(self.values), list(self.keyed))

    def restore(self, state) -> None:
        frames, values, keyed = state
        self.frames, self.values, self.keyed = (
            list(frames), list(values), list(keyed))
        self._changed()

    def _changed(self) -> None:
        self.version += 1
        self._cache = None

    # -- looking ----------------------------------------------------------

    def __len__(self) -> int:
        return len(self.frames)

    def index(self, frame: int):
        """Which key sits exactly on this frame, or None."""
        at = bisect_left(self.frames, int(frame))
        if at < len(self.frames) and self.frames[at] == int(frame):
            return at
        return None

    def _stacked(self):
        """Every key as arrays, and for each key and motor the motor's own
        keys either side -- built once per change, read every frame."""
        if self._cache is not None:
            return self._cache
        count = len(self.frames)
        frames = np.asarray(self.frames, dtype=np.int64)
        if count:
            values = np.stack(self.values).astype(np.float32)
            keyed = np.stack(self.keyed).astype(bool)
        else:
            values = np.zeros((0, self.size), np.float32)
            keyed = np.zeros((0, self.size), bool)
        order = np.arange(count, dtype=np.int32)[:, None]
        back = np.where(keyed, order, -1)
        fore = np.where(keyed, order, count)
        before = (np.maximum.accumulate(back, axis=0) if count
                  else back)
        after = (np.minimum.accumulate(fore[::-1], axis=0)[::-1] if count
                 else fore)
        self._cache = (frames, values, keyed, before, after)
        return self._cache

    def at(self, frame: float) -> np.ndarray:
        """Where every motor of the family is at this frame, in its shape."""
        frames, values, keyed, before, after = self._stacked()
        count = len(frames)
        rest = np.full(self.size, REST[self.family], np.float32)
        if count == 0:
            return rest.reshape(self.shape)
        k = bisect_right(self.frames, frame) - 1
        if k < 0:
            prev = np.full(self.size, -1, np.int32)
        else:
            prev = before[k]
        nxt = (after[k + 1] if k + 1 < count
               else np.full(self.size, count, np.int32))
        motors = np.arange(self.size)
        has_prev, has_next = prev >= 0, nxt < count
        low = values[np.clip(prev, 0, count - 1), motors]
        high = values[np.clip(nxt, 0, count - 1), motors]
        out = rest
        out = np.where(has_prev & ~has_next, low, out)
        out = np.where(~has_prev & has_next, high, out)
        both = has_prev & has_next
        if both.any():
            start = frames[np.clip(prev, 0, count - 1)]
            end = frames[np.clip(nxt, 0, count - 1)]
            span = np.maximum(end - start, 1)
            t = np.clip((frame - start) / span, 0.0, 1.0)
            eased = low + (high - low) * smoothstep(t)
            out = np.where(both, eased, out)
        return out.astype(np.float32).reshape(self.shape)

    def keyed_count(self, index: int) -> int:
        return int(self.keyed[index].sum())

    def keyed_any(self) -> np.ndarray:
        """Which motors have a key at all, flat: the ones this track says
        anything about -- over the layers under it, those it overrides."""
        if self._any is None or self._any[0] != self.version:
            keyed = self._stacked()[2]
            self._any = (self.version, keyed.any(axis=0) if len(keyed)
                         else np.zeros(self.size, bool))
        return self._any[1]

    # -- changing ----------------------------------------------------------

    def write(self, frame: int, values, mask) -> None:
        """Key the motors in `mask` at `values` on this frame.

        A key already there takes them on beside what it keys; otherwise one
        is made, holding the curve's own value for every motor it leaves out
        (never read, but a key looked at in isolation then says the truth).
        """
        frame = int(frame)
        values = np.asarray(values, np.float32).reshape(-1)
        mask = np.asarray(mask, bool).reshape(-1)
        if not mask.any():
            return
        values = self._legal(values)
        if self.family == "lift" and READING == "machine":
            # Row 1 has no jack: whatever is asked of it, it stays.
            values = values.copy()
            values[NO_JACK] = self.at(frame).reshape(-1)[NO_JACK]
        at = self.index(frame)
        if at is None:
            base = self.at(frame).reshape(-1)
            spot = bisect_left(self.frames, frame)
            self.frames.insert(spot, frame)
            self.values.insert(spot, np.where(mask, values, base).astype(np.float32))
            self.keyed.insert(spot, mask.copy())
        else:
            self.values[at] = np.where(mask, values, self.values[at]).astype(np.float32)
            self.keyed[at] = self.keyed[at] | mask
        self._changed()

    def merge(self, frames, values, keyed) -> None:
        """Many keys at once: what `write` does for each of them, but in one
        go -- a piece turned into keys writes hundreds of frames, and each
        `write` looks the whole track over again. (K,) frames, (K, size)
        values, and which motors each keys. The lowest ring's jack is left
        to what it had: it has none."""
        frames = np.asarray(frames, np.int64).reshape(-1)
        if not len(frames):
            return
        values = self._legal(np.asarray(values, np.float32).reshape(len(frames), self.size))
        keyed = np.asarray(keyed, bool).reshape(len(frames), self.size).copy()
        if self.family == "lift" and READING == "machine":
            keyed[:, NO_JACK] = False
        order = np.argsort(frames, kind="stable")
        frames, values, keyed = frames[order], values[order], keyed[order]
        old = np.asarray(self.frames, np.int64)
        every = np.union1d(old, frames)
        count = len(every)
        table = np.zeros((count, self.size), np.float32)
        which = np.zeros((count, self.size), bool)
        if len(old):
            at = np.searchsorted(every, old)
            table[at] = np.stack(self.values)
            which[at] = np.stack(self.keyed)
        at = np.searchsorted(every, frames)
        table[at] = np.where(keyed, values, table[at])
        which[at] |= keyed
        # A slot no motor is keyed in says what the motor holds there, as a
        # key made by `write` does; the curve never reads it.
        rows = np.arange(count)[:, None]
        before = np.maximum.accumulate(np.where(which, rows, -1), axis=0)
        after = np.minimum.accumulate(np.where(which, rows, count)[::-1], axis=0)[::-1]
        source = np.where(before >= 0, before, np.where(after < count, after, -1))
        columns = np.arange(self.size)[None, :]
        held = np.where(source >= 0, table[np.clip(source, 0, count - 1), columns],
                        REST[self.family])
        table = np.where(which, table, held).astype(np.float32)
        live = which.any(axis=1)
        self.frames = [int(f) for f in every[live]]
        self.values = [table[k] for k in np.nonzero(live)[0]]
        self.keyed = [which[k] for k in np.nonzero(live)[0]]
        self._changed()

    def _legal(self, values: np.ndarray) -> np.ndarray:
        low, high = RANGE[self.family]
        values = np.clip(values, low, high)
        if self.family == "lift":
            values = np.round(values)
        return values

    def remove(self, index: int, mask=None) -> None:
        """Take a key away, or only some of the motors it keys."""
        if mask is None:
            left = np.zeros(self.size, bool)
        else:
            left = self.keyed[index] & ~np.asarray(mask, bool).reshape(-1)
        if left.any():
            self.keyed[index] = left
        else:
            del self.frames[index], self.values[index], self.keyed[index]
        self._changed()

    def move(self, index: int, frame: int, mask=None) -> int:
        """Slide a key to another frame; returns where it now is.

        Onto another key it merges, what it keys winning, so dragging a pose
        onto an existing one never silently loses either. With `mask`, only
        those motors' part of the key goes -- a ring's share of a stroke,
        dragged on the ring's own lane -- and the rest stays where it was.
        """
        frame = max(0, int(frame))
        if self.frames[index] == frame:
            return index
        if mask is not None:
            part = self.keyed[index] & np.asarray(mask, bool).reshape(-1)
            if not part.any():
                return index
            if (self.keyed[index] & ~part).any():
                values = self.values[index]
                self.remove(index, part)
                self.write(frame, values, part)
                return self.index(frame)
        values, keyed = self.values[index], self.keyed[index]
        del self.frames[index], self.values[index], self.keyed[index]
        other = self.index(frame)
        if other is not None:
            self.values[other] = np.where(keyed, values, self.values[other])
            self.keyed[other] = self.keyed[other] | keyed
            self._changed()
            return other
        spot = bisect_left(self.frames, frame)
        self.frames.insert(spot, frame)
        self.values.insert(spot, values)
        self.keyed.insert(spot, keyed)
        self._changed()
        return spot

    def segments(self, motor: int) -> list:
        """One motor's keys as the exporter's segments, and its start.

        (value at frame 0, [(frame, start, dest, length), ...]). A pair of
        keys with the same value is a hold, which a motor JSON says by saying
        nothing.
        """
        frames, values, keyed, _, _ = self._stacked()
        mine = np.nonzero(keyed[:, motor])[0] if len(frames) else []
        if len(mine) == 0:
            return REST[self.family], []
        at = frames[mine]
        held = values[mine, motor].astype(np.float64)
        moves = np.nonzero(np.abs(np.diff(held)) >= 1e-6)[0]
        out = list(zip(at[moves].tolist(), held[moves].tolist(), held[moves + 1].tolist(),
                       (at[moves + 1] - at[moves]).tolist()))
        return float(held[0]), out


# -- the limits ---------------------------------------------------------------

def gaps_around(lift) -> tuple[np.ndarray, np.ndarray]:
    """The jack state of the gap below and above each ring, inf for none.

    The machine's reading: jack N (from zero) opens the gap under ring N, so
    the lowest ring stands on the base with nothing below it, and jack 0 is
    not there. Cinema 4D's own rule reads exactly so: ring r between up[r]
    and up[r+1], the lowest ring by up[1] alone, the top one by up[29].
    """
    lift = np.asarray(lift, np.float64).reshape(ROWS)
    below = np.full(ROWS, np.inf)
    above = np.full(ROWS, np.inf)
    if READING == "machine":
        below[1:] = lift[1:]
        above[:-1] = lift[1:]
    else:
        below[1:] = lift[:-1]
        above[:-1] = lift[:-1]
    return below, above


def tilt_reach(lift) -> np.ndarray:
    """Cinema 4D's reach: how far each ring's cells may tilt, either way, in
    JSON units, by the narrower of the two gaps beside the ring."""
    below, above = gaps_around(lift)
    narrow = np.minimum(below, above)
    return np.where(narrow < 1.0, TILT_REACH[0],
                    np.where(narrow < 2.0, TILT_REACH[1], TILT_REACH[2]))


def _houdini_degrees(state) -> np.ndarray:
    """Houdini's ramp: a gap, as its jack's state, to the degrees a cell may
    swing towards it -- 0 mm 2, 330 mm 10, 660 and up 45, straight between.
    The ramp is on the rig's mask, millimetres over the whole travel, so a
    jack half way between two places is half way between their millimetres.
    None (inf) is no neighbour at all, and no limit from it."""
    state = np.asarray(state, np.float64)
    free = ~np.isfinite(state)
    mask = kinetic._state_mm(np.where(free, 3.0, state)) / kinetic.JACK_STATE_MM[3]
    degrees = np.interp(mask, HOUDINI_RAMP[0], HOUDINI_RAMP[1]) * 45.0
    return np.where(free, 45.0, degrees)


def tilt_bounds(lift, push=None, rule: str | None = None):
    """How far each cell may tilt each way, JSON units: (lowest, highest),
    (ROWS, PER_ROW) each.

    Houdini's rule (anim_simple, `rotate_clamp`), the one in force: a cell
    turning its face down swings into the gap under its ring and is held by
    that gap alone; face up, by the gap over it -- through the ramp above,
    the lowest ring having nothing under it and the top one nothing over.
    Then the beam: a cell whose pusher is out less than 0.1 tilts 30 degrees
    at most, from 0.2 out 45, straight between. A positive tilt is face down
    (the viewer's reading, and Houdini's negative: its exporter inverts).

    Cinema 4D's rule, kept beside it: the narrower gap, the same both ways,
    0, 10 or 30 degrees, and no beam.
    """
    rule = rule or TILT_RULE
    if rule == "c4d":
        reach = np.repeat(tilt_reach(lift)[:, None], PER_ROW, axis=1)
        return -reach, reach
    below, above = gaps_around(lift)
    down = np.repeat(_houdini_degrees(below)[:, None], PER_ROW, axis=1)
    up = np.repeat(_houdini_degrees(above)[:, None], PER_ROW, axis=1)
    push = (np.zeros((ROWS, GROUPS)) if push is None
            else np.asarray(push, np.float64).reshape(ROWS, GROUPS))
    beam = np.interp(spread("push", push), [BEAM_PUSH[0], BEAM_PUSH[1]],
                     [BEAM_DEGREES[0], BEAM_DEGREES[1]])
    return (-np.minimum(up, beam) / kinetic.TILT_DEGREES,
            np.minimum(down, beam) / kinetic.TILT_DEGREES)


def clamp_tilt(tilt, lift, push=None) -> np.ndarray:
    low, high = tilt_bounds(lift, push)
    return np.clip(np.asarray(tilt, np.float32).reshape(ROWS, PER_ROW),
                   low, high).astype(np.float32)


def over_limit(tilt, lift, push=None) -> np.ndarray:
    """Which cells tilt further than their gaps and their beam allow."""
    low, high = tilt_bounds(lift, push)
    tilt = np.asarray(tilt).reshape(ROWS, PER_ROW)
    return (tilt > high + 1e-4) | (tilt < low - 1e-4)


# -- keys in the file -----------------------------------------------------------

def tracks_to_dict(tracks: dict) -> dict:
    """A family's keys as the project file keeps them: a frame, the values,
    and which motors it keys as a string of 0 and 1."""
    out = {}
    for family, track in tracks.items():
        out[family] = [{
            "frame": int(frame),
            "values": [round(float(v), 5) for v in values],
            "keyed": "".join("1" if k else "0" for k in keyed),
        } for frame, values, keyed in zip(track.frames, track.values, track.keyed)]
    return out


def tracks_from_dict(data: dict, tracks: dict, called: str) -> None:
    for family in FAMILIES:
        track = tracks[family]
        for key in (data or {}).get(family, []):
            values = np.asarray(key["values"], np.float32)
            keyed = np.frombuffer(key["keyed"].encode("ascii"), np.uint8) == ord("1")
            if values.size != track.size or keyed.size != track.size:
                raise ModelError(tr("{0}: ключ не того размера", called))
            track.write(int(key["frame"]), values, keyed)


# -- a whole piece -----------------------------------------------------------

class Project:
    """Everything an artist has made: the tracks, the length, the media."""

    def __init__(self, length: int = FPS * 60, empty: bool = False) -> None:
        self.length = int(length)
        self.tracks = {family: Track(family) for family in FAMILIES}
        self.video = ""
        self.sound = ""
        self.name = "kinetic"
        self.path: Path | None = None
        # The vase profile each push key was last shaped with, by frame, so
        # it can be taken up again rather than drawn from nothing.
        self.profiles: dict = {}
        # Masks by name, a weight 0..1 a cell (flat, CELLS), and the solids
        # the honeycomb wraps (`kin_prims`), with how often a moving one is
        # keyed when they are turned into keys.
        self.masks: dict = {}
        self.primitives: list = []
        self.prim_step = PRIM_STEP
        # The layers under the keys, as Blender's NLA (`kin_layers`): the
        # clips by name, and the layers from the bottom up, each with its
        # strips -- where a clip plays, how, and how strongly.
        self.clips: dict = {}
        self.layers: list = []
        # Whether the simulation and the export get the piece as a plan of
        # moves the machine carries out (`kin_plan`), and its tolerance.
        self.plan = True
        self.tolerance = PLAN_TOLERANCE
        # Bumped by whatever changes the masks, the primitives or the layers,
        # which have no versions of their own.
        self.revision = 0
        if not empty:
            for family in FAMILIES:
                track = self.tracks[family]
                track.write(0, np.full(track.size, REST[family]),
                            np.ones(track.size, bool))

    def pose(self, frame: float) -> dict:
        """Where every motor is at a frame: its keys where it has any, the
        layers under them where it has none."""
        keys = {family: self.tracks[family].at(frame) for family in FAMILIES}
        if not self.layers:
            return keys
        import kin_layers
        return kin_layers.under_keys(self, frame, keys)

    def key_frames(self) -> list[int]:
        """Every frame any track has a key on."""
        seen = set()
        for track in self.tracks.values():
            seen.update(track.frames)
        return sorted(seen)

    def violations(self) -> list[tuple[int, int]]:
        """(frame, cells over the limit) at every key where there are any.

        At keys only. Whether the motion between keys stays legal -- a jack
        still closing while its neighbours tilt -- is the simulation's
        question, the next stage.
        """
        found = []
        for frame in self.key_frames():
            pose = self.pose(frame)
            count = int(over_limit(pose["tilt"], pose["lift"], pose["push"]).sum())
            if count:
                found.append((frame, count))
        return found

    def state(self):
        # A clip is never changed once made, so the clips are kept as they
        # are; the layers and their strips are, and are copied.
        return ({family: track.state() for family, track in self.tracks.items()},
                self.length, dict(self.profiles), dict(self.masks),
                [one.state() for one in self.primitives], self.prim_step,
                dict(self.clips), [one.state() for one in self.layers],
                self.plan, self.tolerance)

    def restore(self, state) -> None:
        import kin_layers
        import kin_prims
        (tracks, self.length, profiles, masks, primitives, self.prim_step,
         clips, layers, self.plan, self.tolerance) = state
        self.profiles = dict(profiles)
        self.masks = dict(masks)
        self.primitives = [kin_prims.Primitive.from_state(one) for one in primitives]
        self.clips = dict(clips)
        self.layers = [kin_layers.Layer.from_state(one) for one in layers]
        for family, one in tracks.items():
            self.tracks[family].restore(one)
        self.revision += 1

    def changed(self) -> None:
        """The masks or the primitives were changed."""
        self.revision += 1

    def copy(self) -> "Project":
        """A piece of its own with everything this one has, to work on
        elsewhere -- on another thread -- while this one goes on changing.
        Cheap: the keys' arrays are never changed in place, so they are
        shared rather than copied."""
        other = Project(self.length, empty=True)
        other.restore(self.state())
        other.name, other.video, other.sound, other.path = (self.name, self.video,
                                                            self.sound, self.path)
        return other

    @property
    def version(self) -> tuple:
        return (tuple(self.tracks[f].version for f in FAMILIES)
                + (self.length, self.revision))

    # -- the project file ---------------------------------------------------

    def to_dict(self) -> dict:
        tracks = tracks_to_dict(self.tracks)
        return {
            "format": FORMAT, "version": VERSION, "fps": FPS,
            "name": self.name, "length": self.length,
            "media": {"video": self.video, "sound": self.sound},
            "tracks": tracks,
            "profiles": {str(frame): points
                         for frame, points in self.profiles.items()},
            "masks": {name: [round(float(v), 3) for v in weights]
                      for name, weights in self.masks.items()},
            "primitives": [one.to_dict() for one in self.primitives],
            "prim_step": int(self.prim_step),
            "clips": {name: clip.to_dict() for name, clip in self.clips.items()},
            "layers": [one.state() for one in self.layers],
            "plan": bool(self.plan), "tolerance": float(self.tolerance),
        }

    def save(self, path: str | Path) -> None:
        path = Path(path)
        data = self.to_dict()
        data["media"] = {key: _relative(value, path.parent)
                         for key, value in data["media"].items()}
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        temporary = path.with_name(path.name + ".writing")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
        self.path = path

    @classmethod
    def load(cls, path: str | Path) -> "Project":
        path = Path(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as error:  # noqa: BLE001 -- said to whoever opened it
            raise ModelError(f"{path.name}: {error}") from error
        if not isinstance(data, dict) or data.get("format") != FORMAT:
            raise ModelError(tr("{0} — не проект редактора кинетики", path.name))
        project = cls(int(data.get("length") or FPS * 60), empty=True)
        project.name = str(data.get("name") or path.stem)
        media = data.get("media") or {}
        project.video = _absolute(media.get("video", ""), path.parent)
        project.sound = _absolute(media.get("sound", ""), path.parent)
        tracks_from_dict(data.get("tracks"), project.tracks, path.name)
        project.profiles = {int(frame): points for frame, points
                            in (data.get("profiles") or {}).items()}
        import kin_prims
        for name, weights in (data.get("masks") or {}).items():
            weights = np.clip(np.asarray(weights, np.float32), 0.0, 1.0)
            if weights.size != CELLS:
                raise ModelError(tr("{0}: маска не того размера", path.name))
            project.masks[str(name)] = weights
        try:
            project.primitives = [kin_prims.Primitive.from_state(one)
                                  for one in data.get("primitives") or []]
        except (KeyError, TypeError, ValueError) as error:
            raise ModelError(f"{path.name}: {error}") from error
        project.prim_step = int(data.get("prim_step") or PRIM_STEP)
        project.plan = bool(data.get("plan", True))
        project.tolerance = float(data.get("tolerance", PLAN_TOLERANCE))
        import kin_layers
        try:
            project.clips = {str(name): kin_layers.Clip.from_dict(one, path.name)
                             for name, one in (data.get("clips") or {}).items()}
            project.layers = [kin_layers.Layer.from_state(one)
                              for one in data.get("layers") or []]
        except (KeyError, TypeError, ValueError) as error:
            raise ModelError(f"{path.name}: {error}") from error
        for family in FAMILIES:
            # A family with no keys at all is a piece from before there were
            # any -- unless there are layers, where empty keys are the point.
            if not len(project.tracks[family]) and not project.layers:
                track = project.tracks[family]
                track.write(0, np.full(track.size, REST[family]),
                            np.ones(track.size, bool))
        project.path = path
        return project


def _relative(value: str, folder: Path) -> str:
    if not value:
        return ""
    try:
        return str(Path(value).resolve().relative_to(folder.resolve()))
    except ValueError:
        return str(value)


def _absolute(value: str, folder: Path) -> str:
    if not value:
        return ""
    path = Path(value)
    return str(path if path.is_absolute() else (folder / path).resolve())


# -- to and from the motor JSON ------------------------------------------------

def _number(value: float, family: str):
    """As the exporter writes it: whole numbers bare, the rest to 4 places."""
    if family == "lift":
        return int(round(value))
    value = round(float(value), 4)
    return int(value) if float(value).is_integer() else value


def to_motor_json(project: Project, name: str | None = None) -> dict:
    """The piece as one motor JSON, the kind Houdini's exporter writes.

    Every motor gets a zero-length segment at frame 0 saying where it starts,
    as Cinema 4D's exporter does, so a file played after another begins from
    its own pose rather than from wherever the last one left it. The last
    frame gets one more on the first jack, standing still: the show editor
    makes a file as long as its last command, and this is what makes it as
    long as the piece rather than as long as its last movement.
    """
    data: dict = {}
    last = 0
    for family in FAMILIES:
        track = project.tracks[family]
        group = JSON_GROUP[family]
        for motor in range(track.size):
            row, which = motor_address(family, motor)
            first, moves = track.segments(motor)
            segments = [{"frame": 0, "start": _number(first, family),
                         "dest": _number(first, family), "length": 0}]
            for frame, start, dest, length in moves:
                segments.append({"frame": frame,
                                 "start": _number(start, family),
                                 "dest": _number(dest, family),
                                 "length": length})
                last = max(last, frame + length)
            data.setdefault(f"row_{row + 1}", {}).setdefault(group, {})[
                f"id_{which + 1}"] = segments
    end = max(project.length - 1, last)
    if end > last:
        lift = project.tracks["lift"].at(end).reshape(-1)
        held = _number(float(lift[0]), "lift")
        data["row_1"]["jack"]["id_1"].append(
            {"frame": end, "start": held, "dest": held, "length": 0})
    return {
        "name": name or project.name,
        "type": "kinematic_preset",
        "data": data,
        "info": {
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "version": "1",
            "export_range": {"start": 0, "end": end},
            "total_frames": end + 1,
            "part": 1,
            "total_parts": 1,
            "fps": FPS,
        },
    }


def export_motor_json(project: Project, path: str | Path) -> Path:
    """Write the piece as `<name>_1_of_1.json` beside `path`, or at it."""
    path = Path(path)
    if not path.stem.endswith("_of_1"):
        path = path.with_name(f"{path.stem}_1_of_1.json")
    payload = to_motor_json(project, path.stem.removesuffix("_1_of_1"))
    temporary = path.with_name(path.name + ".writing")
    temporary.write_text(json.dumps(payload, indent=4), encoding="utf-8")
    temporary.replace(path)
    return path


def from_motor_json(path: str | Path) -> tuple["Project", list[str]]:
    """A motor JSON, and the parts beside it, as keys. And what was odd.

    Every end of every segment becomes a key of that motor alone, valued off
    the viewer's own reading of the file, so writing it straight back out
    gives the same commands. Two things cannot come through exactly and are
    said instead: a segment that starts somewhere other than where its motor
    was (a jump, which keys cannot say), and segments that overlap.
    """
    path = Path(path)
    try:
        motors = kinetic.Motors(kinetic.parts_beside(path))
    except kinetic.KineticError as error:
        raise ModelError(str(error)) from error
    if motors.fps != FPS:
        raise ModelError(tr("{0}: {1:g} к/с, а редактор работает в {2} к/с",
                            path.name, motors.fps, FPS))
    project = Project(max(motors.frames, 1), empty=True)
    project.name = path.stem.split("_1_of_")[0]
    said = []
    ends: dict = {}
    moves: dict = {}
    overlaps: set = set()
    starts_off: set = set()
    jumps = 0
    for part in motors.parts:
        for row_key, groups in part.data.items():
            row = kinetic._number(row_key) - 1
            if not 0 <= row < ROWS or not isinstance(groups, dict):
                continue
            for group, ids in groups.items():
                family = FAMILY_OF.get(group)
                if family is None or not isinstance(ids, dict):
                    continue
                per = 1 if family == "lift" else (
                    GROUPS if family == "push" else PER_ROW)
                for id_key, segments in ids.items():
                    which = 0 if family == "lift" else kinetic._number(id_key) - 1
                    if not 0 <= which < per:
                        continue
                    motor = row * per + which if family != "lift" else row
                    mine = ends.setdefault((family, motor), {0})
                    spans = moves.setdefault((family, motor), [])
                    for pass_no in range(part.repeats):
                        opens = part.first + pass_no * part.length
                        for one in segments:
                            if not isinstance(one, dict):
                                continue
                            first = int(one.get("frame", 0)) + opens
                            length = max(0, int(one.get("length", 0)))
                            mine.add(first)
                            mine.add(first + length)
                            spans.append((first, length,
                                          float(one.get("start", 0.0))))
    last = motors.frames - 1
    curves = {"lift": motors.jack,
              "push": motors.pusher.reshape(ROWS * GROUPS, -1),
              "tilt": motors.tilt.reshape(ROWS * PER_ROW, -1)}
    # A motor whose segments overlap, or start somewhere it was not, has a
    # curve keys between segment ends cannot draw. It gets a key on every
    # frame from the first such place to its last movement instead, which is
    # the viewer's own reading of it, exact on every frame.
    for (family, motor), spans in moves.items():
        curve = curves[family][motor]
        spans.sort()
        reached, running_from = -1, 0
        odd_from = None
        for first, length, start in spans:
            before = curve[max(0, min(first - 1, last))]
            jumped = first > 0 and abs(start - float(before)) > 1e-4
            if first < reached or jumped:
                # From the start of whatever this cuts into, not from here:
                # the keys before that point still have to draw it whole.
                opening = running_from if first < reached else first
                odd_from = opening if odd_from is None else min(odd_from, opening)
                (overlaps if first < reached else starts_off).add((family, motor))
            if first + length >= reached:
                reached, running_from = first + length, first
        if odd_from is not None:
            ends[(family, motor)].update(
                range(max(0, odd_from - 1), min(reached, last) + 1))
    for family in FAMILIES:
        track = project.tracks[family]
        curve = curves[family]
        frames = sorted({min(frame, last) for (fam, _), got in ends.items()
                         if fam == family for frame in got} | {0})
        index = {frame: at for at, frame in enumerate(frames)}
        keyed = np.zeros((len(frames), track.size), bool)
        keyed[0, :] = True
        for (fam, motor), got in ends.items():
            if fam != family:
                continue
            for frame in got:
                keyed[index[min(frame, last)], motor] = True
        values = curve[:, frames].T.astype(np.float32)
        if family == "lift":
            fractional = np.abs(values - np.round(values)) > 1e-3
            jumps += int((fractional & keyed).sum())
        track.frames = list(frames)
        track.values = [values[k] for k in range(len(frames))]
        track.keyed = [keyed[k] for k in range(len(frames))]
        track._changed()
    for family in FAMILIES:
        if not len(project.tracks[family]):
            track = project.tracks[family]
            track.write(0, np.full(track.size, REST[family]),
                        np.ones(track.size, bool))
    if jumps:
        said.append(tr("ключей домкратов между положениями: {0}", jumps))
    first_row = np.array([one[NO_JACK] for one in project.tracks["lift"].values])
    if READING == "machine" and np.ptp(first_row) > 1e-6:
        said.append(tr("домкрат ряда 1 двигается, а у машины его нет — файл "
                       "пронумерован как в Houdini, подъём сдвинут на кольцо"))
    if overlaps:
        said.append(tr("моторов с наложенными сегментами: {0}", len(overlaps)))
    if starts_off:
        said.append(tr("моторов, где сегмент начат не с места мотора: {0}",
                       len(starts_off)))
    over = project.violations()
    if over:
        said.append(tr("сот вне предела наклона: {0} на {1} ключах",
                       sum(n for _, n in over), len(over)))
    return project, said


# -- what the tools do -----------------------------------------------------------

def cell_mask_for(family: str, cells) -> np.ndarray:
    """Which motors of a family the chosen cells belong to, flat."""
    cells = np.asarray(cells, bool).reshape(ROWS, PER_ROW)
    if family == "lift":
        return cells.any(axis=1)
    if family == "push":
        return cells.reshape(ROWS, GROUPS, PER_PUSHER).any(axis=2).reshape(-1)
    return cells.reshape(-1)


def spread(family: str, values) -> np.ndarray:
    """A family's values laid out on the cells, (ROWS, PER_ROW)."""
    values = np.asarray(values, np.float32)
    if family == "lift":
        return np.repeat(values.reshape(ROWS, 1), PER_ROW, axis=1)
    if family == "push":
        return np.repeat(values.reshape(ROWS, GROUPS), PER_PUSHER, axis=1)
    return values.reshape(ROWS, PER_ROW)


def brush(track: Track, frame: int, weights, target: float,
          strength: float = 1.0, mode: str = "paint", base=None):
    """One dab of the brush on a family: (values, which motors it keys).

    `weights` is how much of the brush each cell is under, 0..1. A cell
    takes the brush in proportion, towards `target` in the family's own
    units; a pusher answers to the most-covered of its five cells and a jack
    to the most-covered cell of its ring -- what is touched moves, which is
    what a brush is for. Houdini's own default for pushers is the centre cell
    of the five; that is for procedural masks, where every cell of a group
    contributing its own ripple makes the pusher shiver.

    A jack has four places, so it goes to the target outright once the brush
    covers its ring past half, and stays otherwise. `base` is where the
    motors stand now -- the layers under the keys included -- when it is
    not the track's own curve.
    """
    weights = np.clip(np.asarray(weights, np.float32).reshape(ROWS, PER_ROW),
                      0.0, 1.0) * float(strength)
    base = (track.at(frame) if base is None else np.asarray(base)).reshape(-1).astype(
        np.float32)
    if mode == "erase":
        target, mode = REST[track.family], "paint"
    if track.family == "lift":
        cover = weights.max(axis=1)
        mask = cover >= 0.5
        if mode == "smooth":
            level = base.reshape(ROWS)
            around = np.convolve(np.pad(level, 1, mode="edge"),
                                 np.ones(3) / 3.0, mode="valid")
            values = np.where(mask, np.round(around), level)
        else:
            values = np.where(mask, float(target), base)
        return values.astype(np.float32), mask
    if track.family == "push":
        cover = weights.reshape(ROWS, GROUPS, PER_PUSHER).max(axis=2).reshape(-1)
        grid = base.reshape(ROWS, GROUPS)
        if mode == "smooth":
            around = (np.roll(grid, 1, axis=1) + np.roll(grid, -1, axis=1)
                      + np.vstack([grid[:1], grid[:-1]])
                      + np.vstack([grid[1:], grid[-1:]]) + grid) / 5.0
            goal = around.reshape(-1)
        else:
            goal = np.full_like(base, float(target))
    else:
        cover = weights.reshape(-1)
        grid = base.reshape(ROWS, PER_ROW)
        if mode == "smooth":
            around = (np.roll(grid, 1, axis=1) + np.roll(grid, -1, axis=1)
                      + np.vstack([grid[:1], grid[:-1]])
                      + np.vstack([grid[1:], grid[-1:]]) + grid) / 5.0
            goal = around.reshape(-1)
        else:
            goal = np.full_like(base, float(target))
    mask = cover > 1e-3
    values = base + (goal - base) * np.clip(cover, 0.0, 1.0)
    return values.astype(np.float32), mask


# -- the vase -------------------------------------------------------------------

def profile_curve(points, count: int = ROWS) -> np.ndarray:
    """A vase profile through its points, sampled at each ring.

    `points` are (height, reach): height 0 the lowest ring and 1 the top,
    reach 0..1 of the pusher's travel. Monotone cubic between them, so the
    curve never swings past a point towards a pusher position that is not
    there -- a vase drawn to 1.0 at its lip must not ask for 1.07 on the way.
    """
    pts = sorted((float(h), float(v)) for h, v in points)
    if not pts:
        return np.zeros(count, np.float32)
    xs = np.array([p[0] for p in pts])
    ys = np.array([p[1] for p in pts])
    at = np.linspace(0.0, 1.0, count)
    if len(pts) == 1:
        return np.clip(np.full(count, ys[0]), 0, 1).astype(np.float32)
    # Fritsch-Carlson slopes.
    h = np.diff(xs)
    h[h == 0] = 1e-9
    delta = np.diff(ys) / h
    slopes = np.zeros(len(xs))
    slopes[0], slopes[-1] = delta[0], delta[-1]
    for i in range(1, len(xs) - 1):
        if delta[i - 1] * delta[i] <= 0:
            slopes[i] = 0.0
        else:
            w1 = 2 * h[i] + h[i - 1]
            w2 = h[i] + 2 * h[i - 1]
            slopes[i] = (w1 + w2) / (w1 / delta[i - 1] + w2 / delta[i])
    out = np.empty(count)
    for n, x in enumerate(at):
        if x <= xs[0]:
            out[n] = ys[0]
            continue
        if x >= xs[-1]:
            out[n] = ys[-1]
            continue
        i = int(np.searchsorted(xs, x) - 1)
        t = (x - xs[i]) / h[i]
        t2, t3 = t * t, t * t * t
        out[n] = ((2 * t3 - 3 * t2 + 1) * ys[i] + (t3 - 2 * t2 + t) * h[i] * slopes[i]
                  + (-2 * t3 + 3 * t2) * ys[i + 1] + (t3 - t2) * h[i] * slopes[i + 1])
    return np.clip(out, 0.0, 1.0).astype(np.float32)


# -- the auto-rotate -------------------------------------------------------------

# How high each ring sits when every jack is at rest, in metres: the rig's
# ring pitch (kinetic, 27.80 cm at state 1). The window hands over the real
# heights off the geometry; this is for when there is none.
RING_PITCH_M = 0.278


def ring_heights(lift, base=None) -> np.ndarray:
    """Where each ring's middle stands, in metres, with the jacks as given."""
    base = (np.arange(ROWS) * RING_PITCH_M if base is None
            else np.asarray(base, np.float64).reshape(ROWS))
    lift = np.asarray(lift, np.float64).reshape(ROWS)
    return base + kinetic.rise_mm(lift, READING) / 1000.0


def cell_azimuths() -> np.ndarray:
    """Where each cell stands round the building, degrees, (ROWS, PER_ROW)."""
    row = np.arange(ROWS)[:, None]
    origin = np.where((row + 1) % 2 == 0, kinetic.ID_ORIGIN_DEGREES[0],
                      kinetic.ID_ORIGIN_DEGREES[1])
    return (origin + np.arange(PER_ROW)[None, :] * kinetic.ID_STEP_DEGREES) % 360.0


def auto_tilt(lift, push, gain: float = 1.0, base=None) -> np.ndarray:
    """Each cell turned to face along the shape its ring and pushers make.

    Houdini's auto-rotate (SETUP_Example/rotate_auto): the surface the cells
    stand on after the jacks and pushers have moved, its slope taken up the
    building at every cell, and the cell swung to lie along it. Here the
    slope is the reach of the cells straight above and below -- the nearest
    one in each neighbouring ring -- over the height between them. A shape
    widening upwards tilts its cells down, which is the positive way.
    `gain` is Houdini's angle_max the other way up: 1 lies them flat on the
    surface, more exaggerates. Not limited; `clamp_tilt` does that.
    """
    heights = ring_heights(lift, base)
    reach = spread("push", push).astype(np.float64) * kinetic.PUSHER_MM / 1000.0
    azimuth = cell_azimuths()
    origin = azimuth[:, 0]

    def beside(row: int) -> np.ndarray:
        """The reach of the cell in `row` nearest above each cell of all."""
        slot = np.round(((azimuth - origin[row]) % 360.0)
                        / kinetic.ID_STEP_DEGREES).astype(int) % PER_ROW
        return reach[row][slot]

    tilt = np.zeros((ROWS, PER_ROW))
    for row in range(ROWS):
        low, high = max(0, row - 1), min(ROWS - 1, row + 1)
        if low == high:
            continue
        down = beside(low)[row] if low != row else reach[row]
        up = beside(high)[row] if high != row else reach[row]
        rise = heights[high] - heights[low]
        tilt[row] = np.degrees(np.arctan2(up - down, max(rise, 1e-6)))
    return (tilt * gain / kinetic.TILT_DEGREES).astype(np.float32)
