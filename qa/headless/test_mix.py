"""Sounds added on one timeline, read the way the card and the render read.

No sound card is needed: a Mix is numbers until a Player hands them over, and
the Player is unchanged apart from asking `read` instead of slicing.
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import pytest

import show as showfile
import sound

RUSDAY = Path(r"D:\Content\_SHOW"
              r"\2026-Daily-RusDay-Matreshka_Day-MuzeyTransporta-v001.trix")


def tone(frames: int, level: int, channels: int = 2, rate: int = 48000,
         name: str = "tone.wav") -> sound.Track:
    samples = np.full((frames, channels), level, dtype="<i2")
    return sound.Track(Path(name), rate, channels, samples.tobytes())


def frames_of(raw: bytes, channels: int = 2) -> np.ndarray:
    return np.frombuffer(raw, dtype="<i2").reshape(-1, channels)


def test_a_track_reads_what_it_always_sliced():
    one = tone(100, 7)
    assert one.read(8, 40) == one.pcm[8:48]
    assert one.size == len(one.pcm)


def test_two_sounds_add_where_they_meet_and_are_silent_between():
    # 1 s of +1000 from 0, 1 s of +500 from 0.5 s, and a 3 s timeline.
    mixed = sound.Mix([(tone(48000, 1000), 0.0, 1.0),
                       (tone(48000, 500), 0.5, 1.0)], 3.0)
    got = frames_of(mixed.read(0, mixed.size))
    assert len(got) == 3 * 48000
    assert (got[:24000] == 1000).all(), "the first alone"
    assert (got[24000:48000] == 1500).all(), "the two added"
    assert (got[48000:72000] == 500).all(), "the second alone"
    assert (got[72000:] == 0).all(), "silence after both"


def test_adding_past_the_top_clips_rather_than_wrapping():
    mixed = sound.Mix([(tone(100, 30000), 0.0, 1.0),
                       (tone(100, 30000), 0.0, 1.0)], 100 / 48000)
    assert (frames_of(mixed.read(0, mixed.size)) == 32767).all()


def test_a_read_from_anywhere_equals_the_whole_mix_cut_there():
    """The card asks in odd-sized pieces from wherever the playhead is."""
    mixed = sound.Mix([(tone(48000, 1000), 0.0, 1.0),
                       (tone(48000, 500), 0.5, 1.0)], 2.0)
    whole = mixed.read(0, mixed.size)
    for at, wanted in ((0, 4), (95996, 16), (95998, 7), (12345 * 4, 3000)):
        start = at // 4 * 4
        assert mixed.read(at, wanted) == whole[start:start + wanted // 4 * 4]


def test_a_mono_sound_is_heard_in_both_ears():
    mixed = sound.Mix([(tone(10, 900, channels=1), 0.0, 1.0)], 10 / 48000)
    got = frames_of(mixed.read(0, mixed.size))
    assert (got == 900).all() and got.shape == (10, 2)
    assert any("channels" in note for note in mixed.notes)


def test_a_sound_at_another_rate_lands_at_the_right_length():
    mixed = sound.Mix([(tone(44100, 100, rate=44100), 0.0, 1.0)], 1.0)
    got = frames_of(mixed.read(0, mixed.size))
    assert abs(int((got[:, 0] != 0).sum()) - 48000) <= 1
    assert any("resampled" in note for note in mixed.notes)


def test_the_render_gets_a_file_with_exactly_the_mix_in_it(tmp_path):
    mixed = sound.Mix([(tone(48000, 1000), 0.0, 1.0),
                       (tone(48000, 500), 0.5, 1.0)], 25.0)
    target = mixed.write(tmp_path / "mix.wav")
    with wave.open(str(target), "rb") as handle:
        assert handle.getframerate() == 48000
        assert handle.getnchannels() == 2
        written = handle.readframes(handle.getnframes())
    assert written == mixed.read(0, mixed.size)
    assert mixed.path == target


@pytest.mark.skipif(not RUSDAY.exists(), reason="the RusDay show is not here")
def test_the_show_is_heard_as_one_track():
    one = showfile.read(RUSDAY)
    mixed = sound.mix_show(one)
    assert abs(mixed.duration - one.length / 60) < 1e-6
    # Five sounds in that show, all of them here.
    assert len(mixed.names) == 5, mixed.names
    # Before the first sound (it starts at 1100): silence. In the crossfade
    # window both sound tracks are running, and something is heard.
    quiet = frames_of(mixed.read(int(10 * 48000) * 4, 4800 * 4))
    assert not quiet.any()
    loud = frames_of(mixed.read(int(11742 / 60 * 48000) * 4, 4800 * 4))
    assert np.abs(loud).max() > 0
