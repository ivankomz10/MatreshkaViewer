"""Which screen, and which point of its frame, is under a point of the picture.

For the advanced mode's tools: a layer is moved by dragging it where it is
seen, on the building as much as on the flat strips. The building is drawn
through one matrix, the view and the projection together (`Scene.
view_projection`), across the whole canvas; a point of the canvas is undone
through it into a ray, and the ray is met with the screens' triangles --
Möller and Trumbore, all of a screen's triangles at once in numpy, a few
milliseconds for the largest. The nearest screen met is the one seen.

Where a ray meets a triangle the UVs of its corners are mixed by the same
weights, and a UV is a point of the screen's frame: across from the left,
down from the top -- the scene reads its video at (u, 1 - v).
"""
from __future__ import annotations

import numpy as np

# The baked surfaces that show a screen's frame, by the screen they show.
SURFACES = {"Screen_Top": ("Screen_Top", "screen"), "Screen_Bottom": ("Screen_Bottom",),
            "Lamel_screen": ("Lamel_screen",)}


def ray(view_projection: np.ndarray, size: tuple, at: tuple):
    """(origin, direction) in the world of a point of the canvas, in pixels."""
    width, height = size
    x = at[0] / max(width, 1) * 2.0 - 1.0
    y = 1.0 - at[1] / max(height, 1) * 2.0
    undo = np.linalg.inv(np.asarray(view_projection, np.float64))
    near = undo @ np.array([x, y, 0.0, 1.0])
    far = undo @ np.array([x, y, 1.0, 1.0])
    near, far = near[:3] / near[3], far[:3] / far[3]
    way = far - near
    return near, way / np.linalg.norm(way)


def meet(origin, direction, points, triangles):
    """(distance, triangle, u, v) of the nearest triangle the ray meets, or None."""
    a = points[triangles[:, 0]]
    edge1 = points[triangles[:, 1]] - a
    edge2 = points[triangles[:, 2]] - a
    p = np.cross(direction, edge2)
    det = np.einsum("ij,ij->i", edge1, p)
    ok = np.abs(det) > 1e-12
    inv = np.zeros_like(det)
    inv[ok] = 1.0 / det[ok]
    s = origin - a
    u = np.einsum("ij,ij->i", s, p) * inv
    q = np.cross(s, edge1)
    v = (q @ direction) * inv
    t = np.einsum("ij,ij->i", edge2, q) * inv
    hit = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 0)
    if not hit.any():
        return None
    index = np.nonzero(hit)[0]
    best = index[np.argmin(t[index])]
    return float(t[best]), int(best), float(u[best]), float(v[best])


class Picker:
    """The screens' surfaces, ready to be met by rays."""

    def __init__(self, raw) -> None:
        self.surfaces = {}
        for name in {one for group in SURFACES.values() for one in group}:
            if f"{name}__points" not in raw.files:
                continue
            self.surfaces[name] = (np.asarray(raw[f"{name}__points"], np.float64),
                                   np.asarray(raw[f"{name}__triangles"], np.int64),
                                   np.asarray(raw[f"{name}__uv"], np.float64))

    def pick(self, view_projection, size, at, shown=None, posed=None):
        """(screen, (u, v) of its frame with v down) under a point, or None.

        `shown` names the surfaces on show (the top screen is drawn either at
        rest or on its motors, never both); `posed` gives a surface its
        vertices as they stand now, where they move."""
        origin, direction = ray(view_projection, size, at)
        best = None
        for screen, names in SURFACES.items():
            for name in names:
                if name not in self.surfaces or (shown is not None and name not in shown):
                    continue
                points, triangles, uv = self.surfaces[name]
                if posed is not None and name in posed:
                    points = posed[name]
                got = meet(origin, direction, points, triangles)
                if got is None or (best is not None and got[0] >= best[0]):
                    continue
                t, index, u, v = got
                corners = uv[triangles[index]]
                mixed = corners[0] * (1 - u - v) + corners[1] * u + corners[2] * v
                best = (t, screen, (float(mixed[0]), float(1.0 - mixed[1])), origin + direction * t)
        return None if best is None else (best[1], best[2])

    def world(self, view_projection, size, at, shown=None, posed=None):
        """The point of the building under a point of the canvas, or None."""
        origin, direction = ray(view_projection, size, at)
        best = None
        for names in SURFACES.values():
            for name in names:
                if name not in self.surfaces or (shown is not None and name not in shown):
                    continue
                points, triangles, _ = self.surfaces[name]
                if posed is not None and name in posed:
                    points = posed[name]
                got = meet(origin, direction, points, triangles)
                if got is not None and (best is None or got[0] < best):
                    best = got[0]
        return None if best is None else origin + direction * best

    def on_frame(self, name, at, posed=None):
        """The point of the building a point of a surface's frame is on --
        (u, v) with v down -- or None where the frame shows nothing."""
        if name not in self.surfaces:
            return None
        points, triangles, uv = self.surfaces[name]
        if posed is not None and name in posed:
            points = posed[name]
        want = np.array([at[0], 1.0 - at[1]])
        a, b, c = (uv[triangles[:, k]] for k in range(3))
        e1, e2, s = b - a, c - a, want - a
        det = e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]
        ok = np.abs(det) > 1e-14
        det = np.where(ok, det, 1.0)
        u = (s[:, 0] * e2[:, 1] - s[:, 1] * e2[:, 0]) / det
        v = (e1[:, 0] * s[:, 1] - e1[:, 1] * s[:, 0]) / det
        inside = ok & (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9)
        if not inside.any():
            return None
        index = int(np.nonzero(inside)[0][0])
        corners = points[triangles[index]]
        return corners[0] * (1 - u[index] - v[index]) + corners[1] * u[index] + corners[2] * v[index]
