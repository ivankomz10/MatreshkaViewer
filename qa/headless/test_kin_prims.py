"""The primitives the honeycomb wraps, and the masks: the arithmetic, no window.

A sphere is stood on the middle of the building's front, and what each cell
does is read off the pose it makes: pushed out to the surface or pressed in
to it, turned along it within the gaps, kept to a mask -- and all of it
turned into keys for the motors, saved, undone.
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from conftest import HOME

import kin_model as km
import kin_prims as kp
import kinetic
from kinetic import PER_PUSHER, PER_ROW, ROWS

OUT = HOME / "kin_prims"
RING, CELL = 15, 40


def _sphere(radius=0.8, offset=0.0, polarity="positive") -> kp.Primitive:
    one = kp.Primitive("sphere", "ball", azimuth=float(km.cell_azimuths()[RING, CELL]))
    values = one.values[0]
    values[kp.HEIGHT], values[kp.OFFSET], values[kp.WIDTH] = RING, offset, radius
    one.polarity = polarity
    return one


def _piece(*primitives) -> km.Project:
    project = km.Project(600)
    project.primitives = list(primitives)
    return project


def test_a_positive_sphere_pushes_what_it_swallows_out_to_its_surface():
    project = _piece(_sphere(radius=0.8))
    pose = kp.pose_at(project, 0)
    push = pose["push"]
    # The group straight in front of its centre goes out by the radius; the
    # far side of the building stays where the keys have it.
    group = CELL // PER_PUSHER
    assert push[RING, group] == pytest.approx(0.8, abs=1e-3)
    moved = push > 1e-6
    assert moved.any() and moved.sum() < 20
    far = (CELL + PER_ROW // 2) % PER_ROW // PER_PUSHER
    assert not moved[:, far].any()
    assert not (push > 1.0).any()
    # The jacks are never a primitive's.
    assert np.array_equal(pose["lift"], project.pose(0)["lift"])


def test_a_negative_sphere_presses_the_cells_in_to_its_surface():
    project = _piece(_sphere(radius=0.6, offset=0.5, polarity="negative"))
    project.tracks["push"].write(0, np.full(ROWS * km.GROUPS, 0.9), np.ones(300, bool))
    pose = kp.pose_at(project, 0)
    group = CELL // PER_PUSHER
    # Its near side is 0.5 - 0.6 below the surface: the cells go back to it,
    # which is the stop.
    assert pose["push"][RING, group] == pytest.approx(0.0, abs=1e-3)
    pressed = pose["push"] < 0.9 - 1e-6
    assert pressed.any() and pressed.sum() < 20
    assert not (pose["push"] > 0.9 + 1e-6).any()


def test_the_cells_lie_along_its_surface_within_their_gaps():
    project = _piece(_sphere(radius=0.8))
    project.tracks["lift"].write(0, np.full(ROWS, 3.0), np.ones(ROWS, bool))
    tilt = kp.pose_at(project, 0)["tilt"] * kinetic.TILT_DEGREES
    # Only the cells it swallows turn -- the others of their groups are
    # carried out by their pusher and keep their tilt.
    turned = np.abs(tilt) > 1e-3
    rows = np.arange(ROWS)[:, None]
    below, above = turned & (rows < RING), turned & (rows > RING)
    # Under its middle the surface faces down, over it up; its middle level.
    assert below.any() and above.any()
    assert (tilt[below] > 1.0).all() and (tilt[above] < -1.0).all()
    assert not turned[RING].any()
    lift = project.pose(0)["lift"]
    assert not km.over_limit(tilt / kinetic.TILT_DEGREES, lift,
                             kp.pose_at(project, 0)["push"]).any()
    project.primitives[0].tilt = False
    assert not np.abs(kp.pose_at(project, 0)["tilt"]).any()


def test_a_box_front_is_flat():
    one = kp.Primitive("box", "box", azimuth=float(km.cell_azimuths()[RING, CELL]))
    values = one.values[0]
    values[kp.HEIGHT], values[kp.OFFSET] = RING, 0.0
    values[kp.WIDTH], values[kp.TALL], values[kp.DEPTH] = 0.6, 0.5, 0.4
    pose = kp.pose_at(_piece(one), 0)
    out = pose["push"][pose["push"] > 0]
    assert len(out) and (out >= 0.4 - 1e-3).all() and (out < 0.5).all()
    assert not np.abs(pose["tilt"]).any()


def test_a_mask_keeps_a_primitive_to_its_cells_and_its_tilt_to_another():
    one = _sphere(radius=0.8)
    project = _piece(one)
    everywhere = kp.touched_cells(project, one, 0)
    half = np.zeros((ROWS, PER_ROW), np.float32)
    half[:RING] = 1.0
    project.masks["low"] = half.reshape(-1)
    one.mask = "low"
    kept = kp.touched_cells(project, one, 0)
    assert kept.any() and not kept[RING + 1:].any()
    assert kept.sum() < everywhere.sum()
    # The tilt to a mask of its own: here nowhere at all.
    project.masks["none"] = np.zeros(ROWS * PER_ROW, np.float32)
    one.mask, one.tilt_mask = "", "none"
    pose = kp.pose_at(project, 0)
    assert (pose["push"] > 0).any() and not np.abs(pose["tilt"]).any()


def test_a_masks_weights_by_motor_and_its_brush():
    weights = np.zeros((ROWS, PER_ROW), np.float32)
    weights[3, :PER_ROW // 2 + 1] = 1.0      # past half of ring 4
    weights[5, 7] = 0.4                      # one cell of a group, part way
    assert kp.motor_weights("lift", weights)[3] == 1.0
    assert kp.motor_weights("lift", weights)[5] == 0.0
    push = kp.motor_weights("push", weights).reshape(ROWS, km.GROUPS)
    assert push[5, 7 // PER_PUSHER] == pytest.approx(0.4)
    dab = np.zeros((ROWS, PER_ROW), np.float32)
    dab[10, 10] = 1.0
    painted = kp.paint_mask(np.zeros(ROWS * PER_ROW), dab, 0.5)
    assert painted.reshape(ROWS, PER_ROW)[10, 10] == pytest.approx(0.5)
    erased = kp.paint_mask(painted, dab, 1.0, "erase")
    assert not erased.any()


def test_a_moving_primitive_becomes_keys_every_step_and_the_rest_keep_theirs():
    one = _sphere(radius=0.8)
    later = one.values[0].copy()
    later[kp.AZIMUTH] = (later[kp.AZIMUTH] + 60.0) % 360.0
    one.write(300, later)
    project = _piece(one)
    project.tracks["tilt"].write(120, np.full(ROWS * PER_ROW, 0.05),
                                 np.ones(ROWS * PER_ROW, bool))
    before = project.to_dict()
    motion = kp.compose(project)
    assert project.to_dict() == before                      # left as it was
    push = motion.tracks["push"]
    assert set(range(0, 301, project.prim_step)) <= set(push.frames)
    # Wherever it is keyed, it is what the primitive makes there.
    for frame in (0, 150, 300):
        assert np.allclose(motion.pose(frame)["push"], kp.pose_at(project, frame)["push"],
                           atol=1e-4)
    # The jacks were never touched; a tilt the sphere never reaches keeps
    # exactly its own keys.
    assert motion.tracks["lift"].frames == project.tracks["lift"].frames
    far = (RING, (CELL + PER_ROW // 2) % PER_ROW)
    motor = far[0] * PER_ROW + far[1]
    assert motion.tracks["tilt"].segments(motor) == project.tracks["tilt"].segments(motor)
    # A piece with none, or none on, is its own motion.
    one.on = False
    assert kp.compose(project) is project


def test_the_motor_json_of_a_piece_with_a_primitive_carries_it():
    OUT.mkdir(parents=True, exist_ok=True)
    project = _piece(_sphere(radius=0.8))
    written = km.export_motor_json(kp.compose(project), OUT / "sphere.json")
    data = json.loads(written.read_text("utf-8"))["data"]
    # The pusher in front of the sphere stands out by its radius from the
    # start, in the file's own units (pusher travel, 0..1).
    segments = data[f"row_{RING + 1}"]["pusher"][f"id_{CELL // PER_PUSHER + 1}"]
    assert segments[0]["frame"] == 0
    assert segments[0]["dest"] == pytest.approx(0.8, abs=1e-3), segments


def test_baking_puts_the_primitives_into_the_keys_and_turns_them_off():
    project = _piece(_sphere(radius=0.8))
    wanted = kp.pose_at(project, 0)
    assert kp.bake(project) == 1
    assert not project.primitives[0].on
    assert np.allclose(project.pose(0)["push"], wanted["push"], atol=1e-4)
    assert np.allclose(project.pose(0)["tilt"], wanted["tilt"], atol=1e-4)
    assert kp.bake(project) == 0


def test_masks_and_primitives_are_saved_and_undone():
    OUT.mkdir(parents=True, exist_ok=True)
    one = _sphere(radius=0.7, polarity="negative")
    one.write(200, one.values[0] * 1.0)
    one.mask, one.tilt = "front", False
    project = _piece(one)
    project.masks["front"] = np.linspace(0, 1, ROWS * PER_ROW).astype(np.float32)
    project.prim_step = 12
    path = OUT / "shapes.kin"
    project.save(path)
    back = km.Project.load(path)
    got = back.primitives[0]
    assert (got.kind, got.polarity, got.mask, got.tilt) == ("sphere", "negative",
                                                           "front", False)
    assert got.frames == [0, 200] and back.prim_step == 12
    assert np.allclose(back.masks["front"], project.masks["front"], atol=1e-3)
    state = project.state()
    version = project.version
    project.primitives.clear()
    project.masks.clear()
    project.restore(state)
    assert len(project.primitives) == 1 and "front" in project.masks
    assert project.version != version            # a restore is a change


def test_a_primitive_eases_between_its_keys_the_short_way_round():
    one = kp.Primitive("sphere", "ball", azimuth=350.0)
    later = one.values[0].copy()
    later[kp.AZIMUTH] = 10.0
    later[kp.WIDTH] = 2.0
    one.write(100, later)
    half = one.at(50)
    assert half[kp.AZIMUTH] == pytest.approx(0.0, abs=1e-6) or \
        half[kp.AZIMUTH] == pytest.approx(360.0, abs=1e-6)
    assert one.values[0][kp.WIDTH] < half[kp.WIDTH] < 2.0
    one.move(1, 60)
    assert one.frames == [0, 60]
