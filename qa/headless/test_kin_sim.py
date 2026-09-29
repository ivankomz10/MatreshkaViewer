"""The motors' own motion, without the window.

Cinema 4D's rule, the machine's: no move faster than the motor, a rest after
every move, a command arriving during either dropped. What comes out has to
be the motion itself, as keys -- drawn, checked and exported like any other.
"""
from __future__ import annotations

import numpy as np
import pytest

from conftest import HOME

import kin_model as km
import kin_sim
import kinetic
from kinetic import PER_ROW, ROWS

OUT = HOME / "kinedit"


def _piece(length: int = 1800) -> km.Project:
    OUT.mkdir(parents=True, exist_ok=True)
    return km.Project(length=length)


def _key(project, family, frame, value, motors=None):
    track = project.tracks[family]
    mask = np.zeros(track.size, bool)
    mask[motors if motors is not None else slice(None)] = True
    track.write(frame, np.full(track.size, value, np.float32), mask)


def test_keys_the_motors_can_keep_up_with_come_out_as_they_are():
    project = _piece()
    _key(project, "push", 300, 0.5)        # 0.5 in 5 s: 2 s at pace
    _key(project, "tilt", 600, 0.1)        # 9 degrees in 10 s
    _key(project, "lift", 1500, 2.0, [4, 5, 6])
    result = kin_sim.simulate(project)
    assert not result.dropped and not result.late
    for frame in range(0, project.length, 37):
        for family in km.FAMILIES:
            assert np.allclose(result.project.tracks[family].at(frame),
                               project.tracks[family].at(frame), atol=1e-5), \
                (family, frame)


def test_a_move_asked_too_fast_arrives_at_the_motors_pace():
    project = _piece()
    _key(project, "push", 60, 0.9, [7])      # 900 mm in one second
    result = kin_sim.simulate(project)
    (late,) = result.late
    assert (late.family, late.motor, late.frame, late.due) == ("push", 7, 0, 60)
    assert late.arrives == int(0.9 * 4 * km.FPS)          # 216
    motion = result.project.tracks["push"]
    assert motion.at(60).reshape(-1)[7] < 0.9 * 0.5
    assert motion.at(216).reshape(-1)[7] == pytest.approx(0.9)
    assert result.worst_late() is late


def test_a_jack_goes_the_whole_of_its_travel_in_fifteen_seconds():
    project = _piece(2400)
    _key(project, "lift", 60, 3.0, [12])     # state 1 to 3: three quarters
    result = kin_sim.simulate(project)
    (late,) = result.late
    assert late.arrives == int(0.75 * 15 * km.FPS)          # 675


def test_a_command_during_the_rest_is_dropped_and_the_motor_stays():
    """Two keys back to back: the second move is asked for the frame the
    first one ends, and the motor is resting then -- as Cinema 4D drops it."""
    project = _piece()
    _key(project, "push", 300, 1.0, [3])     # 4 s of travel in 5: in time
    _key(project, "push", 500, 0.2, [3])     # asked at 300, while resting
    result = kin_sim.simulate(project)
    (dropped,) = result.dropped
    assert (dropped.family, dropped.motor, dropped.frame) == ("push", 3, 300)
    assert dropped.busy_until == 300 + int(0.5 * km.FPS)
    assert result.project.tracks["push"].at(900).reshape(-1)[3] == pytest.approx(1.0)
    assert 300 in result.problems()


def test_putting_the_motion_onto_the_keys_leaves_nothing_to_drop():
    project = _piece()
    _key(project, "push", 60, 0.9, [7, 8, 9])
    _key(project, "push", 100, 0.2, [7, 8, 9])
    _key(project, "tilt", 40, 0.1, [100])
    _key(project, "tilt", 45, -0.1, [100])
    first = kin_sim.simulate(project)
    assert first.dropped and first.late
    for family in km.FAMILIES:
        project.tracks[family].restore(first.project.tracks[family].state())
    again = kin_sim.simulate(project)
    assert not again.dropped and not again.late
    for frame in range(0, project.length, 11):
        for family in km.FAMILIES:
            assert np.allclose(again.project.tracks[family].at(frame),
                               first.project.tracks[family].at(frame), atol=1e-5)
    # And what is exported is that motion, as the viewer plays it.
    motors = kinetic.Motors(km.export_motor_json(project, OUT / "baked.json"))
    for frame in range(0, project.length, 13):
        assert np.allclose(motors.pusher[:, :, frame],
                           first.project.tracks["push"].at(frame), atol=1e-4)


def test_a_tilt_past_the_gaps_while_a_jack_closes_is_caught_on_the_way():
    project = _piece(2400)
    _key(project, "lift", 0, 2.0)
    _key(project, "tilt", 0, 0.3)            # 27 degrees: fine at state 2
    assert not project.violations()
    _key(project, "lift", 1200, 1.0, [10])   # row 11 closes to 330 mm
    result = kin_sim.simulate(project)
    frames = [frame for frame, _ in result.clashes]
    assert frames, "the closing gap under tilted rings was not caught"
    # From when the jack drops below state 2, before its key is reached.
    assert frames[0] < 1200 and all(count <= 2 * PER_ROW for _, count
                                    in result.clashes)


def test_the_cells_left_behind_are_the_ones_said_to_differ():
    project = _piece()
    _key(project, "push", 60, 0.9, [0])      # cells 0..4 of the lowest ring
    result = kin_sim.simulate(project)
    lag = kin_sim.differs(project, result.project, 60)
    assert lag[0, :5].all() and lag.sum() == 5
