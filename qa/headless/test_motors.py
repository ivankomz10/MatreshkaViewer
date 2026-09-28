"""Motor files laid end to end, and played over -- asked of the engine alone.

These were window tests while the rows could be chained. The quick look has
one file a row now and the chains belong to the show mode, but what they
checked is the motors' own arithmetic, and that is still what the show mode
will stand on.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import kinetic

BLOCKS = Path(r"D:\Content\Dostizhenia\JSON")
PARTS = [Path(r"D:\Content\2026-dates\BrendMT\BrendMT_1_of_2.json"),
         Path(r"D:\Content\2026-dates\BrendMT\BrendMT_2_of_2.json")]


def test_seven_blocks_are_one_timeline():
    blocks = sorted(BLOCKS.glob("*.json")) if BLOCKS.exists() else []
    if len(blocks) < 3:
        pytest.skip("the programme's blocks are not on this machine")
    motors = kinetic.Motors(blocks)
    assert len(motors.parts) == len(blocks)
    at = 0
    for part in motors.parts:
        assert part.first == at, f"{part.name} starts at {part.first}, not {at}"
        at += part.length
    # Each part counts its own last frame: the chain is the parts together.
    assert motors.frames == at
    assert len(motors.boundaries) == len(blocks) - 1


def test_nothing_jumps_where_two_parts_meet():
    """The exporter cuts a movement in half; the chain has to finish it."""
    if not all(one.exists() for one in PARTS):
        pytest.skip("the two-part show is not on this machine")
    motors = kinetic.Motors(PARTS)
    join = motors.parts[1].first
    for name, array in (("tilt", motors.tilt), ("pusher", motors.pusher),
                        ("jack", motors.jack)):
        step = float(np.abs(array[..., join] - array[..., join - 1]).max())
        assert step < 0.02, (
            f"{name} jumps {step:.4f} at the join -- the movement the "
            "exporter cut in half was not carried across")


def test_a_part_played_twice_moves_the_same_way_both_times():
    if not all(one.exists() for one in PARTS):
        pytest.skip("the two-part show is not on this machine")
    plain = kinetic.Motors(PARTS)
    looped = kinetic.Motors(PARTS, repeats=[2, 1])
    over = looped.parts[0].length
    assert looped.frames == plain.frames + over
    assert np.allclose(looped.tilt[..., :over], looped.tilt[..., over:2 * over])
    assert np.allclose(looped.tilt[..., 2 * over:], plain.tilt[..., over:])


def test_a_lone_part_finds_the_others_beside_it():
    if not all(one.exists() for one in PARTS):
        pytest.skip("the two-part show is not on this machine")
    assert kinetic.parts_beside(PARTS[0]) == PARTS
