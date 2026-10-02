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


# A clip that would not open is tried again this many seconds later, not on
# every frame drawn: a file missing from a share, asked for sixty times a
# second, is sixty trips to the share a second.
OPEN_AGAIN = 10.0


class _Opening:
    """A clip being opened on a thread of its own.

    Opening a movie reads its header off the disk, and a show's disk is a
    share on the network: when the share is slow, or the file is not on it,
    the read takes as long as the network takes. Done on the window's thread
    -- and a track opens the next clip a second before it is due, from the
    drawing -- that was the window not answering. A thread of its own waits
    instead, and the drawing asks again next frame.
    """

    def __init__(self, path, screen) -> None:
        self.live = None
        self.error: Exception | None = None
        self.done = threading.Event()
        self._cancelled = False
        threading.Thread(target=self._run, args=(path, screen), daemon=True,
                         name="matreshka-open").start()

    def _run(self, path, screen) -> None:
        try:
            live = open_source(path, screen)
            live.start()
            self.live = live
            if self._cancelled:
                let_go([live])
        except Exception as error:  # noqa: BLE001 -- handed to the track
            self.error = error
        finally:
            self.done.set()

    def cancel(self) -> None:
        """Not wanted any more: let go of it once it is open."""
        self._cancelled = True
        if self.done.is_set() and self.live is not None:
            let_go([self.live])


def let_go(streams) -> None:
    """Readers told to finish, and stopped on a thread of their own: never
    waited for here. A reader in the middle of a read from a share that has
    stopped answering would hold whoever waits for it as long as the share
    does -- the window, or its closing."""
    going = [one for one in streams if one is not None]
    for stream in going:
        asking = getattr(stream, "ask_to_stop", None)
        if asking is not None:
            asking()
    if going:
        threading.Thread(target=lambda: [one.stop() for one in going], daemon=True,
                         name="matreshka-let-go").start()


def open_source(path: str | Path, screen=None):
    """A stream for a movie, a still for a picture.

    `screen` is how many pixels the screen has, and only a still uses it: a
    movie is content made at a size and is taken at that size, while a picture
    is fitted to the screen it was dropped on.
    """
    return Still(path, screen) if videofile.is_still(path) else Stream(path)


class Track:
    """One track of one screen: clips placed at frames, with gaps between.

    Every screen plays through one of these, the quick look included, where a
    track is one clip from frame zero. A clip starts at its own frame rather
    than where the one before it ended, and between two clips there may be
    nothing at all -- where the track gives no picture and the screen shows
    whatever else is on it.

    Only a couple of clips are
    open at once, because every open movie is a reader thread and a pool of
    full-size buffers; the next one is opened a second before it is due, so
    the join is not where the opening happens. Every frame handed out is
    labelled with its place on the show's own grid, because the window
    compares those numbers -- how late a frame is, whether the card already
    holds it -- and a clip's own frame numbers start again at zero. And a clip
    of another shape asks the screen to re-shape itself through `on_change`.

    `clips` are `show.Clip`s of one row and one level. Missing ones are left
    out: a file that is not here is a gap, not a failure.

    `later`, as the window has it: a clip is opened on a thread of its own
    (`_Opening`) and the drawing is handed nothing until it is open -- never
    a wait for the disk on the window's thread; one that would not open is
    tried again only every OPEN_AGAIN seconds; and one let go of is stopped
    away from the window too. Off, as a render has it, a clip is opened when
    it is asked for, and the frame waited for -- a render wants every frame.
    """

    LIVE = 2            # clips kept open: the one playing, and the next

    def __init__(self, clips, rate: float = 60.0, screen=None, later: bool = False) -> None:
        self.clips = sorted((one for one in clips
                             if not one.missing and one.kind == "video"),
                            key=lambda one: (one.first, one.ident))
        self.rate = float(rate) or 60.0
        self.screen = screen
        self.error = ""
        self.on_change = None           # told when the clip playing changes
        self._live: dict[int, object] = {}
        self._used: dict[int, int] = {}
        self._clock = 0
        self._reading: int | None = None     # the clip the reader is aimed at
        self._out = None                     # the frame the caller holds
        self._out_at: tuple | None = None    # (clip, its own frame) of that
        self._owner: dict[int, object] = {}
        self.later = bool(later)
        self._opening: dict[int, _Opening] = {}
        self._failed: dict[int, float] = {}     # which -> when to try it again
        self._starts = [one.first for one in self.clips]
        # Whether the reader has been put where it was asked to be. Opening a
        # clip leaves it on its own frame zero, and a show opened in the
        # middle asks for the middle: without this the reader went on from
        # zero until the wait ran out, and handed back frame 7243 for 10642.
        self._placed = False
        # The first clip is opened now: what is above needs a movie to build
        # a surface from before anything is drawn.
        if self.clips:
            self._stream_for(0)
            self._reading = 0

    # -- what the clock and the window need to know -------------------------

    @property
    def duration(self) -> float:
        """How long the track runs. A still gives it no length of its own,
        the same as a still dropped on a row always has: it is on show for
        as long as it is loaded, and the timeline is somebody else's to set."""
        last = max((one.last for one in self.clips if not one.still),
                   default=0)
        return last / self.rate

    @property
    def at(self) -> int:
        return self._reading if self._reading is not None else 0

    @property
    def movie(self):
        live = self._live.get(self.at)
        return live.movie if live is not None else None

    @property
    def decodes(self) -> bool:
        return bool(getattr(self._live.get(self.at), "decodes", True))

    @property
    def counts(self) -> Counts:
        live = self._live.get(self.at)
        return live.counts if live is not None else Counts()

    @property
    def at_end(self) -> bool:
        if not self.clips or self._reading != len(self.clips) - 1:
            return False
        live = self._live.get(self._reading)
        return bool(live is not None and live.at_end)

    @property
    def open_now(self) -> int:
        """How many clips are open at this moment. For the tests, and the log."""
        return len(self._live)

    def index_at(self, seconds: float) -> int:
        return max(0, int(round(seconds * self.rate)))

    def which(self, frame: float) -> int | None:
        """The clip showing at a show frame, by its place in `clips`."""
        from bisect import bisect_right
        spot = bisect_right(self._starts, frame) - 1
        # Clips on one track do not overlap in any show here, but nothing in
        # the format forbids it: look back far enough to be sure.
        for index in range(spot, -1, -1):
            if self.clips[index].covers(frame):
                return index
            if self.clips[index].last <= frame and index < spot - 2:
                break
        return None

    def showing(self, frame: float):
        """The clip on show at that frame, or None in a gap."""
        index = self.which(frame)
        return None if index is None else self.clips[index]

    def opacity_at(self, frame: float) -> float:
        clip = self.showing(frame)
        return clip.opacity_at(frame) if clip is not None else 0.0

    # -- which clips are open -----------------------------------------------

    def _stream_for(self, which: int, wait: bool = True):
        """The clip's stream, opened if it is not; or, with `later` and not
        `wait`, None while it is being opened -- and while one that would
        not open waits to be tried again."""
        live = self._live.get(which)
        if live is None:
            if self.later and not wait:
                live = self._opened(which)
                if live is None:
                    return None
            else:
                clip = self.clips[which]
                try:
                    live = open_source(clip.path, self.screen)
                except Exception as error:  # noqa: BLE001 -- shown beside it
                    self.error = f"{clip.name}: {error}"
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
            if self.later:
                let_go([self._live.pop(oldest)])
            else:
                self._live.pop(oldest).stop()
        return live

    def _opened(self, which: int):
        """A clip opened on its own thread: the stream once it is, None
        until then. Asked for when it is not being opened, it starts."""
        opening = self._opening.get(which)
        if opening is None:
            if time.monotonic() < self._failed.get(which, 0.0):
                return None
            self._opening[which] = _Opening(self.clips[which].path, self.screen)
            return None
        if not opening.done.is_set():
            return None
        del self._opening[which]
        if opening.error is not None or opening.live is None:
            self._failed[which] = time.monotonic() + OPEN_AGAIN
            self.error = f"{self.clips[which].name}: {opening.error}"
            return None
        self._failed.pop(which, None)
        return opening.live

    def _arm(self, frame: float) -> None:
        """Open the next clip a second before it is due, not on its frame.

        The next clip after this frame, whether or not anything is playing
        now: in a gap nothing is, and a clip coming in after a pause is
        exactly the one that would otherwise be opened on its own first frame.
        """
        from bisect import bisect_right
        after = bisect_right(self._starts, frame)
        if after >= len(self.clips) or after in self._live:
            return
        if self.clips[after].first - frame > self.rate:
            return
        playing = self.which(frame)
        try:
            if self._stream_for(after, wait=False) is None:
                return                          # still opening
        except Exception:  # noqa: BLE001 -- said again when it is due
            return
        if playing is not None and playing in self._used:
            self._used[playing] = self._clock    # the one playing stays newest
            self._clock += 1

    def _aim(self, which: int, local: int):
        stream = self._stream_for(which)
        turned = self._reading != which
        if turned or not self._placed:
            stream.seek(local)
            self._reading = which
            self._placed = True
            self._out_at = None
            if turned and self.on_change is not None:
                self.on_change(self)
        return stream

    def _local(self, clip, stream, frame: float) -> int:
        """Which frame of the clip's own file stands at this show frame.

        Counted in the file's own frames and held to the file's own length:
        a clip's `frames` are on the show's grid, and a 30 fps movie has half
        as many of its own.
        """
        rate = getattr(stream, "rate", 0.0) or 0.0
        if not rate or not clip.frames:
            return 0
        into = (int(frame) - clip.tx) * rate / self.rate
        own = int(getattr(getattr(stream, "movie", None), "frames", 0) or 0)
        top = (own or clip.frames) - 1
        return max(0, min(top, int(round(into))))

    def _label(self, clip, stream, local: int) -> int:
        rate = getattr(stream, "rate", 0.0) or 0.0
        if not rate:
            # A still is current for the whole of its span. Labelled with its
            # first frame, the window would call it a second late a second in
            # and seek -- and then re-send the same picture every frame.
            return clip.last - 1
        return clip.tx + int(round(local * self.rate / rate))

    # -- what the drawing side asks for -------------------------------------

    def take(self, wanted: int, holding: Frame | None) -> Frame | None:
        """The newest frame no later than `wanted`, or None if nothing new.

        None as well in a gap -- `showing` is how the caller tells the two
        apart, and a screen whose track is in a gap shows nothing of it.
        """
        if holding is not self._out:
            self._out, self._out_at = holding, None
        which = self.which(wanted)
        if which is None:
            self._arm(wanted)
            return None
        clip = self.clips[which]
        stream = self._stream_for(which, wait=False)
        if stream is None:                   # being opened, away from here
            self._arm(wanted)
            return None
        local = self._local(clip, stream, wanted)
        stream = self._aim(which, local)
        self._arm(wanted)
        if self._out_at is not None and self._out_at[0] == which \
                and self._out_at[1] >= local:
            return None                      # what is up is new enough
        # Never the caller's own frame: its index is on the show's grid now,
        # and the stream would read it as a frame of its own.
        got = stream.take(local, None)
        if got is None:
            return None
        if self._out_at is not None and self._out_at[0] == which \
                and got.index <= self._out_at[1]:
            stream.give_back(got)            # older than what is already up
            return None
        self._out, self._out_at = got, (which, got.index)
        self._owner[id(got)] = stream
        got.index = self._label(clip, stream, got.index)
        return got

    def exact(self, wanted: int, holding: Frame | None,
              should_stop=None, timeout: float = 30.0) -> Frame | None:
        """Exactly this frame, however long it takes. None in a gap."""
        if holding is not self._out:
            self._out, self._out_at = holding, None
        which = self.which(wanted)
        if which is None:
            self._arm(wanted)
            return None
        clip = self.clips[which]
        stream = self._stream_for(which)
        local = self._local(clip, stream, wanted)
        stream = self._aim(which, local)
        self._arm(wanted)
        if self._out_at == (which, local):
            return self._out
        got = stream.exact(local, None, should_stop, timeout)
        if got is None:
            return None
        self._out, self._out_at = got, (which, got.index)
        self._owner[id(got)] = stream
        got.index = self._label(clip, stream, got.index)
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
        which = self.which(index)
        if which is None:
            self._out, self._out_at = None, None
            return
        try:
            stream = self._stream_for(which, wait=False)
            self._placed = False          # a seek always moves the reader
            if stream is None:
                # Still being opened: aimed when it is, as `_placed` says.
                self._out, self._out_at = None, None
                return
            local = self._local(self.clips[which], stream, index)
            self._aim(which, local)
        except Exception:  # noqa: BLE001 -- said when a frame is asked for
            return
        self._out, self._out_at = None, None

    def start(self) -> None:
        pass              # each clip's reader is started when it is opened

    def ask_to_stop(self) -> None:
        """Tell every reader to finish, without waiting for any of them."""
        for live in list(self._live.values()):
            asking = getattr(live, "ask_to_stop", None)
            if asking is not None:
                asking()
        for opening in self._opening.values():
            opening.cancel()

    def stop(self) -> None:
        for opening in self._opening.values():
            opening.cancel()
        self._opening.clear()
        for live in list(self._live.values()):
            live.stop()
        self._live.clear()
        self._used.clear()
        self._owner.clear()


class Stack:
    """The tracks of one screen, and which of them are on show at a frame.

    Nothing here decides which is in front. The layers of a screen add -- the
    show editor was checked for it: an opaque black clip on level 0 does not
    hide the level 1 clip fading out over it -- so a stack is only a list, and
    the level is only which row of the timeline a track is drawn on.
    """

    def __init__(self, tracks) -> None:
        self.tracks = [one for one in tracks if one.clips]

    @classmethod
    def of(cls, show, row: str, rate: float = 60.0, screen=None) -> "Stack":
        return cls([Track(show.on(row, level), rate, screen)
                    for level in show.levels(row)])

    def layers_at(self, frame: float) -> list:
        """(track, clip, opacity) for every track showing something here."""
        found = []
        for track in self.tracks:
            clip = track.showing(frame)
            if clip is not None:
                level = clip.opacity_at(frame)
                if level > 0.0:
                    found.append((track, clip, level))
        return found

    @property
    def duration(self) -> float:
        return max((one.duration for one in self.tracks), default=0.0)

    def stop(self) -> None:
        for track in self.tracks:
            track.stop()


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

    def ask_to_stop(self) -> None:
        """Tell the reader to finish, and do not wait for it. A reader takes
        about sixty milliseconds to notice, and six of them told one at a
        time were a third of a second of the window standing still."""
        self._stop.set()

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
