"""The top screen out to Blender, without a window.

What has to hold: the cells in the cache stand where the viewer stands them;
the projection the scene does is the viewer's own camera, to the digit; and
the .blend Blender builds plays the cache frame for frame and projects as the
viewer says. The last of these runs Blender itself, so it needs one installed
and a motor file on the content drive; it writes only into the test's folder.
"""
from __future__ import annotations

import glob
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

import blender_export as bx
import kinetic
import scene3d
from conftest import TOOL

HERE = Path(__file__).resolve().parent
BAKED = TOOL / "baked"
MOTORS = sorted(glob.glob(r"D:\Content\Skazka_7-sisters\7Sisters_060_KIN_v004_1_of_1.json"))
needs_motors = pytest.mark.skipif(not MOTORS, reason="the 7Sisters motor file is not here")
BLENDER = bx.find_blender()
needs_blender = pytest.mark.skipif(not BLENDER, reason="no Blender installed")


@pytest.fixture(scope="module")
def mesh():
    return bx.Baked(BAKED)


@pytest.fixture(scope="module")
def placed():
    if not MOTORS:
        pytest.skip("the 7Sisters motor file is not here")
    return kinetic.Placed([(0, kinetic.Motors(MOTORS[0]))])


def test_a_point_cache_reads_back_as_written(tmp_path):
    frames = [np.random.default_rng(seed).normal(size=(7, 3)).astype(np.float32) for seed in range(5)]
    bx.write_pc2(tmp_path / "x.pc2", iter(frames), 7, 5)
    total, count, data = bx.read_pc2(tmp_path / "x.pc2")
    assert (total, count) == (5, 7)
    assert np.array_equal(data, np.stack(frames))


@needs_motors
def test_the_cells_move_whole_and_stand_still_at_rest(mesh, placed):
    poser = bx.Poser(mesh, placed.at)
    rest = bx.Poser(mesh, lambda frame: None).at(1500)
    assert np.array_equal(rest, poser.points)
    moved = poser.at(1500)
    assert np.abs(moved - rest).max() > 0.05          # something is moving there
    for cell in range(0, 1500, 37):                    # and every cell as one body
        corners = np.nonzero(poser.cell == cell)[0]
        before = np.linalg.norm(rest[corners][:, None] - rest[corners][None], axis=2)
        after = np.linalg.norm(moved[corners][:, None] - moved[corners][None], axis=2)
        assert np.abs(before - after).max() < 1e-6


def test_the_projection_is_the_viewers_own_camera(mesh):
    """The sum the geometry nodes do, against the viewer's projection of the
    file camera rendering 9:16."""
    camera = bx.file_camera(mesh)
    points = np.asarray(mesh.raw["screen__points"], np.float64)
    ours = bx.project(points, camera, bx.CONTENT[0] / bx.CONTENT[1])
    view = scene3d.look_through(np.array(mesh.raw["camera_matrix"]))
    proj = scene3d.projection(mesh.lens, mesh.sensor, str(mesh.raw["sensor_fit"]), bx.CONTENT, 0.1, 1000.0)
    clip = np.concatenate([points, np.ones((len(points), 1))], axis=1) @ (proj @ view).T
    theirs = (clip[:, :2] / clip[:, 3:4] + 1.0) / 2.0
    assert np.abs(ours - theirs).max() < 1e-6
    # And the screen is in the picture: the top screen fills the middle of it.
    assert 0.2 < ours[:, 0].min() and ours[:, 0].max() < 0.8


@needs_motors
def test_the_export_writes_the_cache_and_what_blender_is_told(mesh, placed, tmp_path):
    request = bx.Request(target=str(tmp_path / "piece.blend"), first=1500, length=10, mode="decal")
    made = bx.export(request, mesh, placed.at, BLENDER, run=False)
    total, count, data = bx.read_pc2(made["cache"])
    assert (total, count) == (10, len(mesh.raw["screen__points"]))
    poser = bx.Poser(mesh, placed.at)
    assert np.abs(data[3] - poser.at(1503) * bx.CM).max() < 1e-3
    told = json.loads(made["description"].read_text(encoding="utf-8"))
    assert told["mode"] == 1 and told["frame"] == [2560, 1150] and told["fps"] == 60
    assert told["cameras"]["viewer"]["name"] == "Zaryadye_ProjectionCamera_9x16_v1"
    assert abs(told["cameras"]["viewer"]["tan_half"] - 20.25 / 2 / 26.45) < 1e-6
    assert not made["blend"].exists()


def test_the_target_is_named_by_the_show_and_its_frames(tmp_path):
    assert bx.default_target(tmp_path, "День Знаний: v1", 1100, 600).name == \
        "День_Знаний_v1_top_001100-001699.blend"


@needs_motors
@needs_blender
def test_blender_builds_a_scene_that_plays_the_cache_and_projects_as_the_viewer(mesh, placed, tmp_path):
    request = bx.Request(target=str(tmp_path / "piece.blend"), first=1500, length=12, mode="viewer")
    made = bx.export(request, mesh, placed.at, BLENDER)
    assert made["blend"].exists()
    probe = tmp_path / "probe.npz"
    run = subprocess.run([BLENDER, "-b", str(made["blend"]), "--factory-startup", "--python-exit-code", "1",
                          "-P", str(HERE / "blender_probe.py"), "--", str(probe), "1,6,12"],
                         capture_output=True, text=True, timeout=600)
    assert run.returncode == 0, run.stdout[-2000:] + run.stderr[-2000:]
    got = np.load(probe)
    _, _, cache = bx.read_pc2(made["cache"])
    camera = bx.file_camera(mesh)
    for frame in (1, 6, 12):
        assert np.abs(got[f"co_{frame}"] - cache[frame - 1]).max() < 1e-3, frame
        expect = bx.project(got[f"co_{frame}"].astype(np.float64) / bx.CM, camera,
                            bx.CONTENT[0] / bx.CONTENT[1])[got["loop_vertex"]]
        assert np.abs(got[f"proj_{frame}"] - expect).max() < 1e-5, frame
    flat = got["flat"]
    assert flat[:, 0].min() >= -1e-3 and flat[:, 0].max() <= 2560 + 1e-3
    assert flat[:, 1].min() >= -1e-3 and flat[:, 1].max() <= 1150 + 1e-3
    assert list(got["render_size"]) == [2560, 1150] and list(got["frames"]) == [1, 12]
