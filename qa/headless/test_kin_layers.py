"""The layers under the keys, as Blender's NLA: the arithmetic, no window.

A wave of push on one ring -- out and back -- is put into a clip, and what
the strips then make of it is read off the pose: blended over what is under
them, faded, repeated, reversed, moved round the building, kept to a mask;
the keys on top; and all of it turned into keys for the motors, saved,
undone, put back as keys.
"""
from __future__ import annotations

import numpy as np
import pytest

from conftest import HOME

import kin_layers as kl
import kin_model as km
from kinetic import PER_ROW, ROWS

OUT = HOME / "kin_layers"
RING = 4


def _wave(project=None, ring=RING, at=100, height=0.6):
    """Ring `ring`'s pushers out to `height` and back, 60 frames each way."""
    project = project or km.Project(1200)
    push = project.tracks["push"]
    mask = np.zeros(ROWS * km.GROUPS, bool)
    mask[ring * km.GROUPS:(ring + 1) * km.GROUPS] = True
    for frame, value in ((at, 0.0), (at + 60, height), (at + 120, 0.0)):
        push.write(frame, np.full(push.size, value), mask)
    return project


def _clip(project=None):
    project = _wave(project)
    kl.push_down(project, "wave", "L1")
    return project, project.layers[0].strips[0]


def test_keys_into_a_clip_leave_the_piece_as_it_was():
    project = _wave()
    before = {frame: project.pose(frame)["push"].copy() for frame in range(0, 400, 7)}
    index = kl.push_down(project, "wave", "L1")
    assert index == 0 and len(project.layers) == 1
    # The keys went -- the rest every motor started at too, which says
    # nothing -- and the clip begins where the ring begins to move.
    assert all(not len(track) for track in project.tracks.values())
    strip = project.layers[0].strips[0]
    clip = project.clips["wave"]
    assert (strip.start, clip.length) == (100, 120)
    assert not clip.keyed()["lift"].any() and not clip.keyed()["tilt"].any()
    for frame, push in before.items():
        assert np.allclose(project.pose(frame)["push"], push, atol=1e-5), frame


def test_the_keys_lie_over_the_layers_where_a_motor_has_any():
    project, _ = _clip()
    push = project.tracks["push"]
    one = np.zeros(push.size, bool)
    one[RING * km.GROUPS] = True               # the ring's first pusher only
    push.write(0, np.full(push.size, 0.2), one)
    pose = project.pose(160)["push"]
    assert pose[RING, 0] == pytest.approx(0.2)          # its own key, held
    assert pose[RING, 1] == pytest.approx(0.6)          # the clip's


def test_the_three_ways_a_strip_lies_on_what_is_under_it():
    project, low = _clip()
    top = kl.Layer("L2")
    over = kl.Strip("wave", 100)
    top.strips.append(over)
    project.layers.append(top)
    low.influence = 1.0
    over.influence = 0.5
    # Over the same wave, half as strong: half way from it to itself.
    assert project.pose(160)["push"][RING, 0] == pytest.approx(0.6)
    over.start = 40                          # its top at 100, the other's at 160
    assert project.pose(100)["push"][RING, 0] == pytest.approx(0.3)
    over.mode, over.influence = "add", 1.0
    assert project.pose(130)["push"][RING, 0] == pytest.approx(
        project.clips["wave"].pose(30)["push"][RING, 0]
        + project.clips["wave"].pose(90)["push"][RING, 0], abs=1e-5)
    over.mode = "max"
    at_130 = project.pose(130)["push"][RING, 0]
    assert at_130 == pytest.approx(max(project.clips["wave"].pose(30)["push"][RING, 0],
                                       project.clips["wave"].pose(90)["push"][RING, 0]))
    # Nothing past the pusher's travel.
    over.mode = "add"
    over.start = 100
    assert project.pose(160)["push"][RING, 0] == pytest.approx(1.0)


def test_a_jack_is_never_left_between_two_places():
    project = km.Project(600)
    lift = project.tracks["lift"]
    ring = np.zeros(ROWS, bool)
    ring[10] = True
    lift.write(0, np.full(ROWS, 1.0), ring)
    lift.write(30, np.full(ROWS, 3.0), ring)
    kl.push_down(project, "jack", "L1")
    strip = project.layers[0].strips[0]
    strip.influence = 0.4
    assert project.pose(30)["lift"][10] == 1.0          # under half: not at all
    strip.influence = 0.6
    assert project.pose(30)["lift"][10] == 3.0          # past half: all the way
    assert project.pose(15)["lift"][10] == pytest.approx(
        project.clips["jack"].pose(15)["lift"][10])     # and its own ease between


def test_fades_ease_a_strip_in_and_out():
    project, strip = _clip()
    strip.fade_in = strip.fade_out = 40
    clip = project.clips["wave"]
    assert project.pose(100)["push"][RING, 0] == pytest.approx(0.0)
    half = project.pose(120)["push"][RING, 0]
    assert half == pytest.approx(clip.pose(20)["push"][RING, 0] * 0.5, abs=1e-5)
    assert project.pose(160)["push"][RING, 0] == pytest.approx(0.6)
    assert project.pose(200)["push"][RING, 0] == pytest.approx(
        clip.pose(100)["push"][RING, 0] * 0.5, abs=1e-5)


def test_repeated_sped_and_reversed():
    project, strip = _clip()
    clip = project.clips["wave"]
    strip.repeat, strip.speed = 2, 2.0
    assert strip.length(clip) == 120
    assert project.pose(130)["push"][RING, 0] == pytest.approx(0.6)     # first top
    assert project.pose(190)["push"][RING, 0] == pytest.approx(0.6)     # second
    strip.repeat, strip.speed = 1, 1.0
    # A ramp, reversed, is the ramp down: an in made an out.
    ramp = km.Project(600)
    push = ramp.tracks["push"]
    mask = np.zeros(push.size, bool)
    mask[0] = True
    push.write(0, np.zeros(push.size), mask)
    push.write(0, np.zeros(push.size), mask)
    push.write(100, np.full(push.size, 0.8), mask)
    kl.push_down(ramp, "in", "L1")
    in_ = ramp.layers[0].strips[0]
    assert ramp.pose(100)["push"][0, 0] == pytest.approx(0.8)
    in_.reverse = True
    assert ramp.pose(0)["push"][0, 0] == pytest.approx(0.8)
    assert ramp.pose(100)["push"][0, 0] == pytest.approx(0.0)
    # Held past its end, or let go.
    in_.reverse, in_.hold = False, True
    assert ramp.pose(300)["push"][0, 0] == pytest.approx(0.8)
    in_.hold = False
    assert ramp.pose(300)["push"][0, 0] == pytest.approx(0.0)


def test_moved_round_the_building_and_up_and_kept_to_a_mask():
    project, strip = _clip()
    strip.rings = 3
    pose = project.pose(160)["push"]
    assert np.allclose(pose[RING + 3], 0.6) and not pose[RING].any()
    # Round by groups: a wave on one pusher goes to the next but one.
    one = km.Project(600)
    push = one.tracks["push"]
    mask = np.zeros(push.size, bool)
    mask[RING * km.GROUPS + 1] = True
    push.write(0, np.zeros(push.size), mask)
    push.write(50, np.full(push.size, 0.5), mask)
    kl.push_down(one, "dot", "L1")
    dot = one.layers[0].strips[0]
    dot.round = 2
    got = one.pose(50)["push"][RING]
    assert got[3] == pytest.approx(0.5) and got[1] == 0.0
    dot.round = -2                                # round the seam
    assert one.pose(50)["push"][RING][km.GROUPS - 1] == pytest.approx(0.5)
    # A mask keeps it to its cells.
    dot.round = 0
    cells = np.zeros((ROWS, PER_ROW), np.float32)
    one.masks["none"] = cells.reshape(-1)
    dot.mask = "none"
    assert not one.pose(50)["push"].any()
    # A jack moved onto the lowest ring stays there: it has none.
    lifts = km.Project(600)
    ring = np.zeros(ROWS, bool)
    ring[2] = True
    lifts.tracks["lift"].write(0, np.full(ROWS, 3.0), ring)
    kl.push_down(lifts, "jack", "L1")
    lifts.layers[0].strips[0].rings = -2
    assert lifts.pose(0)["lift"][km.NO_JACK] == km.REST["lift"]


def test_the_layers_become_keys_the_motors_can_play():
    project, strip = _clip()
    strip.fade_in = 30
    top = kl.Layer("L2")
    again = kl.Strip("wave", 400)
    again.rings, again.mode = 5, "add"
    top.strips.append(again)
    project.layers.append(top)
    tilt = project.tracks["tilt"]
    tilt.write(0, np.full(tilt.size, 0.05), np.ones(tilt.size, bool))
    before = project.to_dict()
    motion = kl.flatten(project)
    assert project.to_dict() == before
    assert not motion.layers
    # Where it keys, it is what the layers make; the keys stay exactly.
    for frame in motion.tracks["push"].frames:
        assert np.allclose(motion.pose(frame)["push"], project.pose(frame)["push"],
                           atol=1e-4), frame
    assert motion.tracks["tilt"].frames == tilt.frames
    assert {99, 100, 220, 221, 400, 460} <= set(motion.tracks["push"].frames)
    # The motor JSON of it carries the wave on both rings.
    data = km.to_motor_json(motion)["data"]
    assert data[f"row_{RING + 1}"]["pusher"]["id_1"]
    assert data[f"row_{RING + 6}"]["pusher"]["id_1"]
    # Nothing playing: the piece itself.
    for layer in project.layers:
        layer.muted = True
    assert kl.flatten(project) is project


def test_a_strip_goes_back_to_keys_as_it_plays():
    project, strip = _clip()
    strip.start, strip.rings = 300, 2
    count = kl.to_keys(project, 0, 0)
    assert count == 3 and not project.layers[0].strips
    push = project.tracks["push"]
    assert push.frames == [300, 360, 420]
    assert np.allclose(project.pose(360)["push"][RING + 2], 0.6)


def test_layers_are_saved_undone_and_baked():
    OUT.mkdir(parents=True, exist_ok=True)
    project, strip = _clip()
    strip.mode, strip.fade_out, strip.reverse = "max", 12, True
    path = OUT / "layers.kin"
    project.save(path)
    back = km.Project.load(path)
    got = back.layers[0].strips[0]
    assert (got.mode, got.fade_out, got.reverse, got.start) == ("max", 12, True, 100)
    assert back.clips["wave"].same(project.clips["wave"])
    # Empty keys stay empty: the layers are what plays.
    assert all(not len(track) for track in back.tracks.values())
    assert np.allclose(back.pose(150)["push"], project.pose(150)["push"])
    state = project.state()
    version = project.version
    strip.start = 500
    project.layers.append(kl.Layer("more"))
    project.restore(state)
    assert project.layers[0].strips[0].start == 100 and len(project.layers) == 1
    assert project.version != version
    # At the keys it makes: through a fade between two of them the motors ease.
    wanted = {frame: project.pose(frame)["push"].copy() for frame in (100, 160, 208)}
    kl.bake_all(project)
    assert not project.layers and not project.clips
    for frame, push in wanted.items():
        assert np.allclose(project.pose(frame)["push"], push, atol=1e-4)


def test_a_piece_at_rest_and_keys_that_cover_a_strip_are_told():
    fresh = km.Project(600)
    assert kl.resting(fresh)
    assert not kl.resting(_wave())
    project, strip = _clip()
    assert kl.overridden(project, strip) == 0
    push = project.tracks["push"]
    push.write(0, np.zeros(push.size), np.ones(push.size, bool))
    assert kl.overridden(project, strip) == km.GROUPS
