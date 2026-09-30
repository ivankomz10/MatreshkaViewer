"""The layers under the keys, as Blender's NLA: clips, strips, and their blend.

A clip is keys of a stretch of a piece, from its own frame 0 -- what the
timeline held when it was put into a clip ("В клип", Blender's Push Down),
or what came from the library. A clip is never changed once made.

A layer holds strips; a strip plays one clip from a frame of the piece:

  mode        how it lies on what is under it: замена (replace), сложение
              (add -- its distance from rest is added) or максимум (max)
  influence   how strongly, 0..1; fade in and out over so many frames at
              its ends, eased
  repeat      whole times over; speed, played faster or slower; reverse,
              played backwards -- an in turned into an out
  hold        held at its last frame after its end, rather than letting go
  round       moved round the building by whole groups of five (36 degrees)
  rings       moved up or down by whole rings
  mask        kept to a mask's cells (`Project.masks`)

A clip says something only about the motors it keys. The layers are played
from the bottom up, each strip over what is under it; the keys on the
timeline lie over all of them -- a motor with keys of its own plays its keys,
as the active action does in Blender -- and the primitives over that.

A jack stands in one of four places: a strip moves it where its weight is
past half, and never leaves it standing between two. Pushers and tilts blend
continuously and are held to their limits, the tilts to their gaps, where a
strip moved them.

The motors can only ever go from one key to the next, so for the simulation
and the export the layers are turned into keys (`flatten`): at every clip's
keys where its strips play them, at every strip's ends, and every so many
frames through its fades -- on the motors the layers move and the keys
leave alone.
"""
from __future__ import annotations

import numpy as np

import kin_model as km
from kinetic import PER_PUSHER, smoothstep

MODES = ("replace", "add", "max")


class Clip:
    """Keys from frame 0: what a strip plays."""

    def __init__(self, length: int = 1) -> None:
        self.tracks = {family: km.Track(family) for family in km.FAMILIES}
        self.length = max(1, int(length))

    def pose(self, frame: float) -> dict:
        return {family: self.tracks[family].at(frame) for family in km.FAMILIES}

    def keyed(self) -> dict:
        return {family: self.tracks[family].keyed_any() for family in km.FAMILIES}

    def frames(self) -> list:
        seen = set()
        for track in self.tracks.values():
            seen.update(track.frames)
        return sorted(seen)

    def to_dict(self) -> dict:
        return {"length": int(self.length), "tracks": km.tracks_to_dict(self.tracks)}

    @classmethod
    def from_dict(cls, data: dict, called: str = "") -> "Clip":
        clip = cls(int(data.get("length") or 1))
        km.tracks_from_dict(data.get("tracks"), clip.tracks, called)
        return clip

    def same(self, other: "Clip") -> bool:
        return self.to_dict() == other.to_dict()


FIELDS = {"clip": "", "start": 0, "mode": "replace", "influence": 1.0,
          "fade_in": 0, "fade_out": 0, "repeat": 1, "speed": 1.0,
          "reverse": False, "hold": False, "round": 0, "rings": 0, "mask": "",
          "muted": False}


class Strip:
    """A clip played from a frame of the piece, and how."""

    def __init__(self, clip: str = "", start: int = 0) -> None:
        for name, value in FIELDS.items():
            setattr(self, name, value)
        self.clip, self.start = clip, int(start)

    def length(self, clip: Clip) -> int:
        """How many frames of the piece it plays for."""
        return max(1, int(round(clip.length * max(1, int(self.repeat))
                                / max(self.speed, 1e-3))))

    def end(self, clip: Clip) -> int:
        return self.start + self.length(clip)

    def state(self) -> dict:
        return {name: getattr(self, name) for name in FIELDS}

    @classmethod
    def from_state(cls, state: dict) -> "Strip":
        one = cls()
        for name, value in FIELDS.items():
            got = state.get(name, value)
            setattr(one, name, type(value)(got) if not isinstance(value, str) else str(got))
        return one


class Layer:
    """Strips, played in the order they start."""

    def __init__(self, name: str = "") -> None:
        self.name = name
        self.muted = False
        self.strips: list = []

    def state(self) -> dict:
        return {"name": self.name, "muted": self.muted,
                "strips": [one.state() for one in self.strips]}

    @classmethod
    def from_state(cls, state: dict) -> "Layer":
        one = cls(str(state.get("name", "")))
        one.muted = bool(state.get("muted", False))
        one.strips = [Strip.from_state(s) for s in state.get("strips", [])]
        return one


# -- a strip at a frame ----------------------------------------------------------------

def local(strip: Strip, clip: Clip, frame: float):
    """(the clip's frame, the weight) a strip plays at a frame of the piece,
    or None where it plays nothing."""
    length = strip.length(clip)
    t = float(frame) - strip.start
    if t < 0:
        return None
    held = t > length
    if held:
        if not strip.hold:
            return None
        t = float(length)
    span = clip.length
    u = t * strip.speed
    if u >= span * max(1, int(strip.repeat)) - 1e-6:
        u = float(span)                     # the very end, not the next start
    elif u > span:
        u = u % span
    if strip.reverse:
        u = span - u
    weight = float(strip.influence)
    if not held:
        if strip.fade_in > 0 and t < strip.fade_in:
            weight *= smoothstep(t / strip.fade_in)
        if strip.fade_out > 0 and length - t < strip.fade_out:
            weight *= smoothstep((length - t) / strip.fade_out)
    return u, weight


def shifted(family: str, values, keyed, rings: int = 0, round_: int = 0):
    """A family's values and which it keys, moved round the building by
    whole groups and up or down by whole rings; what goes past the top or
    the bottom is lost, and the lowest ring's jack is never keyed."""
    shape = km.SHAPE[family]
    values = np.asarray(values, np.float64).reshape(shape)
    keyed = np.asarray(keyed, bool).reshape(shape)
    if round_ and family != "lift":
        by = int(round_) * (1 if family == "push" else PER_PUSHER)
        values = np.roll(values, by, axis=1)
        keyed = np.roll(keyed, by, axis=1)
    rings = int(rings)
    if rings:
        moved_v = np.full_like(values, km.REST[family])
        moved_k = np.zeros_like(keyed)
        if rings > 0:
            moved_v[rings:], moved_k[rings:] = values[:-rings], keyed[:-rings]
        else:
            moved_v[:rings], moved_k[:rings] = values[-rings:], keyed[-rings:]
        values, keyed = moved_v, moved_k
    if family == "lift":
        keyed = keyed.copy()
        keyed[km.NO_JACK] = False
    return values.reshape(-1), keyed.reshape(-1)


def _live(project):
    """(layer index, strip index, strip, clip) of every strip that plays."""
    for li, layer in enumerate(project.layers):
        if layer.muted:
            continue
        for si, strip in enumerate(layer.strips):
            clip = project.clips.get(strip.clip)
            if clip is not None and not strip.muted:
                yield li, si, strip, clip


def stack(project, frame: float, only=None):
    """What the layers make at a frame, from rest up: (values, touched) by
    family, flat -- `touched` the motors some strip moved. `only`, a
    (layer, strip) pair, plays that strip alone."""
    import kin_prims
    values = {family: np.full(project.tracks[family].size, km.REST[family], np.float64)
              for family in km.FAMILIES}
    touched = {family: np.zeros(project.tracks[family].size, bool)
               for family in km.FAMILIES}
    for li, si, strip, clip in _live(project):
        if only is not None and (li, si) != tuple(only):
            continue
        got = local(strip, clip, frame)
        if got is None or got[1] <= 0:
            continue
        u, weight = got
        pose, keyed = clip.pose(u), clip.keyed()
        cells = project.masks.get(strip.mask) if strip.mask else None
        for family in km.FAMILIES:
            value, keys = shifted(family, pose[family], keyed[family], strip.rings,
                                  strip.round)
            share = weight * keys
            if cells is not None:
                share = share * kin_prims.motor_weights(family, cells)
            if family == "lift":
                share = (share >= 0.5).astype(np.float64)
            below = values[family]
            if strip.mode == "add":
                goal = below + (value - km.REST[family])
            elif strip.mode == "max":
                goal = np.maximum(below, value)
            else:
                goal = value
            values[family] = below + (goal - below) * share
            touched[family] |= share > 0
    low, high = km.RANGE["lift"]
    values["lift"] = np.clip(values["lift"], low, high)
    values["push"] = np.clip(values["push"], 0.0, 1.0)
    return values, touched


def under_keys(project, frame: float, keys: dict) -> dict:
    """The pose at a frame: the keys where a motor has any, the layers where
    it has none -- and a tilt the layers moved held to its gaps."""
    values, touched = stack(project, frame)
    out = {}
    for family in km.FAMILIES:
        shape = km.SHAPE[family]
        own = project.tracks[family].keyed_any()
        out[family] = np.where(own, np.asarray(keys[family]).reshape(-1),
                               values[family]).reshape(shape)
    moved = (touched["tilt"] & ~project.tracks["tilt"].keyed_any()).reshape(km.SHAPE["tilt"])
    if moved.any():
        out["tilt"] = np.where(moved, km.clamp_tilt(out["tilt"], out["lift"], out["push"]),
                               out["tilt"])
    return {family: np.asarray(out[family], np.float32) for family in km.FAMILIES}


# -- the layers as keys -----------------------------------------------------------------

def _strip_frames(strip: Strip, clip: Clip) -> set:
    """The frames of the piece where a strip plays one of its clip's keys."""
    return {frame for key in clip.frames() for frame in _played_at(strip, clip, key)}


def _played_at(strip: Strip, clip: Clip, key: int) -> list:
    """The frames of the piece where a strip plays one key of its clip."""
    start, span, end = strip.start, clip.length, strip.end(clip)
    out = []
    for time in range(max(1, int(strip.repeat))):
        u = span - key if strip.reverse else key
        frame = start + int(round((time * span + u) / max(strip.speed, 1e-3)))
        if start <= frame <= end:
            out.append(frame)
    return out


def wants(project, step: int | None = None) -> dict:
    """{frame: {family: motors}}: where each motor the layers move wants a
    key -- at the keys of its own in each strip that moves it, as the strip
    plays them, at the strip's ends and the frame either side, and every
    `step` frames through its fades. A motor is keyed where its own strips
    say, never at another's: a move split at someone else's keys would be
    a string of small commands, and the motors drop what comes mid-move."""
    import kin_prims
    step = max(1, int(step or getattr(project, "prim_step", km.PRIM_STEP)))
    out: dict = {}
    sizes = {family: project.tracks[family].size for family in km.FAMILIES}

    def add(frame, family, motors):
        if 0 <= frame < project.length and motors.any():
            slot = out.setdefault(frame, {f: np.zeros(sizes[f], bool) for f in km.FAMILIES})
            slot[family] |= motors

    for _, _, strip, clip in _live(project):
        start, end = strip.start, strip.end(clip)
        edges = {start - 1, start, end, end + 1}
        if strip.fade_in > 0:
            edges |= set(range(start, start + int(strip.fade_in), step))
            edges.add(start + int(strip.fade_in))
        if strip.fade_out > 0:
            edges |= set(range(end, end - int(strip.fade_out), -step))
            edges.add(end - int(strip.fade_out))
        cells = project.masks.get(strip.mask) if strip.mask else None
        for family in km.FAMILIES:
            track = clip.tracks[family]
            blank = np.zeros(sizes[family])
            _, reach = shifted(family, blank, track.keyed_any(), strip.rings, strip.round)
            if cells is not None:
                reach &= kin_prims.motor_weights(family, cells) > 0
            if not reach.any():
                continue
            for frame in edges:
                add(frame, family, reach)
            for key, keyed in zip(track.frames, track.keyed):
                _, mine = shifted(family, blank, keyed, strip.rings, strip.round)
                mine &= reach
                for frame in _played_at(strip, clip, key):
                    add(frame, family, mine)
    return out


def frames(project, step: int | None = None) -> list:
    """Every frame some motor the layers move wants a key on."""
    return sorted(wants(project, step))


def flatten(project):
    """The piece with its layers turned into keys, as the motors will run
    it; `project` itself is left as it is. The keys it has stay exactly;
    every motor the layers move and the keys leave alone is keyed where its
    strips want keys (`wants`). No layers playing: the piece itself."""
    if not any(True for _ in _live(project)):
        return project
    out = km.Project(project.length, empty=True)
    out.name, out.video, out.sound = project.name, project.video, project.sound
    out.masks, out.primitives, out.prim_step = (project.masks, project.primitives,
                                                project.prim_step)
    for family in km.FAMILIES:
        out.tracks[family].restore(project.tracks[family].state())
    own = {family: project.tracks[family].keyed_any() for family in km.FAMILIES}
    for frame, motors in sorted(wants(project).items()):
        pose = project.pose(frame)
        for family in km.FAMILIES:
            need = motors[family] & ~own[family]
            if need.any():
                out.tracks[family].write(frame, pose[family].reshape(-1), need)
    return out


# -- moving keys in and out of clips -----------------------------------------------------

def push_down(project, clip_name: str, layer_name: str, parts=None):
    """The keys into a clip on a new layer on top, from where the first of
    them stands; they leave the timeline. `parts` {(family, frame): motors}
    takes those alone. Returns the new layer's index, or None with no keys."""
    if parts is None:
        parts = {}
        for family, track in project.tracks.items():
            for frame, keyed in zip(track.frames, track.keyed):
                parts[(family, frame)] = keyed
    taken = []
    for (family, frame), mask in parts.items():
        track = project.tracks[family]
        at = track.index(frame)
        if at is None:
            continue
        take = track.keyed[at] & np.asarray(mask, bool).reshape(-1)
        if take.any():
            taken.append((family, frame, track.values[at], take))
    # A motor whose keys only ever say "at rest" says nothing a clip should
    # carry: in the clip it would hold everything under it at rest. The
    # rest a new piece starts with is that, on every motor.
    moving = {family: np.zeros(project.tracks[family].size, bool) for family in km.FAMILIES}
    for family, _, values, take in taken:
        moving[family] |= take & (np.abs(values - km.REST[family]) > 1e-6)
    for family, frame, values, take in taken:
        track = project.tracks[family]
        idle = take & ~moving[family]
        if idle.any():
            track.remove(track.index(frame), idle)
    taken = [(family, frame, values, take & moving[family])
             for family, frame, values, take in taken if (take & moving[family]).any()]
    # Nor does the rest a motor stands at before it starts to move: a clip
    # begins where something happens, and under it the layers play on.
    taken.sort(key=lambda one: one[1])
    for family in km.FAMILIES:
        mine = [one for one in taken if one[0] == family]
        size = project.tracks[family].size
        started = np.zeros(size, bool)
        for number, (_, frame, values, take) in enumerate(mine):
            # A key at rest whose motor's next key is at rest too, before the
            # motor has moved: a hold, and left out.
            later = np.full(size, np.nan)
            for _, _, next_values, next_take in mine[number + 1:]:
                fresh_ = np.isnan(later) & next_take
                later[fresh_] = next_values[fresh_]
            resting_now = np.abs(values - km.REST[family]) <= 1e-6
            still = (take & ~started & resting_now
                     & (np.abs(np.nan_to_num(later, nan=np.inf) - km.REST[family]) <= 1e-6))
            if still.any():
                track = project.tracks[family]
                track.remove(track.index(frame), still)
                take &= ~still
            started |= take
    taken = [one for one in taken if one[3].any()]
    if not taken:
        return None
    first = min(frame for _, frame, _, _ in taken)
    last = max(frame for _, frame, _, _ in taken)
    clip = Clip(max(1, last - first))
    for family, frame, values, take in taken:
        clip.tracks[family].write(frame - first, values, take)
        track = project.tracks[family]
        track.remove(track.index(frame), take)
    project.clips[clip_name] = clip
    layer = Layer(layer_name)
    layer.strips.append(Strip(clip_name, first))
    project.layers.append(layer)
    project.changed()
    return len(project.layers) - 1


def to_keys(project, layer: int, index: int) -> int:
    """A strip's clip back onto the timeline, as it plays -- moved, turned
    round, repeated, sped, reversed -- and the strip gone: to change what
    is in it, and put it into a clip again. How it blended stays behind.
    Returns how many keys were written."""
    strip = project.layers[layer].strips[index]
    clip = project.clips[strip.clip]
    start, span = strip.start, clip.length
    written = set()
    for family in km.FAMILIES:
        track = clip.tracks[family]
        for key, values, keyed in zip(track.frames, track.values, track.keyed):
            value, keys = shifted(family, values, keyed, strip.rings, strip.round)
            if not keys.any():
                continue
            for time in range(max(1, int(strip.repeat))):
                u = span - key if strip.reverse else key
                frame = start + int(round((time * span + u) / max(strip.speed, 1e-3)))
                if 0 <= frame < project.length:
                    project.tracks[family].write(frame, value, keys)
                    written.add(frame)
    del project.layers[layer].strips[index]
    project.changed()
    return len(written)


def bake_all(project) -> None:
    """Every layer into the keys for good; the layers go, and the clips no
    strip plays."""
    done = flatten(project)
    if done is not project:
        for family in km.FAMILIES:
            project.tracks[family].restore(done.tracks[family].state())
    project.layers = []
    project.clips = {}
    project.changed()


def overridden(project, strip: Strip) -> int:
    """How many of a strip's motors the keys on the timeline cover -- which
    then play their keys, not the strip."""
    clip = project.clips.get(strip.clip)
    if clip is None:
        return 0
    keyed = clip.keyed()
    count = 0
    for family in km.FAMILIES:
        _, keys = shifted(family, np.zeros(keyed[family].size), keyed[family],
                          strip.rings, strip.round)
        count += int((keys & project.tracks[family].keyed_any()).sum())
    return count


def resting(project) -> bool:
    """Whether the keys are only the rest a new piece starts with."""
    for family, track in project.tracks.items():
        if not len(track):
            continue
        if track.frames != [0] or not np.allclose(track.values[0], km.REST[family]):
            return False
    return True
