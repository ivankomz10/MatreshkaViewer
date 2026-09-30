"""Primitives the honeycomb wraps, and the masks that keep work to some cells.

A primitive is a solid standing by the building. Each cell looks along its
own ray -- straight out from the axis, the way its pusher drives it -- and
meets the solid or not:

  positive   a cell the solid has swallowed is pushed out to where its ray
             leaves the solid: the honeycomb takes the solid's shape, a
             bulge where a sphere sticks through it
  negative   a cell standing inside the solid is pulled back to where its
             ray enters it: an imprint, a dent the solid's shape

Its pusher moves five cells together, so a group goes as far as its most
swallowed cell needs (positive) or back as far as its deepest (negative).
With `tilt` on, each touched cell also turns to lie along the solid's surface
where it meets it -- its face along the surface's normal, as far as its gaps
and the beam allow. A primitive can keep to a mask, and its tilt to another.

Where a primitive stands, how big it is and how strongly it works are keys
of its own, eased between as the motors' are. What it does sits over the
keys: a positive one's push wins where it is further out, a negative one's
where it is further in, and its tilts where it touches. `compose` turns the
lot into keys of the same kind as the rest -- the motors can only ever do
moves from one key to the next, so it keys the result at the keys of the
piece and of its primitives, and between them the motors ease.

A mask is a weight on every cell, 0..1, kept by name in the piece: made
from what is chosen or painted with the brush. It keeps a primitive, or its
tilt, to its cells; and in the window, the one chosen for editing keeps
every edit made at the playhead to its cells (`motor_weights`).

Noise is a primitive too, as Houdini's animated noise: a field of smooth
random values wrapped round the building, drifting and changing in time,
that pushes the cells out (positive) or in (negative) and turns them. It
has the same seven keyed numbers, which for it say: drift round (degrees a
second), drift up (rings a second), the push it gives (metres), its size
(cells), how fast it changes (a second), the tilt it gives (degrees), and
its strength.

Placed in the building's own terms: azimuth round it in degrees (world, as
the cells' own), height in rings (0 the lowest, fractional between), and
the centre's distance out from the cells' surface in metres, negative for
inside. Sizes in metres: a sphere's radius; a box's half width round the
building, half height, and half depth outward.
"""
from __future__ import annotations

import math

import numpy as np

import kin_model as km
import kinetic
from kinetic import PER_PUSHER, PER_ROW, ROWS, smoothstep

KINDS = ("sphere", "box", "noise")
PARAMS = ("azimuth", "height", "offset", "width", "tall", "depth", "strength")
AZIMUTH, HEIGHT, OFFSET, WIDTH, TALL, DEPTH, STRENGTH = range(len(PARAMS))

# Where the cells' centres stand from the axis, at rest: the rigged surface.
CELL_RADIUS_M = 2.5266
REACH_M = kinetic.PUSHER_MM / 1000.0     # a pusher's whole travel


class Primitive:
    """One solid: what it is, how it acts, and its keys."""

    def __init__(self, kind: str = "sphere", name: str = "", azimuth: float = 0.0) -> None:
        self.kind = kind if kind in KINDS else "sphere"
        self.name = name or self.kind
        self.polarity = "positive"
        self.tilt = True
        self.mask = ""                  # the cells it may move, by mask name
        self.tilt_mask = ""             # the cells it may turn
        self.on = True
        self.seed = 0                   # the noise's own
        if self.kind == "noise":
            start = np.array([0.0, 0.0, 0.3, 6.0, 0.4, 15.0, 1.0], np.float64)
        else:
            start = np.array([azimuth, ROWS / 2.0, 0.25, 1.2, 1.2, 1.2, 1.0], np.float64)
        self.frames: list[int] = [0]
        self.values: list[np.ndarray] = [start]

    # -- keys --------------------------------------------------------------

    def index(self, frame: int):
        return self.frames.index(frame) if frame in self.frames else None

    def at(self, frame: float) -> np.ndarray:
        """Every parameter at a frame, eased between keys; the azimuth the
        short way round."""
        frames = self.frames
        if frame <= frames[0]:
            return self.values[0].copy()
        if frame >= frames[-1]:
            return self.values[-1].copy()
        k = int(np.searchsorted(frames, frame, side="right") - 1)
        a, b = self.values[k], self.values[k + 1]
        t = smoothstep((frame - frames[k]) / max(1, frames[k + 1] - frames[k]))
        out = a + (b - a) * t
        if self.kind != "noise":            # a noise's first number is a speed
            turn = (b[AZIMUTH] - a[AZIMUTH] + 180.0) % 360.0 - 180.0
            out[AZIMUTH] = (a[AZIMUTH] + turn * t) % 360.0
        return out

    def write(self, frame: int, values) -> None:
        values = np.asarray(values, np.float64).copy()
        values[STRENGTH] = min(1.0, max(0.0, values[STRENGTH]))
        for size in (WIDTH, TALL, DEPTH):
            values[size] = max(0.05, values[size])
        frame = int(frame)
        at = self.index(frame)
        if at is not None:
            self.values[at] = values
            return
        spot = int(np.searchsorted(self.frames, frame))
        self.frames.insert(spot, frame)
        self.values.insert(spot, values)

    def remove(self, index: int) -> None:
        if len(self.frames) > 1:
            del self.frames[index], self.values[index]

    def move(self, index: int, frame: int) -> None:
        values = self.values[index]
        del self.frames[index], self.values[index]
        self.write(max(0, int(frame)), values)

    # -- undo and the file ---------------------------------------------------

    def state(self) -> dict:
        return {"kind": self.kind, "name": self.name, "polarity": self.polarity,
                "tilt": self.tilt, "mask": self.mask, "tilt_mask": self.tilt_mask,
                "on": self.on, "seed": int(self.seed), "frames": list(self.frames),
                "values": [one.copy() for one in self.values]}

    @classmethod
    def from_state(cls, state: dict) -> "Primitive":
        one = cls(state.get("kind", "sphere"), state.get("name", ""))
        one.polarity = state.get("polarity", "positive")
        one.tilt = bool(state.get("tilt", True))
        one.mask = state.get("mask", "") or ""
        one.tilt_mask = state.get("tilt_mask", "") or ""
        one.on = bool(state.get("on", True))
        one.seed = int(state.get("seed", 0))
        one.frames = [int(f) for f in state["frames"]]
        one.values = [np.asarray(v, np.float64).copy() for v in state["values"]]
        return one

    def to_dict(self) -> dict:
        data = self.state()
        data["values"] = [[round(float(v), 5) for v in one] for one in self.values]
        return data


# -- noise ------------------------------------------------------------------------------

def _hash(ix, iy, iz, iw, seed: int) -> np.ndarray:
    """A lattice point's random value, -1..1, the same every time."""
    mix = (ix.astype(np.uint64) * np.uint64(0x9E3779B1)
           ^ iy.astype(np.uint64) * np.uint64(0x85EBCA77)
           ^ iz.astype(np.uint64) * np.uint64(0xC2B2AE3D)
           ^ iw.astype(np.uint64) * np.uint64(0x27D4EB2F)
           ^ np.uint64((seed * 0x165667B1) & 0xFFFFFFFF))
    mix = (mix ^ (mix >> np.uint64(15))) * np.uint64(0x2C1B3C6D)
    mix = (mix ^ (mix >> np.uint64(12))) * np.uint64(0x297A2D39)
    mix = mix ^ (mix >> np.uint64(15))
    return (mix & np.uint64(0xFFFF)).astype(np.float64) / 32767.5 - 1.0


def value_noise(x, y, z, w, seed: int = 0) -> np.ndarray:
    """Smooth 4D value noise, -1..1: random values on a lattice, eased
    between (quintic, so it has no creases)."""
    corners = [np.floor(c) for c in (x, y, z, w)]
    parts = [c - f for c, f in zip((x, y, z, w), corners)]
    ease = [p * p * p * (p * (p * 6.0 - 15.0) + 10.0) for p in parts]
    base = [f.astype(np.int64) for f in corners]
    out = np.zeros(np.shape(x), np.float64)
    for corner in range(16):
        bits = [(corner >> k) & 1 for k in range(4)]
        weight = np.ones_like(out)
        for bit, e in zip(bits, ease):
            weight = weight * (e if bit else 1.0 - e)
        out += weight * _hash(*(b + bit for b, bit in zip(base, bits)), seed)
    return out


def noise_field(values, frame: float, seed: int = 0) -> np.ndarray:
    """The noise over every cell at a frame, -1..1, (ROWS, PER_ROW): a
    field wrapped seamlessly round the building (the cells' own cylinder,
    a cell to a unit), `size` cells to a feature, drifting round and up and
    changing at its speed, two octaves."""
    seconds = float(frame) / km.FPS
    size = max(0.2, float(values[WIDTH]))
    azimuth = np.radians(km.cell_azimuths() - values[AZIMUTH] * seconds)
    radius = PER_ROW / (2.0 * math.pi)
    rings = np.arange(ROWS, dtype=np.float64)[:, None] * np.ones((1, PER_ROW))
    up = (rings - values[HEIGHT] * seconds) * math.sqrt(3.0) / 2.0
    x, y = radius * np.cos(azimuth), radius * np.sin(azimuth)
    time = seconds * max(0.0, float(values[TALL]))
    out = np.zeros((ROWS, PER_ROW))
    amplitude, scale, total = 1.0, 1.0 / size, 0.0
    for octave in range(2):
        out += amplitude * value_noise(x * scale, y * scale, up * scale,
                                       np.full_like(x, time * (1 + octave)), seed + octave)
        total += amplitude
        amplitude *= 0.5
        scale *= 2.0
    return np.clip(out / total * 1.6, -1.0, 1.0)


# -- where the cells look ---------------------------------------------------------

def rays(lift, base=None):
    """Every cell's centre at no push, and the way its pusher drives it:
    (origin, out), each (ROWS, PER_ROW, 3), in world metres."""
    azimuth = np.radians(km.cell_azimuths())
    out = np.stack([np.cos(azimuth), np.sin(azimuth), np.zeros_like(azimuth)], axis=-1)
    heights = km.ring_heights(lift, base)
    origin = out * CELL_RADIUS_M
    origin[..., 2] = heights[:, None]
    return origin, out


def ring_height(ring: float, base=None, lift=None) -> float:
    """A fractional ring's height, metres, with the jacks as given -- and
    past the lowest and the highest, on at the rings' own pitch, so a solid
    can stand under the building or over it and pass through."""
    heights = km.ring_heights(np.full(ROWS, km.REST["lift"]) if lift is None else lift,
                              base)
    ring = float(ring)
    if ring < 0:
        return float(heights[0] + ring * km.RING_PITCH_M)
    if ring > ROWS - 1:
        return float(heights[-1] + (ring - (ROWS - 1)) * km.RING_PITCH_M)
    return float(np.interp(ring, np.arange(ROWS), heights))


def frame_of(values, base=None, lift=None):
    """The primitive's centre and its own axes -- out, round, up -- in world."""
    azimuth = math.radians(values[AZIMUTH])
    out = np.array([math.cos(azimuth), math.sin(azimuth), 0.0])
    round_ = np.array([-math.sin(azimuth), math.cos(azimuth), 0.0])
    up = np.array([0.0, 0.0, 1.0])
    centre = out * (CELL_RADIUS_M + values[OFFSET])
    centre[2] = ring_height(values[HEIGHT], base, lift)
    return centre, out, round_, up


def hits(kind: str, values, origin, out, base=None, lift=None):
    """Where each cell's ray enters and leaves the solid, metres along it,
    and the solid's outward normal there: (t_in, t_out, n_in, n_out). A ray
    that misses has t_in = inf."""
    centre, e_out, e_round, e_up = frame_of(values, base, lift)
    shape = origin.shape[:-1]
    if kind == "sphere":
        radius = values[WIDTH]
        gap = origin - centre
        b = np.einsum("...i,...i->...", gap, out)
        c = np.einsum("...i,...i->...", gap, gap) - radius * radius
        disc = b * b - c
        root = np.sqrt(np.maximum(disc, 0.0))
        missed = disc <= 0
        t_in = np.where(missed, np.inf, -b - root)
        t_out = np.where(missed, -np.inf, -b + root)
        p_in = origin + out * np.where(missed, 0, t_in)[..., None]
        p_out = origin + out * np.where(missed, 0, t_out)[..., None]
        return (t_in, t_out, (p_in - centre) / radius, (p_out - centre) / radius)
    # A box: slabs in its own frame.
    axes = np.stack([e_out, e_round, e_up])                 # rows: local axes
    half = np.array([values[DEPTH], values[WIDTH], values[TALL]])
    local_origin = np.einsum("ij,...j->...i", axes, origin - centre)
    local_way = np.einsum("ij,...j->...i", axes, out)
    safe = np.where(np.abs(local_way) < 1e-9, 1e-9, local_way)
    t1 = (-half - local_origin) / safe
    t2 = (half - local_origin) / safe
    near = np.minimum(t1, t2)
    far = np.maximum(t1, t2)
    # A ray running parallel to a slab is in it or out of it for good.
    flat = np.abs(local_way) < 1e-9
    outside = flat & (np.abs(local_origin) > half)
    near = np.where(flat, -np.inf, near)
    far = np.where(flat, np.inf, far)
    t_in = near.max(axis=-1)
    t_out = far.min(axis=-1)
    missed = (t_in > t_out) | outside.any(axis=-1)
    enter_axis = near.argmax(axis=-1)
    leave_axis = far.argmin(axis=-1)
    sign_in = -np.sign(np.take_along_axis(local_way, enter_axis[..., None], -1))[..., 0]
    sign_out = np.sign(np.take_along_axis(local_way, leave_axis[..., None], -1))[..., 0]
    n_in = axes[enter_axis] * sign_in[..., None]
    n_out = axes[leave_axis] * sign_out[..., None]
    return (np.where(missed, np.inf, t_in), np.where(missed, -np.inf, t_out),
            n_in, n_out)


def facing_tilt(normal, out) -> np.ndarray:
    """The tilt that turns a cell's face along a normal, in JSON units: the
    normal's slope up the building, as the cell swings (plus is face down)."""
    along = np.einsum("...i,...i->...", normal, out)
    up = normal[..., 2]
    degrees = np.degrees(np.arctan2(-up, np.maximum(along, 1e-6)))
    return degrees / kinetic.TILT_DEGREES


# -- what the primitives do to a pose -------------------------------------------------

def apply(pose: dict, primitives, frame: float, masks: dict | None = None,
          base=None) -> dict:
    """The pose with every primitive that is on laid over it, in order."""
    active = [one for one in primitives if one.on]
    if not active:
        return pose
    masks = masks or {}
    lift = np.asarray(pose["lift"], np.float64)
    push = np.asarray(pose["push"], np.float64).reshape(ROWS, km.GROUPS).copy()
    tilt = np.asarray(pose["tilt"], np.float64).reshape(ROWS, PER_ROW).copy()
    origin, out = rays(lift, base)
    for one in active:
        values = one.at(frame)
        strength = float(values[STRENGTH])
        if strength <= 0:
            continue
        if one.kind == "noise":
            push, tilt = _noise(one, values, frame, strength, masks, push, tilt)
            continue
        t_in, t_out, n_in, n_out = hits(one.kind, values, origin, out, base, lift)
        now = np.repeat(push, PER_PUSHER, axis=1) * REACH_M     # metres out, a cell
        inside = (t_in <= now + 1e-9) & (now < t_out)
        weight = strength * _weights(masks, one.mask)
        if one.polarity == "negative":
            target = np.clip(t_in, 0.0, REACH_M)
            touched = inside & (target < now)
            wanted = np.where(touched, target, np.inf).reshape(ROWS, km.GROUPS, PER_PUSHER)
            deepest = wanted.min(axis=2)
            moving = np.isfinite(deepest)
            goal = np.where(moving, deepest / REACH_M, push)
            normal = -n_in
        else:
            target = np.clip(t_out, 0.0, REACH_M)
            touched = inside & (target > now)
            wanted = np.where(touched, target, -np.inf).reshape(ROWS, km.GROUPS, PER_PUSHER)
            furthest = wanted.max(axis=2)
            moving = np.isfinite(furthest)
            goal = np.where(moving, furthest / REACH_M, push)
            normal = n_out
        group_weight = weight.reshape(ROWS, km.GROUPS, PER_PUSHER).max(axis=2)
        push = np.where(moving, push + (goal - push) * group_weight, push)
        if one.tilt:
            lies = facing_tilt(normal, out)
            turn = (strength * _weights(masks, one.tilt_mask or one.mask)
                    * touched)
            tilt = tilt + (lies - tilt) * turn
    push = np.clip(push, 0.0, 1.0)
    # Only what the solids moved is held to its limits here: a cell past
    # them in the keys themselves is the keys' own red, not the solid's.
    was_push = np.asarray(pose["push"], np.float64).reshape(ROWS, km.GROUPS)
    was_tilt = np.asarray(pose["tilt"], np.float64).reshape(ROWS, PER_ROW)
    moved = (np.abs(tilt - was_tilt) > 1e-6) | np.repeat(
        np.abs(push - was_push) > 1e-6, PER_PUSHER, axis=1)
    if moved.any():
        tilt = np.where(moved, km.clamp_tilt(tilt, lift, push), was_tilt)
    return {"lift": pose["lift"], "push": push.astype(np.float32),
            "tilt": np.asarray(tilt, np.float32)}


def _noise(one, values, frame, strength, masks, push, tilt):
    """A noise over the pose: its push out (or in), 0..its push, a pusher by
    the middle of its five cells; its tilt either way, a cell by its own."""
    field = noise_field(values, frame, one.seed)
    sign = -1.0 if one.polarity == "negative" else 1.0
    weight = strength * _weights(masks, one.mask)
    middle = field[:, PER_PUSHER // 2::PER_PUSHER]
    group_weight = weight.reshape(ROWS, km.GROUPS, PER_PUSHER).max(axis=2)
    amount = float(values[OFFSET]) / REACH_M
    push = push + sign * amount * (middle * 0.5 + 0.5) * group_weight
    if one.tilt:
        turn = strength * _weights(masks, one.tilt_mask or one.mask)
        tilt = tilt + field * (float(values[DEPTH]) / kinetic.TILT_DEGREES) * turn
    return push, tilt


def _weights(masks: dict, name: str) -> np.ndarray:
    if not name or name not in masks:
        return np.ones((ROWS, PER_ROW))
    return np.clip(np.asarray(masks[name], np.float64).reshape(ROWS, PER_ROW), 0, 1)


# -- masks ------------------------------------------------------------------------------

def motor_weights(family: str, weights) -> np.ndarray:
    """A mask on the cells as a weight for each motor of a family, flat: a
    pusher as much as its most-weighted cell, a jack all or nothing -- in
    when its ring is half in or more, as the brush takes a jack."""
    weights = np.clip(np.asarray(weights, np.float64).reshape(ROWS, PER_ROW), 0, 1)
    if family == "lift":
        return (weights.max(axis=1) >= 0.5).astype(np.float64)
    if family == "push":
        return weights.reshape(ROWS, km.GROUPS, PER_PUSHER).max(axis=2).reshape(-1)
    return weights.reshape(-1)


def paint_mask(weights, dab, strength: float = 1.0, mode: str = "paint") -> np.ndarray:
    """One dab of the brush on a mask: towards 1 painting, towards 0
    erasing, towards its neighbours smoothing."""
    weights = np.clip(np.asarray(weights, np.float32).reshape(ROWS, PER_ROW), 0, 1)
    dab = np.clip(np.asarray(dab, np.float32).reshape(ROWS, PER_ROW), 0, 1) * strength
    if mode == "erase":
        out = weights * (1.0 - dab)
    elif mode == "smooth":
        around = (np.roll(weights, 1, axis=1) + np.roll(weights, -1, axis=1)
                  + np.vstack([weights[:1], weights[:-1]])
                  + np.vstack([weights[1:], weights[-1:]]) + weights) / 5.0
        out = weights + (around - weights) * dab
    else:
        out = weights + (1.0 - weights) * dab
    return np.clip(out, 0, 1).astype(np.float32).reshape(-1)


# -- the lot as keys ----------------------------------------------------------------------

def _frames_of(primitives, length: int, step: int) -> list:
    """Where the primitives want keys: at each of theirs, and every `step`
    frames between two of them that differ -- a solid moving is followed."""
    frames = set()
    for one in primitives:
        frames.update(one.frames)
        if one.kind == "noise":
            # It changes all the time, keys or not.
            frames.update(range(0, length, step))
            continue
        for k in range(len(one.frames) - 1):
            if not np.allclose(one.values[k], one.values[k + 1]):
                frames.update(range(one.frames[k] + step, one.frames[k + 1], step))
    return sorted(f for f in frames if 0 <= f < length)


def compose(project: km.Project, base=None) -> km.Project:
    """The piece with its primitives turned into keys, as the motors will
    run it; `project` itself is left as it is.

    Every motor a primitive ever moves is keyed where the solid wants it:
    at the primitive's keys and its steps between, wherever the solid moves
    it then or next to then -- so it goes in and comes out again -- and at
    its own keys, what it had there with the solid laid over. Everything
    else keeps its own keys exactly. What the simulation runs and what is
    exported.
    """
    primitives = [one for one in getattr(project, "primitives", []) if one.on]
    if not primitives:
        return project
    out = km.Project(project.length, empty=True)
    out.name = project.name
    for family in km.FAMILIES:
        out.tracks[family].restore(project.tracks[family].state())
    step = max(1, int(getattr(project, "prim_step", km.PRIM_STEP)))
    wanted = _frames_of(primitives, project.length, step)
    theirs = set(wanted)
    frames = theirs | set(project.tracks["push"].frames) | set(project.tracks["tilt"].frames)
    if getattr(project, "layers", None):
        # What the layers under the keys do moves too: their keys as well.
        import kin_layers
        frames |= set(kin_layers.frames(project))
    frames = sorted(frames)
    frames = [f for f in frames if 0 <= f < project.length]
    masks = getattr(project, "masks", {})
    made = {"push": [], "tilt": []}
    moved = {"push": [], "tilt": []}
    for frame in frames:
        pose = project.pose(frame)
        after = apply(pose, primitives, frame, masks, base)
        for family in ("push", "tilt"):
            now = np.asarray(after[family], np.float32).reshape(-1)
            was = np.asarray(pose[family], np.float32).reshape(-1)
            made[family].append(now)
            moved[family].append(np.abs(now - was) > 1e-5)
    is_theirs = np.array([f in theirs for f in frames])
    for family in ("push", "tilt"):
        hit = np.array(moved[family])
        ever = hit.any(axis=0)
        if not ever.any():
            continue
        near = hit.copy()
        near[1:] |= hit[:-1]
        near[:-1] |= hit[1:]
        source = project.tracks[family]
        when, rows, masks = [], [], []
        for i, frame in enumerate(frames):
            at = source.index(frame)
            own = source.keyed[at] if at is not None else np.zeros(source.size, bool)
            need = ever & (own | hit[i] | (near[i] & is_theirs[i]))
            if need.any():
                when.append(frame)
                rows.append(made[family][i])
                masks.append(need)
        out.tracks[family].merge(when, rows, masks)
    return out


def pose_at(project: km.Project, frame: float, pose=None, base=None) -> dict:
    """The piece at a frame with its primitives over its keys: what is shown."""
    pose = project.pose(frame) if pose is None else pose
    return apply(pose, getattr(project, "primitives", []), frame,
                 getattr(project, "masks", {}), base)


def bake(project: km.Project, base=None) -> int:
    """The primitives into the keys for good, and turned off: how many there
    were. Undo is the caller's."""
    done = compose(project, base)
    count = sum(1 for one in project.primitives if one.on)
    if done is project:
        return 0
    for family in km.FAMILIES:
        project.tracks[family].restore(done.tracks[family].state())
    for one in project.primitives:
        one.on = False
    project.changed()
    return count


def touched_cells(project: km.Project, primitive: "Primitive", frame: float,
                  base=None) -> np.ndarray:
    """Which cells one primitive moves or turns at a frame, (ROWS, PER_ROW)."""
    pose = project.pose(frame)
    was = primitive.on
    primitive.on = True
    try:
        after = apply(pose, [primitive], frame, getattr(project, "masks", {}), base)
    finally:
        primitive.on = was
    push = np.abs(km.spread("push", after["push"]) - km.spread("push", pose["push"])) > 1e-6
    tilt = np.abs(after["tilt"] - pose["tilt"]) > 1e-6
    return push | tilt
