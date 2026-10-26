"""A show clip with layers baked into a file of its own for a .trix: the file
is the clip with its layers on it, frame for frame, and the show written out
plays it where the clip was."""
from __future__ import annotations

import json

import numpy as np
import pytest
from PIL import Image

import layer_bake
import layer_rasters
import layers
import media
import player
import screen_gpu
import show as showfile
import trix_export


@pytest.fixture(scope="module")
def device():
    _, made = screen_gpu.make_device()
    return made


def _clip(path, ident=5):
    return showfile.Clip(kind="video", row="Bottom", level=0, path=str(path), tx=200,
                         frames=media.FRAMES, crop_start=10, fade_start=20, ident=ident)


def test_light_comes_back_as_it_went_in():
    light = np.zeros((1, 2, 4), np.float32)
    light[0, 0] = (0.25, 0.0, 0.0, 0.5)              # half covered, a quarter of light
    light[0, 1] = (1.0, 1.0, 1.0, 1.0)
    assert tuple(layer_bake.light_to_pixels(light, True)[0, 0]) == (64, 0, 0, 128)
    assert tuple(layer_bake.light_to_pixels(light, False)[0, 0]) == (128, 0, 0, 128)
    assert tuple(layer_bake.light_to_pixels(light, False)[0, 1]) == (255, 255, 255, 255)


def test_a_clip_is_baked_with_its_layers_and_the_show_plays_the_file(device, tmp_path):
    source = media.build()["bottom"]
    red = np.zeros((40, 40, 4), np.uint8)
    red[..., 0], red[..., 3] = 255, 255
    Image.fromarray(red).save(tmp_path / "red.png")
    clip = _clip(source)
    layer = layers.Layer("image", "red", path=str(tmp_path / "red.png"))
    layers.Stacks.of_clip(clip).add("Bottom", layer)
    show = showfile.Show(name="baked", length=1000)
    show.clips = [clip, showfile.Clip(kind="video", row="Top", level=0, path=str(source), tx=0,
                                      frames=media.FRAMES, ident=6)]
    assert layer_bake.to_bake(show) == [clip]
    target = tmp_path / "baked-v002.trix"
    where = layer_bake.file_for(target, clip)
    assert where.parent == tmp_path / "baked-v002_layers" and where.suffix == ".mov"
    frame = (232, 80)
    rasters = layer_rasters.Rasters(device, tmp_path / "rasters")
    baker = layer_bake.Baker(device, clip, "Screen_Bottom", frame, rasters, True, None)
    said = []
    assert baker.run(where, progress=said.append)
    assert said[-1] == media.FRAMES == baker.count
    # The file: as many frames as the source, the size of the frame, red in
    # the middle where the picture lies and the source at the sides.
    stream = player.open_source(where)
    stream.start()
    try:
        assert stream.movie.frames == media.FRAMES
        assert (stream.movie.width, stream.movie.height) == frame
        got = stream.exact(30, None)
        screen = screen_gpu.Screen(device, stream.movie)
        screen.upload([memoryview(b) for b in got.buffers])
        composer = screen_gpu.Compositor(device, *frame)
        composer.compose([(screen, 1.0)])
        pixels = composer.to_array()
    finally:
        player.let_go([stream])
    middle = pixels[40, 116]
    assert middle[0] > 0.9 and middle[1] < 0.1 and middle[2] < 0.1
    assert pixels[40, 2, 2] > 0.1                       # the source's own blue at the side
    # The show written out: the baked file where the clip was, nothing else moved.
    written = trix_export.export(layer_bake.baked_show(show, {clip.ident: where}), target)
    raw = json.loads(written.read_text(encoding="utf-8"))
    entries = [entry for held in raw["video"].values() for entry in held.values()
               if "_layers" in entry["path"]]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["path"].endswith(where.name) and entry["tx"] == 200
    assert entry["crop_start"] == 10 and entry["fade_start"] == 20
    assert clip.layers == [layer] and clip.path == str(source)   # the show itself untouched
