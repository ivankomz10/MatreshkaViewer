"""The honeycomb and the building, driven with no window open.

Everything here runs the viewer's own code from `tool/` -- the same limits,
the same arithmetic, the same renderer that draws the window -- but in this
process and into an array instead of onto a canvas. That is what lets a
generator work in a loop: pose, check, look, correct, hundreds of times,
without a mouse and without taking the screen away from whoever is using it.

Two halves, and the first one needs no graphics card at all:

    the limits    what the motors may do, and the smallest change that makes
                  a wanted pose legal (`fit`) -- pure arithmetic on arrays
    the picture   a pose drawn from the file's camera or from a free one
                  (`Studio`) -- wgpu, offscreen, no canvas

The reason `fit` exists: a cell swings into the gap beside its ring, and the
gap is opened by a jack. Push the cells out without raising the jacks and the
tilts are simply impossible -- the machine will not do them, and the editor
paints them red. A generator that only writes pushers makes shapes that look
right in its own head and cannot be built.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent / "tool"
SANDBOX = HERE / "scratch"

if not (TOOL / "kin_model.py").is_file():          # pragma: no cover -- setup
    raise SystemExit(f"the viewer's sources are not beside this: {TOOL}")

sys.path.insert(0, str(TOOL))

import logfile                                      # noqa: E402

# The application keeps its settings and its log beside itself, which from
# source means inside `tool`. Pointed at a scratch folder before anything of
# the application's is built, so a session leaves nothing in the working tree.
# What it *reads* -- the baked mesh, the calibration pictures -- still comes
# from `tool`, which is what `bundled` is for.
_BESIDE = logfile.app_dir()
SANDBOX.mkdir(parents=True, exist_ok=True)
logfile.app_dir = lambda: SANDBOX                   # noqa: E731 -- the point
logfile.bundled = lambda name: (_BESIDE / name if (_BESIDE / name).exists()
                                else None)

import lang                                         # noqa: E402

# Whatever the editor's window is set to, what comes back over this wire is
# read by a model prompted in English -- including the notes an imported file
# earns itself, which the importer writes through `lang.tr`.
lang.set_language("en")

import kinetic                                      # noqa: E402
import kin_model as km                              # noqa: E402
import kin_sim                                      # noqa: E402

ROWS = kinetic.ROWS                                 # 30 rings
PER_ROW = kinetic.PER_ROW                           # 50 cells round a ring
PER_PUSHER = kinetic.PER_PUSHER                     # cells one pusher carries
GROUPS = km.GROUPS                                  # 10 pushers round a ring
TILT_DEGREES = kinetic.TILT_DEGREES                 # a tilt value times this


class BridgeError(Exception):
    """Something the caller asked for that cannot be done."""


# -- poses as plain numbers ---------------------------------------------------

def _as(family: str, value, fill: float | None = None) -> np.ndarray:
    """A pose field as its own shape, from a number, a list or nothing."""
    shape = km.SHAPE[family]
    if value is None:
        value = km.REST[family] if fill is None else fill
    array = np.asarray(value, dtype=np.float64)
    if array.ndim == 0:
        return np.full(shape, float(array))
    if array.shape == shape:
        return array.copy()
    # A per-ring list for a per-cell family: every cell of the ring alike.
    if array.shape == (ROWS,) and len(shape) == 2:
        return np.repeat(array[:, None], shape[1], axis=1)
    if array.size == int(np.prod(shape)):
        return array.reshape(shape).copy()
    raise BridgeError(
        f"{family} wants {shape} or one number per ring, got {array.shape}")


def pose_from(lift=None, push=None, tilt=None) -> dict:
    """Three arrays, whatever shorthand they arrived in."""
    return {"lift": _as("lift", lift), "push": _as("push", push),
            "tilt": _as("tilt", tilt)}


def pose_out(pose: dict) -> dict:
    """A pose as lists, for a tool result."""
    return {name: np.asarray(value).round(6).tolist()
            for name, value in pose.items()}


# -- the limits ---------------------------------------------------------------

# The gap a jack opens, by its state, and the swing that gap allows. Both are
# Houdini's (`anim_simple`), which is the rule the show runs on.
JACK_STATE_MM = dict(kinetic.JACK_STATE_MM)         # 0, 330, 660, 1300
GAP_DEGREES = (2.0, 10.0, 45.0, 45.0)               # by state, straight between
BEAM_PUSH = km.BEAM_PUSH                            # (0.1, 0.2)
BEAM_DEGREES = km.BEAM_DEGREES                      # (30, 45)


def limits(lift=None, push=None) -> dict:
    """How far each ring's cells may tilt, in degrees, at this pose.

    Face down is positive and swings into the gap *under* the ring; face up is
    negative and swings into the gap *over* it. The bottom ring has nothing
    under it and the top one nothing over, so on those sides only the beam
    holds them.
    """
    pose = pose_from(lift, push)
    low, high = km.tilt_bounds(pose["lift"], pose["push"])
    below, above = km.gaps_around(pose["lift"])
    rows = []
    for ring in range(ROWS):
        rows.append({
            "row": ring + 1,
            "gap_below": None if not np.isfinite(below[ring]) else round(float(below[ring]), 3),
            "gap_above": None if not np.isfinite(above[ring]) else round(float(above[ring]), 3),
            "down_degrees": round(float(high[ring].max() * TILT_DEGREES), 2),
            "up_degrees": round(float(low[ring].min() * TILT_DEGREES), 2),
        })
    return {"rule": km.TILT_RULE, "rows": rows}


def _state_for(degrees: np.ndarray) -> np.ndarray:
    """The lowest whole jack state whose gap allows this much swing."""
    degrees = np.asarray(degrees, np.float64)
    need = np.zeros(degrees.shape, np.float64)
    for state, allowed in enumerate(GAP_DEGREES):
        need = np.where((degrees > allowed + 1e-6) & (need <= state), state + 1.0, need)
    return np.minimum(need, 3.0)


def _beam_degrees(push) -> np.ndarray:
    """How far the beam lets a cell swing at this much pusher."""
    return np.interp(np.asarray(push, np.float64),
                     list(BEAM_PUSH), list(BEAM_DEGREES))


def _push_for(degrees: np.ndarray) -> np.ndarray:
    """The least a pusher must be out for a cell to clear the beam.

    Nothing at all up to 30 degrees: that much is allowed with the pushers
    fully in, and `np.interp` alone would ask for 0.1 where 0 will do.
    """
    degrees = np.asarray(degrees, np.float64)
    need = np.interp(degrees, list(BEAM_DEGREES), list(BEAM_PUSH))
    return np.clip(np.where(degrees <= BEAM_DEGREES[0], 0.0, need), 0.0, 1.0)


def check(lift=None, push=None, tilt=None) -> dict:
    """Is this pose one the machine can hold, and if not, why not."""
    pose = pose_from(lift, push, tilt)
    low, high = km.tilt_bounds(pose["lift"], pose["push"])
    over = km.over_limit(pose["tilt"], pose["lift"], pose["push"])
    degrees = pose["tilt"] * TILT_DEGREES

    out_of_range = {}
    for family, (lowest, highest) in km.RANGE.items():
        values = pose[family]
        bad = (values < lowest - 1e-6) | (values > highest + 1e-6)
        if bad.any():
            out_of_range[family] = int(bad.sum())

    worst = []
    if over.any():
        rows = np.unique(np.nonzero(over)[0])
        for ring in rows[:12]:
            cells = np.nonzero(over[ring])[0]
            want = degrees[ring, cells]
            pick = cells[np.argmax(np.abs(want))]
            asked = float(degrees[ring, pick])
            worst.append({
                "row": int(ring) + 1,
                "id": int(pick) + 1,
                "wants_degrees": round(asked, 2),
                "allowed_degrees": round(float(
                    high[ring, pick] if asked > 0 else low[ring, pick]) * TILT_DEGREES, 2),
                "held_by": _held_by(pose, ring, pick, asked),
                "cells_over_in_row": int(over[ring].sum()),
            })
    return {
        "legal": not over.any() and not out_of_range,
        "cells_over_limit": int(over.sum()),
        "rows_affected": sorted(int(r) + 1 for r in np.unique(np.nonzero(over)[0])),
        "out_of_range": out_of_range,
        "worst": worst,
    }


def _held_by(pose: dict, ring: int, cell: int, asked: float) -> str:
    """Which of the two rules is the one stopping this cell."""
    below, above = km.gaps_around(pose["lift"])
    gap = below[ring] if asked > 0 else above[ring]
    gap_allows = 45.0 if not np.isfinite(gap) else float(
        np.interp(kinetic._state_mm(np.array([gap]))[0] / JACK_STATE_MM[3],
                  km.HOUDINI_RAMP[0], km.HOUDINI_RAMP[1]) * 45.0)
    out = float(pose["push"][ring, cell // PER_PUSHER])
    beam_allows = float(_beam_degrees(out))
    if gap_allows <= beam_allows:
        side = "below" if asked > 0 else "above"
        return (f"the gap {side} ring {ring + 1} is at jack state "
                f"{'none' if not np.isfinite(gap) else round(float(gap), 2)}, "
                f"which allows {gap_allows:.1f} degrees")
    return (f"the beam: pusher {cell // PER_PUSHER + 1} is out {out:.3f}, "
            f"which allows {beam_allows:.1f} degrees")


def fit(lift=None, push=None, tilt=None,
        may_change=("lift", "push", "tilt")) -> dict:
    """The smallest change that makes a wanted pose one the machine can hold.

    In this order, because it is the order that keeps the shape: raise the
    jacks that the tilts need, push the pushers out far enough to clear the
    beam, and only then give up and clamp the tilt. Nothing is ever lowered or
    pulled back in -- a fitted pose is the asked-for one or more open than it.

    This is the call a generator wants. Writing pushers alone and leaving the
    jacks where they were is the one mistake that makes a shape unbuildable.
    """
    may = set(may_change)
    pose = pose_from(lift, push, tilt)
    asked = {name: value.copy() for name, value in pose.items()}

    for family, (lowest, highest) in km.RANGE.items():
        pose[family] = np.clip(pose[family], lowest, highest)
    wanted = np.abs(pose["tilt"]) * TILT_DEGREES

    notes = []
    if "lift" in may:
        # Face down needs the gap under the ring, face up the gap over it.
        down = np.where(pose["tilt"] > 0, wanted, 0.0).max(axis=1)
        up = np.where(pose["tilt"] < 0, wanted, 0.0).max(axis=1)
        need_below, need_above = _state_for(down), _state_for(up)
        raised = pose["lift"].copy()
        for ring in range(1, ROWS):                 # lift[0] is not a jack
            raised[ring] = max(raised[ring], need_below[ring], need_above[ring - 1])
        raised = np.ceil(raised - 1e-9)
        moved = int((raised > pose["lift"] + 1e-6).sum())
        if moved:
            notes.append(f"raised {moved} jacks so the tilts have room")
        pose["lift"] = np.clip(raised, 0.0, 3.0)

    if "push" in may:
        need = _push_for(wanted).reshape(ROWS, GROUPS, PER_PUSHER).max(axis=2)
        out = np.maximum(pose["push"], need)
        moved = int((out > pose["push"] + 1e-6).sum())
        if moved:
            notes.append(f"pushed {moved} pushers out to clear the beam")
        pose["push"] = np.clip(out, 0.0, 1.0)

    before = km.over_limit(pose["tilt"], pose["lift"], pose["push"])
    if "tilt" in may and before.any():
        pose["tilt"] = km.clamp_tilt(pose["tilt"], pose["lift"], pose["push"])
        notes.append(f"clamped {int(before.sum())} tilts that no jack can allow")

    pose["lift"] = np.round(pose["lift"])
    changed = {name: int(np.count_nonzero(
        np.abs(pose[name] - asked[name]) > 1e-6)) for name in pose}
    return {
        "pose": pose_out(pose),
        "changed": changed,
        "notes": notes,
        "check": check(pose["lift"], pose["push"], pose["tilt"]),
    }


def machine() -> dict:
    """What the thing is, in numbers. Nothing here changes between shows."""
    return {
        "rings": ROWS,
        "cells_per_ring": PER_ROW,
        "cells_per_pusher": PER_PUSHER,
        "pushers_per_ring": GROUPS,
        "cells_total": ROWS * PER_ROW,
        "fps": km.FPS,
        "motors": {
            "jack": {
                "one_per": "gap between two rings, rows 1..29, row 30 has none",
                "json_range": [0, 3],
                "states_mm": {str(k): v for k, v in JACK_STATE_MM.items()},
                "whole_numbers_only": True,
                # The four places along one travel: a jack sent from 0 to 1
                # takes a quarter of its 15 seconds, not all of them.
                "states_along_travel": list(kin_sim.LIFT_TRAVEL),
                "full_travel_seconds": kin_sim.PACE["lift"][0],
                "rest_seconds": kin_sim.PACE["lift"][1],
            },
            "pusher": {
                "one_per": f"{PER_PUSHER} cells of a ring, ids 1..{GROUPS}",
                "json_range": [0.0, 1.0],
                "millimetres_at_1": kinetic.PUSHER_MM,
                "full_travel_seconds": kin_sim.PACE["push"][0],
                "rest_seconds": kin_sim.PACE["push"][1],
            },
            "tilt": {
                "one_per": f"cell, ids 1..{PER_ROW}",
                # What the encoding can hold, and what the motor can reach.
                # They are not the same: the file goes to 45 degrees, the
                # machine to 30.
                "json_range": [-0.5, 0.5],
                "degrees_at_1": TILT_DEGREES,
                "reaches_degrees": [-kinetic.TILT_LIMIT_DEGREES,
                                    kinetic.TILT_LIMIT_DEGREES],
                "reaches_json": [-kinetic.TILT_LIMIT_DEGREES / TILT_DEGREES,
                                 kinetic.TILT_LIMIT_DEGREES / TILT_DEGREES],
                "positive_is": "face down",
                # End to end, which for this motor is -30 to +30.
                "whole_range_seconds": kin_sim.PACE["tilt"][0],
                "rest_seconds": kin_sim.PACE["tilt"][1],
                "speed_is_linear": False,
            },
        },
        "tilt_rule": {
            "name": km.TILT_RULE,
            "motor_reaches_degrees": kinetic.TILT_LIMIT_DEGREES,
            "gap_degrees_by_jack_state": list(GAP_DEGREES),
            "beam_push": list(BEAM_PUSH),
            "beam_degrees": list(BEAM_DEGREES),
            "down_uses": "the gap below the ring (jack row R-1)",
            "up_uses": "the gap above the ring (jack row R)",
            "bottom_ring_free_below": True,
            "top_ring_free_above": True,
        },
        "jack_numbering": {
            "reading": kinetic.JACK_READING,
            "means": "jack row N opens the gap between rings N and N+1",
        },
        "geometry": {
            "ring_pitch_m": km.RING_PITCH_M,
            "hinge_radius_m": kinetic.HINGE_RADIUS_M,
            "id_1_degrees_by_row_parity": dict(kinetic.ID_ORIGIN_DEGREES),
            "degrees_between_ids": round(kinetic.ID_STEP_DEGREES, 4),
        },
        "preview_caveat": (
            "The rendered ring lift is a tenth of the site's, because the "
            "rigged geometry this draws moves that way (kinetic.JACK_SCALE). "
            "Judge jack states by number, not by how far the rings part in a "
            "picture."),
    }


# -- the picture --------------------------------------------------------------

import scene3d                                      # noqa: E402
import renderer3d                                   # noqa: E402
import screen_gpu                                   # noqa: E402

BAKED = "baked"
# The honeycomb wears the top screen's feed, which is why a picture put on
# Screen_Top shows on the cells as well as on the drum under them.
FEEDS = ("Screen_Bottom", "Screen_Top", "Lamel_screen")


class PoseMotors:
    """A pose, answering the three questions `kinetic.transforms` asks.

    The same adapter the editor uses (`kinedit.PoseMotors`), repeated here so
    that drawing a pose needs no Qt: importing the editor's window would pull
    PySide6 into a server that otherwise never opens one.
    """

    def __init__(self, pose: dict) -> None:
        self.pose = pose

    def angle(self, frame=None) -> np.ndarray:
        return self.pose["tilt"] * TILT_DEGREES

    def out(self, frame=None) -> np.ndarray:
        return np.repeat(self.pose["push"], PER_PUSHER, axis=1) * kinetic.PUSHER_MM

    def rise(self, frame=None) -> np.ndarray:
        return kinetic.rise_mm(self.pose["lift"], km.READING)


class Studio:
    """The scene, the card and the renderer, built once and kept.

    Building a device and reading the baked mesh takes about a second, and a
    generator asks for hundreds of frames.
    """

    def __init__(self) -> None:
        self.adapter, self.device = screen_gpu.make_device()
        folder = logfile.bundled(BAKED)
        if folder is None:
            raise BridgeError(f"no baked geometry beside {TOOL}")
        self.folder = folder
        self.mesh = scene3d.Scene(self.device, folder)
        self.cell_at = self.mesh.cell_middles(scene3d.KINETIC_SCREEN)
        self.cell_is = kinetic.cell_addresses(self.cell_at)
        self.solid = renderer3d.Renderer3D(self.mesh, "rgba8unorm")
        self.solid.dark_backs(True)
        self._pictures: dict[str, str] = {}
        self._calibrated = False

    # -- what is on the screens ---------------------------------------------

    def put_picture(self, feed: str, rgba) -> None:
        """A still on one screen. The honeycomb wears Screen_Top's."""
        if feed not in self.mesh.screens:
            raise BridgeError(f"no screen called {feed!r}; "
                              f"there are {self.mesh.screens}")
        self.solid.load_calibration(feed, np.ascontiguousarray(rgba))
        self.solid.set_backing(True)

    def calibration(self, on: bool) -> None:
        """The baked test cards on the screens, for finding one's bearings."""
        if on and not self._calibrated:
            for feed in self.mesh.screens:
                picture = self.folder / f"calibrate_{feed}.png"
                if picture.is_file():
                    self.solid.load_calibration(feed, _read_png(picture))
            self._calibrated = True
        self.solid.set_backing(bool(on) or bool(self._pictures))

    # -- where the camera stands --------------------------------------------

    def aim(self, view: str, width: int, height: int,
            yaw: float | None = None, pitch: float | None = None,
            distance: float | None = None) -> None:
        """`camera` is the file's own 9x16 projection camera -- the view every
        reference render of this show is made from. `honeycomb` and `orbit`
        are a free camera, the first framed on the cells."""
        if view == "camera":
            self.mesh.fly(False)
            self.mesh.spill = (1.0, 1.0)
            self.mesh.crop_to(width, height)
            return
        self.mesh.uncrop()
        self.mesh.fly(True)
        free = self.mesh.free
        free.frame_aspect = None
        free.spill = (1.0, 1.0)
        if view == "honeycomb":
            middle = self.cell_at.mean(axis=0)
            free.centre = np.array([0.0, 0.0, float(middle[2])])
            free.distance = 17.0
            free.pitch = np.radians(6.0)
            free.yaw = np.radians(-135.0)
        elif view != "orbit":
            raise BridgeError(f"view must be camera, honeycomb or orbit, not {view!r}")
        if yaw is not None:
            free.yaw = np.radians(float(yaw))
        if pitch is not None:
            free.pitch = np.radians(float(pitch))
        if distance is not None:
            free.distance = float(distance)

    # -- drawing -------------------------------------------------------------

    def draw(self, pose: dict, width: int = 540, height: int = 960,
             view: str = "camera", pieces: str = "all",
             mark_over_limit: bool = True, paint: str | None = None,
             **camera) -> np.ndarray:
        """One frame of this pose, as an RGBA array."""
        wanted = {
            "all": lambda name: name != scene3d.DEFAULT_TOP,
            "honeycomb": lambda name: name == scene3d.KINETIC_SCREEN,
            "building": lambda name: name not in (scene3d.KINETIC_SCREEN,),
        }.get(pieces)
        if wanted is None:
            raise BridgeError(f"pieces must be all, honeycomb or building, "
                              f"not {pieces!r}")
        for piece in self.mesh.pieces:
            self.solid.show(piece.name, wanted(piece.name))

        self.solid.set_cells(kinetic.transforms(
            self.cell_at, self.cell_is, PoseMotors(pose), 0))

        rows, ids = self.cell_is[:, 0], self.cell_is[:, 1]
        colours = _paint_colours(pose, paint)
        over = np.zeros((ROWS, PER_ROW, 4), np.float32)
        if mark_over_limit:
            over[km.over_limit(pose["tilt"], pose["lift"], pose["push"])] = \
                (0.95, 0.25, 0.25, 0.75)
        self.solid.set_tints(colours[rows, ids], over[rows, ids])
        self.solid.show_paint(paint is not None)

        self.aim(view, width, height, **camera)
        return self.solid.to_array(int(width), int(height))


# Dark grey, the editor's own, so a cell at rest is not mistaken for a hole.
_DARK = np.array([0.10, 0.105, 0.115], np.float32)
_FAMILY = {"lift": (0.42, 0.65, 0.95), "push": (0.45, 0.85, 0.55),
           "tilt": (0.55, 0.60, 0.95)}


def _paint_colours(pose: dict, paint: str | None) -> np.ndarray:
    """Every cell's colour when the cells are shown in paint, not in video."""
    if paint is None:
        return np.zeros((ROWS, PER_ROW, 3), np.float32)
    if paint == "lift":
        level = np.interp(km.spread("lift", pose["lift"]), [0, 1, 2, 3],
                          [0.0, 0.33, 0.66, 1.0])
    elif paint == "push":
        level = km.spread("push", pose["push"])
    elif paint == "tilt":
        level = np.abs(pose["tilt"]) / 0.5
    else:
        raise BridgeError(f"paint must be lift, push or tilt, not {paint!r}")
    colour = np.array(_FAMILY[paint], np.float32)
    level = np.clip(level, 0, 1)[..., None].astype(np.float32)
    return _DARK * (1 - level) + colour * level


def _read_png(path: Path) -> np.ndarray:
    """A picture as RGBA, without dragging Qt in to do it."""
    from PIL import Image
    with Image.open(path) as picture:
        return np.asarray(picture.convert("RGBA"), dtype=np.uint8)


# -- a piece in time ----------------------------------------------------------

class Session:
    """One open piece and one studio, kept between calls.

    A generator works on a piece the way the editor does: keys at frames, with
    the motors carrying on through frames they are not keyed at. The two
    things worth knowing before exporting are in `simulate` -- a command sent
    while a motor is still moving is thrown away by the machine, not queued.
    """

    def __init__(self) -> None:
        self.project = km.Project()
        self.path: Path | None = None
        self.notes: list[str] = []
        self._studio: Studio | None = None

    @property
    def studio(self) -> Studio:
        if self._studio is None:
            self._studio = Studio()
        return self._studio

    # -- the document --------------------------------------------------------

    def new(self, seconds: float = 20.0, name: str = "generated") -> dict:
        self.project = km.Project(length=max(1, int(round(seconds * km.FPS))))
        self.project.name = name
        self.path = None
        self.notes = []
        return self.summary()

    def open(self, path: str | Path) -> dict:
        path = Path(path)
        if not path.is_file():
            raise BridgeError(f"no such file: {path}")
        if path.suffix.lower() == ".json":
            self.project, self.notes = km.from_motor_json(path)
        else:
            self.project, self.notes = km.Project.load(path), []
        self.path = path
        return self.summary()

    def save(self, path: str | Path) -> dict:
        self.project.save(Path(path))
        self.path = Path(path)
        return {"written": str(self.path)}

    def export(self, path: str | Path, plan: bool = True) -> dict:
        """The motor JSON the site plays, in Houdini's own layout.

        Planned by default: keys straight out of a generator are moves butted
        end to end, and the machine drops every command that lands while a
        motor is still going. See `simulate`.
        """
        piece = self.planned() if plan else self.project
        written = km.export_motor_json(piece, Path(path))
        return {"written": str(written), "planned": bool(plan),
                "frames": km.last_arrival(piece) + 1}

    # -- reading and writing keys --------------------------------------------

    def summary(self) -> dict:
        keys = {family: len(track) for family, track in self.project.tracks.items()}
        violations = self.project.violations()
        return {
            "name": self.project.name,
            "path": None if self.path is None else str(self.path),
            "frames": int(self.project.length),
            "seconds": round(self.project.length / km.FPS, 3),
            "fps": km.FPS,
            "keys": keys,
            "key_frames": self.project.key_frames()[:64],
            "over_limit_frames": len(violations),
            "notes": self.notes,
        }

    def pose_at(self, frame: float) -> dict:
        pose = self.project.pose(float(frame))
        return {"frame": frame, "pose": pose_out(pose),
                "check": check(pose["lift"], pose["push"], pose["tilt"])}

    def key(self, frame: int, lift=None, push=None, tilt=None,
            fit_first: bool = True) -> dict:
        """Put a key on every motor the call names, at one frame."""
        asked = {"lift": lift, "push": push, "tilt": tilt}
        given = [name for name, value in asked.items() if value is not None]
        if not given:
            raise BridgeError("name at least one of lift, push or tilt")
        standing = self.project.pose(float(frame))
        pose = pose_from(*(asked[name] if asked[name] is not None else standing[name]
                           for name in ("lift", "push", "tilt")))
        report = None
        keyed = set(given)
        if fit_first:
            report = fit(pose["lift"], pose["push"], pose["tilt"])
            pose = pose_from(**{name: np.asarray(value)
                                for name, value in report["pose"].items()})
            # Fitting moves motors the caller did not name -- jacks for the
            # room a tilt needs, pushers to clear the beam. Those have to be
            # keyed as well, or what is written is not what was fitted.
            keyed |= {name for name, count in report["changed"].items() if count}
        frame = int(frame)
        for family in sorted(keyed):
            track = self.project.tracks[family]
            track.write(frame, pose[family].reshape(-1),
                        np.ones(track.size, bool))
        return {"frame": frame, "keyed": sorted(keyed),
                "fit": report, "summary": self.summary()}

    # -- what the machine would really do ------------------------------------

    def planned(self) -> km.Project:
        """The keys spaced out into commands the motors can take."""
        import kin_plan
        return kin_plan.plan(self.project)

    def simulate(self, plan: bool = True) -> dict:
        piece = self.planned() if plan else self.project
        result = kin_sim.simulate(piece)
        worst = result.worst_late()
        return {
            "planned": bool(plan),
            "dropped": len(result.dropped),
            "late": len(result.late),
            "worst_late_frames": None if worst is None else int(worst.arrives - worst.due),
            "over_limit_moments": len(result.clashes),
            "by_family": result.by_family(),
            "first_problem_frames": result.problems()[:16],
            "arrives_at_frame": int(km.last_arrival(piece)),
            "advice": _advice(result),
        }


def _advice(result) -> list[str]:
    said = []
    if result.dropped:
        said.append(
            f"{len(result.dropped)} commands were thrown away: the machine "
            "ignores a move that arrives while that motor is still going or "
            "resting. Spread the keys further apart in time, or export with "
            "plan=true, which does it for you.")
    if result.late:
        said.append(f"{len(result.late)} moves arrive after the key asked for "
                    "them -- a jack needs 15 s for its whole travel.")
    if result.clashes:
        said.append(f"{len(result.clashes)} moments have a cell tilted past "
                    "its gaps while the jacks are between states. Raise the "
                    "jacks earlier than the tilts, not at the same frame.")
    if not said:
        said.append("every command is carried out on time.")
    return said


_SESSION: Session | None = None


def session() -> Session:
    """The one open piece, made on first use."""
    global _SESSION
    if _SESSION is None:
        _SESSION = Session()
    return _SESSION


# -- making a shape in the first place ---------------------------------------

def profile(points, close_the_top: bool = False) -> dict:
    """A vase profile sampled at every ring: (height 0..1, reach 0..1) pairs.

    Monotone between the points, so a curve drawn to 1.0 at its widest does
    not overshoot to 1.07 on the way -- a pusher cannot go there.
    """
    curve = km.profile_curve([(float(h), float(v)) for h, v in points], ROWS)
    push = np.repeat(np.asarray(curve, np.float64)[:, None], GROUPS, axis=1)
    if close_the_top:
        push[-1] = 0.0
    return {"push": push.round(6).tolist(),
            "per_ring": np.asarray(curve, np.float64).round(6).tolist()}


def auto_tilt(lift=None, push=None, gain: float = 1.0) -> dict:
    """Every cell turned to lie along the shape the jacks and pushers make.

    Houdini's own auto-rotate. A shape widening upwards tilts its cells face
    down, which is the positive way. Nothing here is limited -- run `fit` on
    the result, which is what raises the jacks the tilts have just asked for.
    """
    pose = pose_from(lift, push)
    tilt = km.auto_tilt(pose["lift"], pose["push"], float(gain))
    return {"tilt": np.asarray(tilt, np.float64).round(6).tolist(),
            "degrees_widest": round(float(np.abs(tilt).max() * TILT_DEGREES), 2)}


def ring_heights(lift=None) -> list:
    """Where each ring's middle stands, in metres, at this jack pose."""
    return km.ring_heights(_as("lift", lift)).round(4).tolist()


def cell_azimuths() -> list:
    """Where each cell stands round the building, in degrees."""
    return km.cell_azimuths().round(3).tolist()
