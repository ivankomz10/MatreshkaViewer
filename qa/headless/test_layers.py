"""The advanced mode's stacks of layers, without a window: the moves made on a
stack, and the graphics card's blending held to the sums in `layers.blend`."""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

import layer_gpu
import layers
import screen_gpu


def test_a_stack_keeps_its_order_and_moves(tmp_path):
    stacks = layers.Stacks()
    a = layers.Layer("image", "a", path="a.png")
    b = layers.Layer("image", "b", path="b.png")
    folder = layers.Layer("folder", "f")
    for one in (a, b, folder):
        stacks.add("Bottom", one)
    assert [one.name for one in stacks.stack("Bottom")] == ["a", "b", "f"]
    assert stacks.move(a, folder, "in") and folder.children == [a]
    assert stacks.move(b, folder, "above")
    assert [one.name for one in stacks.stack("Bottom")] == ["f", "b"]
    assert not stacks.move(folder, a, "in")              # not into what it holds
    stacks.add("Top", layers.Layer("image", "t", path="t.png"))
    assert not stacks.move(b, stacks.stack("Top")[0], "above")   # not across screens
    a.opacity, a.blend, b.visible = 0.5, "overlay", False
    back = layers.Stacks.from_dict(stacks.to_dict())
    assert back.to_dict() == stacks.to_dict()
    shown = back.shown("Bottom")
    assert [one.name for one, _ in shown] == ["f"] and shown[0][1][0][0].blend == "overlay"


@pytest.fixture(scope="module")
def device():
    _, made = screen_gpu.make_device()
    return made


def _put(composer, pixels):
    composer.device.queue.write_texture(
        {"texture": composer.texture}, np.ascontiguousarray(pixels.astype(np.float16)),
        {"bytes_per_row": composer.width * 8, "rows_per_image": composer.height},
        (composer.width, composer.height, 1))


@pytest.mark.parametrize("mode", layers.BLENDS)
def test_every_mode_on_the_card_is_the_reference_sum(device, tmp_path, mode):
    rng = np.random.default_rng(7)
    width, height = 64, 32
    # What is under: premultiplied, light up to one, covering most of it.
    cover = rng.uniform(0.3, 1.0, (height, width, 1))
    base = np.concatenate([rng.uniform(0, 1, (height, width, 3)) * cover, cover], axis=-1)
    picture = rng.integers(0, 256, (height, width, 4), dtype=np.uint8)
    path = tmp_path / "picture.png"
    Image.fromarray(picture).save(path)
    composer = screen_gpu.Compositor(device, width, height)
    _put(composer, base)
    layer = layers.Layer("image", "p", path=str(path), opacity=0.7, blend=mode)
    stacks = layers.Stacks()
    stacks.add("Bottom", layer)
    blender = layer_gpu.LayerBlender(device, width, height)
    assert blender.apply(None, composer.texture, stacks.shown("Bottom"), layer_gpu.Pictures(device))
    got = composer.to_array()
    straight = picture.astype(np.float64) / 255.0
    top = np.concatenate([straight[..., :3] * straight[..., 3:], straight[..., 3:]], axis=-1)
    want = layers.blend(base.astype(np.float16).astype(np.float64), top, mode, 0.7)
    assert np.abs(got - want).max() < 4e-3, mode


def test_a_folder_lies_as_one_layer(device, tmp_path):
    width, height = 16, 8
    base = np.zeros((height, width, 4))
    base[..., :] = (0.2, 0.4, 0.6, 1.0)
    red = np.zeros((height, width, 4), np.uint8)
    red[..., 0], red[..., 3] = 255, 128
    Image.fromarray(red).save(tmp_path / "red.png")
    composer = screen_gpu.Compositor(device, width, height)
    _put(composer, base)
    folder = layers.Layer("folder", "f", opacity=0.5, blend="multiply")
    folder.children = [layers.Layer("image", "r", path=str(tmp_path / "red.png"))]
    stacks = layers.Stacks()
    stacks.add("Top", folder)
    layer_gpu.LayerBlender(device, width, height).apply(
        None, composer.texture, stacks.shown("Top"), layer_gpu.Pictures(device))
    got = composer.to_array()
    a = 128 / 255
    inner = layers.blend(np.zeros((height, width, 4)), np.concatenate(
        [np.full((height, width, 1), a), np.zeros((height, width, 2)), np.full((height, width, 1), a)], -1),
        "normal")
    want = layers.blend(base, inner, "multiply", 0.5)
    assert np.abs(got - want).max() < 4e-3


def test_a_picture_is_fitted_whole_and_centred():
    rows = layer_gpu.fitted((400, 100), (200, 200))      # a square in a wide frame
    u = lambda x, y: rows[0][0] * x + rows[0][1] * y + rows[0][2]
    v = lambda x, y: rows[1][0] * x + rows[1][1] * y + rows[1][2]
    assert abs(u(150, 0)) < 1e-9 and abs(u(250, 0) - 1) < 1e-9     # 100 px wide, centred
    assert abs(v(0, 0)) < 1e-9 and abs(v(0, 100) - 1) < 1e-9
