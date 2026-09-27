"""A WAV alongside the picture: heard while watching, written into the render.

Read here rather than through ffmpeg because a WAV is PCM with a header on it
and the standard library already opens one. That keeps sound working on a
machine with no ffmpeg, which is the same machine that can watch but not write.

Played through a device of our own rather than a media player, because the
clock is the thing everything follows and a media player wants to keep its own.
Here a seek is an index into a buffer, so scrubbing lands where it is told
instead of somewhere near.
"""
from __future__ import annotations

import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import QIODevice
from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices


class SoundError(Exception):
    """The file is not a WAV this can read."""


@dataclass
class Track:
    """One sound, as signed 16-bit frames."""

    path: Path
    rate: int
    channels: int
    pcm: bytes                       # interleaved Int16

    @property
    def block(self) -> int:
        """Bytes for one frame across all channels."""
        return self.channels * 2

    @property
    def frames(self) -> int:
        return len(self.pcm) // self.block

    @property
    def duration(self) -> float:
        return self.frames / self.rate if self.rate else 0.0

    def describe(self) -> str:
        kind = {1: "mono", 2: "stereo"}.get(self.channels, f"{self.channels} ch")
        return f"{self.rate / 1000:g} kHz  {kind}  {self.duration:.2f} s"

    @property
    def size(self) -> int:
        """Bytes of sound there are. Past this is silence."""
        return len(self.pcm)

    def read(self, at: int, wanted: int) -> bytes:
        """`wanted` bytes from byte `at`, shorter at the end."""
        return self.pcm[at:at + wanted]


class Mix:
    """Several sounds laid on one timeline and added, as one track.

    A show has two sound tracks running at once in 39 of its 40 files, and
    what the square hears is both. So they are added -- the same as the
    pictures -- and handed to the card and to ffmpeg as one.

    Added as they are read rather than all at once. The whole of a 22 minute
    show in stereo is 253 MB of sound at sixteen bits and twice that in the
    wider numbers the adding needs, most of it silence or one track alone,
    for a card that asks for a few kilobytes at a time. Here a read is the
    handful of pieces that overlap it, added and clipped, and nothing else is
    held but the files themselves -- which were being held already.

    It wears a Track's surface -- rate, channels, block, frames, duration,
    size, read -- so the Player plays it without knowing, and `write` puts it
    in a file for the render, which gives ffmpeg a path.
    """

    CHUNK = 48000 * 10          # frames written at a time: ten seconds

    def __init__(self, pieces, seconds: float, rate: int = 48000,
                 channels: int = 2) -> None:
        """`pieces` is a list of (Track, start in seconds, gain)."""
        self.rate = int(rate)
        self.channels = int(channels)
        self.total = max(0, int(round(float(seconds) * self.rate)))
        self.path = None                 # set once written for a render
        self.notes: list = []            # anything worth a line in the log
        self._pieces = []
        for track, start, gain in pieces:
            samples = self._fitted(track)
            offset = int(round(float(start) * self.rate))
            self._pieces.append((samples, offset, float(gain)))
        self.names = [Path(getattr(track, "path", "") or "").name
                      for track, _, _ in pieces]

    def _fitted(self, track):
        """A track's samples as (frames, channels) at this mix's rate."""
        raw = np.frombuffer(track.pcm, dtype="<i2")
        samples = raw.reshape(-1, track.channels)
        name = Path(getattr(track, "path", "") or "").name
        if track.channels != self.channels:
            if track.channels == 1:
                samples = np.repeat(samples, self.channels, axis=1)
            elif self.channels == 1:
                samples = samples.mean(axis=1, keepdims=True).astype(np.int16)
            else:
                samples = samples[:, :self.channels]
            self.notes.append(f"{name}: {track.channels} channels made "
                              f"{self.channels}")
        if track.rate != self.rate and len(samples):
            # Linear, which is enough for hearing where things fall and not
            # enough for a master. Every sound in the forty shows is 48 kHz,
            # so this is for the file that turns up one day and is not.
            wanted = int(round(len(samples) * self.rate / track.rate))
            source = np.arange(len(samples)) / track.rate
            target = np.arange(wanted) / self.rate
            samples = np.stack(
                [np.interp(target, source, samples[:, one])
                 for one in range(samples.shape[1])], axis=1
            ).round().clip(-32768, 32767).astype(np.int16)
            self.notes.append(f"{name}: {track.rate} Hz resampled to "
                              f"{self.rate} Hz, linearly")
        return samples

    # -- a Track's surface ---------------------------------------------------

    @property
    def block(self) -> int:
        return self.channels * 2

    @property
    def frames(self) -> int:
        return self.total

    @property
    def duration(self) -> float:
        return self.total / self.rate if self.rate else 0.0

    @property
    def size(self) -> int:
        return self.total * self.block

    def describe(self) -> str:
        kind = {1: "mono", 2: "stereo"}.get(self.channels, f"{self.channels} ch")
        return (f"{len(self._pieces)} sounds added  {self.rate / 1000:g} kHz  "
                f"{kind}  {self.duration:.2f} s")

    def samples(self, first: int, count: int) -> np.ndarray:
        """Frames `first` to `first + count` of the mix, as Int16."""
        count = max(0, min(count, self.total - first))
        added = np.zeros((count, self.channels), dtype=np.int32)
        for samples, offset, gain in self._pieces:
            low = max(first, offset)
            high = min(first + count, offset + len(samples))
            if low >= high:
                continue
            part = samples[low - offset:high - offset]
            if gain != 1.0:
                part = (part.astype(np.float32) * gain).round()
            added[low - first:high - first] += part.astype(np.int32)
        return added.clip(-32768, 32767).astype("<i2")

    def read(self, at: int, wanted: int) -> bytes:
        # Whole frames only, and from a whole frame: the card asks in bytes,
        # and half a stereo frame is a channel swapped for the rest of the
        # piece.
        first = max(0, at) // self.block
        count = max(0, wanted) // self.block
        return self.samples(first, count).tobytes()

    def write(self, target: str | Path) -> Path:
        """The whole mix as a WAV, ten seconds at a time. For the render."""
        target = Path(target)
        with wave.open(str(target), "wb") as handle:
            handle.setnchannels(self.channels)
            handle.setsampwidth(2)
            handle.setframerate(self.rate)
            for first in range(0, self.total, self.CHUNK):
                handle.writeframes(self.samples(first, self.CHUNK).tobytes())
        self.path = target
        return target


def mix_show(show, fps: float = 60.0, rate: int = 48000,
             channels: int = 2) -> Mix:
    """Every sound clip of a show, read and laid where the show puts it."""
    pieces, notes = [], []
    for clip in show.clips:
        if clip.kind != "audio" or clip.missing:
            continue
        try:
            track = read_wav(clip.path)
        except SoundError as error:
            notes.append(str(error))
            continue
        pieces.append((track, clip.tx / fps, 1.0))
    mixed = Mix(pieces, show.length / fps, rate, channels)
    mixed.notes[:0] = notes
    return mixed


def read_wav(path: str | Path) -> Track:
    """A WAV as Int16 frames, whatever width it was written at.

    Everything is brought to Int16 because that is what gets handed to the
    card and what gets handed to ffmpeg, and converting once here beats
    deciding again at each of them.
    """
    path = Path(path)
    try:
        with wave.open(str(path), "rb") as handle:
            channels = handle.getnchannels()
            width = handle.getsampwidth()
            rate = handle.getframerate()
            raw = handle.readframes(handle.getnframes())
    except wave.Error as error:
        raise SoundError(f"{path.name}: {error}") from error
    except OSError as error:
        raise SoundError(f"{path.name} will not open ({error})") from error

    if not channels or not rate:
        raise SoundError(f"{path.name} does not say how it was recorded")

    if width == 2:
        samples = np.frombuffer(raw, dtype="<i2")
    elif width == 1:
        # Eight-bit WAV is unsigned, and centred on 128 rather than zero.
        samples = (np.frombuffer(raw, dtype=np.uint8).astype(np.int16) - 128) << 8
    elif width == 3:
        # Three bytes a sample, little endian, no numpy type for it: the top
        # two bytes of each are the sixteen bits wanted.
        trio = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
        samples = (trio[:, 1].astype(np.int16)
                   | (trio[:, 2].astype(np.int8).astype(np.int16) << 8))
    elif width == 4:
        samples = (np.frombuffer(raw, dtype="<i4") >> 16).astype(np.int16)
    else:
        raise SoundError(f"{path.name} is {width * 8}-bit, which this cannot read")

    return Track(path, rate, channels,
                 np.ascontiguousarray(samples, dtype="<i2").tobytes())


class Feed(QIODevice):
    """What the sound card pulls from: a position in the track, and silence
    past its end.

    Silence rather than stopping, because the card stopping is a state to get
    out of again, and the clock may still be running -- the sound has ended,
    the piece has not.
    """

    def __init__(self, track: Track) -> None:
        super().__init__()
        self.track = track
        self.at = 0

    def readData(self, wanted: int) -> bytes:  # noqa: N802 -- Qt naming
        piece = self.track.read(self.at, wanted)
        self.at += len(piece)
        if len(piece) < wanted:
            piece += bytes(wanted - len(piece))
        return piece

    def writeData(self, data) -> int:  # noqa: N802 -- Qt naming
        return 0

    def bytesAvailable(self) -> int:  # noqa: N802 -- Qt naming
        # Never zero. Reporting nothing left is how a device tells the card it
        # is done, and the card then idles and stops counting -- which froze
        # the timeline at the end of the sound rather than at the end of the
        # piece. There is always more here, because silence is more.
        left = self.track.size - self.at
        return max(left, self.track.rate * self.track.block)             + super().bytesAvailable()

    def isSequential(self) -> bool:  # noqa: N802 -- Qt naming
        return True


class Player:
    """One track, and the clock everything else keeps to.

    The sound leads rather than follows. A picture arriving a few milliseconds
    early is invisible; a gap in the sound is not, so the thing that must not
    be interfered with is the one that gets to say what time it is.

    An earlier version had this the other way round and pulled the playhead
    whenever it seemed to have drifted. It seemed to drift constantly -- 99
    corrections in 8 seconds -- because what was being compared to the clock
    was how much had been handed to the card, not how much had come out of it.
    Those differ by the card's buffer, a quarter of a second here, and the
    difference wanders. Every correction was a jump in the sound, and none of
    them were fixing anything.
    """

    def __init__(self, track: Track) -> None:
        self.track = track
        shape = QAudioFormat()
        shape.setSampleRate(track.rate)
        shape.setChannelCount(track.channels)
        shape.setSampleFormat(QAudioFormat.SampleFormat.Int16)

        device = QMediaDevices.defaultAudioOutput()
        if device is None or device.isNull():
            raise SoundError("this machine has no audio output")
        if not device.isFormatSupported(shape):
            raise SoundError(
                f"the sound card will not take {track.rate / 1000:g} kHz "
                f"{track.channels}-channel audio")

        self.sink = QAudioSink(device, shape)
        self.feed = Feed(track)
        self.feed.open(QIODevice.OpenModeFlag.ReadOnly)
        self.playing = False
        self.started = False
        # Where the playhead was when the card last picked up, and what it had
        # processed by then: together these turn its own counter into a
        # position in the track.
        self.head = 0.0              # where playing is meant to carry on from
        self.origin = 0.0
        self.origin_processed = 0.0

    # -- what the window asks for ---------------------------------------------

    def set_volume(self, level: float) -> None:
        self.sink.setVolume(max(0.0, min(1.0, float(level))))

    @property
    def handed_over(self) -> float:
        """How much has been given to the card. Ahead of what is heard."""
        return self.feed.at / (self.track.rate * self.track.block)

    @property
    def played(self) -> float | None:
        """Where in the track the sound actually is, as the card counts it.

        Measured every 16 ms this advances in clean steps of ten to twenty
        milliseconds, never stalls, and wanders from a straight line by three
        milliseconds. That is a fifth of a frame at sixty a second, which is
        why it can be handed the whole timeline to keep.

        None once the sound has run out. Past its own end it has no opinion
        about what time it is, and a piece longer than its soundtrack has to
        go on running.
        """
        at = self.origin + (self.sink.processedUSecs() / 1e6
                            - self.origin_processed)
        return None if at > self.track.duration else at

    def _remember(self, seconds: float) -> None:
        self.origin = max(0.0, seconds)
        self.origin_processed = self.sink.processedUSecs() / 1e6

    def move_to(self, seconds: float) -> None:
        frame = int(max(0.0, seconds) * self.track.rate)
        self.feed.at = min(self.track.size, frame * self.track.block)
        self.head = max(0.0, seconds)
        self._remember(self.head)

    def play(self) -> None:
        if self.playing:
            return
        # From where playing was asked to carry on, not from how much has been
        # handed over: starting the card fills its buffer at once, and taking
        # that as the position put the whole timeline a quarter of a second
        # ahead of the first sound anybody heard.
        self._remember(self.head)
        self.playing = True
        if not self.started:
            self.sink.start(self.feed)
            self.started = True
        else:
            self.sink.resume()

    def pause(self) -> None:
        if not self.playing:
            return
        at = self.played
        self.playing = False
        self.sink.suspend()
        if at is not None:
            self.head = at

    def stop(self) -> None:
        self.playing = False
        try:
            self.sink.stop()
        except Exception:  # noqa: BLE001 -- going away regardless
            pass
