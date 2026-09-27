"""A screen made out of its layers, and handed to the scene.

The screen's layers are drawn into a texture of their own and ADDED -- the
rule measured in the show editor -- and the scene is given that. What has to
hold: one layer made that way is the picture the scene would have made from
the file directly, and more layers are the sum of what each gives out.
"""
from __future__ import annotations

import numpy as np
import pytest

import screen_gpu

# Two pictures of the same scene, one through the compositor and one bound
# directly, may differ by where the filtering happens: the scene filters the
# compressed blocks and then decodes them, the compositor decodes first.
# Measured on an RTX 3080: never more than one code value of 255, in about
# 275 of 518 400 pixels, 0.0002 on average -- both alpha readings. Two is
# allowed, for a card that rounds its half floats differently, or a Mac that
# unpacks the blocks in a pass of its own before any of this sees them.
MOST = 2             # the largest difference allowed anywhere, of 255
MEAN = 0.01          # and on average over the whole frame


def top_screen(window):
    for index, feeds in enumerate(window.feeding):
        if feeds == "Screen_Top" and index < len(window.screens):
            return window.screens[index]
    pytest.skip("nothing is loaded on the top screen")


def settled(window, tick):
    window._move(0.5)
    tick(0.6)
    return top_screen(window)


def test_layers_add_and_a_fade_scales(window, tick):
    screen = settled(window, tick)
    comp = screen_gpu.Compositor(window.device, screen.width, screen.height)
    comp.compose([(screen, 1.0)])
    one = comp.to_array()
    comp.compose([(screen, 1.0), (screen, 1.0)])
    two = comp.to_array()
    comp.compose([(screen, 0.5)])
    half = comp.to_array()
    comp.compose([])
    nothing = comp.to_array()

    assert one[..., :3].max() > 0.1, "the layer drew nothing"
    # Half floats: eleven bits of mantissa, so a few thousandths near two.
    assert np.abs(two - 2 * one).max() < 4e-3, "two layers are not the sum"
    assert np.abs(half - 0.5 * one).max() < 2e-3, "a half fade is not half"
    assert not nothing.any(), "an empty screen is not empty"


def test_straight_and_premultiplied_are_read_the_way_the_scene_reads_them(
        window, tick):
    """The test clips are transparent down their left quarter, and coloured
    under it. Straight multiplies that colour away; premultiplied keeps it;
    neither covers the backing there."""
    screen = settled(window, tick)
    comp = screen_gpu.Compositor(window.device, screen.width, screen.height)
    clear = slice(0, screen.width // 4 - 4)
    solid = slice(screen.width // 2, screen.width - 4)

    comp.compose([(screen, 1.0)], premultiplied=True)
    kept = comp.to_array()
    comp.compose([(screen, 1.0)], premultiplied=False)
    gone = comp.to_array()

    assert kept[:, clear, :3].max() > 0.05, "premultiplied lost the colour"
    assert gone[:, clear, :3].max() < 2e-3, "straight kept the colour"
    assert kept[:, clear, 3].max() < 2e-3 and gone[:, clear, 3].max() < 2e-3
    assert abs(kept[:, solid, 3].mean() - 1.0) < 2e-3, "the solid part is not solid"


@pytest.mark.parametrize("premultiplied", [True, False])
def test_one_layer_composed_is_the_picture_bound_directly(
        window, tick, premultiplied):
    """The scene, drawn twice: once with the file bound as it is now, once
    with the same file composed first and bound as already light."""
    window.alpha.setCurrentIndex(0 if premultiplied else 1)
    screen = settled(window, tick)
    solid = window.solid
    width, height = 960, 540
    try:
        direct = solid.to_array(width, height).astype(np.int32)
        comp = screen_gpu.Compositor(window.device, screen.width, screen.height)
        comp.compose([(screen, 1.0)], premultiplied=premultiplied)
        solid.set_video("Screen_Top", comp.texture, comp.texture,
                        False, 3, (1.0, 1.0))
        composed = solid.to_array(width, height).astype(np.int32)
    finally:
        solid.set_video("Screen_Top", screen.planes[0].texture,
                        screen.planes[1].texture, screen.ycocg,
                        screen.alpha_from, screen.uv_scale)
        window.alpha.setCurrentIndex(0)
        tick(0.2)

    apart = np.abs(direct[..., :3] - composed[..., :3])
    worst, mean = int(apart.max()), float(apart.mean())
    changed = int((apart.max(axis=2) > 0).sum())
    print(f"\n  {'premultiplied' if premultiplied else 'straight':13} worst "
          f"{worst}  mean {mean:.4f}  {changed} of {width * height} pixels "
          f"differ at all")
    assert direct[..., :3].max() > 20, "nothing was drawn to compare"
    assert worst <= MOST and mean <= MEAN, (
        f"{'premultiplied' if premultiplied else 'straight'}: worst {worst}, "
        f"mean {mean:.4f}, {changed} of {width * height} pixels differ")
