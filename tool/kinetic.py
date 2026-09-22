"""The moving half of the top screen: motors, read from a JSON, as geometry.

The honeycomb above the canopy is kinetic. Thirty rings of fifty cells, and
three families of motor behind them -- jacks that set the gap between rings,
pushers that drive a group of five cells out radially, tilts that swing one
cell about a horizontal axis. A JSON holds their commands; Houdini turns that
into a clip and a rig; this turns it into the same motion, in the viewer.

What this moves is `screen`: the rigged copy of the honeycomb in the blend,
baked at its first frame and then driven from here. The older `Screen_Top`
beside it is not touched -- it is what the viewer shows when no JSON is loaded,
the screens standing at rest.

Everything below was measured rather than assumed, against Houdini's own clip
of the same file and against the rig's own animation read back out of Blender.

  reading      exact: rebuilt from the JSON and compared with the clip on all
               1829 tracks of a real piece, worst disagreement zero
  tilt         value x 90 degrees, so the mechanical limit is at one third
  pusher       value x 1000 mm, radially out; measured 99.77 cm at 0.9979
  jack         a state number, not a fraction. States 1, 2 and 3 are 330, 660
               and 1300 mm of ring gap; state 0 exists but is a service
               position and is never commanded. A move between two states
               passes through the millimetres of every state between them, not
               straight from one to the other: 1 to 3 goes by way of 660, and
               reading it the other way is 320 mm wrong at the top ring.
  numbering    row 1 is the lowest ring; id counts round in steps of 7.2
               degrees from 77.6 for even rows and 59.6 for odd ones. Checked
               against the rig's own bones: every one of the 1500 cells lands
               on its bone to within a ten-thousandth of a degree.

Against Blender's own animated mesh, at 38 frames spread over the whole of a
1488-frame calibration piece: worst 5.6 mm on any of the 9000 vertices, on a
cell 340 mm across. What is left is a fifth of a millimetre per ring in the
jacks, accumulating up the stack, and it is not worth chasing.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# -- what a unit of each motor is worth --------------------------------------

TILT_DEGREES = 90.0            # value x this, so +-1/3 is the +-30 degree limit
PUSHER_MM = 1000.0             # value x this, radially outward

# Jack states, in millimetres of ring gap.
JACK_STATE_MM = {0: 0.0, 1: 330.0, 2: 660.0, 3: 1300.0}

# Which state the geometry this drives already sits at. A ring moves by the
# difference from here, not by the whole of the commanded gap.
#
# `screen` is baked at the first frame of the rig's own animation, where every
# jack is at state 1 -- ring pitch 27.80 cm, and the calibration JSON opens on
# state 1 for all thirty of them. The still `Screen_Top` beside it was modelled
# at state 2, pitch 31.10; it is never driven from here, and if it ever were,
# this would have to say 2 instead.
JACK_REST_STATE = 1

# The rig moves its jacks by a tenth of what the site does -- 33, 66 and 130
# where the specification says 330, 660 and 1300 mm. This follows the rig,
# because the rig is what the blend, the FBX and the clip all agree on, and
# agreeing with them is how the viewer can be checked at all. Set this to 1.0
# for the machine's own travel, which will show ten times the ring movement of
# any render made from that rig. Tilts and pushers are the same either way.
JACK_LIKE_THE_RIG = True
JACK_SCALE = 0.1 if JACK_LIKE_THE_RIG else 1.0

ROWS, PER_ROW, PER_PUSHER = 30, 50, 5

# A cell swings about a hinge on its own meridian, level with the cell centre,
# at this distance from the structure's axis -- 100 mm inboard of the rigged
# surface, which stands at 2.5266 m.
#
# Given as a radius rather than as an offset because the two honeycomb meshes
# in the file sit at different radii, 350 mm apart, and an offset that is right
# for one is wrong for the other by exactly that much. Solved from the
# animation, not read off the rig; anywhere between 2.420 and 2.426 fits it
# equally well, the residual there being the jacks rather than the hinge.
HINGE_RADIUS_M = 2.42660

# Where id_1 sits, in degrees round the structure, and the step to the next.
ID_STEP_DEGREES = 360.0 / PER_ROW
ID_ORIGIN_DEGREES = {0: 77.6, 1: 59.6}      # by the row number's parity


class KineticError(Exception):
    """The file is not a motor JSON this can read."""


def smoothstep(t):
    """The easing the exporter uses, and the only one it has ever written.

    Named `ease_in_out` there. Segments may carry an easing of their own, and
    the other shapes are implemented below for when one finally does.
    """
    return t * t * (3.0 - 2.0 * t)


def _ease(t, mode):
    # No tag means the exporter's global default, which is this one -- not
    # linear. Reading it the other way round makes every ramp a straight line,
    # which looks plausible and is wrong everywhere: it put a jack a fifth of a
    # state out at the middle of a long move.
    if mode in (None, ""):
        return smoothstep(t)
    if mode in ("linear", "none"):
        return t
    if mode in ("ease_in", "quad_in"):
        return t * t
    if mode in ("ease_out", "quad_out"):
        return 1.0 - (1.0 - t) ** 2
    if mode in ("ease_in_out", "smoothstep"):
        return smoothstep(t)
    if mode == "sine_in":
        return 1.0 - np.cos(t * np.pi / 2.0)
    if mode == "sine_out":
        return np.sin(t * np.pi / 2.0)
    if mode in ("sine_in_out", "sine"):
        return 0.5 - 0.5 * np.cos(np.pi * t)
    return smoothstep(t)


@dataclass
class Track:
    """One motor's whole timeline, sampled once and then only looked up.

    Sampled rather than searched because the drawing side asks 1830 of these
    for a time, sixty times a second, and a table read is nothing while a
    binary search through segments, per motor, per frame, is not.
    """

    frames: np.ndarray             # value at json frame 0, 1, 2, ...

    def at(self, frame: float) -> float:
        i = int(np.clip(frame, 0, len(self.frames) - 1))
        return float(self.frames[i])


def _sample(segments, length: int) -> np.ndarray:
    """A motor's segments as a value for every json frame.

    The rules are the exporter's own: hold the first `start` before anything
    happens, ease across a segment, hold the previous `dest` in the gaps, and
    keep the last one for ever after. A segment of no length reports its
    `start`, which is what the exporter does and which never matters, because
    in every file seen so far such a segment has `start` equal to `dest`.
    """
    out = np.empty(length, dtype=np.float32)
    if not segments:
        out[:] = 0.0
        return out

    at = 0
    value = float(segments[0]["start"])
    for s in segments:
        first = int(s["frame"])
        span = max(0, int(s["length"]))
        if first > at:
            out[at:min(first, length)] = value
            at = min(first, length)
        if at >= length:
            break
        start, dest = float(s["start"]), float(s["dest"])
        if span <= 0:
            value = start
        else:
            last = min(first + span, length)
            if last > at:
                t = (np.arange(at, last) - first) / span
                out[at:last] = start + (dest - start) * _ease(
                    np.clip(t, 0.0, 1.0), s.get("easing") or s.get("ease"))
                at = last
            value = dest
    if at < length:
        out[at:] = value
    return out


class Part:
    """One file of a chain: what it is called, where it sits, how long it is."""

    def __init__(self, path: Path, payload: dict) -> None:
        self.path = path
        self.data = payload.get("data")
        info = payload.get("info", {})
        if not isinstance(self.data, dict) or not self.data:
            raise KineticError(f"{path.name} has no motor data in it")
        self.fps = float(info.get("fps") or 60.0)
        start = int(info.get("export_range", {}).get("start", 0))
        end = info.get("export_range", {}).get("end")
        total = int(info.get("total_frames") or 0)
        self.length = int(end) - start if end is not None else total
        if self.length <= 0:
            self.length = total or 1
        # Where the exporter thinks this part sits, and which of how many it
        # is. Both are what it says about itself, not what the chain decides.
        self.declared_at = start
        self.number = int(info.get("part") or 1)
        self.of = int(info.get("total_parts") or 1)
        self.first = 0                  # filled in by the chain below
        self.repeats = 1                # and how many times over it is played

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def span(self) -> int:
        """Every frame this part takes up, its repeats counted in."""
        return self.length * self.repeats

    def __repr__(self) -> str:
        return (f"<{self.name} {self.number}/{self.of} "
                f"{self.length} frames x{self.repeats} at {self.first}>")


def parts_beside(path: str | Path) -> list[Path]:
    """The other parts of the same show, in order, if this is one of several.

    A file says `part` and `total_parts` in its own header, and its name ends
    in `_1_of_2`. Either is enough to know that the rest exist; the name is
    what finds them, because opening every json in a folder to read a header
    is a folder full of reading.
    """
    path = Path(path)
    match = re.search(r"^(?P<stem>.*?)(?P<one>\d+)_of_(?P<many>\d+)$", path.stem)
    if not match:
        return [path]
    many = int(match.group("many"))
    if many <= 1:
        return [path]
    found = []
    for which in range(1, many + 1):
        beside = path.with_name(
            f"{match.group('stem')}{which}_of_{many}{path.suffix}")
        if beside.exists():
            found.append(beside)
    return found or [path]


class Motors:
    """A kinetic show: one json, or several played one after another.

    Several, because a long show comes out of the exporter in parts and a
    programme comes out as a block a scene. They are not independent: a part
    begins in the state the one before it left -- its first segment carries
    that value as its `start`, and a motor it does not mention at all is one
    that simply holds. So the chain is laid end to end and every motor the
    next part says nothing about keeps the value it had.
    """

    def __init__(self, paths: str | Path | list, repeats=None) -> None:
        if isinstance(paths, (str, Path)):
            paths = [paths]
        self.paths = [Path(one) for one in paths]
        if not self.paths:
            raise KineticError("no kinetic file given")
        # How many times each part is played before the next one starts. One
        # each unless somebody has asked for more, which is what the count
        # beside a row means.
        times = list(repeats or [])
        times += [1] * (len(self.paths) - len(times))

        self.parts: list[Part] = []
        for path in self.paths:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception as error:  # noqa: BLE001 -- shown beside the field
                raise KineticError(f"{path.name}: {error}") from error
            self.parts.append(Part(path, payload))

        self.fps = self.parts[0].fps
        odd = [one for one in self.parts if one.fps != self.fps]
        if odd:
            raise KineticError(
                f"{odd[0].name} is {odd[0].fps:g} fps and "
                f"{self.parts[0].name} is {self.fps:g}; a chain has to be one rate")

        at = 0
        for part, over in zip(self.parts, times):
            part.repeats = max(1, int(over))
            part.first = at
            at += part.length * part.repeats
        # The last frame counts as a whole frame, the same as for one file.
        self.frames = at + 1
        self.path = self.parts[0].path

        # Row and id are numbers, not names: everything downstream indexes.
        self.tilt = np.zeros((ROWS, PER_ROW, self.frames), np.float32)
        self.pusher = np.zeros((ROWS, PER_ROW // PER_PUSHER, self.frames), np.float32)
        self.jack = np.full((ROWS, self.frames), float(JACK_REST_STATE), np.float32)

        # Every motor's segments from every part, in order, with each part's
        # frames shifted to where that part sits. Sampled once over the whole
        # chain afterwards: that is what lets a movement the exporter cut in
        # half finish, and what makes a part that says nothing about a motor
        # simply a gap, which already means "hold".
        gathered: dict = {}
        for part in self.parts:
            for row_key, groups in part.data.items():
                row = _number(row_key) - 1
                if not 0 <= row < ROWS or not isinstance(groups, dict):
                    continue
                for group, ids in groups.items():
                    if group not in ("tilt", "pusher", "jack") \
                            or not isinstance(ids, dict):
                        continue
                    for id_key, segments in ids.items():
                        which = _number(id_key) - 1
                        if group == "tilt" and not 0 <= which < PER_ROW:
                            continue
                        if group == "pusher" \
                                and not 0 <= which < self.pusher.shape[1]:
                            continue
                        clean = [one for one in segments if isinstance(one, dict)]
                        moved = []
                        for pass_no in range(part.repeats):
                            opens = part.first + pass_no * part.length
                            if pass_no and clean:
                                # A pass has to begin where the part begins,
                                # not where the pass before it ended. A segment
                                # of no length reports its own `start`, which is
                                # the exporter's own way of saying "be here" --
                                # so the snap lands on the frame the loop turns
                                # over rather than drifting into it.
                                back = float(clean[0].get("start", 0.0))
                                moved.append({"frame": opens, "length": 0,
                                              "start": back, "dest": back})
                            moved += [dict(one,
                                           frame=int(one.get("frame", 0)) + opens)
                                      for one in clean]
                        gathered.setdefault((group, row, which), []).extend(moved)

        for (group, row, which), segments in gathered.items():
            curve = _sample(segments, self.frames)
            if group == "tilt":
                self.tilt[row, which] = curve
            elif group == "pusher":
                self.pusher[row, which] = curve
            else:
                self.jack[row] = curve
        if not gathered:
            raise KineticError(f"{self.path.name} has no motors this understands")
        self.motors = len(gathered)

    # -- what the window says about the chain --------------------------------

    @property
    def boundaries(self) -> list:
        """Where each part, and each repeat of it, starts: (frame, name)."""
        marks = []
        for part in self.parts:
            for pass_no in range(part.repeats):
                if part.first == 0 and pass_no == 0:
                    continue          # the start of the piece is not a join
                marks.append((part.first + pass_no * part.length, part.name))
        return marks

    def complaints(self) -> list[str]:
        """Anything about this chain worth saying out loud in the row.

        The order is the one the rows are in -- that is what somebody can see
        and change -- so a chain that disagrees with what the files say about
        themselves is played as it stands and mentioned.
        """
        said = []
        numbered = [one for one in self.parts if one.of > 1]
        if numbered:
            want = [one.number for one in numbered]
            if want != sorted(want):
                said.append("parts are out of order: "
                            + ", ".join(f"{one.number}/{one.of}" for one in numbered))
            missing = [n for n in range(1, numbered[0].of + 1) if n not in want]
            if missing and len(numbered) < numbered[0].of:
                said.append(f"part {numbered[0].number} of {numbered[0].of}; "
                            f"missing {', '.join(str(n) for n in missing)}")
        return said

    @property
    def duration(self) -> float:
        return (self.frames - 1) / self.fps if self.fps else 0.0

    def index_at(self, seconds: float) -> int:
        return int(np.clip(round(seconds * self.fps), 0, self.frames - 1))

    def describe(self) -> str:
        passes = sum(one.repeats for one in self.parts)
        many = (f"{len(self.parts)} files  " if len(self.parts) > 1 else "")
        if passes > len(self.parts):
            many += f"{passes} passes  "
        return (f"{many}{self.motors} motors  {self.frames - 1} frames  "
                f"{self.fps:g} fps  {self.duration:.2f} s")

    # -- what the drawing side asks for --------------------------------------

    def rise(self, frame: int) -> np.ndarray:
        """How much each ring has risen, in millimetres, bottom to top.

        The jack sets the gap to its neighbour, so a ring stands on the sum of
        every gap below it. The modelled geometry already sits at state 1, so
        what counts is the difference from there.
        """
        states = self.jack[:, frame]
        gaps = (_state_mm(states) - JACK_STATE_MM[JACK_REST_STATE]) * JACK_SCALE
        return np.concatenate([[0.0], np.cumsum(gaps[:-1])])

    def out(self, frame: int) -> np.ndarray:
        """How far each cell has been pushed out, in millimetres."""
        return np.repeat(self.pusher[:, :, frame], PER_PUSHER, axis=1) * PUSHER_MM

    def angle(self, frame: int) -> np.ndarray:
        """How far each cell has swung, in degrees."""
        return self.tilt[:, :, frame] * TILT_DEGREES


def _state_mm(states) -> np.ndarray:
    """A jack state, whole or part way between two, as millimetres.

    The steps are not even -- 330, 660, then 1300 -- so a value halfway
    between two states is halfway between their millimetres, not half of the
    top one. The motors move smoothly between the states they are commanded
    to, which is why this interpolates at all.
    """
    states = np.clip(np.asarray(states, dtype=np.float64), 0, 3)
    low = np.floor(states).astype(int)
    high = np.minimum(low + 1, 3)
    part = states - low
    table = np.array([JACK_STATE_MM[i] for i in range(4)])
    return table[low] * (1.0 - part) + table[high] * part


def transforms(centres: np.ndarray, addresses: np.ndarray,
               motors: "Motors", frame: int, much: float = 1.0) -> np.ndarray:
    """One 4x4 for every cell, ready to hand to the card.

    A cell rises with its ring, is pushed straight out, and swings about a
    hinge just inboard of itself. Written as a matrix per cell because the
    drawing side has 1500 of them and no interest in any of this.
    """
    rows, ids = addresses[:, 0], addresses[:, 1]
    flat = centres[:, :2]
    out = flat / np.linalg.norm(flat, axis=1, keepdims=True)
    radial = np.concatenate([out, np.zeros((len(centres), 1))], axis=1)
    # The axis a cell turns about: horizontal, across its own face.
    axis = np.stack([-out[:, 1], out[:, 0], np.zeros(len(centres))], axis=1)

    # `much` exaggerates or damps the whole motion at once, for looking at.
    angle = np.radians(motors.angle(frame)[rows, ids] * much)[:, None]
    push = (motors.out(frame)[rows, ids] * much / 1000.0)[:, None]
    rise = motors.rise(frame)[rows] * much / 1000.0

    reach = np.linalg.norm(flat, axis=1)[:, None]
    pivot = centres - radial * (reach - HINGE_RADIUS_M)
    cos, sin = np.cos(angle), np.sin(angle)

    m = np.zeros((len(centres), 4, 4), np.float32)
    m[:, 3, 3] = 1.0
    for column in range(3):
        basis = np.zeros((len(centres), 3))
        basis[:, column] = 1.0
        # Rodrigues, about `axis` which is already a unit vector.
        turned = (basis * cos + np.cross(axis, basis) * sin
                  + axis * np.einsum("ci,ci->c", axis, basis)[:, None] * (1 - cos))
        m[:, :3, column] = turned
    shifted = pivot + radial * push - np.einsum("cij,cj->ci", m[:, :3, :3], pivot)
    shifted[:, 2] += rise
    m[:, :3, 3] = shifted
    return m


def _number(key: str) -> int:
    """`row_7` and `id_23` are 7 and 23; anything else is 0."""
    try:
        return int(str(key).rsplit("_", 1)[1])
    except (IndexError, ValueError):
        return 0


def cell_addresses(points: np.ndarray) -> np.ndarray:
    """Which (row, id) each of the 1500 cells is, from where it sits.

    Read off the geometry rather than stored beside it, because the geometry
    is the thing that is certain to be in step with itself. Rows are the
    thirty heights, counted from the bottom; ids run round in steps of 7.2
    degrees from an origin that alternates with the row's parity.

    Checked against the rig's own bones for all 1500: the same cell, every
    time, to within a ten-thousandth of a degree.
    """
    if len(points) != ROWS * PER_ROW:
        raise KineticError(
            f"expected {ROWS * PER_ROW} cells on the top screen, found {len(points)}")

    order = np.argsort(points[:, 2])
    row = np.empty(len(points), np.int32)
    for band in range(ROWS):
        row[order[band * PER_ROW:(band + 1) * PER_ROW]] = band

    angle = np.degrees(np.arctan2(points[:, 1], points[:, 0])) % 360.0
    origin = np.where((row + 1) % 2 == 0,
                      ID_ORIGIN_DEGREES[0], ID_ORIGIN_DEGREES[1])
    which = np.round(((angle - origin) % 360.0) / ID_STEP_DEGREES).astype(np.int32)
    return np.stack([row, which % PER_ROW], axis=1)
