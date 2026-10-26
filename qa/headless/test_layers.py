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


def test_where_a_moved_turned_picture_lies():
    frame, picture = (400, 100), (200, 200)
    layer = layers.Layer("image", "p")
    assert np.allclose(layer_gpu.placed(frame, picture, layer), layer_gpu.fitted(frame, picture))

    def uv(rows, x, y):
        return (rows[0][0] * x + rows[0][1] * y + rows[0][2], rows[1][0] * x + rows[1][1] * y + rows[1][2])

    layer.x, layer.y = 30, -10                         # moved: its middle follows
    assert np.allclose(uv(layer_gpu.placed(frame, picture, layer), 230, 40), (0.5, 0.5))
    layer.x = layer.y = 0
    layer.scale = 2.0                                  # twice: the frame's height is half of it
    assert np.allclose(uv(layer_gpu.placed(frame, picture, layer), 200, 0), (0.5, 0.25))
    layer.scale, layer.rotation = 1.0, 90.0            # a quarter turn clockwise
    # the picture's top middle (0.5, 0) now stands right of the frame's middle
    assert np.allclose(uv(layer_gpu.placed(frame, picture, layer), 250, 50), (0.5, 0.0))
    layer.rotation, layer.flip = 0.0, True             # mirrored: its left is on the right
    assert np.allclose(uv(layer_gpu.placed(frame, picture, layer), 150, 50), (1.0, 0.5))
    back = layers.Layer.from_dict(layer.to_dict())
    assert (back.flip, back.scale, back.x) == (True, 1.0, 0.0)


# -- step 8: masks and effects ---------------------------------------------------------

def _touched_case(device, tmp_path, layer, base, picture, screen="Bottom"):
    import layer_rasters
    height, width = base.shape[:2]
    composer = screen_gpu.Compositor(device, width, height)
    _put(composer, base)
    stacks = layers.Stacks()
    stacks.add(screen, layer)
    pictures = layer_gpu.Pictures(device)
    pictures.rasters = layer_rasters.Rasters(device, tmp_path / "rasters")
    return composer, stacks, pictures


def _straight_to_top(picture):
    straight = picture.astype(np.float64) / 255.0
    return straight


def test_an_hsl_effect_turns_the_layers_colour(device, tmp_path):
    rng = np.random.default_rng(11)
    width, height = 48, 24
    base = np.zeros((height, width, 4))
    base[...] = (0.1, 0.2, 0.3, 1.0)
    picture = rng.integers(0, 256, (height, width, 4), dtype=np.uint8)
    picture[..., 3] = rng.integers(40, 256, (height, width))
    Image.fromarray(picture).save(tmp_path / "p.png")
    layer = layers.Layer("image", "p", path=str(tmp_path / "p.png"), opacity=0.8)
    effect = layer.add_effect("hsl")
    effect.hue, effect.saturation, effect.lightness = 70.0, -0.4, 0.2
    composer, stacks, pictures = _touched_case(device, tmp_path, layer, base, picture)
    layer_gpu.LayerBlender(device, width, height).apply(None, composer.texture, stacks.shown("Bottom"), pictures)
    straight = _straight_to_top(picture)
    turned = layers.hsl(straight[..., :3], 70.0, -0.4, 0.2)
    top = np.concatenate([turned * straight[..., 3:], straight[..., 3:]], -1)
    want = layers.blend(base, top, "normal", 0.8)
    assert np.abs(composer.to_array() - want).max() < 6e-3


def test_a_mask_cuts_the_layer_and_paint_lies_under_it(device, tmp_path):
    width, height = 40, 20
    base = np.zeros((height, width, 4))
    base[...] = (0.0, 0.0, 0.5, 1.0)
    picture = np.zeros((height, width, 4), np.uint8)
    picture[..., 1], picture[..., 3] = 255, 255                  # green, whole
    Image.fromarray(picture).save(tmp_path / "g.png")
    layer = layers.Layer("image", "g", path=str(tmp_path / "g.png"), blend="screen")
    paint = layer.add_effect("paint")
    layer.add_mask()
    assert layer.target == "mask" and layer.touched
    composer, stacks, pictures = _touched_case(device, tmp_path, layer, base, picture)
    mask = pictures.rasters.mask(layer, (width, height))
    ramp = np.linspace(0, 255, width).round().astype(np.uint8)
    mask.array[..., :3] = ramp[None, :, None]                     # black at the left, white at the right
    mask.touch()
    strokes = pictures.rasters.paint(paint, (width, height))
    strokes.array[:, : width // 2] = (255, 0, 0, 128)            # half red over the left half
    strokes.touch()
    layer_gpu.LayerBlender(device, width, height).apply(None, composer.texture, stacks.shown("Bottom"), pictures)
    own = np.zeros((height, width, 4))
    own[...] = (0.0, 1.0, 0.0, 1.0)
    red = np.zeros((height, width, 4))
    red[:, : width // 2] = (128 / 255, 0, 0, 128 / 255)
    own = layers.blend(own, red, "normal")
    own = own * (ramp / 255.0)[None, :, None]
    want = layers.blend(base, own, "screen")
    assert np.abs(composer.to_array() - want).max() < 6e-3
    # Saved, and read back for a stack opened again.
    assert sorted(pictures.rasters.save()) == sorted([layer.mask_raster, paint.raster])
    import layer_rasters
    again = layer_rasters.Rasters(device, tmp_path / "rasters").mask(layer, (width, height))
    assert np.array_equal(again.array, mask.array)
    back = layers.Layer.from_dict(layer.to_dict())
    assert back.mask and back.effects[0].key == paint.key and back.target == "mask"


def test_effects_are_worked_bottom_up_and_a_hidden_one_is_not(device, tmp_path):
    width, height = 16, 8
    base = np.zeros((height, width, 4))
    picture = np.full((height, width, 4), 255, np.uint8)
    picture[..., :3] = (200, 50, 50)
    Image.fromarray(picture).save(tmp_path / "r.png")
    layer = layers.Layer("image", "r", path=str(tmp_path / "r.png"))
    paint = layer.add_effect("paint")
    grey = layer.add_effect("hsl")
    grey.saturation = -1.0                                        # over the paint: greys it too
    composer, stacks, pictures = _touched_case(device, tmp_path, layer, base, picture)
    strokes = pictures.rasters.paint(paint, (width, height))
    strokes.array[...] = (0, 0, 255, 255)
    strokes.touch()
    layer_gpu.LayerBlender(device, width, height).apply(None, composer.texture, stacks.shown("Bottom"), pictures)
    got = composer.to_array()[4, 8]
    assert abs(got[0] - got[2]) < 4e-3 and got[3] > 0.99         # blue painted, then greyed
    grey.visible = False
    composer2, stacks2, _ = _touched_case(device, tmp_path, layer, base, picture)
    layer_gpu.LayerBlender(device, width, height).apply(None, composer2.texture, stacks2.shown("Bottom"), pictures)
    assert composer2.to_array()[4, 8][2] > 0.99                    # blue as painted


def test_a_folder_is_masked_as_one(device, tmp_path):
    width, height = 16, 8
    base = np.zeros((height, width, 4))
    base[...] = (0.2, 0.2, 0.2, 1.0)
    white = np.full((height, width, 4), 255, np.uint8)
    Image.fromarray(white).save(tmp_path / "w.png")
    folder = layers.Layer("folder", "f")
    folder.children = [layers.Layer("image", "w", path=str(tmp_path / "w.png"))]
    folder.add_mask()
    composer, stacks, pictures = _touched_case(device, tmp_path, folder, base, white)
    mask = pictures.rasters.mask(folder, (width, height))
    mask.array[:, : width // 2, :3] = 0
    mask.touch()
    layer_gpu.LayerBlender(device, width, height).apply(None, composer.texture, stacks.shown("Bottom"), pictures)
    got = composer.to_array()
    assert np.allclose(got[:, : width // 2, :3], 0.2, atol=4e-3)   # masked out: what is under
    assert np.allclose(got[:, width // 2:, :3], 1.0, atol=4e-3)
