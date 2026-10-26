"""A movie as a layer: the frame of the clock less the layer's start, laid
the way a picture is, nothing before its start or past its end unless it
goes round."""
from __future__ import annotations

from types import SimpleNamespace

import av
import numpy as np
import pytest

import layer_gpu
import layer_video
import layers
import screen_gpu

RATE = 30
FRAMES = 60          # two seconds


def _movie(path):
    """Two seconds at thirty, each second a colour of its own: red, then blue."""
    with av.open(str(path), "w") as out:
        stream = out.add_stream("mpeg4", rate=RATE)
        stream.width, stream.height, stream.pix_fmt = 64, 32, "yuv420p"
        stream.bit_rate = 4_000_000
        for index in range(FRAMES):
            pixels = np.zeros((32, 64, 3), np.uint8)
            if index < RATE:
                pixels[..., 0] = 255
            else:
                pixels[..., 2] = 255
            for packet in stream.encode(av.VideoFrame.from_ndarray(pixels, format="rgb24")):
                out.mux(packet)
        for packet in stream.encode():
            out.mux(packet)


@pytest.fixture(scope="module")
def device():
    _, made = screen_gpu.make_device()
    return made


@pytest.fixture(scope="module")
def movie(tmp_path_factory):
    path = tmp_path_factory.mktemp("movie") / "two.mp4"
    _movie(path)
    return path


def test_the_movies_own_time_from_the_clock():
    held = layer_video.LayerMovie.__new__(layer_video.LayerMovie)
    held.stream = SimpleNamespace(duration=2.0)
    layer = layers.Layer("video", "v", path="v.mp4", offset=1.0)
    assert held.local(0.5, layer) is None              # not started yet
    assert held.local(1.5, layer) == pytest.approx(0.5)
    assert held.local(3.5, layer) is None              # over
    layer.loop = True
    assert held.local(3.5, layer) == pytest.approx(0.5)
    back = layers.Layer.from_dict(layer.to_dict())
    assert (back.kind, back.offset, back.loop) == ("video", 1.0, True)


def _laid(device, movie, layer, seconds):
    width, height = 64, 32
    composer = screen_gpu.Compositor(device, width, height)
    stacks = layers.Stacks()
    stacks.add("Bottom", layer)
    pictures = layer_gpu.Pictures(device)
    pictures.movies = layer_video.Movies(device)
    try:
        pictures.movies.exact(seconds, stacks.playing())
        layer_gpu.LayerBlender(device, width, height).apply(
            None, composer.texture, stacks.shown("Bottom"), pictures)
        return composer.to_array()
    finally:
        pictures.movies.close()


def test_a_movie_layer_shows_the_frame_of_the_clock(device, movie):
    layer = layers.Layer("video", "v", path=str(movie))
    early = _laid(device, movie, layer, 0.4)[16, 32]
    late = _laid(device, movie, layer, 1.6)[16, 32]
    assert early[0] > 0.8 and early[2] < 0.2, early        # red in the first second
    assert late[2] > 0.8 and late[0] < 0.2, late           # blue in the second
    assert early[3] > 0.99 and late[3] > 0.99


def test_a_movie_starts_late_and_goes_round(device, movie):
    layer = layers.Layer("video", "v", path=str(movie), offset=1.0)
    assert _laid(device, movie, layer, 0.5)[..., 3].max() == 0.0     # before its start
    started = _laid(device, movie, layer, 1.4)[16, 32]
    assert started[0] > 0.8 and started[2] < 0.2                     # its own 0.4 s: red
    assert _laid(device, movie, layer, 3.5)[..., 3].max() == 0.0     # past its end
    layer.loop = True
    round_again = _laid(device, movie, layer, 3.6)[16, 32]           # 2.6 -> 0.6: red
    assert round_again[0] > 0.8 and round_again[2] < 0.2


def test_a_movie_layer_lies_remapped_too(device, movie):
    import blender_export
    import scene3d
    from conftest import TOOL
    mesh = blender_export.Baked(TOOL / "baked")
    raw = mesh.raw
    matrix = np.array(raw["camera_matrix"], np.float64)
    near, far = (float(v) for v in raw["clip"])
    vp = scene3d.projection(mesh.lens, mesh.sensor, str(raw["sensor_fit"]),
                            layer_gpu.CAMERA_PICTURE, max(near, 0.01), far) @ scene3d.look_through(matrix)
    size = (256, 128)
    composer = screen_gpu.Compositor(device, *size)
    layer = layers.Layer("video", "v", path=str(movie), bind="camera", scale=3.0)
    stacks = layers.Stacks()
    stacks.add("Bottom", layer)
    pictures = layer_gpu.Pictures(device)
    pictures.movies = layer_video.Movies(device)
    try:
        pictures.movies.exact(1.6, stacks.playing())
        surface = layer_gpu.Surface(device, raw, "Screen_Bottom")
        layer_gpu.LayerBlender(device, *size).apply(
            None, composer.texture, stacks.shown("Bottom"), pictures, (surface, (vp, matrix[:3, 3])))
        got = composer.to_array()
    finally:
        pictures.movies.close()
    blue = (got[..., 2] > 0.8) & (got[..., 0] < 0.2)
    assert 0.01 < blue.mean() < 0.9, blue.mean()
