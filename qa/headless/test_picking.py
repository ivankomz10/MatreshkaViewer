"""Which screen and which point of its frame a point of the picture falls on."""
from __future__ import annotations

import numpy as np

import blender_export
import picking
import scene3d
from conftest import TOOL


def test_a_point_of_a_screen_seen_through_the_camera_is_found_again():
    mesh = blender_export.Baked(TOOL / "baked")
    raw = mesh.raw
    view = scene3d.look_through(np.array(raw["camera_matrix"]))
    projection = scene3d.projection(mesh.lens, mesh.sensor, str(raw["sensor_fit"]), (1080, 1920), 0.1, 1000.0)
    vp = projection @ view
    picker = picking.Picker(raw)
    points = np.asarray(raw["Screen_Bottom__points"], np.float64)
    triangles = np.asarray(raw["Screen_Bottom__triangles"], np.int64)
    uv = np.asarray(raw["Screen_Bottom__uv"], np.float64)
    # A triangle facing the camera, near the middle of what it sees.
    middle = points[triangles].mean(axis=1)
    clip = np.concatenate([middle, np.ones((len(middle), 1))], axis=1) @ vp.T
    ndc = clip[:, :2] / clip[:, 3:4]
    near_middle = np.argsort(np.abs(ndc).sum(axis=1))[:40]
    found = 0
    for index in near_middle:
        x = (ndc[index, 0] + 1) / 2 * 1080
        y = (1 - ndc[index, 1]) / 2 * 1920
        got = picker.pick(vp, (1080, 1920), (x, y), shown={"Screen_Bottom", "Lamel_screen", "Screen_Top"})
        if got is None or got[0] != "Screen_Bottom":
            continue                       # hidden behind the lamellas, from here
        want = uv[triangles[index]].mean(axis=0)
        assert abs(got[1][0] - want[0]) < 1e-3 and abs(got[1][1] - (1 - want[1])) < 1e-3
        found += 1
    assert found >= 10
