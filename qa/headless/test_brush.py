"""The brushes without a window: where a dab lands on the frame, by the frame,
by the building and by the view, and what a stroke does to a picture."""
from __future__ import annotations

import numpy as np

import blender_export
import brush
import scene3d
from conftest import TOOL

FRAME = (4608, 1584)


def _mesh():
    return blender_export.Baked(TOOL / "baked")


def test_a_flat_dab_is_a_disc_and_goes_round_the_seam():
    xs, ys, w = brush.flat_dab((100, 50), (50.0, 25.0), 10.0, 0.5)
    assert w.max() == 1.0 and np.hypot(xs + 0.5 - 50, ys + 0.5 - 25).max() <= 10.0
    inner = np.hypot(xs + 0.5 - 50, ys + 0.5 - 25) <= 5.0
    assert np.all(w[inner] == 1.0)                      # the hard middle
    xs, ys, w = brush.flat_dab((100, 50), (2.0, 25.0), 6.0, 0.0)
    assert xs.max() == 99 and xs.min() == 0             # across the seam, on the other edge
    assert (xs >= 0).all() and (xs < 100).all()


def test_a_stroke_takes_the_strongest_dab_and_is_undone():
    picture = np.full((20, 20, 4), 255, np.uint8)       # a white mask
    stroke = brush.Stroke(picture, "mask", flow=0.5)
    xs, ys, w = brush.flat_dab((20, 20), (10.0, 10.0), 4.0, 0.9)
    stroke.dab(xs, ys, w)
    once = picture.copy()
    stroke.dab(xs, ys, w)                                # the same place again
    assert np.array_equal(picture, once)                 # not darker for it
    assert picture[10, 10, 0] == 128 and picture[0, 0, 0] == 255
    y0, y1, x0, x1, was = stroke.undo()
    picture[y0:y1, x0:x1] = was
    assert (picture == 255).all()
    # The eraser brings a mask back to white.
    picture[...] = 0
    picture[..., 3] = 255
    brush.Stroke(picture, "mask", erase=True).dab(xs, ys, w)
    assert picture[10, 10, 0] == 255 and picture[0, 0, 0] == 0


def test_paint_lies_its_colour_over_and_the_eraser_takes_it_away():
    picture = np.zeros((10, 10, 4), np.uint8)
    xs, ys, w = brush.flat_dab((10, 10), (5.0, 5.0), 3.0, 0.9)
    brush.Stroke(picture, "paint", colour=(255, 0, 0)).dab(xs, ys, w)
    assert tuple(picture[5, 5]) == (255, 0, 0, 255) and picture[0, 0, 3] == 0
    brush.Stroke(picture, "paint", colour=(0, 0, 255), flow=0.5).dab(xs, ys, w)
    assert picture[5, 5, 3] == 255 and 120 < picture[5, 5, 0] < 135 and 120 < picture[5, 5, 2] < 135
    brush.Stroke(picture, "paint", erase=True).dab(xs, ys, w)
    assert picture[5, 5, 3] == 0


def _middle_triangle(raw, name):
    points = np.asarray(raw[f"{name}__points"], np.float64)
    triangles = np.asarray(raw[f"{name}__triangles"], np.int64)
    normals = np.asarray(raw[f"{name}__normals"], np.float64)
    uv = np.asarray(raw[f"{name}__uv"], np.float64)
    middle = points[triangles].mean(1)
    pick = int(np.argmin(np.abs(uv[triangles].mean(1) - (0.4, 0.5)).sum(1)))
    normal = normals[triangles[pick]].mean(0)
    return middle[pick], normal / np.linalg.norm(normal), uv[triangles[pick]].mean(0)


def test_a_model_dab_lies_on_the_surface_within_its_radius():
    raw = _mesh().raw
    geometry = brush.Geometry.of(raw, "Screen_Bottom", FRAME)
    centre, normal, uv = _middle_triangle(raw, "Screen_Bottom")
    radius = 0.3
    xs, ys, w = brush.model_dab(geometry, centre, normal, radius, 0.5)
    assert len(xs) > 100
    # The pixel under the middle is fully in it.
    at = (int(uv[0] * FRAME[0]), int((1 - uv[1]) * FRAME[1]))
    hit = (xs == at[0]) & (ys == at[1])
    assert hit.any() and w[hit].max() == 1.0
    # Every pixel painted is on the building within the radius of the middle.
    every = geometry.pixels(np.arange(len(geometry.triangles)))
    where = {(x, y): p for x, y, p in zip(every[0], every[1], every[2])}
    far = max(np.linalg.norm(where[(x, y)] - centre) for x, y in zip(xs[:500], ys[:500]))
    assert far <= radius * 1.25
    # A bigger brush covers about as many more pixels as its area says.
    xs2, _, _ = brush.model_dab(geometry, centre, normal, radius * 2, 0.5)
    assert 3.0 < len(xs2) / len(xs) < 5.0


def test_a_camera_dab_is_a_circle_of_the_view():
    mesh = _mesh()
    raw = mesh.raw
    matrix = np.array(raw["camera_matrix"], np.float64)
    size = (1080, 1920)
    vp = scene3d.projection(mesh.lens, mesh.sensor, str(raw["sensor_fit"]), size, 0.1, 1000.0) \
        @ scene3d.look_through(matrix)
    geometry = brush.Geometry.of(raw, "Screen_Bottom", FRAME)
    centre, _, _ = _middle_triangle(raw, "Screen_Bottom")
    clip = vp @ np.array([*centre, 1.0])
    at = ((clip[0] / clip[3] + 1) / 2 * size[0], (1 - clip[1] / clip[3]) / 2 * size[1])
    xs, ys, w = brush.camera_dab(geometry, vp, size, at, 25.0, 0.5)
    assert len(xs) > 50 and w.max() == 1.0
    every = geometry.pixels(np.arange(len(geometry.triangles)))
    where = {(x, y): p for x, y, p in zip(every[0], every[1], every[2])}
    for x, y in list(zip(xs, ys))[::37]:
        seen = vp @ np.array([*where[(x, y)], 1.0])
        px = ((seen[0] / seen[3] + 1) / 2 * size[0], (1 - seen[1] / seen[3]) / 2 * size[1])
        assert np.hypot(px[0] - at[0], px[1] - at[1]) <= 25.0 + 1e-6
