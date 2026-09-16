"""The baked scene: what the file said must still be true after the bake.

Read straight off `scene_mesh.npz` -- no window, no card, a tenth of a second.
The UV seam was lost here once: Blender keeps a UV per face corner, the bake
kept one per vertex, and the corner that closes the ring took its neighbour's
value. That turned the closing face into a face spanning the whole width of
the video, which is the band of noise that was seen at the back of the top
and bottom screens.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

BAKED = Path(__file__).resolve().parents[2] / "tool" / "baked" / "scene_mesh.npz"
SCREENS = ("Screen_Bottom", "Screen_Top", "screen", "Lamel_screen")
CELLS_ON_KINETIC = 1500


@pytest.fixture(scope="module")
def baked():
    assert BAKED.exists(), f"nothing baked at {BAKED}"
    return np.load(BAKED)


@pytest.mark.parametrize("name", SCREENS)
def test_no_face_spans_the_whole_video(baked, name):
    """A face may cover a little of the picture; none may cover most of it."""
    uv, tris = baked[f"{name}__uv"], baked[f"{name}__triangles"]
    spans = uv[tris, 0].max(axis=1) - uv[tris, 0].min(axis=1)
    worst = float(spans.max())
    assert worst < 0.5, (
        f"{name}: {int((spans > 0.5).sum())} of {len(spans)} faces span more "
        f"than half the width of the video, the worst {worst:.3f} -- the seam "
        "was flattened again")


@pytest.mark.parametrize("name", SCREENS)
def test_the_ends_of_the_video_are_both_there(baked, name):
    """The first column and the last, or the ring is missing a stripe of content."""
    u = baked[f"{name}__uv"][:, 0]
    assert u.min() < 1e-3, (
        f"{name}: u starts at {u.min():.4f}; the first column of the video is "
        "not on the building anywhere")
    assert u.max() > 1.0 - 1e-3, f"{name}: u stops at {u.max():.4f}"


@pytest.mark.parametrize("name", SCREENS)
def test_every_vertex_says_which_cell_it_is_in(baked, name):
    """The card reads the cell off the vertex; it used to divide the index by six."""
    key = f"{name}__cell"
    assert key in baked, f"{name} carries no cell index"
    cell, points = baked[key], baked[f"{name}__points"]
    assert len(cell) == len(points), (
        f"{name}: {len(cell)} cell indices for {len(points)} vertices")


def test_the_moving_screen_has_its_fifteen_hundred(baked):
    cell = baked["screen__cell"]
    assert int(cell.max()) + 1 == CELLS_ON_KINETIC, (
        f"the moving screen counts {int(cell.max()) + 1} cells")
    how_many = np.bincount(cell)
    # Six corners each, and a few more where a corner was split at the seam.
    assert how_many.min() == 6, f"a cell with {how_many.min()} corners"
    assert how_many.max() <= 8, f"a cell with {how_many.max()} corners"


def test_the_two_top_screens_still_match_cell_for_cell(baked):
    """Still and moving are the same honeycomb; the same content must land
    on the same cell whichever of them is drawn."""
    still, moving = baked["Screen_Top__uv"], baked["screen__uv"]
    assert still.shape == moving.shape
    apart = float(np.abs(still - moving).max())
    assert apart < 1e-4, f"their UVs differ by up to {apart}"
