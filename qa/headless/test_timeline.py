"""The show mode's own arithmetic, without a window: loops, and chains laid out.

`ShowView` is what the strips share -- where the playhead is, the loops and
whether one is holding -- and `show.chained` is how the rows and a 0.3 chain
become a show. Both are asked here with numbers alone.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import show as showfile
import timeline

PARTS = [Path(r"D:\Content\2026-dates\BrendMT\BrendMT_1_of_2.json"),
         Path(r"D:\Content\2026-dates\BrendMT\BrendMT_2_of_2.json")]


def viewed(loops) -> timeline.ShowView:
    view = timeline.ShowView()
    view.open(showfile.Show(length=79200, loops=list(loops)))
    return view


def play(view, start: float, frames: int, step: float = 1.0) -> list:
    """Where the playhead goes, a step at a time, from `start`."""
    at, been = float(start), []
    for _ in range(frames):
        now = at + step
        jump = view.step(at, now)
        at = now if jump is None else jump
        view.set_frame(at)
        been.append(at)
    return been


def test_crossing_a_loop_from_the_left_lights_it_and_it_holds():
    view = viewed([(800, 1099)])
    been = play(view, 790, 900)
    assert view.looping, "the playhead drove in and LOOP stayed dark"
    assert max(been) < 1099 and min(been[20:]) >= 800, (
        "the loop let the playhead out by itself")


def test_a_big_step_does_not_jump_over_the_far_edge():
    """A tick of a whole second is looked up where the playhead was."""
    view = viewed([(800, 1099)])
    been = play(view, 790, 60, step=37.0)
    assert all(800 <= one < 1099 for one in been[1:]), been[:8]


def test_starting_inside_a_loop_does_not_light_it():
    view = viewed([(800, 1099)])
    been = play(view, 900, 300)
    assert not view.looping
    assert been[-1] > 1099, "a scrub into the middle of a wait became a wait"


def test_let_go_by_hand_the_playhead_leaves_and_the_next_one_catches():
    view = viewed([(800, 1099), (2000, 2100)])
    play(view, 790, 50)
    assert view.looping
    view.set_looping(False)                  # the hand on the switch
    been = play(view, view.frame, 1400)
    assert max(been) >= 2000, "let go, the playhead never left the first loop"
    assert view.looping, "the second loop did not catch the playhead"
    assert all(one < 2100 for one in been), "the second loop let it through"


def test_the_switch_by_hand_holds_a_loop_it_is_standing_in():
    view = viewed([(800, 1099)])
    view.set_frame(900)
    view.set_looping(True)
    been = play(view, 900, 400)
    assert max(been) < 1099


# -- the rows and a 0.3 chain, as a show -------------------------------------

def test_a_movie_played_over_is_that_many_copies_one_after_another(clips):
    got = showfile.media_frames(str(clips["top"]))
    show = showfile.chained({"Top": [(str(clips["top"]), 3),
                                     (str(clips["bottom"]), 1)]})
    placed = [(one.name, one.tx) for one in show.on("Top")]
    assert placed == [("qa_top.mov", 0), ("qa_top.mov", got),
                      ("qa_top.mov", 2 * got), ("qa_bottom.mov", 3 * got)]
    assert show.length == 3 * got + showfile.media_frames(str(clips["bottom"]))


def test_a_picture_in_a_chain_stands_its_count_in_seconds(tmp_path, clips):
    from PySide6.QtGui import QImage
    picture = tmp_path / "still.png"
    QImage(8, 8, QImage.Format.Format_RGBA8888).save(str(picture))
    show = showfile.chained({"Top": [(str(picture), 2),
                                     (str(clips["top"]), 1)]})
    still, movie = show.on("Top")
    assert still.still and still.last == int(2 * showfile.FPS)
    assert movie.tx == still.last
    # Alone on its row, as dropped on the quick look, it stands for good.
    alone = showfile.chained({"Top": [(str(picture), 1)],
                              "Bottom": [(str(clips["bottom"]), 1)]})
    assert alone.on("Top")[0].until == showfile.FOREVER
    assert alone.length == showfile.media_frames(str(clips["bottom"]))


@pytest.mark.skipif(not all(one.exists() for one in PARTS),
                    reason="the two-part show is not on this machine")
def test_motor_parts_follow_where_the_one_before_ends():
    show = showfile.chained({"Kinetic": [(str(one), 1) for one in PARTS]})
    first, second = show.on("Kinetic")
    # Where the chain of motors puts the second part: the first part's own
    # length on, which is its frames less the one that closes it.
    import kinetic
    assert second.tx == kinetic.Motors([str(one) for one in PARTS]).parts[1].first
    assert second.tx == first.frames - 1
