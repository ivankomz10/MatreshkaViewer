"""Keeping three movies ahead of one clock.

Each movie is read by a thread of its own, which demuxes a packet and undoes
its packing straight into a buffer taken from a small pool. The drawing thread
then only has to hand finished blocks to the card. Unpacking three screens
costs about 3.7 ms of a 16.7 ms frame, and doing it here rather than there is
the difference between that cost overlapping the drawing and being added to it.

The clock is in seconds rather than frames on purpose: the three real files run
38.00, 38.00 and 39.35 seconds, and nothing says the next set will agree any
better. Each stream turns seconds into its own frame number at its own rate.

When a stream falls behind, the tempo is kept and frames are dropped -- time
goes on being true even when the picture skips. The alternative, slowing the
clock to show every frame, tells the truth about the content and lies about
its timing, which is the wrong way round for judging a thirty-eight second
piece meant to play at sixty.
"""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import av

import hapfile
import videofile


@dataclass
class Counts:
    """What the stream has been doing, for the window to show."""

    read: int = 0
    dropped: int = 0
    starved: int = 0
    skipped: int = 0
    unpack_ms: float = 0.0
    demux_ms: float = 0.0

    def note_unpack(self, milliseconds: float) -> None:
        # A running mean that forgets, so the number on screen is about now.
        self.unpack_ms += (milliseconds - self.unpack_ms) * 0.1

    def note_demux(self, milliseconds: float) -> None:
        self.demux_ms += (milliseconds - self.demux_ms) * 0.1


@dataclass
class Frame:
    """One frame's texture blocks, which frame it is, and when it was read.

    `mark` counts seeks. A frame carrying an older one than the stream's was
    read before somebody asked to be somewhere else, and answers a question
    nobody is asking any more.
    """

    index: int
    buffers: list[bytearray]
    mark: int = 0


class Still:
    """One picture, wearing everything a stream wears.

    A snapshot has no rate, no length and nothing to read ahead, so there is
    no thread here and no queue: the single frame is decoded when the file is
    opened and handed out once. It is given the same surface as `Stream` so
    that nothing above has to ask which of the two it is holding -- a still on
    one screen and a sixty-a-second HAP on the next both simply draw.
    """

    def __init__(self, path: str | Path, screen=None) -> None:
        self.movie = videofile.open_picture(path, screen)
        self.decodes = True
        self.counts = Counts()
        self.counts.read = 1
        self.error = ""
        self.at_end = False        # nothing to run out of
        self._frame = Frame(0, [self.movie.pixels])

    @property
    def rate(self) -> float:
        return 0.0

    @property
    def duration(self) -> float:
        return 0.0

    def index_at(self, seconds: float) -> int:
        return 0

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def seek(self, index: int) -> None:
        pass

    def take(self, wanted: int, holding: Frame | None) -> Frame | None:
        # Once, and then never again: handing it back every draw would upload
        # the same pixels sixty times a second and keep the window awake for
        # a picture that is not changing.
        return None if holding is not None else self._frame

    def exact(self, wanted: int, holding: Frame | None,
              should_stop=None, timeout: float = 30.0) -> Frame | None:
        # None once it is up, the same as `take`: the caller reads that as
        # "nothing newer, keep what you have". Handing the frame back every
        # time would re-upload the whole picture for every frame written.
        return None if holding is self._frame else self._frame

    def give_back(self, frame: Frame) -> None:
        pass                       # there is no pool; there is one frame


def open_source(path: str | Path, screen=None):
    """A stream for a movie, a still for a picture.

    `screen` is how many pixels the screen has, and only a still uses it: a
    movie is content made at a size and is taken at that size, while a picture
    is fitted to the screen it was dropped on.
    """
    return Still(path, screen) if videofile.is_still(path) else Stream(path)


class Stream:
    """One movie, read ahead of where the clock is."""

    def __init__(self, path: str | Path, depth: int = 4) -> None:
        # HAP first, because it is the one worth having; anything else PyAV
        # can read is decoded instead and says so on screen.
        try:
            self.movie, self.container = hapfile.open_movie(path)
            self.decodes = False
        except Exception:  # noqa: BLE001 -- not HAP is not an error, just slower
            self.movie, self.container = videofile.open_movie(path)
            self.decodes = True

        self.stream = self.container.streams.video[0]
        self.counts = Counts()

        self.free: queue.Queue[Frame] = queue.Queue()
        self.ready: queue.Queue[Frame] = queue.Queue(maxsize=depth)
        for _ in range(depth + 1):
            self.free.put(Frame(-1, self.movie.buffers()))

        self._stop = threading.Event()
        self._seek_to: int | None = None
        self._mark = 0               # bumped by every seek asked for
        self._skip_until = 0
        self._lock = threading.Lock()
        self._packets = (self.container.decode(self.stream) if self.decodes
                         else self.container.demux(self.stream))
        self._thread: threading.Thread | None = None
        self.error = ""
        self.at_end = False

    # -- what the clock needs to know --------------------------------------

    @property
    def rate(self) -> float:
        return self.movie.rate or 60.0

    @property
    def duration(self) -> float:
        return self.movie.duration

    def index_at(self, seconds: float) -> int:
        return max(0, min(self.movie.frames - 1, int(round(seconds * self.rate))))

    def _index_of(self, packet) -> int:
        """Which frame a packet is, from its own timestamp rather than a count.

        Counting works until the first seek, and then quietly does not.
        """
        if packet.pts is None:
            return self.counts.read
        return int(round(float(packet.pts * packet.time_base) * self.rate))

    # -- the reading thread -------------------------------------------------

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        self.container.close()

    def seek(self, index: int) -> None:
        """Ask the reader to continue from a different frame.

        Exact, and worth one read: HAP has no inter-frame compression, so
        every frame is a keyframe and there is nothing to decode forward from.

        The mark moves at once, here, rather than when the reader gets round
        to it. Between the two there are frames already in the queue that were
        read from the old place, and they have to be recognisable: `exact`
        takes the first frame at or past the one it wants, and after a seek
        backwards that description fits half the piece.
        """
        with self._lock:
            self._seek_to = max(0, min(self.movie.frames - 1, index))
            self._mark += 1

    def _apply_seek(self, index: int) -> None:
        offset = int(index / self.rate / float(self.stream.time_base))
        # Every HAP frame is a keyframe, so any_frame lands exactly. A decoded
        # movie has to start from a keyframe and work forward, so it does not.
        self.container.seek(offset, stream=self.stream,
                            any_frame=not self.decodes)
        # A decoded movie lands on the keyframe before the target and has to be
        # played forward to it. Those frames are thrown away here rather than
        # pushed through the ring: the drawing side can only take a few per
        # frame, and while it worked through them the clock went on without it.
        self._skip_until = index if self.decodes else 0
        self._packets = (self.container.decode(self.stream) if self.decodes
                         else self.container.demux(self.stream))
        while True:                       # give the pool everything back
            try:
                self.free.put(self.ready.get_nowait())
            except queue.Empty:
                break
        self.at_end = False

    def _run(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                wanted, self._seek_to = self._seek_to, None
                mark = self._mark
            if wanted is not None:
                self._apply_seek(wanted)

            try:
                frame = self.free.get(timeout=0.05)
            except queue.Empty:
                continue                  # the drawing side is behind; wait

            try:
                started = time.perf_counter()
                packet = None
                for candidate in self._packets:
                    if self.decodes or candidate.size:
                        packet = candidate
                        break
                if packet is None:
                    self.at_end = True
                    self.free.put(frame)
                    time.sleep(0.02)
                    continue
                middle = time.perf_counter()

                frame.index = self._index_of(packet)
                frame.mark = mark
                if frame.index < self._skip_until:
                    self.counts.skipped += 1
                    self.free.put(frame)
                    continue
                self._skip_until = 0
                if self.decodes:
                    videofile.frame_into(packet, frame.buffers)
                else:
                    hapfile.unpack_into(bytes(packet), frame.buffers)
                done = time.perf_counter()

                self.counts.note_demux(1000 * (middle - started))
                self.counts.note_unpack(1000 * (done - middle))
                self.counts.read += 1
            except Exception as error:    # noqa: BLE001 -- shown in the window
                self.error = str(error)
                self.free.put(frame)
                time.sleep(0.05)
                continue

            while not self._stop.is_set():
                try:
                    self.ready.put(frame, timeout=0.05)
                    break
                except queue.Full:
                    with self._lock:
                        if self._seek_to is not None:
                            break         # a seek is waiting; drop this one
            else:
                self.free.put(frame)

    # -- what the drawing side asks for -------------------------------------

    def take(self, wanted: int, holding: Frame | None) -> Frame | None:
        """The newest frame no later than `wanted`, dropping any older ones.

        Returns None when nothing new is ready, and the caller keeps showing
        what it had -- which is what dropping a frame looks like from here.
        """
        # Nothing to do if what is already up is new enough. Without this the
        # picture advances once per drawing rather than once per frame wanted,
        # so a thirty a second movie runs at twice its speed on a sixty a
        # second clock while a sixty one looks perfectly correct.
        if holding is not None and holding.index >= wanted:
            return None

        best = holding
        while True:
            try:
                frame = self.ready.get_nowait()
            except queue.Empty:
                break
            if frame.mark != self._mark:      # read before the last seek
                self.free.put(frame)
                continue
            if best is not None and best is not holding:
                self.free.put(best)
                self.counts.dropped += 1
            best = frame
            if frame.index >= wanted:
                break

        if best is holding:
            self.counts.starved += 1
            return None
        return best

    def exact(self, wanted: int, holding: Frame | None,
              should_stop=None, timeout: float = 30.0) -> Frame | None:
        """Exactly this frame, waited for however long it takes.

        The opposite of `take`, and deliberately so. Showing a clip means
        keeping the tempo and dropping what does not arrive in time; writing
        one out means every frame is the frame that was asked for, however
        long the disk takes to give it up. A render that quietly skips is
        worse than a render that is slow.
        """
        if holding is not None and holding.index == wanted:
            return holding

        best = None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if should_stop is not None and should_stop():
                return None
            try:
                frame = self.ready.get(timeout=0.05)
            except queue.Empty:
                if self.at_end:
                    return best
                continue
            if frame.mark != self._mark:      # read before the last seek
                self.free.put(frame)
                continue
            if best is not None:
                self.free.put(best)
            best = frame
            if frame.index >= wanted:
                return best
        return best

    def give_back(self, frame: Frame | None) -> None:
        if frame is not None:
            self.free.put(frame)


class Clock:
    """One time for all the screens, in seconds, answered on a frame grid.

    Counted off the machine's clock, unless something better is offered. When
    a sound is playing `source` returns where it has actually got to, and that
    becomes the time: a card runs on its own crystal, and a picture chasing
    the sound is right where a sound chasing the picture would stutter.

    `rate` is the grid the whole piece is watched on, sixty or thirty. It is
    applied on the way out and not on the way in: `raw` keeps the true time,
    unrounded, and `seconds` is what the pictures are asked to stand at. That
    order matters, because the true time is often the sound's own, and a
    rounding fed back into the sound would pull the thing that everything else
    is following.
    """

    def __init__(self) -> None:
        self.raw = 0.0               # the true time, to the microsecond
        self.rate = 60.0             # frames a second the piece is watched at
        self.duration = 0.0
        self.source = None           # a callable giving seconds, or None
        self._playing = False
        self._last = time.perf_counter()

    @property
    def seconds(self) -> float:
        """Where the pictures should be: the true time, on the grid."""
        return self.on_grid(self.raw)

    def on_grid(self, seconds: float) -> float:
        if not self.rate:
            return seconds
        at = round(seconds * self.rate) / self.rate
        return min(at, self.duration) if self.duration else at

    @property
    def playing(self) -> bool:
        return self._playing

    @playing.setter
    def playing(self, on) -> None:
        on = bool(on)
        # Starting again, after a pause of any length: without this the first
        # tick afterwards adds every second the window sat idle, because
        # nothing was drawn in between to carry the mark forward. A minute
        # spent looking at a still frame put the piece a minute in the moment
        # Play was pressed.
        if on and not self._playing:
            self._last = time.perf_counter()
        self._playing = on

    def tick(self) -> float:
        now = time.perf_counter()
        elapsed, self._last = now - self._last, now
        if self._playing:
            told = self.source() if self.source is not None else None
            # Never backwards: a source that hiccups must not rewind the
            # picture, and the machine's own clock is a fair enough fallback
            # for the one frame it takes to settle.
            self.raw = (max(self.raw, told) if told is not None
                        else self.raw + elapsed)
            if self.duration and self.raw >= self.duration:
                self.raw = self.duration
                self.playing = False
        return self.seconds

    def move_to(self, seconds: float) -> None:
        self.raw = max(0.0, min(self.duration, seconds))
        self._last = time.perf_counter()
