"""The top screen's motion, out to Blender: a scene that renders the screen's
own frame, every frame, with the cells where the motors put them.

The remap the content team has used so far is still. The picture is rendered
from the viewer's camera (`Zaryadye_ProjectionCamera_9x16_v1`, 9:16), the top
screen takes it through UVs projected from that camera once, and the screen
unrolled flat to its own UV layout is filmed from straight above: what comes
out is the frame the screen plays. On a kinetic screen that is right only at
rest. A cell pushed out a metre or swung thirty degrees is somewhere else, and
its piece of the picture belongs to wherever it now is.

So the projection is worked out again on every frame, on the cells as they
stand. The viewer already knows where they stand -- the same motors, measured
against Blender's own rig to 5.6 mm -- so nothing goes through Houdini or an
FBX: the vertices of every frame are written as a point cache (.pc2), and a
script run inside Blender builds the scene around it.

What Blender gets, in centimetres as the studio's own files are:

  Top 3D          the cells on the cache, the building around them, the
                  viewer's camera, the camera the viewer was looking through
                  when this was exported, and an empty for the decal
  Top развертка   the same cells unrolled to the screen's frame and filmed
                  from above, 2560 x 1150, every frame: what goes back on the
                  timeline at the frame it came from

and one projection in geometry nodes, three ways, chosen by a number on the
modifier and kept switchable in the file:

  0 по зрителю    from the viewer's camera, as the remap always was, but on
                  the cells as they stand that frame: from where the audience
                  sits the picture holds together and the moving cells cut it
                  into hexes
  1 декаль        laid on the cells round the building, in metres of their
                  own surface, so it is not stretched by the shape: the cells
                  carry it as they move
  2 с камеры вида from the camera the viewer was looking through, for a
                  projector anywhere else

The script that runs inside Blender is `blender_top.py`; everything it is told
goes in one JSON beside the cache.
"""
from __future__ import annotations

import json
import os
import re
import struct
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

import kinetic
import scene3d
from lang import tr

MODES = ("viewer", "decal", "view")
FPS = 60
FRAME = (2560, 1150)               # the top screen's own frame
CONTENT = (2160, 3840)             # what the viewer's camera renders, 9:16
CM = 100.0                         # the viewer is in metres, the studio in cm
SCRIPT = Path(__file__).resolve().with_name("blender_top.py")
BLENDERS = Path(r"C:\Program Files\Blender Foundation")
# The name the second camera has in the .blend: a name in a file, not a word
# of the window, so it is the same in either language.
VIEW_CAMERA = "Камера вида"


class BlenderExportError(Exception):
    """The scene could not be made; says why."""


@dataclass
class Request:
    """What to make: a stretch of the show, a picture, a way of laying it."""

    target: str                    # the .blend to write
    first: int                     # show frame of the first frame
    length: int                    # how many frames
    mode: str = "viewer"
    source: str = ""               # picture, sequence or movie; "" for a test grid
    source_offset: int = 0         # which frame of it the first frame shows
    name: str = ""
    view: dict = field(default_factory=dict)    # the camera being looked through


# -- Blender itself ------------------------------------------------------------

def _version(path: Path) -> tuple:
    found = re.search(r"(\d+)\.(\d+)", path.parent.name)
    return (int(found.group(1)), int(found.group(2))) if found else (0, 0)


def find_blender(remembered: str = "") -> str:
    """The Blender to run: the one remembered if it is still there, else the
    newest one installed. "" when there is none."""
    if remembered and Path(remembered).is_file():
        return remembered
    found = sorted(BLENDERS.glob("*/blender.exe"), key=_version) if BLENDERS.exists() else []
    return str(found[-1]) if found else ""


# -- the baked scene, without a graphics card ------------------------------------

class Baked:
    """What `scene3d.Scene` knows of the bake, read without a device: enough to
    pose the cells and place the cameras, for the tests and anything else that
    runs away from the window."""

    def __init__(self, folder: str | Path) -> None:
        from types import SimpleNamespace
        data = np.load(Path(folder) / "scene_mesh.npz", allow_pickle=True)
        self.raw = data
        self.names = [str(n) for n in data["order"]]
        self.camera = str(data["camera"])
        self.lens = float(data["lens"])
        self.sensor = tuple(float(v) for v in data["sensor"])
        self.pieces = [SimpleNamespace(name=n, cell=np.asarray(data[f"{n}__cell"])
                                       if f"{n}__cell" in data.files else None)
                       for n in self.names]

    points_of = scene3d.Scene.points_of
    cell_middles = scene3d.Scene.cell_middles


# -- where the cells stand -------------------------------------------------------

class Poser:
    """The top screen's vertices at a show frame, in metres.

    `motors_at` is what the window plays the cells from: a function of the
    show frame giving (motors, their own frame) or None for rest.
    """

    def __init__(self, mesh, motors_at) -> None:
        raw = mesh.raw
        name = scene3d.KINETIC_SCREEN
        self.points = np.asarray(raw[f"{name}__points"], np.float64)
        self.normals = np.asarray(raw[f"{name}__normals"], np.float64)
        self.uv = np.asarray(raw[f"{name}__uv"], np.float32)
        self.triangles = np.asarray(raw[f"{name}__triangles"], np.int64)
        self.cell = np.asarray(raw[f"{name}__cell"], np.int64)
        self.cell_at = mesh.cell_middles(name)
        self.cell_is = kinetic.cell_addresses(self.cell_at)
        self.motors_at = motors_at
        self._rest = np.concatenate([self.points, np.ones((len(self.points), 1))], axis=1)

    def at(self, frame: int) -> np.ndarray:
        got = self.motors_at(frame)
        if got is None:
            return self.points.copy()
        motors, own = got
        m = kinetic.transforms(self.cell_at, self.cell_is, motors, own).astype(np.float64)
        return np.einsum("vij,vj->vi", m[self.cell], self._rest)[:, :3]


def write_pc2(path: Path, frames, count: int, total: int, progress=None) -> None:
    """A point cache as Blender's Mesh Cache reads it: a header, then every
    frame's vertices as float32, one after another."""
    with open(path, "wb") as out:
        out.write(b"POINTCACHE2\0" + struct.pack("<iiffi", 1, count, 1.0, 1.0, total))
        for index, points in enumerate(frames):
            out.write(np.ascontiguousarray(points, np.float32).tobytes())
            if progress is not None and index % 60 == 0:
                progress(index, total)


def read_pc2(path: Path):
    """(frames, count, data) back out of a cache: for the tests."""
    raw = Path(path).read_bytes()
    if raw[:12] != b"POINTCACHE2\0":
        raise BlenderExportError(f"{Path(path).name} is not a point cache")
    _, count, _, _, total = struct.unpack("<iiffi", raw[12:32])
    data = np.frombuffer(raw, np.float32, offset=32).reshape(total, count, 3)
    return total, count, data


# -- the cameras -----------------------------------------------------------------

def file_camera(mesh) -> dict:
    """The viewer's camera as Blender has it: where, which way, what lens.

    The matrix in the bake carries the object's scale of 100 (the studio's
    files are in centimetres and the camera was scaled to match); the axes are
    taken unit length and the position put in centimetres.
    """
    matrix = np.array(mesh.raw["camera_matrix"], np.float64)
    axes = matrix[:3, :3] / np.linalg.norm(matrix[:3, :3], axis=0)
    lens = float(mesh.lens)
    sensor = float(mesh.sensor[0])
    return {"name": str(mesh.camera), "location": (matrix[:3, 3] * CM).tolist(),
            "axes": axes.T.tolist(), "lens": lens, "sensor": sensor,
            # 9:16 under AUTO fit puts the sensor's width on the long side,
            # the vertical: that is the angle the content is rendered at.
            "tan_half": sensor / 2.0 / lens, "resolution": list(CONTENT)}


def view_camera(orbit, fallback: dict) -> dict:
    """The camera the viewer is looking through, for the third projection:
    the Inspection one when there is one, else the file's."""
    if orbit is None:
        return dict(fallback, name=VIEW_CAMERA)
    right, up, forward = orbit.axes()
    tan_half = float(np.tan(orbit.fov_y / 2.0))
    return {"name": VIEW_CAMERA, "location": (np.asarray(orbit.eye()) * CM).tolist(),
            "axes": [list(map(float, right)), list(map(float, up)), list(map(float, -forward))],
            "lens": 12.0 / tan_half, "sensor": 24.0, "tan_half": tan_half,
            "resolution": list(CONTENT)}


def project(points_m: np.ndarray, camera: dict, aspect: float) -> np.ndarray:
    """Where points land in a picture projected from a camera, 0..1 up from
    the bottom left -- the same sum the geometry nodes do, for checking them."""
    axes = np.array(camera["axes"], np.float64)            # rows: right, up, back
    rel = points_m * CM - np.array(camera["location"], np.float64)
    local = rel @ axes.T
    depth = -local[:, 2]
    v = 0.5 + local[:, 1] / depth / (2.0 * camera["tan_half"])
    u = 0.5 + local[:, 0] / depth / (2.0 * camera["tan_half"]) / aspect
    return np.stack([u, v], axis=1)


# -- the rest of the building, for looking at --------------------------------------

def surroundings(mesh) -> list:
    """Everything else in the bake, as plain matte geometry in centimetres."""
    out = []
    for piece in mesh.pieces:
        if piece.name in (scene3d.KINETIC_SCREEN, scene3d.DEFAULT_TOP):
            continue
        out.append(piece.name)
    return out


# -- the export ---------------------------------------------------------------------

def default_target(folder: str | Path, show_name: str, first: int, length: int) -> Path:
    stem = re.sub(r"[^\w\-]+", "_", show_name or "show").strip("_") or "show"
    return Path(folder) / f"{stem}_top_{first:06d}-{first + length - 1:06d}.blend"


def export(request: Request, mesh, motors_at, blender: str, orbit=None,
           progress=None, run=True) -> dict:
    """Write the cache and the scene's description, and have Blender build it.

    Returns what was written: the .blend, the cache, the description, where the
    render will go. `run` False stops before Blender, for the tests.
    """
    if request.mode not in MODES:
        raise BlenderExportError(f"unknown projection {request.mode}")
    if request.length < 1:
        raise BlenderExportError("nothing to export: the stretch is empty")
    target = Path(request.target)
    if target.suffix.lower() != ".blend":
        target = target.with_suffix(".blend")
    target.parent.mkdir(parents=True, exist_ok=True)
    stem = target.stem
    cache = target.with_name(f"{stem}_top.pc2")
    geometry = target.with_name(f"{stem}_top.npz")
    described = target.with_name(f"{stem}_top.json")

    poser = Poser(mesh, motors_at)
    frames = (poser.at(request.first + step) * CM for step in range(request.length))
    write_pc2(cache, frames, len(poser.points), request.length, progress)

    others = {}
    for name in surroundings(mesh):
        others[f"{name}__points"] = np.asarray(mesh.raw[f"{name}__points"], np.float32) * CM
        others[f"{name}__triangles"] = np.asarray(mesh.raw[f"{name}__triangles"], np.uint32)
    np.savez_compressed(geometry, points=(poser.points * CM).astype(np.float32),
                        triangles=poser.triangles.astype(np.uint32), uv=poser.uv,
                        cell=poser.cell.astype(np.int32), names=np.array(list(surroundings(mesh))),
                        **others)

    viewer = file_camera(mesh)
    rest = poser.points
    centre = rest.mean(axis=0)
    toward = np.array(viewer["location"]) / CM - centre
    azimuth = float(np.arctan2(toward[1], toward[0]))
    reach = float(np.linalg.norm(rest[:, :2], axis=1).mean())
    height = float(rest[:, 2].max() - rest[:, 2].min())
    description = {
        "request": asdict(request), "fps": FPS, "frame": list(FRAME),
        "cache": cache.name, "geometry": geometry.name, "target": target.name,
        "render": f"//render/{stem}_top_",
        "mode": MODES.index(request.mode),
        "cameras": {"viewer": viewer, "view": view_camera(orbit, viewer)},
        # The decal starts facing the audience, as tall as the screen.
        "decal": {"location": [float(np.cos(azimuth) * reach * CM), float(np.sin(azimuth) * reach * CM),
                               float(centre[2] * CM)], "height": height * CM},
    }
    described.write_text(json.dumps(description, ensure_ascii=False, indent=1), encoding="utf-8")
    made = {"blend": target, "cache": cache, "geometry": geometry, "description": described,
            "render": target.parent / "render"}
    if not run:
        return made
    if not blender or not Path(blender).is_file():
        raise BlenderExportError(tr("Blender не найден: укажите blender.exe"))
    if target.exists():
        raise BlenderExportError(tr("{0} уже есть, поверх не пишется", target.name))
    env = dict(os.environ)
    result = subprocess.run(
        [blender, "-b", "--factory-startup", "--python-exit-code", "1", "-P", str(SCRIPT), "--", str(described)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=900)
    log = target.with_name(f"{stem}_top_blender.log")
    log.write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
    if result.returncode != 0 or not target.exists():
        tail = (result.stdout + result.stderr).strip().splitlines()[-6:]
        raise BlenderExportError(tr("Blender не собрал сцену:") + "\n" + "\n".join(tail))
    made["log"] = log
    return made
