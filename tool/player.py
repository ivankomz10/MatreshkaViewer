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


def open_chain(entries, screen=None):
    """What a row of files comes to: one source if that is all it is.

    `entries` is a list of `(path, repeats)`. A single file played once is
    opened exactly as it always was -- no chain, no relabelling, no second
    code path to be wrong in. Anything else is a `Chain`, which wears the
    same surface as the one below it.
    """
    entries = [(str(path), max(1, int(times))) for path, times in entries
               if str(path).strip()]
    if not entries:
        raise ValueError("no files in this row")
    if len(entries) == 1 and entries[0][1] == 1:
        return open_source(entries[0][0], screen)
    return Chain(entries, screen)


class Link:
    """One clip of a chain: what it is, how long, and how many times over."""

    def __init__(self, path: str, repeats: int, screen=None) -> None:
        self.path = Path(path)
        self.repeats = max(1, int(repeats))
        self.still = videofile.is_still(path)
        self.source: Still | None = None
        if self.still:
            # A picture is decoded once and then simply held out, so the probe
            # and the thing that plays are the same object.
            self.source = Still(path, screen)
            self.movie = self.source.movie
            self.rate, self.frames, self.length = 0.0, 1, 0.0
        else:
            try:
                movie, container = hapfile.open_movie(path)
            except Exception:  # noqa: BLE001 -- not HAP is not an error
                movie, container = videofile.open_movie(path)
            container.close()
            self.movie = movie
            self.rate = movie.rate or 60.0
            self.frames = max(1, int(movie.frames))
            self.length = float(movie.duration)
        self.screen = screen
        self.first = 0             # the chain frame this clip's first pass opens on
        self.span = 0              # chain frames one pass of it takes
        self.passes = 1

    def open(self):
        return self.source if self.still else Stream(str(self.path))

    def __repr__(self) -> str:
        return (f"<{self.path.name} x{self.repeats} "
                f"{self.span} frames at {self.first}>")


class Chain:
    """Several clips on one screen, one after another, each played N times.

    A show comes out of the exporter in blocks, and a block that is a five
    second idle is played six times rather than exported six times over. So a
    row is a list of files with a count beside each, and this lays them end to
    end on one frame grid and answers for the whole of it.

    Two things make that more than a loop over a list.

    The clips need not share a rate, so the chain has a grid of its own -- the
    fastest of them -- and every frame handed out is relabelled with its place
    on that grid. The label is what the window upstream compares against: how
    late a frame is, whether the card is already holding it, whether a seek
    would be quicker than reading forward. A clip's own frame numbers start
    again at zero in every clip and every pass, and reading them as the
    timeline's would walk the picture backwards at every join.

    And the clips need not share a shape. Only a few are kept open -- fifteen
    blocks of a HAP Q Alpha would be gigabytes of read-ahead buffers for
    fourteen clips nobody is watching -- so a clip is opened when the play
    head nears it and dropped when it is well past. When the one that comes
    up is another size or another codec, `on_change` is called and the screen
    above re-shapes itself around it.
    """

    LIVE = 3          # clips kept open at once: the one playing, the next, one back

    def __init__(self, entries, screen=None) -> None:
        self.links = [Link(path, times, screen) for path, times in entries]
        self.screen = screen
        self.error = ""
        self.on_change = None          # told when the clip playing changes

        moving = [one.rate for one in self.links if not one.still]
        self.rate = max(moving) if moving else 60.0

        at = 0
        for link in self.links:
            if link.still:
                # A picture has no length of its own, so its count is read as
                # seconds instead of as passes -- there is nothing to play
                # twice, only a while to hold it up for.
                link.passes = 1
                link.span = max(1, int(round(link.repeats * self.rate)))
            else:
                link.passes = link.repeats
                link.span = max(1, int(round(link.length * self.rate)))
            link.first = at
            at += link.span * link.passes
        self.frames = max(1, at)

        self._live: dict[int, object] = {}
        self._used: dict[int, int] = {}
        self._clock = 0
        self._reading: tuple | None = None   # (clip, pass) the reader is aimed at
        self._out = None                     # the frame the caller is holding
        self._out_at: int | None = None      # and which of its clip's frames it is
        self._owner: dict[int, object] = {}  # which stream to hand a frame back to
        self._shape = 0                      # bumped when the clip playing changes
        # The first clip is opened here rather than lazily: what is above needs
        # a movie to build a surface out of before anything is ever drawn.
        self._stream_for(0)
        self._reading = (0, 0)

    # -- what the clock needs to know ---------------------------------------

    @property
    def duration(self) -> float:
        return self.frames / self.rate if self.rate else 0.0

    @property
    def movie(self):
        return self.links[self.at].movie

    @property
    def at(self) -> int:
        """Which clip is playing."""
        return self._reading[0] if self._reading else 0

    @property
    def decodes(self) -> bool:
        live = self._live.get(self.at)
        return bool(getattr(live, "decodes", True))

    @property
    def counts(self) -> Counts:
        live = self._live.get(self.at)
        return live.counts if live is not None else Counts()

    @property
    def at_end(self) -> bool:
        """Nothing more will ever come: the last pass of the last clip, run out."""
        if self._reading is None:
            return False
        which, pass_no = self._reading
        if which != len(self.links) - 1 or pass_no != self.links[which].passes - 1:
            return False
        live = self._live.get(which)
        return bool(live is not None and live.at_end)

    def index_at(self, seconds: float) -> int:
        return max(0, min(self.frames - 1, int(round(seconds * self.rate))))

    @property
    def joins(self) -> list:
        """Where each clip, and each repeat of it, begins: (seconds, name)."""
        marks = []
        for link in self.links:
            for pass_no in range(link.passes):
                if link.first == 0 and pass_no == 0:
                    continue           # the start of the piece is not a join
                at = (link.first + pass_no * link.span) / self.rate
                marks.append((at, link.path.name))
        return marks

    def describe(self) -> str:
        passes = sum(one.passes for one in self.links)
        return (f"{len(self.links)} файлов, {passes} проходов  "
                f"{self.frames} кадров  {self.rate:g} fps  {self.duration:.2f} s")

    # -- where a chain frame falls ------------------------------------------

    def _at(self, frame: int) -> tuple:
        """A chain frame as (which clip, which pass, how far into that pass)."""
        frame = max(0, min(self.frames - 1, int(frame)))
        for which, link in enumerate(self.links):
            whole = link.span * link.passes
            if frame < link.first + whole:
                into = frame - link.first
                pass_no = min(link.passes - 1, into // link.span)
                return which, int(pass_no), int(into - pass_no * link.span)
        link = self.links[-1]
        return len(self.links) - 1, link.passes - 1, link.span - 1

    def _local(self, link: Link, into: int) -> int:
        """How far into a pass, in that clip's own frames."""
        if link.still or not self.rate:
            return 0
        return max(0, min(link.frames - 1,
                          int(round(into * link.rate / self.rate))))

    def _label(self, link: Link, pass_no: int, local: int) -> int:
        """A clip's own frame number as a frame of the chain.

        Stable rather than merely increasing: a thirty a second clip on a
        sixty a second chain answers two chain frames with one of its own, and
        both have to carry the same label or the card is sent the same picture
        twice every frame.
        """
        if link.still or not link.rate:
            offset = 0
        else:
            offset = int(round(local * self.rate / link.rate))
        return link.first + pass_no * link.span + min(offset, link.span - 1)

    # -- which clips are open -----------------------------------------------

    def _stream_for(self, which: int):
        live = self._live.get(which)
        if live is None:
            try:
                live = self.links[which].open()
            except Exception as error:  # noqa: BLE001 -- shown beside the field
                self.error = f"{self.links[which].path.name}: {error}"
                raise
            live.start()
            self._live[which] = live
        self._used[which] = self._clock
        self._clock += 1
        while len(self._live) > self.LIVE:
            oldest = min(self._live, key=lambda key: self._used[key])
            if oldest == which:
                break
            self._used.pop(oldest, None)
            gone = self._live.pop(oldest)
            if not self.links[oldest].still:
                gone.stop()
        return live

    def _arm(self, which: int, pass_no: int, into: int) -> None:
        """Open the next clip a second before the join, not at it.

        Opening a file, allocating its buffers and starting its reader is tens
        of milliseconds, and doing that on the frame the join falls on is a
        hitch exactly where the picture changes and it shows most.
        """
        link = self.links[which]
        if which + 1 >= len(self.links) or pass_no != link.passes - 1:
            return
        if link.span - into > self.rate or which + 1 in self._live:
            return
        try:
            self._stream_for(which + 1)
        except Exception:  # noqa: BLE001 -- it will be said again at the join
            return
        self._used[which] = self._clock     # the one playing stays the newest
        self._clock += 1

    def _aim(self, which: int, pass_no: int, local: int):
        """Point the reader at a place, seeking if it is not there already."""
        stream = self._stream_for(which)
        if self._reading != (which, pass_no):
            turned = self._reading is None or self._reading[0] != which
            stream.seek(local)
            self._reading = (which, pass_no)
            self._out_at = None
            if turned:
                self._shape += 1
                if self.on_change is not None:
                    self.on_change(self)
        return stream

    # -- what the drawing side asks for -------------------------------------

    def take(self, wanted: int, holding: Frame | None) -> Frame | None:
        if holding is not self._out:
            self._out, self._out_at = holding, None
        which, pass_no, into = self._at(wanted)
        link = self.links[which]
        local = self._local(link, into)
        stream = self._aim(which, pass_no, local)
        self._arm(which, pass_no, into)

        if self._out_at is not None and self._out_at >= local:
            return None                    # what is up is new enough
        # Never the caller's own frame: its index has been relabelled onto the
        # chain's grid, and the stream below would read that as a frame from
        # somewhere in the middle of the piece.
        got = stream.take(local, None)
        if got is None:
            return None
        if self._out_at is not None and got.index <= self._out_at:
            stream.give_back(got)          # older than what is already up
            return None
        self._out, self._out_at = got, got.index
        self._owner[id(got)] = stream
        got.index = self._label(link, pass_no, got.index)
        return got

    def exact(self, wanted: int, holding: Frame | None,
              should_stop=None, timeout: float = 30.0) -> Frame | None:
        if holding is not self._out:
            self._out, self._out_at = holding, None
        which, pass_no, into = self._at(wanted)
        link = self.links[which]
        local = self._local(link, into)
        stream = self._aim(which, pass_no, local)
        if self._out_at is not None and self._out_at == local:
            return self._out               # exactly this one is already up
        got = stream.exact(local, None, should_stop, timeout)
        if got is None:
            return None
        self._out, self._out_at = got, got.index
        self._owner[id(got)] = stream
        got.index = self._label(link, pass_no, got.index)
        return got

    def give_back(self, frame: Frame | None) -> None:
        if frame is None:
            return
        owner = self._owner.pop(id(frame), None)
        if owner is not None:
            owner.give_back(frame)
        if frame is self._out:
            self._out, self._out_at = None, None

    def seek(self, index: int) -> None:
        which, pass_no, into = self._at(index)
        try:
            self._aim(which, pass_no, self._local(self.links[which], into))
        except Exception:  # noqa: BLE001 -- said when a frame is asked for
            return
        self._out, self._out_at = None, None

    def start(self) -> None:
        pass              # every clip's reader is started when it is opened

    def stop(self) -> None:
        for which, live in list(self._live.items()):
            if not self.links[which].still:
                live.stop()
        self._live.clear()
        self._used.clear()
        self._owner.clear()


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
