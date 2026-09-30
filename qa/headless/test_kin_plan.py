"""The plan of moves: keys the machine carries out, made of what the piece wants.

Each case is a curve the machine would mangle as it is -- keys one after
another with no rest, a move too long for its time, a peak too quick -- and
what the plan makes of it is run through the same simulation the window
runs: nothing dropped, nothing late that could be on time, the last shape
reached.
"""
from __future__ import annotations

import numpy as np
import pytest

import kin_model as km
import kin_plan
import kin_prims as kp
import kin_sim

PUSH_FULL = kin_sim.PACE["push"][0] * km.FPS         # 240 frames the whole way
REST = int(kin_sim.PACE["push"][1] * km.FPS)          # 30


def _piece(curve, family="push", motor=0, length=1200):
    """One motor keyed along (frame, value) pairs."""
    project = km.Project(length)
    track = project.tracks[family]
    mask = np.zeros(track.size, bool)
    mask[motor] = True
    for frame, value in curve:
        track.write(frame, np.full(track.size, value), mask)
    return project


def _run(project):
    result = kin_sim.simulate(project)
    return result, result.project.tracks["push"]


def test_keys_side_by_side_become_one_move_that_is_carried_out():
    # A slope sampled every ten frames: as it is, every other command drops.
    curve = [(100 + 10 * k, 0.8 * k / 20) for k in range(21)]
    project = _piece(curve)
    raw, _ = _run(project)
    assert raw.dropped
    planned = kin_plan.plan(project)
    result, _ = _run(planned)
    assert not result.dropped and not result.late
    assert result.project.pose(1100)["push"][0, 0] == pytest.approx(0.8)
    # One move, where the slope was.
    first, moves = planned.tracks["push"].segments(0)
    assert len(moves) == 1 and moves[0][0] == 100 and moves[0][2] == pytest.approx(0.8)


def test_a_move_too_long_for_its_time_is_centred_on_the_curves():
    project = _piece([(0, 0.0), (400, 0.0), (460, 1.0)])      # a second for 4 seconds
    planned = kin_plan.plan(project)
    result, track = _run(planned)
    assert not result.dropped and not result.late
    _, moves = planned.tracks["push"].segments(0)
    frame, start, dest, length = moves[0]
    # Half of it before the curve's own move, half after.
    assert length == PUSH_FULL and abs(frame + length / 2 - 430) <= 1
    assert result.project.pose(frame + length)["push"][0, 0] == pytest.approx(1.0)


def test_a_peak_too_quick_goes_as_far_as_it_can_and_the_last_shape_in_full():
    # Out to 0.8 and back in 60 frames each way, then out to 0.5 to stay.
    project = _piece([(0, 0.0), (300, 0.0), (360, 0.8), (420, 0.0), (600, 0.0),
                      (660, 0.5)])
    planned = kin_plan.plan(project)
    result, _ = _run(planned)
    assert not result.dropped
    peak = max(float(result.project.pose(f)["push"][0, 0]) for f in range(280, 440))
    assert 0.1 < peak < 0.8                 # turned back on time
    assert result.project.pose(1100)["push"][0, 0] == pytest.approx(0.5)


def test_keys_the_machine_carries_out_stay_exactly():
    curve = [(0, 0.0), (100, 0.0), (400, 0.6), (460, 0.6), (800, 0.1)]
    project = _piece(curve)
    assert not kin_sim.simulate(project).dropped
    planned = kin_plan.plan(project)
    assert planned.tracks["push"].segments(0) == project.tracks["push"].segments(0)
    assert planned.planned == 0


def test_a_jack_goes_to_its_places_late_rather_than_between():
    project = _piece([(0, 1.0), (100, 1.0), (130, 3.0), (160, 1.0)], family="lift",
                     motor=10, length=2400)
    planned = kin_plan.plan(project)
    result = kin_sim.simulate(planned)
    assert not result.dropped
    values = {float(v) for v in planned.tracks["lift"].values for v in [v[10]]}
    assert values <= {0.0, 1.0, 2.0, 3.0}
    assert result.project.pose(2390)["lift"][10] == 1.0


def test_a_wiggle_under_the_tolerance_is_no_move():
    items = kin_plan.pieces([0, 100, 110, 200], [0.0, 0.5, 0.49, 0.9], "push", 0.02)
    assert [one[0] for one in items] == ["run"]
    items = kin_plan.pieces([0, 100, 200, 300], [0.0, 0.5, 0.5, 0.0], "push", 0.02)
    assert [one[0] for one in items] == ["run", "hold", "run"]


def test_a_sphere_passing_up_the_building_is_followed_and_left_behind():
    """The case that asked for all this: a sphere from under the building to
    over it -- as sampled keys, the pushers are left half out."""
    project = km.Project(1800)
    project.prim_step = 10
    ball = kp.Primitive("sphere", "ball", azimuth=float(km.cell_azimuths()[15, 40]))
    values = ball.values[0]
    values[kp.HEIGHT], values[kp.OFFSET], values[kp.WIDTH] = -8.0, -1.5, 2.6
    ball.frames, ball.values = [], []
    ball.write(60, values.copy())
    values[kp.HEIGHT] = 38.0
    ball.write(1260, values.copy())
    project.primitives = [ball]
    wanted = kp.compose(project)
    raw = kin_sim.simulate(wanted)
    assert raw.dropped
    result = kin_sim.simulate(kin_plan.plan(wanted))
    assert not result.dropped and not result.late
    end = result.project.pose(1799)
    assert np.allclose(end["push"], wanted.pose(1799)["push"], atol=1e-4)
    assert np.allclose(end["tilt"], wanted.pose(1799)["tilt"], atol=1e-4)
    # And along the way nearer the sphere than the sampled keys got.
    errors = [np.abs(r.project.pose(f)["push"] - wanted.pose(f)["push"]).mean()
              for r in (raw, result) for f in (500, 700, 900)]
    assert np.mean(errors[3:]) < np.mean(errors[:3])


def test_the_plan_is_kept_in_the_project():
    from conftest import HOME
    project = km.Project(600)
    project.plan, project.tolerance = False, 0.05
    path = HOME / "plan.kin"
    project.save(path)
    back = km.Project.load(path)
    assert (back.plan, back.tolerance) == (False, pytest.approx(0.05))
