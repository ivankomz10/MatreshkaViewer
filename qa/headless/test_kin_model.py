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
    payload = km.to_motor_json(project)
    data = payload["data"]
    # Laid out as Houdini lays a file out: thirty rows, pusher, tilt and
    # jack in each, and the jacks numbered 1 to 29 as TouchDesigner counts
    # them -- the thirtieth row has none.
    assert list(data) == [f"row_{n}" for n in range(1, ROWS + 1)]
    for number, row in enumerate(data.values(), 1):
        assert list(row) == (["pusher", "tilt", "jack"] if number < ROWS
                             else ["pusher", "tilt"])
        assert len(row["tilt"]) == PER_ROW and len(row["pusher"]) == km.GROUPS
    # Each motor says where it starts, and the range is the piece's.
    assert all(segments == [{"frame": 0, "start": segments[0]["start"],
                             "dest": segments[0]["start"], "length": 0}]
               for row in data.values() for ids in row.values()
               for segments in ids.values())
    assert payload["info"]["export_range"] == {"start": 0, "end": project.length}
    assert payload["info"]["total_frames"] == project.length


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


def test_a_jack_keys_only_its_four_places_and_row_one_has_none():
    track = km.Project().tracks["lift"]
    track.write(60, np.full(ROWS, 1.7), np.ones(ROWS, bool))
    key = track.values[track.index(60)]
    assert set(np.unique(key[1:])) == {2.0}
    track.write(90, np.full(ROWS, 9.0), np.ones(ROWS, bool))
    assert set(np.unique(track.values[track.index(90)][1:])) == {3.0}
    # The lowest ring stands on the base: row 1 is asked, and stays.
    assert track.at(90)[km.NO_JACK] == km.REST["lift"]


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
    # As long as its commands run, as the show editor counts a Houdini file.
    assert motors.frames == 1320 + 1
    for frame in range(0, motors.frames, 7):
        pose = project.pose(frame)
        # The file's jack row N is the editor's lift[N]; row 30 has none.
        assert np.allclose(motors.jack[:ROWS - 1, frame], pose["lift"][1:], atol=1e-4)
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
    # A jack row 30 is no jack of TouchDesigner's: a Cinema 4D file's is left
    # out, and said.
    for got, want in ((again.jack[:ROWS - 1], original.jack[:ROWS - 1]),
                      (again.pusher, original.pusher), (again.tilt, original.tilt)):
        assert np.abs(got[..., :frames] - want[..., :frames]).max() < 1e-4
    if name.startswith("23 February"):
        assert any("наложенными" in one for one in said), said
    moving_last = np.ptp(original.jack[ROWS - 1]) > 0
    assert moving_last == any("ряда 30" in one for one in said), said


def test_the_jacks_are_numbered_as_touchdesigner_counts_them():
    """Jack N, 1 to 29 from the bottom, opens the gap between rings N and
    N+1 -- TouchDesigner's count and Houdini's. The editor keeps it as
    lift[N], the gap under ring N+1; the viewer reads a file so; and the
    two lift the same rings."""
    assert kinetic.JACK_READING == "rig"
    project = km.Project(length=600)
    lift = project.tracks["lift"]
    ring = np.zeros(ROWS, bool)
    ring[5] = True                         # the gap under ring 6
    lift.write(100, np.full(ROWS, 3.0), ring)
    data = km.to_motor_json(project)["data"]
    moving = [number for number in range(1, ROWS)
              if any(one["start"] != one["dest"]
                     for one in data[f"row_{number}"]["jack"]["id_1"])]
    assert moving == [5], "jack 5 is the gap over ring 5"
    assert "jack" not in data[f"row_{ROWS}"]
    motors = _read_back(project, "jacks")
    editor = km.ring_heights(project.pose(100)["lift"]) - km.ring_heights(
        np.full(ROWS, 1.0))
    assert np.all(editor[:5] == 0) and np.all(editor[5:] > 0)
    assert np.allclose(motors.rise(100) / 1000.0, editor, atol=1e-6)


def _houdini_file(folder):
    """A motor file laid out as Houdini's exporter lays it out, with the
    things keys alone cannot say: ids out of order, a motor moving from frame
    0 (no segment of no length), a hold, a pause, a 0.0 for 0, and a range
    longer than its commands."""
    import json
    data = {}
    for number in range(1, ROWS + 1):
        row = {"pusher": {}, "tilt": {}}
        ids = list(range(1, km.GROUPS + 1))
        if number == 3:
            ids = ids[4:] + ids[:4]           # Houdini's own points' order
        for which in ids:
            row["pusher"][f"id_{which}"] = [
                {"frame": 0, "start": 0.1, "dest": 0.1, "length": 0}]
        for which in range(1, PER_ROW + 1):
            row["tilt"][f"id_{which}"] = [
                {"frame": 0, "start": 0, "dest": 0, "length": 0}]
        if number < ROWS:
            row["jack"] = {"id_1": [{"frame": 0, "start": 1, "dest": 1, "length": 0}]}
        data[f"row_{number}"] = row
    data["row_2"]["pusher"]["id_1"] = [                     # moving from frame 0
        {"frame": 0, "start": 0.1, "dest": 0.5, "length": 120},
        {"frame": 200, "start": 0.5, "dest": 0.5, "length": 60},    # a hold
        {"frame": 400, "start": 0.5, "dest": 0.0, "length": 120}]   # after a pause
    data["row_4"]["pusher"]["id_3"] = [
        {"frame": 0, "start": 0.1, "dest": 0.1, "length": 0},
        {"frame": 50, "start": 0.1, "dest": 0.0, "length": 100},
        {"frame": 300, "start": 0.0, "dest": 0.25, "length": 90}]
    data["row_7"]["jack"]["id_1"] = [
        {"frame": 0, "start": 1, "dest": 1, "length": 0},
        {"frame": 60, "start": 1, "dest": 2, "length": 600}]
    data["row_9"]["tilt"]["id_17"] = [
        {"frame": 0, "start": 0, "dest": 0, "length": 0},
        {"frame": 30, "start": 0, "dest": 0.0556, "length": 75}]
    payload = {"name": "houdini_like", "type": "kinematic_preset", "data": data,
               "info": {"created_at": "2026-10-03 12:00:00.123456", "version": "1",
                        "export_range": {"start": 0, "end": 900}, "total_frames": 900,
                        "part": 1, "total_parts": 1, "fps": 60}}
    path = folder / "houdini_like_1_of_1.json"
    text = json.dumps(payload, indent=4)
    path.write_text(text, encoding="utf-8")
    return path, text


def test_a_houdini_file_read_in_and_written_out_is_the_same_file():
    import json
    OUT.mkdir(parents=True, exist_ok=True)
    path, text = _houdini_file(OUT)
    project, said = km.from_motor_json(path)
    assert project.length == 900
    back = km.to_motor_json(project, "houdini_like")
    back["info"]["created_at"] = "2026-10-03 12:00:00.123456"
    assert json.dumps(back, indent=4) == text
    # Through the editor's own file too: saved as a piece and opened again.
    piece = OUT / "houdini_like.kin"
    project.save(piece)
    again = km.to_motor_json(km.Project.load(piece), "houdini_like")
    again["info"]["created_at"] = "2026-10-03 12:00:00.123456"
    assert json.dumps(again, indent=4) == text
    # The motion is what TouchDesigner plays either way.
    played = kinetic.Motors(path)
    ours = _read_back(project, "houdini_like_back")
    frames = min(played.frames, ours.frames)
    assert np.abs(played.pusher[..., :frames] - ours.pusher[..., :frames]).max() < 1e-4
    assert np.abs(played.jack[..., :frames] - ours.jack[..., :frames]).max() < 1e-4


HOUDINI = ("Matreshka_bunker_1_of_1.json",
           "Carshering_all_animation_5_v1_2026_07_24_1_of_1.json")


@pytest.mark.parametrize("name", HOUDINI)
def test_a_real_houdini_file_comes_back_to_the_byte(name):
    import json
    found = glob.glob(str(CONTENT / "**" / name), recursive=True)
    if not found:
        pytest.skip(f"{name} is not on this machine")
    text = Path(found[0]).read_text(encoding="utf-8")
    original = json.loads(text)
    project, _ = km.from_motor_json(found[0])
    back = km.to_motor_json(project, original["name"])
    back["info"]["created_at"] = original["info"]["created_at"]
    assert json.dumps(back, indent=4) == text


# -- the limits ----------------------------------------------------------------------

def _degrees(lift, push=None):
    low, high = km.tilt_bounds(lift, push)
    return -low[:, 0] * 90, high[:, 0] * 90          # up, down: by ring


def test_tilts_are_held_the_houdini_way_by_the_gap_they_swing_into():
    lift = np.full(ROWS, 1.0)
    up, down = _degrees(lift)
    assert np.allclose(up[:-1], 10) and np.allclose(down[1:], 10)
    # Nothing under the lowest ring, nothing over the top one: only the beam.
    assert down[0] == pytest.approx(30) and up[-1] == pytest.approx(30)
    # Row 11's jack closed: the gap under ring 11 (from zero, 10) and over
    # ring 10 (9). Face down into it from above, face up into it from below.
    lift[10] = 0.0
    up, down = _degrees(lift)
    assert down[10] == pytest.approx(2) and up[10] == pytest.approx(10)
    assert up[9] == pytest.approx(2) and down[9] == pytest.approx(10)
    # A gap of 660 mm lets 45 through, and the beam holds it to 30 until the
    # pusher is out: 0.1 still 30, 0.2 all 45, half way half way.
    lift = np.full(ROWS, 2.0)
    for push, want in ((0.0, 30), (0.1, 30), (0.15, 37.5), (0.2, 45), (0.8, 45)):
        up, down = _degrees(lift, np.full((ROWS, km.GROUPS), push))
        assert np.allclose(up, want) and np.allclose(down, want), push
    # Row 1 has no jack; a jack between two places is between their degrees.
    lift[0] = 0.0
    assert np.allclose(_degrees(lift)[1], 30)
    lift = np.full(ROWS, 1.5)                 # 495 mm, half way to 660
    assert _degrees(lift, np.full((ROWS, km.GROUPS), 1.0))[1][5] == \
        pytest.approx(10 + (45 - 10) / 2, abs=0.01)
    tilt = np.full((ROWS, PER_ROW), 0.45)
    held = km.clamp_tilt(tilt, np.full(ROWS, 1.0))
    assert np.allclose(held[1:], 10 / 90) and np.allclose(held[0], 30 / 90)
    assert not km.over_limit(held, np.full(ROWS, 1.0)).any()
    held = km.clamp_tilt(-tilt, np.full(ROWS, 1.0))
    assert np.allclose(held[:-1], -10 / 90) and np.allclose(held[-1], -30 / 90)


def test_cinema4ds_rule_is_kept_beside_it():
    lift = np.full(ROWS, 1.0)
    reach = km.tilt_reach(lift)
    assert np.allclose(reach, 10 / 90)
    low, high = km.tilt_bounds(lift, rule="c4d")
    assert np.allclose(high, 10 / 90) and np.allclose(low, -10 / 90)
    # Row 11's jack closed: the gap under ring 11, over ring 10 (from zero,
    # 10 and 9) -- the machine's numbering, Cinema 4D's.
    lift[10] = 0.0
    reach = km.tilt_reach(lift)
    assert reach[10] == 0.0 and reach[9] == 0.0
    assert reach[8] == pytest.approx(10 / 90) and reach[11] == pytest.approx(10 / 90)
    lift = np.full(ROWS, 2.0)
    assert np.allclose(km.tilt_reach(lift), 30 / 90)
    # Row 1 has no jack: what it says changes nothing. The top ring has only
    # the gap under it.
    lift[0] = 0.0
    assert np.allclose(km.tilt_reach(lift), 30 / 90)
    lift[ROWS - 1] = 0.0
    reach = km.tilt_reach(lift)
    assert reach[ROWS - 1] == 0.0 and reach[ROWS - 2] == 0.0
    assert reach[ROWS - 3] == pytest.approx(30 / 90)


def test_violations_are_found_at_keys():
    project = km.Project(length=600)
    tilt = project.tracks["tilt"]
    tilt.write(300, np.full(tilt.size, 0.3), np.ones(tilt.size, bool))
    found = dict(project.violations())
    # 27 degrees face down: past the 10 of every gap at 330 mm, and within
    # the beam's 30 on the lowest ring, which has no gap under it.
    assert found == {300: (ROWS - 1) * PER_ROW}


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


def test_the_export_is_as_long_as_the_motors_move():
    """Trimmed to the frame the last motor gets there, that frame in: a
    transition of a few seconds on a minute's timeline is a few seconds."""
    import json
    project = km.Project(length=3600)
    push = project.tracks["push"]
    one = np.zeros(push.size, bool)
    one[7] = True
    push.write(60, np.zeros(push.size), one)
    push.write(225, np.full(push.size, 0.4), one)
    written = km.export_motor_json(project, OUT / "trimmed.json")
    info = json.loads(written.read_text("utf-8"))["info"]
    assert info["export_range"] == {"start": 0, "end": 226}
    assert info["total_frames"] == 226
    assert km.last_arrival(project) == 225
    # What the show editor makes of it agrees.
    data = json.loads(written.read_text("utf-8"))["data"]
    assert showfile.commands_of(data)[0] == 226
    # A piece that never moves is one frame: its pose.
    still = km.export_motor_json(km.Project(length=600), OUT / "still.json")
    assert json.loads(still.read_text("utf-8"))["info"]["total_frames"] == 1


def test_an_old_export_read_in_goes_out_in_houdinis_order():
    """A file this editor wrote before had its groups jack first: read in
    and written out again, it is laid out as Houdini lays a file out; the
    ids keep the order they came in."""
    import json
    OUT.mkdir(parents=True, exist_ok=True)
    path, text = _houdini_file(OUT)
    payload = json.loads(text)
    for row in payload["data"].values():
        if "jack" in row:
            jack = row.pop("jack")
            row_items = list(row.items())
            row.clear()
            row["jack"] = jack
            row.update(row_items)
    old = OUT / "old_order_1_of_1.json"
    old.write_text(json.dumps(payload, indent=4), encoding="utf-8")
    project, _ = km.from_motor_json(old)
    back = km.to_motor_json(project)
    assert list(back["data"]["row_1"]) == ["pusher", "tilt", "jack"]
    assert list(back["data"]["row_3"]["pusher"]) == list(payload["data"]["row_3"]["pusher"])
