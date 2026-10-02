"""Tracks: clips placed at frames, played the way the window will play them.

No window: a track hands out frames on its own, so it is asked directly, the
way the drawing side and the writer ask -- `take` for watching, `exact` for a
render. The small clips in qa/media are 60 frames each and of three different
sizes, which is what a join between two shapes needs.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import player
import show as showfile

RUSDAY = Path(r"D:\Content\_SHOW"
              r"\2026-Daily-RusDay-Matreshka_Day-MuzeyTransporta-v001.trix")


def clip(path, tx, ident=1, level=0, **more):
    return showfile.Clip(kind="video", row="Top", level=level, path=str(path),
                         tx=tx, frames=60, ident=ident, **more)


def walk(track, frames):
    """Every frame the way a render asks for them. (frame, label or None)."""
    held, seen = None, []
    for frame in frames:
        got = track.exact(frame, held, timeout=10.0)
        if track.showing(frame) is None:
            seen.append((frame, None))
            continue
        if got is not None and held is not None and got is not held:
            track.give_back(held)
        if got is not None:
            held = got
        seen.append((frame, held.index if held is not None else None))
    return seen


def test_a_gap_is_nothing_at_all(clips):
    track = player.Track([clip(clips["top"], 0),
                          clip(clips["top"], 100, ident=2)])
    try:
        assert track.showing(30) is track.clips[0]
        assert track.showing(80) is None, "a gap showed a clip"
        assert track.showing(120) is track.clips[1]
        assert track.take(80, None) is None
        assert track.opacity_at(80) == 0.0
        assert abs(track.duration - 160 / 60) < 1e-9
    finally:
        track.stop()


def test_every_frame_is_labelled_with_its_place_in_the_show(clips):
    """Clip frames start again at zero; the labels must not."""
    track = player.Track([clip(clips["top"], 0),
                          clip(clips["top"], 100, ident=2)])
    try:
        seen = walk(track, range(0, 160))
        for frame, label in seen:
            if 60 <= frame < 100:
                assert label is None, f"frame {frame} is in the gap"
            else:
                assert label == frame, f"frame {frame} came out as {label}"
    finally:
        track.stop()


def test_no_more_than_two_clips_are_ever_open(clips):
    """Every open movie is a reader thread and a pool of full-size buffers."""
    track = player.Track([clip(clips["top"], at, ident=n)
                          for n, at in enumerate((0, 60, 120, 180, 240), 1)])
    try:
        most, held = 0, None
        for frame in range(0, 300):
            got = track.exact(frame, held, timeout=10.0)
            if got is not None and held is not None and got is not held:
                track.give_back(held)
            held = got or held
            most = max(most, track.open_now)
        assert most <= player.Track.LIVE, f"{most} clips were open at once"
    finally:
        track.stop()


def test_the_next_clip_is_open_before_its_frame(clips):
    """Opening a file on the frame it is due is a hitch where it shows most.

    After a gap as well: nothing is playing in a gap, and the clip coming in
    after a pause is exactly the one that would otherwise be opened late.
    """
    track = player.Track([clip(clips["top"], 0),
                          clip(clips["top"], 300, ident=2)])
    try:
        track.take(20, None)
        assert 1 not in track._live, "opened more than a second early"
        track.take(200, None)                    # in the gap, 100 frames out
        assert 1 not in track._live, "opened more than a second early"
        track.take(260, None)                    # in the gap, 40 frames out
        assert 1 in track._live, "not open before its frame, after a gap"
    finally:
        track.stop()


def test_a_track_opened_in_the_middle_starts_in_the_middle(clips):
    """Opened, a clip's reader stands on its frame zero. Asked for frame 40,
    it has to go there, not read on from zero until the wait runs out."""
    track = player.Track([clip(clips["top"], 0)])
    try:
        got = track.exact(40, None, timeout=10.0)
        assert got is not None and got.index == 40, got and got.index
    finally:
        track.stop()


def test_a_block_of_another_shape_asks_to_be_reshaped(clips):
    track = player.Track([clip(clips["top"], 0),
                          clip(clips["bottom"], 60, ident=2)])
    told = []
    track.on_change = lambda one: told.append((one.movie.width,
                                               one.movie.height))
    try:
        assert (track.movie.width, track.movie.height) == (256, 120)
        walk(track, range(0, 120))
        assert told == [(464, 160)], told
    finally:
        track.stop()


def test_a_cropped_tail_stops_the_picture_early(clips):
    track = player.Track([clip(clips["top"], 0, crop_end=-20)])
    try:
        assert track.showing(39) is not None
        assert track.showing(40) is None
        assert walk(track, [45]) == [(45, None)]
    finally:
        track.stop()


def test_a_screen_is_a_list_of_tracks_that_add(clips):
    one = showfile.Show(length=200, clips=[
        clip(clips["top"], 0, level=0),
        showfile.Clip(kind="video", row="Top", level=1, path=str(clips["top"]),
                      tx=30, frames=60, ident=2, fade_end=-20)])
    stack = player.Stack.of(one, "Top")
    try:
        assert len(stack.tracks) == 2
        assert [c.level for _, c, _ in stack.layers_at(10)] == [0]
        both = stack.layers_at(40)
        assert sorted(c.level for _, c, _ in both) == [0, 1]
        # Frame 80 is ten frames from the end of a twenty-frame fade.
        fading = next(level for _, c, level in stack.layers_at(80)
                      if c.level == 1)
        assert abs(fading - 10 / 20) < 1e-9
    finally:
        stack.stop()


@pytest.mark.skipif(not RUSDAY.exists(), reason="the RusDay show is not here")
def test_the_top_screen_at_the_crossfade():
    """Frame 11742 of the real show: two layers, and the right frames of each."""
    one = showfile.read(RUSDAY)
    stack = player.Stack.of(one, "Top")
    try:
        layers = stack.layers_at(11742)
        found = sorted((c.level, c.name, round(level, 4))
                       for _, c, level in layers)
        assert found == [
            (0, "RusDay_SHOW_Top_v02_2026-06-09.mov", 1.0),
            (1, "kinetic_screen_out_-100px.mov", round(98 / 120, 4))], found
        for track, c, _ in layers:
            got = track.exact(11742, None, timeout=20.0)
            assert got is not None, f"{c.name} gave no frame"
            assert got.index == 11742, f"{c.name} labelled {got.index}"
            track.give_back(got)
    finally:
        stack.stop()


# -- the window's tracks: nothing waits for the disk on its thread --------------------------

def _wait_for(what, within=10.0):
    import time
    ends = time.perf_counter() + within
    while time.perf_counter() < ends:
        got = what()
        if got:
            return got
        time.sleep(0.01)
    return what()


def test_a_slow_share_never_holds_the_drawing(clips, monkeypatch):
    """A clip on a share that takes a second to answer: the window's track
    hands the drawing nothing at once, and the frame when it is open."""
    import time
    opened = player.open_source

    def slow(path, screen=None):
        time.sleep(1.0)
        return opened(path, screen)

    track = player.Track([clip(clips["top"], 0),
                          clip(clips["top"], 100, ident=2)], later=True)
    monkeypatch.setattr(player, "open_source", slow)
    try:
        started = time.perf_counter()
        assert track.take(110, None) is None        # its first look: opening
        assert time.perf_counter() - started < 0.2
        got = _wait_for(lambda: track.take(110, None))
        assert got is not None and abs(got.index - 110) <= 2
    finally:
        track.stop()


def test_a_clip_that_will_not_open_is_not_asked_for_every_frame(clips, monkeypatch):
    import time
    asked = []

    def missing(path, screen=None):
        asked.append(path)
        raise FileNotFoundError(f"[Errno 2] No such file: {path}")

    track = player.Track([clip(clips["top"], 0),
                          clip(clips["top"], 100, ident=2)], later=True)
    monkeypatch.setattr(player, "open_source", missing)
    monkeypatch.setattr(player, "OPEN_AGAIN", 0.5)
    try:
        ends = time.perf_counter() + 0.4
        while time.perf_counter() < ends:
            assert track.take(110, None) is None
            time.sleep(1 / 60)
        assert len(asked) == 1, f"asked {len(asked)} times in a few frames"
        assert "No such file" in track.error
        time.sleep(0.5)
        _wait_for(lambda: track.take(110, None) is None and len(asked) >= 2, 2.0)
        assert len(asked) == 2, "never asked again"
    finally:
        track.stop()


def test_letting_go_never_waits_for_a_reader():
    import time

    class Stuck:
        stopped = False

        def ask_to_stop(self):
            pass

        def stop(self):
            time.sleep(2.0)                          # a read that will not end
            Stuck.stopped = True

    started = time.perf_counter()
    player.let_go([Stuck(), Stuck()])
    assert time.perf_counter() - started < 0.1
