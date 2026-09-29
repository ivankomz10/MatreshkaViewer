"""The kinetic editor's model, without its window.

What it has to get right is what the site will run: keys that ease the way
the exporter's segments do, a motor JSON the viewer reads back as exactly
those curves, real shows that go in as keys and come out as the same
commands, and Cinema 4D's limits on the tilts.
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

import numpy as np
import pytest

from conftest import HOME, TOOL

import kin_model as km
import kinetic
import show as showfile
from kinetic import PER_ROW, ROWS, smoothstep

OUT = HOME / "kinedit"
CONTENT = Path(r"D:\Content")


@pytest.fixture(autouse=True)
def _out_folder():
    OUT.mkdir(parents=True, exist_ok=True)
    yield


def _read_back(project: km.Project, name: str) -> kinetic.Motors:
    return kinetic.Motors(km.export_motor_json(project, OUT / f"{name}.json"))


# -- keys ------------------------------------------------------------------------

def test_a_new_piece_stands_at_rest_and_says_every_motor():
    project = km.Project(length=600)
    pose = project.pose(321)
    assert np.all(pose["lift"] == 1) and not pose["push"].any() \
        and not pose["tilt"].any()
    data = km.to_motor_json(project)["data"]
    assert len(data) == ROWS
    assert all(len(row["tilt"]) == PER_ROW and len(row["pusher"]) == km.GROUPS
               and len(row["jack"]) == 1 for row in data.values())
    # As long as the piece, by the show editor's own count.
    assert showfile.commands_of(data)[0] == project.length


def test_keys_ease_like_the_exporter_and_only_where_they_are():
    project = km.Project(length=1200)
    lift = project.tracks["lift"]
    wanted = np.full(ROWS, 3.0)
    ring = np.zeros(ROWS, bool)
    ring[4] = True
    lift.write(600, wanted, ring)
    at = lift.at(300)
    assert at[4] == pytest.approx(1 + 2 * smoothstep(0.5))
    assert np.all(np.delete(at, 4) == 1.0), "a key for one ring moved the rest"
    # Another motor keyed half way does not bend the first one's curve.
    other = np.zeros(ROWS, bool)
    other[9] = True
    lift.write(300, np.full(ROWS, 0.0), other)
    assert lift.at(150)[4] == pytest.approx(1 + 2 * smoothstep(0.25))
    assert lift.at(150)[9] == pytest.approx(1 - smoothstep(0.5))
    assert lift.at(1100)[4] == 3.0 and lift.at(1100)[9] == 0.0


def test_a_jack_keys_only_its_four_places():
    track = km.Project().tracks["lift"]
    track.write(60, np.full(ROWS, 1.7), np.ones(ROWS, bool))
    assert set(np.unique(track.values[track.index(60)])) == {2.0}
    track.write(90, np.full(ROWS, 9.0), np.ones(ROWS, bool))
    assert set(np.unique(track.values[track.index(90)])) == {3.0}


def test_moving_a_key_onto_another_merges_and_undo_puts_it_back():
    project = km.Project(length=900)
    tilt = project.tracks["tilt"]
    first = np.zeros(ROWS * PER_ROW, bool)
    first[:10] = True
    tilt.write(300, np.full(ROWS * PER_ROW, 0.1), first)
    second = np.zeros(ROWS * PER_ROW, bool)
    second[5:20] = True
    tilt.write(500, np.full(ROWS * PER_ROW, -0.1), second)
    kept = project.state()
    tilt.move(tilt.index(500), 300)
    assert tilt.frames == [0, 300]
    merged = tilt.values[1]
    assert np.allclose(merged[5:20], -0.1) and np.allclose(merged[:5], 0.1)
    project.restore(kept)
    assert tilt.frames == [0, 300, 500]


def test_the_viewer_reads_the_export_as_the_same_curves():
    project = km.Project(length=1500)
    rng = np.random.default_rng(7)
    for family in km.FAMILIES:
        track = project.tracks[family]
        low, high = km.RANGE[family]
        for frame in (120, 480, 481, 900, 1320):
            mask = rng.random(track.size) < 0.3
            values = rng.uniform(low, min(high, 0.3 if family == "tilt" else high),
                                 track.size)
            track.write(frame, values, mask)
    motors = _read_back(project, "curves")
    assert motors.frames == project.length
    for frame in range(0, project.length, 7):
        pose = project.pose(frame)
        assert np.allclose(motors.jack[:, frame], pose["lift"], atol=1e-4)
        assert np.allclose(motors.pusher[:, :, frame], pose["push"], atol=1e-4)
        assert np.allclose(motors.tilt[:, :, frame], pose["tilt"], atol=1e-4)


REAL = ("MosMetro_5798 Frames.json",
        "Carshering_all_animation_5_v1_2026_07_24_1_of_1.json",
        "DenGoroda.v1.2026.09.01_1_of_1.json",
        "23 February_3421-4560.json")


@pytest.mark.parametrize("name", REAL)
def test_a_real_show_goes_in_as_keys_and_comes_out_the_same(name):
    """Every frame of every motor, as the viewer plays the original and the
    editor's export of it -- including a file whose segments overlap and
    start where the motor was not, which comes in as a key a frame."""
    found = glob.glob(str(CONTENT / "**" / name), recursive=True)
    if not found:
        pytest.skip(f"{name} is not on this machine")
    original = kinetic.Motors(kinetic.parts_beside(found[0]))
    project, said = km.from_motor_json(found[0])
    again = _read_back(project, "real")
    frames = min(original.frames, again.frames)
    assert again.frames >= original.frames - 1
    for got, want in ((again.jack, original.jack), (again.pusher, original.pusher),
                      (again.tilt, original.tilt)):
        assert np.abs(got[..., :frames] - want[..., :frames]).max() < 1e-4
    if name.startswith("23 February"):
        assert any("наложенными" in one for one in said), said


# -- the limits ----------------------------------------------------------------------

def test_tilts_are_held_to_cinema4d_by_the_narrower_gap():
    lift = np.full(ROWS, 1.0)
    reach = km.tilt_reach(lift)
    assert np.allclose(reach, 10 / 90)
    lift[10] = 0.0                  # the gap between rings 10 and 11 closed
    reach = km.tilt_reach(lift)
    assert reach[10] == 0.0 and reach[11] == 0.0
    assert reach[9] == pytest.approx(10 / 90) and reach[12] == pytest.approx(10 / 90)
    lift = np.full(ROWS, 2.0)
    assert np.allclose(km.tilt_reach(lift), 30 / 90)
    # The top ring has only the gap below it; the last jack moves nothing.
    lift[ROWS - 1] = 0.0
    assert km.tilt_reach(lift)[ROWS - 1] == pytest.approx(30 / 90)
    tilt = np.full((ROWS, PER_ROW), 0.45)
    held = km.clamp_tilt(tilt, np.full(ROWS, 1.0))
    assert np.allclose(held, 10 / 90)
    assert not km.over_limit(held, np.full(ROWS, 1.0)).any()


def test_violations_are_found_at_keys():
    project = km.Project(length=600)
    tilt = project.tracks["tilt"]
    tilt.write(300, np.full(tilt.size, 0.3), np.ones(tilt.size, bool))
    found = dict(project.violations())
    assert found == {300: ROWS * PER_ROW}


# -- the tools -------------------------------------------------------------------------

def test_the_brush_moves_what_it_touches_towards_its_weight():
    track = km.Project().tracks["tilt"]
    weights = np.zeros((ROWS, PER_ROW), np.float32)
    weights[5, 7] = 1.0
    weights[5, 8] = 0.5
    values, mask = km.brush(track, 0, weights, 0.2, 1.0, "paint")
    grid = values.reshape(ROWS, PER_ROW)
    assert grid[5, 7] == pytest.approx(0.2) and grid[5, 8] == pytest.approx(0.1)
    assert mask.sum() == 2
    erased, _ = km.brush(track, 0, weights, 0.2, 1.0, "erase")
    assert not erased.any()

    push = km.Project().tracks["push"]
    one = np.zeros((ROWS, PER_ROW), np.float32)
    one[3, 12] = 1.0                    # the third cell of pusher 2
    values, mask = km.brush(push, 0, one, 0.8, 1.0)
    assert mask.sum() == 1 and values.reshape(ROWS, km.GROUPS)[3, 2] == \
        pytest.approx(0.8)

    lift = km.Project().tracks["lift"]
    ring = np.zeros((ROWS, PER_ROW), np.float32)
    ring[20, :] = 0.4
    values, mask = km.brush(lift, 0, ring, 3, 1.0)
    assert not mask.any(), "a jack answered a brush under half its ring"
    ring[20, 3] = 0.9
    values, mask = km.brush(lift, 0, ring, 3, 1.0)
    assert mask.sum() == 1 and values[20] == 3.0


def test_the_auto_rotate_lays_every_cell_along_the_surface():
    """Pushed into a cone, the cells turn so that each one's face is
    square to the slope up the building -- read through the viewer's own
    transforms, the ones checked against the rig."""
    data = np.load(TOOL / "baked" / "scene_mesh.npz", allow_pickle=True)
    points = data["screen__points"].astype(np.float64)
    cell = data["screen__cell"].astype(np.int64)
    once = np.unique(np.concatenate([cell[:, None].astype(np.float64), points],
                                    axis=1), axis=0)
    which = once[:, 0].astype(int)
    middles = np.zeros((which.max() + 1, 3))
    np.add.at(middles, which, once[:, 1:])
    middles /= np.bincount(which)[:, None]
    addresses = kinetic.cell_addresses(middles.astype(np.float32))
    base = np.array([middles[addresses[:, 0] == r, 2].mean() for r in range(ROWS)])

    lift = np.full(ROWS, 1.0)
    push = np.repeat(np.linspace(0.0, 0.6, ROWS)[:, None], km.GROUPS, axis=1)
    tilt = km.auto_tilt(lift, push, base=base)
    assert (tilt[1:-1] > 0).all(), "a cone widening upwards tilts its cells down"

    import kinedit
    motors = kinedit.PoseMotors({"lift": lift, "push": push, "tilt": tilt})
    matrices = kinetic.transforms(middles.astype(np.float32), addresses, motors, 0)
    flat = middles[:, :2]
    radial = np.concatenate([flat / np.linalg.norm(flat, axis=1, keepdims=True),
                             np.zeros((len(middles), 1))], axis=1)
    faces = np.einsum("cij,cj->ci", matrices[:, :3, :3], radial)
    slope = 0.6 / (ROWS - 1) / np.diff(base).mean()
    inside = (addresses[:, 0] > 0) & (addresses[:, 0] < ROWS - 1)
    up = np.concatenate([radial[:, :2] * slope, np.ones((len(middles), 1))], axis=1)
    up /= np.linalg.norm(up, axis=1, keepdims=True)
    assert np.abs(np.einsum("ci,ci->c", faces[inside], up[inside])).max() < 1e-3


def test_the_vase_goes_through_its_points_without_overshooting():
    points = [(0.0, 0.0), (0.4, 0.9), (0.6, 0.9), (1.0, 0.2)]
    curve = km.profile_curve(points)
    assert curve[0] == pytest.approx(0.0) and curve[-1] == pytest.approx(0.2)
    assert curve.max() <= 0.9 + 1e-6 and curve.min() >= -1e-6
    assert np.all(np.diff(curve[:12]) >= -1e-6)


def test_the_cells_a_selection_takes_by_family():
    cells = np.zeros((ROWS, PER_ROW), bool)
    cells[2, 11] = True
    assert km.cell_mask_for("lift", cells).sum() == 1
    push = km.cell_mask_for("push", cells).reshape(ROWS, km.GROUPS)
    assert push[2, 2] and push.sum() == 1
    assert km.cell_mask_for("tilt", cells).sum() == 1


# -- the project file ----------------------------------------------------------------------

def test_a_project_comes_back_as_it_was_saved():
    project = km.Project(length=2400)
    project.name = "round"
    track = project.tracks["push"]
    mask = np.zeros(track.size, bool)
    mask[::7] = True
    track.write(777, np.full(track.size, 0.625), mask)
    project.profiles[777] = [[0.0, 0.1], [1.0, 0.5]]
    project.sound = str(OUT / "nothing.wav")
    path = OUT / "round.kin"
    project.save(path)
    again = km.Project.load(path)
    assert again.length == 2400 and again.name == "round"
    assert again.tracks["push"].frames == [0, 777]
    assert np.array_equal(again.tracks["push"].keyed[1], mask)
    assert np.allclose(again.pose(500)["push"], project.pose(500)["push"])
    assert again.profiles == {777: [[0.0, 0.1], [1.0, 0.5]]}
    assert again.sound == project.sound
    with pytest.raises(km.ModelError):
        (OUT / "not.kin").write_text(json.dumps({"format": "other"}), "utf-8")
        km.Project.load(OUT / "not.kin")
