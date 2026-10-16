r"""What the documents promise, checked against the code they describe.

Run from this folder with the viewer's own interpreter:

    ..\tool\.venv\Scripts\python.exe -m pytest -q

The tests that need a graphics card say so and are skipped without one.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

import bridge

HERE = Path(__file__).resolve().parent
OUT = HERE / "scratch"


def test_the_machine_is_the_shape_the_documents_say():
    facts = bridge.machine()
    assert facts["rings"] == 30
    assert facts["cells_per_ring"] == 50
    assert facts["pushers_per_ring"] == 10
    assert facts["cells_per_pusher"] == 5
    assert facts["cells_total"] == 1500
    assert facts["fps"] == 60
    assert facts["motors"]["jack"]["states_mm"] == {
        "0": 0.0, "1": 330.0, "2": 660.0, "3": 1300.0}
    assert facts["jack_numbering"]["reading"] == "rig"


def test_a_closed_machine_lets_a_cell_move_two_degrees():
    found = bridge.limits(lift=0, push=0)
    middle = found["rows"][14]
    assert middle["down_degrees"] == pytest.approx(2.0, abs=0.01)
    assert middle["up_degrees"] == pytest.approx(-2.0, abs=0.01)


def test_each_jack_state_opens_the_swing_the_ramp_says():
    for state, degrees in ((0, 2.0), (1, 10.0), (2, 30.0), (3, 30.0)):
        rows = bridge.limits(lift=state, push=1.0)["rows"]
        assert rows[14]["down_degrees"] == pytest.approx(degrees, abs=0.01), state


def test_the_motor_stops_at_thirty_so_the_beam_never_binds():
    """The beam allows 30 at a pusher fully in and 45 fully out, but the
    motor only reaches 30 either way -- so pushing out buys no swing."""
    for out in (0.0, 0.15, 0.2, 1.0):
        row = bridge.limits(lift=3, push=out)["rows"][14]
        assert row["down_degrees"] == pytest.approx(30.0, abs=0.01), out
        assert row["up_degrees"] == pytest.approx(-30.0, abs=0.01), out


def test_the_widest_any_cell_goes_is_the_motors_own_reach():
    import kinetic
    assert kinetic.TILT_LIMIT_DEGREES == 30.0
    rows = bridge.limits(lift=3, push=1.0)["rows"]
    assert max(r["down_degrees"] for r in rows) == pytest.approx(30.0, abs=0.01)
    assert min(r["up_degrees"] for r in rows) == pytest.approx(-30.0, abs=0.01)
    # And a pose past it is refused, however wide the gaps are.
    assert not bridge.check(lift=3, push=1.0, tilt=0.4)["legal"]
    assert bridge.check(lift=3, push=1.0, tilt=1 / 3)["legal"]


def test_the_bottom_ring_has_nothing_under_it_and_the_top_nothing_over():
    rows = bridge.limits(lift=0, push=1.0)["rows"]
    assert rows[0]["gap_below"] is None
    assert rows[0]["down_degrees"] == pytest.approx(30.0, abs=0.01)
    assert rows[-1]["gap_above"] is None
    assert rows[-1]["up_degrees"] == pytest.approx(-30.0, abs=0.01)


def test_the_mistake_the_generator_makes_is_caught():
    """Pushers out, jacks left alone: the tilts are simply not possible."""
    push = np.zeros((30, 10)); push[10:20] = 0.8
    tilt = np.zeros((30, 50)); tilt[10:20] = 0.3          # 27 degrees
    said = bridge.check(lift=1, push=push, tilt=tilt)
    assert not said["legal"]
    assert said["cells_over_limit"] == 500
    assert said["worst"][0]["allowed_degrees"] == pytest.approx(10.0, abs=0.01)
    assert "gap" in said["worst"][0]["held_by"]


def test_fitting_raises_the_jacks_rather_than_flattening_the_shape():
    push = np.zeros((30, 10)); push[10:20] = 0.8
    tilt = np.zeros((30, 50)); tilt[10:20] = 0.3
    fitted = bridge.fit(lift=1, push=push, tilt=tilt)
    assert fitted["check"]["legal"]
    assert fitted["changed"]["tilt"] == 0          # the shape is kept whole
    assert fitted["changed"]["lift"] > 0
    assert "raised" in " ".join(fitted["notes"])
    # Rings 11 to 20 tilt face down, so the gap under each of them opens.
    lift = np.array(fitted["pose"]["lift"])
    assert lift[10:20].min() >= 2
    assert set(np.unique(lift)) <= {0.0, 1.0, 2.0, 3.0}


def test_fitting_may_be_told_to_clamp_instead():
    tilt = np.zeros((30, 50)); tilt[10:20] = 0.3
    fitted = bridge.fit(lift=1, push=0.0, tilt=tilt, may_change=["tilt"])
    assert fitted["check"]["legal"]
    assert fitted["changed"]["lift"] == 0
    assert np.abs(np.array(fitted["pose"]["tilt"])).max() == pytest.approx(10 / 90, abs=1e-6)


def test_fitting_pushes_out_only_for_a_swing_the_beam_would_stop():
    small = bridge.fit(lift=3, push=0.0, tilt=0.3)       # 27 degrees
    assert small["changed"]["push"] == 0
    wide = bridge.fit(lift=3, push=0.0, tilt=0.5)        # 45
    assert np.array(wide["pose"]["push"]).min() == pytest.approx(0.2, abs=1e-6)
    assert wide["check"]["legal"]


def test_a_fitted_pose_is_never_pulled_back_in():
    rng = np.random.default_rng(7)
    push = rng.random((30, 10))
    tilt = (rng.random((30, 50)) - 0.5)
    fitted = bridge.fit(lift=0, push=push, tilt=tilt)
    assert np.array(fitted["pose"]["push"]).min() >= -1e-9
    # A hair of slack: a pose comes back rounded to six places for the wire.
    assert (np.array(fitted["pose"]["push"]) >= push - 1e-6).all()
    assert fitted["check"]["legal"]


# -- the piece in time ---------------------------------------------------------

def test_keys_write_and_read_back():
    one = bridge.Session()
    one.new(seconds=5)
    one.key(0, push=0.0, tilt=0.0)
    one.key(180, push=0.6, tilt=0.3)
    read = one.pose_at(180)
    assert read["check"]["legal"]
    assert np.array(read["pose"]["push"]).max() == pytest.approx(0.6, abs=1e-5)
    assert one.summary()["frames"] == 300


def test_keying_raises_the_jacks_the_tilt_needs():
    one = bridge.Session()
    one.new(seconds=5)
    one.key(120, tilt=0.4)                     # 36 degrees, needs state 2
    assert np.array(one.pose_at(120)["pose"]["lift"])[10] >= 2
    assert one.pose_at(120)["check"]["legal"]


def test_moves_butted_together_are_dropped_and_planning_fixes_it():
    one = bridge.Session()
    one.new(seconds=10)
    for at, value in ((0, 0.0), (6, 0.9), (12, 0.0), (18, 0.9)):
        one.key(at, push=value, fit_first=False)
    raw = one.simulate(plan=False)
    assert raw["dropped"] > 0
    assert "thrown away" in " ".join(raw["advice"])
    assert one.simulate(plan=True)["dropped"] == 0


def test_export_writes_houdinis_own_layout():
    one = bridge.Session()
    one.new(seconds=4)
    one.key(0, push=0.0)
    one.key(150, push=0.5, tilt=0.2)
    OUT.mkdir(parents=True, exist_ok=True)
    written = one.export(OUT / "exported.json")
    data = json.loads(Path(written["written"]).read_text(encoding="utf-8"))
    assert data["type"] == "kinematic_preset"
    assert list(data["data"]) == [f"row_{n}" for n in range(1, 31)]
    assert set(data["data"]["row_1"]) == {"pusher", "tilt", "jack"}
    assert "jack" not in data["data"]["row_30"]
    assert len(data["data"]["row_1"]["pusher"]) == 10
    assert len(data["data"]["row_1"]["tilt"]) == 50
    first = data["data"]["row_1"]["pusher"]["id_1"][0]
    assert set(first) == {"frame", "start", "dest", "length"}


def test_a_motor_file_goes_in_and_comes_back_out():
    one = bridge.Session()
    one.new(seconds=4)
    one.key(0, push=0.0)
    one.key(120, push=0.4)
    OUT.mkdir(parents=True, exist_ok=True)
    path = Path(one.export(OUT / "round.json")["written"])
    two = bridge.Session()
    opened = two.open(path)
    assert opened["frames"] > 0
    assert two.pose_at(120)["pose"]["push"][0][0] == pytest.approx(0.4, abs=1e-3)


# -- the picture ---------------------------------------------------------------

@pytest.fixture(scope="module")
def studio():
    try:
        return bridge.Studio()
    except Exception as error:                  # noqa: BLE001 -- no card, no test
        pytest.skip(f"no graphics card here: {error}")


def test_a_pose_draws_from_the_file_camera(studio):
    pose = bridge.pose_from(lift=2, push=0.7, tilt=0.0)
    image = studio.draw(pose, 270, 480, view="camera", mark_over_limit=False)
    assert image.shape == (480, 270, 4)
    assert image[..., :3].max() > 32                 # something is lit


def test_the_honeycomb_can_be_looked_at_on_its_own(studio):
    pose = bridge.pose_from(lift=2, push=0.7, tilt=0.2)
    image = studio.draw(pose, 320, 320, view="honeycomb", pieces="honeycomb",
                        paint="push")
    assert image[..., :3].max() > 32


def test_cells_past_their_limit_are_marked_red(studio):
    tilt = np.zeros((30, 50)); tilt[10:20] = 0.3
    bad = bridge.pose_from(lift=1, push=0.8, tilt=tilt)
    good = bridge.pose_from(**{k: np.asarray(v) for k, v in
                               bridge.fit(1, 0.8, tilt)["pose"].items()})
    reds = []
    for pose in (bad, good):
        image = studio.draw(pose, 320, 320, view="honeycomb",
                            pieces="honeycomb", mark_over_limit=True)
        rgb = image[..., :3].astype(np.int16)
        reds.append(int(((rgb[..., 0] > 110) & (rgb[..., 0] - rgb[..., 1] > 50)
                         & (rgb[..., 0] - rgb[..., 2] > 50)).sum()))
    assert reds[0] > 500, reds
    assert reds[1] * 10 < reds[0], reds


def test_a_picture_can_be_put_on_a_screen(studio):
    green = np.zeros((64, 64, 4), np.uint8)
    green[..., 1] = 255
    green[..., 3] = 255
    studio.put_picture("Screen_Bottom", green)
    image = studio.draw(bridge.pose_from(), 270, 480, view="camera",
                        mark_over_limit=False)
    rgb = image[..., :3].astype(np.int16)
    assert int(((rgb[..., 1] - rgb[..., 0] > 40)
                & (rgb[..., 1] - rgb[..., 2] > 40)).sum()) > 2000


# -- the facts the documents state --------------------------------------------

def test_a_pusher_carries_five_cells_in_a_row():
    push = np.zeros((30, 10))
    push[0, 2] = 1.0                              # pusher id_3 of ring 1
    spread = bridge.km.spread("push", push)
    assert list(np.nonzero(spread[0])[0] + 1) == [11, 12, 13, 14, 15]


def test_cells_sit_where_the_documents_say():
    azimuths = np.array(bridge.cell_azimuths())
    assert azimuths[0, 0] == pytest.approx(59.6, abs=0.01)     # row 1, odd
    assert azimuths[1, 0] == pytest.approx(77.6, abs=0.01)     # row 2, even
    assert azimuths[0, 1] - azimuths[0, 0] == pytest.approx(7.2, abs=0.001)
    assert azimuths.shape == (30, 50)


def test_rings_stand_a_pitch_apart_and_rise_with_their_jacks():
    at_rest = np.array(bridge.ring_heights(1))
    assert at_rest[1] - at_rest[0] == pytest.approx(0.278, abs=1e-6)
    raised = np.array(bridge.ring_heights(3))
    assert (raised[1:] > at_rest[1:]).all()       # the bottom ring never moves
    assert raised[0] == pytest.approx(at_rest[0], abs=1e-9)


def test_a_silhouette_never_overshoots_its_widest_point():
    curve = np.array(bridge.profile([(0, 0.05), (0.5, 1.0), (1, 0.1)])["per_ring"])
    assert curve.max() <= 1.0 + 1e-9
    assert len(curve) == 30


def test_auto_tilt_turns_a_widening_shape_face_down():
    widening = np.repeat(np.linspace(0.0, 0.8, 30)[:, None], 10, axis=1)
    tilt = np.array(bridge.auto_tilt(lift=1, push=widening)["tilt"])
    assert tilt[10:20].mean() > 0                 # positive is face down


def test_an_old_cinema_4d_file_says_so_when_it_is_opened(tmp_path):
    """Those files number the jacks a ring higher, so row 30 moves in them."""
    one = bridge.Session()
    one.new(seconds=4)
    one.key(0, push=0.0)
    path = Path(one.export(tmp_path / "c4d.json")["written"])
    data = json.loads(path.read_text(encoding="utf-8"))
    data["data"]["row_30"]["jack"] = {
        "id_1": [{"frame": 0, "start": 1, "dest": 2, "length": 60}]}
    path.write_text(json.dumps(data, indent=4), encoding="utf-8")

    notes = bridge.Session().open(path)["notes"]
    assert any("row 30" in note for note in notes), notes
    assert any("Cinema 4D" in note for note in notes), notes
    # And in English, whatever the editor's window is set to.
    assert not any("р" in note for note in notes), notes


def test_the_speeds_quoted_are_the_simulator_s_own():
    """So a document can never drift from the thing it describes."""
    import kin_sim
    import kinetic
    motors = bridge.machine()["motors"]
    for family, name in (("lift", "jack"), ("push", "pusher")):
        travel, rest = kin_sim.PACE[family]
        assert motors[name]["full_travel_seconds"] == travel
        assert motors[name]["rest_seconds"] == rest
    assert motors["jack"]["states_along_travel"] == list(kin_sim.LIFT_TRAVEL)
    # The tilt is quoted over the range it actually has, as the specification
    # states it: 1.5 s from -30 to +30.
    assert motors["tilt"]["whole_range_seconds"] == pytest.approx(1.5, abs=1e-6)
    assert motors["tilt"]["reaches_degrees"] == [-30.0, 30.0]
    assert motors["tilt"]["speed_is_linear"] is False


def test_one_jack_frees_the_ring_above_it_and_the_ring_below():
    """The crux of the document: for ring R the gap below is jack row R-1
    and the gap above is jack row R."""
    lift = np.zeros(30)
    lift[5] = 3.0                                  # the jack of file row 5
    rows = bridge.limits(lift=lift, push=1.0)["rows"]
    at = {row["row"]: row for row in rows}
    assert at[5]["up_degrees"] == pytest.approx(-30.0, abs=0.01)
    assert at[5]["down_degrees"] == pytest.approx(2.0, abs=0.01)
    assert at[6]["down_degrees"] == pytest.approx(30.0, abs=0.01)
    assert at[6]["up_degrees"] == pytest.approx(-2.0, abs=0.01)
    for other in (4, 7):
        assert at[other]["down_degrees"] == pytest.approx(2.0, abs=0.01)
        assert at[other]["up_degrees"] == pytest.approx(-2.0, abs=0.01)


def test_a_tilt_crosses_its_whole_range_in_the_time_the_spec_says():
    """And the number in PACE is that time, not a figure needing conversion."""
    import numpy as np
    import kin_sim
    import kin_model as kmod
    piece = kmod.Project(length=600)
    track = piece.tracks["tilt"]
    only = np.zeros(track.size, bool)
    only[0] = True
    track.write(0, np.full(track.size, -1 / 3), only)
    track.write(1, np.full(track.size, 1 / 3), only)      # asked for at once
    late = [one for one in kin_sim.simulate(piece).late if one.family == "tilt"]
    assert late, "the motor should report it cannot be there that fast"
    took = (late[0].arrives - late[0].frame) / kmod.FPS
    assert took == pytest.approx(kin_sim.PACE["tilt"][0], abs=0.02)
    assert kin_sim.PACE["tilt"][0] == 1.5
