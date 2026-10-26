"""The advanced mode's brushes: where a dab lands on a screen's frame, and
what a stroke does to the picture it is painted into.

What is painted is always a picture of the screen's frame -- a layer's mask
or one of its paint effects (`layer_rasters`) -- and a dab is a set of the
frame's pixels with a weight each, worked out one of three ways:

  flat    a disc on the frame itself, in its pixels; across the seam the
          frame goes round the building, so the disc does too
  model   a disc on the building where the pointer is, lying flat against
          the surface there (its normal), in centimetres: a pixel is in it
          when its place on the building is within the radius along the
          surface, not further off it than 0.6 of the radius, and facing much
          the same way -- the far side of an edge is not painted through
  camera  a circle in the view, in its pixels: every place of the screen the
          view sees inside it, facing the view

Only the triangles near the dab are looked at: the screen's mesh is drawn in
its own UV (each triangle onto the part of the frame it shows), pixel centres
inside it found by their weights, and those weights mix the corners' places
on the building.

Within one stroke a pixel takes the strongest weight any of its dabs gave it,
not the sum -- a slow stroke is not darker than a quick one -- and the stroke
is laid over the picture as it was when the stroke began. A brush paints its
colour into paint and black into a mask (hiding the layer there); the eraser
takes paint away and brings a mask back to white. A stroke remembers what it
covered, for undoing.
"""
from __future__ import annotations

import numpy as np

MODES = ("flat", "model", "camera")
DEPTH = 0.6             # of the radius: how far off the surface a model dab reaches
FACING = 0.3            # the least cosine between a pixel's normal and the dab's


class Geometry:
    """A screen's mesh on its frame: for finding which pixels a dab covers."""

    def __init__(self, points, triangles, uv, normals, frame: tuple) -> None:
        self.points = np.asarray(points, np.float64)
        self.triangles = np.asarray(triangles, np.int64)
        self.uv = np.asarray(uv, np.float64)
        self.normals = np.asarray(normals, np.float64)
        self.width, self.height = int(frame[0]), int(frame[1])
        corners = self.points[self.triangles]
        self.middles = corners.mean(axis=1)
        self.reach = np.linalg.norm(corners - self.middles[:, None], axis=2).max(axis=1)
        # The corners in frame pixels, v down.
        uv = self.uv[self.triangles]
        self.px = np.stack([uv[..., 0] * self.width, (1.0 - uv[..., 1]) * self.height], -1)

    @classmethod
    def of(cls, raw, name: str, frame: tuple) -> "Geometry":
        return cls(raw[f"{name}__points"], raw[f"{name}__triangles"], raw[f"{name}__uv"],
                   raw[f"{name}__normals"], frame)

    def pixels(self, chosen, points=None):
        """(xs, ys, places, normals) of the frame pixels inside the chosen
        triangles: their centres, and where on the building each one is --
        at rest, or on `points` where they stand now."""
        points = self.points if points is None else np.asarray(points, np.float64)
        xs, ys, places, normals = [], [], [], []
        for index in np.asarray(chosen, np.int64):
            a, b, c = self.px[index]
            low = np.floor(np.minimum(np.minimum(a, b), c)).astype(int)
            high = np.ceil(np.maximum(np.maximum(a, b), c)).astype(int)
            low = np.maximum(low, 0)
            high = np.minimum(high, (self.width, self.height))
            if (high <= low).any():
                continue
            gx, gy = np.meshgrid(np.arange(low[0], high[0]), np.arange(low[1], high[1]))
            centre = np.stack([gx.ravel() + 0.5, gy.ravel() + 0.5], -1)
            e1, e2, s = b - a, c - a, centre - a
            det = e1[0] * e2[1] - e1[1] * e2[0]
            if abs(det) < 1e-12:
                continue
            u = (s[:, 0] * e2[1] - s[:, 1] * e2[0]) / det
            v = (e1[0] * s[:, 1] - e1[1] * s[:, 0]) / det
            inside = (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9)
            if not inside.any():
                continue
            u, v = u[inside], v[inside]
            corner = self.triangles[index]
            p = points[corner]
            n = self.normals[corner]
            w = np.stack([1 - u - v, u, v], -1)
            xs.append(gx.ravel()[inside])
            ys.append(gy.ravel()[inside])
            places.append(w @ p)
            normals.append(w @ n)
        if not xs:
            empty = np.zeros(0, np.int64)
            return empty, empty, np.zeros((0, 3)), np.zeros((0, 3))
        normals = np.concatenate(normals)
        normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)
        return np.concatenate(xs), np.concatenate(ys), np.concatenate(places), normals


def falloff(distance, radius: float, hardness: float):
    """1 inside the hard middle, down to 0 at the edge."""
    hard = radius * min(max(hardness, 0.0), 0.99)
    return np.clip((radius - distance) / max(radius - hard, 1e-9), 0.0, 1.0)


def flat_dab(frame: tuple, at, radius: float, hardness: float):
    """(xs, ys, weights) of a disc on the frame at `at`, in its pixels; the
    frame's left and right edges meet, as they do round the building."""
    width, height = int(frame[0]), int(frame[1])
    r = int(np.ceil(radius))
    gx, gy = np.meshgrid(np.arange(int(at[0]) - r - 1, int(at[0]) + r + 2),
                         np.arange(max(0, int(at[1]) - r - 1), min(height, int(at[1]) + r + 2)))
    distance = np.hypot(gx + 0.5 - at[0], gy + 0.5 - at[1])
    weight = falloff(distance, radius, hardness)
    keep = weight > 0
    return (gx[keep] % width).astype(np.int64), gy[keep].astype(np.int64), weight[keep]


def model_dab(geometry: Geometry, centre, normal, radius: float, hardness: float):
    """(xs, ys, weights) of a disc lying on the building at `centre`, facing
    `normal`, `radius` in the building's units (metres)."""
    centre = np.asarray(centre, np.float64)
    normal = np.asarray(normal, np.float64)
    normal = normal / max(np.linalg.norm(normal), 1e-12)
    near = np.nonzero(np.linalg.norm(geometry.middles - centre, axis=1)
                      <= radius + geometry.reach)[0]
    xs, ys, places, normals = geometry.pixels(near)
    off = places - centre
    height = off @ normal
    along = np.linalg.norm(off - height[:, None] * normal, axis=1)
    weight = falloff(along, radius, hardness)
    weight = np.where((np.abs(height) <= DEPTH * radius) & (normals @ normal >= FACING), weight, 0.0)
    keep = weight > 0
    return xs[keep], ys[keep], weight[keep]


def camera_dab(geometry: Geometry, view_projection, size: tuple, at, radius: float,
               hardness: float, points=None):
    """(xs, ys, weights) of a circle of the view at `at`, `radius` in the
    view's pixels: the places of the screen it sees there, facing it."""
    points = geometry.points if points is None else np.asarray(points, np.float64)
    vp = np.asarray(view_projection, np.float64)
    width, height = size
    clip = np.concatenate([points, np.ones((len(points), 1))], 1) @ vp.T
    w = np.where(np.abs(clip[:, 3]) > 1e-9, clip[:, 3], 1e-9)
    screen = np.stack([(clip[:, 0] / w + 1) / 2 * width, (1 - clip[:, 1] / w) / 2 * height], -1)
    corners = screen[geometry.triangles]
    ahead = (clip[geometry.triangles][..., 3] > 0).all(axis=1)
    middle = corners.mean(axis=1)
    spread = np.linalg.norm(corners - middle[:, None], axis=2).max(axis=1)
    near = np.nonzero(ahead & (np.linalg.norm(middle - np.asarray(at, np.float64), axis=1)
                               <= radius + spread))[0]
    xs, ys, places, normals = geometry.pixels(near, points)
    if not len(xs):
        return xs, ys, np.zeros(0)
    eye = _eye(vp)
    facing = (normals * (eye - places)).sum(axis=1) > 0
    seen = np.concatenate([places, np.ones((len(places), 1))], 1) @ vp.T
    sx = (seen[:, 0] / seen[:, 3] + 1) / 2 * width
    sy = (1 - seen[:, 1] / seen[:, 3]) / 2 * height
    weight = falloff(np.hypot(sx - at[0], sy - at[1]), radius, hardness)
    weight = np.where(facing & (seen[:, 3] > 0), weight, 0.0)
    keep = weight > 0
    return xs[keep], ys[keep], weight[keep]


def _eye(view_projection) -> np.ndarray:
    rows = np.asarray(view_projection, np.float64)[[0, 1, 3]]
    return np.linalg.solve(rows[:, :3], -rows[:, 3])


class Stroke:
    """One stroke into one picture: dabs laid over the picture as the stroke
    found it, each pixel as strongly as its strongest dab."""

    def __init__(self, array, kind: str, colour=(255, 255, 255), flow: float = 1.0,
                 erase: bool = False) -> None:
        self.array = array                       # (h, w, 4) uint8, changed in place
        self.kind = kind                         # "paint" | "mask"
        self.colour = np.asarray(colour, np.float64)[:3] / 255.0
        self.flow = float(min(max(flow, 0.0), 1.0))
        self.erase = bool(erase)
        self.before = array.copy()
        self.weight = np.zeros(array.shape[:2], np.float32)
        self.box = None                          # (y0, y1, x0, x1) covered so far

    def dab(self, xs, ys, weights):
        """Laid; the (y0, y1, x0, x1) of the frame it changed, or None."""
        if not len(xs):
            return None
        weights = np.asarray(weights, np.float32) * self.flow
        np.maximum.at(self.weight, (ys, xs), weights)
        box = (int(ys.min()), int(ys.max()) + 1, int(xs.min()), int(xs.max()) + 1)
        y0, y1, x0, x1 = box
        self.box = box if self.box is None else (min(self.box[0], y0), max(self.box[1], y1),
                                                 min(self.box[2], x0), max(self.box[3], x1))
        self._lay(y0, y1, x0, x1)
        return box

    def _lay(self, y0, y1, x0, x1) -> None:
        was = self.before[y0:y1, x0:x1].astype(np.float64) / 255.0
        a = self.weight[y0:y1, x0:x1, None].astype(np.float64)
        if self.kind == "mask":
            goal = 1.0 if self.erase else 0.0
            value = was[..., :3] + (goal - was[..., :3]) * a
            out = np.concatenate([value, np.ones_like(a)], -1)
        elif self.erase:
            out = np.concatenate([was[..., :3], was[..., 3:] * (1 - a)], -1)
        else:
            alpha = a + was[..., 3:] * (1 - a)
            colour = (self.colour * a + was[..., :3] * was[..., 3:] * (1 - a)) / np.maximum(alpha, 1e-9)
            out = np.concatenate([np.where(alpha > 0, colour, 0.0), alpha], -1)
        self.array[y0:y1, x0:x1] = np.round(np.clip(out, 0, 1) * 255).astype(np.uint8)

    def undo(self):
        """What to put back to undo it: (y0, y1, x0, x1, pixels), or None."""
        if self.box is None:
            return None
        y0, y1, x0, x1 = self.box
        return y0, y1, x0, x1, self.before[y0:y1, x0:x1].copy()
