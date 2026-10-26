"""A layer laid on the building as the file's camera sees it: the card's remap
pass held to the same sums done in numpy, point by point of the screen."""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

import blender_export
import layer_gpu
import layers
import scene3d
import screen_gpu
from conftest import TOOL


@pytest.fixture(scope="module")
def device():
    _, made = screen_gpu.make_device()
    return made


@pytest.fixture(scope="module")
def mesh():
    return blender_export.Baked(TOOL / "baked")


def _camera(mesh):
    raw = mesh.raw
    matrix = np.array(raw["camera_matrix"], np.float64)
    near, far = (float(v) for v in raw["clip"])
    projection = scene3d.projection(mesh.lens, mesh.sensor, str(raw["sensor_fit"]),
                                    layer_gpu.CAMERA_PICTURE, max(near, 0.01), far)
    return projection @ scene3d.look_through(matrix), matrix[:3, 3]


def _ramp(path):
    """A 9:16 picture whose red is how far across and green how far down."""
    wide, tall = 90, 160
    x = np.linspace(0, 255, wide)[None, :].repeat(tall, 0)
    y = np.linspace(0, 255, tall)[:, None].repeat(wide, 1)
    pixels = np.stack([x, y, np.zeros_like(x), np.full_like(x, 255)], -1).astype(np.uint8)
    Image.fromarray(pixels).save(path)
    return wide, tall


def _laid(device, mesh, layer, size, cells=None, name="Screen_Bottom"):
    composer = screen_gpu.Compositor(device, *size)
    surface = layer_gpu.Surface(device, mesh.raw, name, kinetic=name == "screen")
    surface.pose(cells)
    stacks = layers.Stacks()
    stacks.add("Bottom", layer)
    blender = layer_gpu.LayerBlender(device, *size)
    assert blender.apply(None, composer.texture, stacks.shown("Bottom"), layer_gpu.Pictures(device),
                         (surface, _camera(mesh)))
    return composer.to_array()


def _expected(mesh, name, size, picture, layer, posed=None):
    """(frame pixel, picture uv) at the middles of the screen's triangles that
    face the camera and that it sees inside the picture."""
    raw = mesh.raw
    points = np.asarray(raw[f"{name}__points"], np.float64) if posed is None else posed
    normals = np.asarray(raw[f"{name}__normals"], np.float64)
    uv = np.asarray(raw[f"{name}__uv"], np.float64)
    triangles = np.asarray(raw[f"{name}__triangles"], np.int64)
    vp, eye = _camera(mesh)
    middle = points[triangles].mean(axis=1)
    facing = (normals[triangles].mean(axis=1) * (eye - middle)).sum(axis=1) > 0
    clip = np.concatenate([middle, np.ones((len(middle), 1))], 1) @ vp.T
    ndc = clip[:, :2] / clip[:, 3:4]
    camera_px = np.stack([(ndc[:, 0] + 1) / 2 * layer_gpu.CAMERA_PICTURE[0],
                          (1 - ndc[:, 1]) / 2 * layer_gpu.CAMERA_PICTURE[1], np.ones(len(ndc))], 1)
    rows = np.asarray(layer_gpu.camera_rows(picture, layer), np.float64)
    want = camera_px @ rows.T
    inside = (want >= 0.02).all(1) & (want <= 0.98).all(1) & (clip[:, 3] > 0) & facing
    at = uv[triangles].mean(axis=1)
    frame = np.stack([at[:, 0] * size[0], (1 - at[:, 1]) * size[1]], 1)
    # Only triangles large enough in the frame that their middle is theirs.
    span = np.ptp(uv[triangles], axis=1) * np.array(size)
    big = (span > 3).all(1)
    return frame[inside & big], want[inside & big]


def _check(got, frame, want, picture):
    assert len(frame) >= 20
    wide, tall = picture
    misses = 0
    for (x, y), (u, v) in zip(frame, want):
        r, g = got[int(y), int(x), :2]
        ru = np.clip((u * wide - 0.5) / (wide - 1), 0, 1)
        gv = np.clip((v * tall - 0.5) / (tall - 1), 0, 1)
        if abs(r - ru) > 0.03 or abs(g - gv) > 0.03:
            misses += 1
    assert misses <= len(frame) * 0.05, (misses, len(frame))


def test_a_picture_lies_where_the_camera_sees_it(device, mesh, tmp_path):
    picture = _ramp(tmp_path / "ramp.png")
    size = (512, 256)
    layer = layers.Layer("image", "r", path=str(tmp_path / "ramp.png"), remap=True)
    layer.x, layer.y, layer.scale = 120.0, 300.0, 1.4
    got = _laid(device, mesh, layer, size)
    frame, want = _expected(mesh, "Screen_Bottom", size, picture, layer)
    _check(got, frame, want, picture)
    # The back of the building is out of the camera's sight: nothing laid there.
    assert got[..., 3].min() == 0.0


def test_up_in_the_camera_is_plus():
    rows = layer_gpu.camera_rows((90, 160), layers.Layer("image", "r", y=100.0))
    middle = np.array([layer_gpu.CAMERA_PICTURE[0] / 2, layer_gpu.CAMERA_PICTURE[1] / 2 - 100.0, 1.0])
    assert np.allclose(np.asarray(rows) @ middle, (0.5, 0.5))


def test_the_top_screen_is_laid_as_its_cells_stand(device, mesh, tmp_path):
    picture = _ramp(tmp_path / "ramp.png")
    size = (512, 256)
    layer = layers.Layer("image", "r", path=str(tmp_path / "ramp.png"), remap=True)
    raw = mesh.raw
    cell = np.asarray(raw["screen__cell"], np.int64)
    cells = np.tile(np.eye(4), (int(cell.max()) + 1, 1, 1))
    cells[:, 2, 3] = 1.5                              # every cell lifted
    rest = np.asarray(raw["screen__points"], np.float64)
    posed = rest + cells[cell][:, :3, 3]
    got = _laid(device, mesh, layer, size, cells, "screen")
    frame, want = _expected(mesh, "screen", size, picture, layer, posed)
    _check(got, frame, want, picture)
    still = _laid(device, mesh, layer, size, None, "screen")
    assert np.abs(got - still).max() > 0.05             # it did move with them
