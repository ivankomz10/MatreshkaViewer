"""Work that must not block the window: writing the preview out, and fetching
ffmpeg.

The window and the render must not touch the graphics device at the same time,
so for the duration of a render the canvas stops drawing and the device belongs
to this thread alone. That is simpler and safer than sharing it, and the only
thing lost is the live picture, which nobody is watching while they wait.

Frames are asked for exactly rather than taken as they come. Showing a clip
means keeping the tempo and dropping what is late; writing one out means every
frame is the frame that was asked for, however long the disk takes.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QThread, Signal

import depends
import export
import player
import rebake
import screen_gpu


class FlatExportJob(QThread):
    """The flat strips, each written on its own.

    One pass over the piece per screen rather than one pass writing three at
    once. It costs the reading three times over -- which measured at two
    hundredths of a millisecond a frame, so it costs nothing -- and it draws
    exactly as much as a combined pass would, because each pass draws only its
    own screen. What it buys is one encoder at a time and one thing to say
    about how far along it is.
    """

    progress = Signal(int, int, float, float)   # done, total, fps, eta
    failed = Signal(str)
    finished_ok = Signal(dict)

    def __init__(self, streams, screens, draw, work, kind: str, first: int,
                 count: int, rate: float, fps: int, parent=None) -> None:
        super().__init__(parent)
        self.streams = streams
        self.screens = screens
        # How to draw one screen at a size, handed in rather than reached for:
        # this runs on a thread of its own and the window is not its to touch.
        self.draw = draw
        self.work = list(work)              # (screen, target, width, height)
        self.kind = kind
        self.first, self.count, self.rate, self.fps = first, count, rate, fps
        self._stop = False
        self.held = [None] * len(streams)

    def cancel(self) -> None:
        self._stop = True

    def _at(self, seconds: float) -> bool:
        """Put every stream at that instant. False when one cannot get there."""
        for index, stream in enumerate(self.streams):
            if stream.duration and seconds > stream.duration:
                continue                      # this one has ended; it goes dark
            wanted = stream.index_at(seconds)
            frame = stream.exact(wanted, self.held[index],
                                 should_stop=lambda: self._stop)
            if frame is None:
                if self.held[index] is None:
                    return False
                continue                      # nothing newer; keep what is up
            if self.held[index] is not None and self.held[index] is not frame:
                stream.give_back(self.held[index])
            self.held[index] = frame
            self.screens[index].upload([memoryview(b) for b in frame.buffers])
        return True

    def run(self) -> None:  # noqa: D102 -- QThread entry point
        started = time.perf_counter()
        done = [0]
        total = self.count * len(self.work)
        written, complaints, encoder = [], [], ""
        try:
            for name, target, wide, tall in self.work:
                for stream in self.streams:
                    stream.seek(stream.index_at(self.first / self.rate))

                def one(step: int, screen=name, w=wide, h=tall):
                    if not self._at((self.first + step) / self.rate):
                        return None
                    picture = self.draw(screen, w, h)
                    done[0] += 1
                    return np.ascontiguousarray(picture).tobytes()

                # A folder of numbered stills, or one file.
                writing = (target / "%06d.png"
                           if self.kind.startswith("png") else target)
                output = export.Output(kind=self.kind, path=writing,
                                       fps=self.fps, width=wide, height=tall)
                result = export.write(
                    one, self.count, output,
                    on_progress=lambda p: self.progress.emit(
                        done[0], total,
                        done[0] / max(1e-6, time.perf_counter() - started),
                        (total - done[0]) * (time.perf_counter() - started)
                        / max(1, done[0])),
                    should_stop=lambda: self._stop)
                if result["cancelled"]:
                    self.failed.emit("cancelled")
                    return
                written.append(str(target))
                encoder = result.get("encoder", "")
                if result.get("complaints"):
                    complaints.append(result["complaints"])
            ran = time.perf_counter() - started
            self.finished_ok.emit({
                "frames": done[0], "seconds": ran,
                "fps": done[0] / ran if ran else 0.0,
                "output": ", ".join(written), "encoder": encoder,
                "complaints": " ".join(complaints)})
        except Exception as error:  # noqa: BLE001 -- surfaced in the window
            self.failed.emit(str(error))
        finally:
            for index, stream in enumerate(self.streams):
                if self.held[index] is not None:
                    stream.give_back(self.held[index])
                    self.held[index] = None


class DownloadJob(QThread):
    """Fetching ffmpeg, off the UI thread."""

    progress = Signal(int, int)                 # bytes done, bytes total
    failed = Signal(str)
    finished_ok = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._stop = False

    def cancel(self) -> None:
        self._stop = True

    def run(self) -> None:  # noqa: D102 -- QThread entry point
        try:
            path = depends.install_ffmpeg(
                on_progress=lambda done, total: self.progress.emit(done, total),
                should_stop=lambda: self._stop)
            self.finished_ok.emit(str(path))
        except Exception as error:  # noqa: BLE001 -- shown in the dialog
            self.failed.emit(str(error))


class ExportJob(QThread):
    """One render of the scene to a file."""

    progress = Signal(int, int, float, float)   # done, total, fps, eta
    failed = Signal(str)
    finished_ok = Signal(dict)

    def __init__(self, streams, screens, renderer, output: export.Output,
                 first: int, count: int, rate: float, move=None,
                 parent=None) -> None:
        super().__init__(parent)
        self.streams = streams
        self.screens = screens
        self.renderer = renderer
        self.output = output
        self.first = first
        self.count = count
        self.rate = rate
        # Where the moving screen stands at an instant. A callable rather than
        # a reach back into the window, because this runs on a thread of its
        # own. It has to be called for every frame, and once was not: the
        # honeycomb moved on screen and came out of the file standing still.
        self.move = move
        self._stop = False
        self.held = [None] * len(streams)

    def cancel(self) -> None:
        self._stop = True

    def _frame(self, step: int):
        """Every screen at the same instant, drawn once."""
        seconds = (self.first + step) / self.rate
        for index, stream in enumerate(self.streams):
            if stream.duration and seconds > stream.duration:
                continue                      # this one has ended; it goes dark
            wanted = stream.index_at(seconds)
            frame = stream.exact(wanted, self.held[index],
                                 should_stop=lambda: self._stop)
            if frame is None:
                if self.held[index] is None:
                    return None
                continue                      # nothing newer; keep what is up
            if self.held[index] is not None and self.held[index] is not frame:
                stream.give_back(self.held[index])
            self.held[index] = frame
            self.screens[index].upload([memoryview(b) for b in frame.buffers])

        # The geometry is part of the frame, not a thing the window does to
        # what it happens to be showing.
        if self.move is not None:
            self.move(seconds)
        picture = self.renderer.to_array(self.output.width, self.output.height)
        return np.ascontiguousarray(picture).tobytes()

    def run(self) -> None:  # noqa: D102 -- QThread entry point
        try:
            for stream in self.streams:
                stream.seek(stream.index_at(self.first / self.rate))
            result = export.write(
                self._frame, self.count, self.output,
                on_progress=lambda p: self.progress.emit(
                    p.frames_done, p.total, p.fps, p.eta),
                should_stop=lambda: self._stop)
            if result["cancelled"]:
                self.failed.emit("cancelled")
            else:
                self.finished_ok.emit(result)
        except Exception as error:  # noqa: BLE001 -- surfaced in the window
            self.failed.emit(str(error))
        finally:
            for index, stream in enumerate(self.streams):
                stream.give_back(self.held[index])
                self.held[index] = None


class _Piece:
    """One file being re-baked, and how far along it is."""

    def __init__(self, source, target, stream, screen, writer) -> None:
        self.source, self.target = source, target
        self.stream, self.screen, self.writer = stream, screen, writer
        self.held = None
        self.at = 0
        self.going = True

    def close(self) -> None:
        if self.writer is not None:          # still open: it did not finish
            try:
                self.writer.cancel()
            except Exception:  # noqa: BLE001 -- going away regardless
                pass
        if self.held is not None:
            self.stream.give_back(self.held)
            self.held = None
        self.stream.stop()


class RebakeJob(QThread):
    """One or more source files re-baked and written out, off the UI thread.

    A source of its own is opened for each, rather than borrowing the one the
    window is playing: this walks a file from the first frame to the last and
    has no business moving somebody else's playhead while it does.
    """

    progress = Signal(int, int, float, float)   # done, total, fps, eta
    failed = Signal(str)
    finished_ok = Signal(dict)

    def __init__(self, painter, work, what: int, threshold: int,
                 colour: int, kind: int = 0, parent=None) -> None:
        super().__init__(parent)
        self.painter = painter
        self.work = list(work)                  # (source path, target path)
        self.what = what
        self.threshold = threshold
        self.colour = colour
        self.kind = kind
        self._stop = False

    # Two temporary files stand beside the finished one while it is built --
    # the colour ffmpeg compressed and the alpha this made -- and only at the
    # end are they folded together and thrown away. So the widest moment wants
    # about twice the source. Measured: a 12.7 GB source peaked at 20.6, a
    # 5.1 GB one at 8.7. Sources here reach a hundred and fifty gigabytes,
    # where running out nine tenths of the way through costs an hour, so the
    # room is counted before the first frame rather than found out later.
    ROOM = 2.0

    def cancel(self) -> None:
        self._stop = True

    def _room_for(self, work) -> None:
        """Refuse a re-bake that the target drive cannot hold."""
        wanted: dict[str, int] = {}
        for source, target in work:
            drive = Path(target).resolve().anchor or str(Path(target).parent)
            wanted[drive] = wanted.get(drive, 0) + Path(source).stat().st_size
        for drive, size in wanted.items():
            need, free = size * self.ROOM, shutil.disk_usage(drive).free
            if free < need:
                raise RuntimeError(
                    f"{drive.rstrip(chr(92))} has {free / 1e9:.0f} GB free and "
                    f"this needs about {need / 1e9:.0f}: the colour and the "
                    f"alpha are written beside the finished file before being "
                    f"folded into it")

    def _open(self, source, target):
        """One file made ready: its reader, its screen and its writer."""
        stream = player.open_source(source)
        screen = screen_gpu.Screen(self.painter.device, stream.movie)
        if self.what == rebake.DITHER:
            screen.load_noise(rebake.blue_noise(screen.height, screen.width))
        screen.set_rebake(self.what, self.threshold / 255.0, self.colour,
                          own_colour=True)
        writer = rebake.writer_for(self.kind, target, screen.width,
                                   screen.height, stream.rate or 60.0)
        return _Piece(source, target, stream, screen, writer)

    def _turn(self, piece) -> bool:
        """One frame of one file. False when that file has no more."""
        frame = piece.stream.exact(piece.at, piece.held,
                                   should_stop=lambda: self._stop)
        if frame is None:
            return False
        if piece.held is not None and piece.held is not frame:
            piece.stream.give_back(piece.held)
        piece.held = frame
        piece.screen.upload([memoryview(b) for b in frame.buffers])
        # Clean leaves the alpha exactly as it found it, so the plane is
        # carried across rather than made again. Dither replaces it and there
        # is nothing to carry.
        keep = (rebake.alpha_of(frame) if self.what == rebake.CLEAN else None)
        piece.writer.write(self.painter.frame_of(piece.screen), keep)
        piece.at += 1
        return True

    def run(self) -> None:  # noqa: D102 -- QThread entry point
        pieces: list = []
        try:
            self._room_for(self.work)
            for source, target in self.work:
                pieces.append(self._open(source, target))
            total = sum(piece.stream.movie.frames for piece in pieces)
            started = time.perf_counter()
            done = 0

            # Turn and turn about rather than one file and then the other.
            # The card is the one thing that cannot be shared -- there is a
            # single device and this thread has it -- but each writer has its
            # own thread and its own ffmpeg, so while this draws a frame of
            # the top screen the bottom one's encoder is still busy with the
            # last frame it was given. Two files that took 65 and 157 seconds
            # one after the other overlap into rather less than both.
            for piece in pieces:
                piece.stream.start()
            while any(piece.going for piece in pieces):
                for piece in pieces:
                    if not piece.going:
                        continue
                    if self._stop:
                        for other in pieces:
                            other.writer.cancel()
                            other.writer = None
                        self.failed.emit("cancelled")
                        return
                    if piece.at >= piece.stream.movie.frames                             or not self._turn(piece):
                        piece.going = False
                        continue
                    done += 1
                    if done % 10 == 0 or done == total:
                        ran = time.perf_counter() - started
                        rate = done / ran if ran > 0 else 0.0
                        self.progress.emit(done, total, rate,
                                           (total - done) / rate if rate else 0.0)

            # Finished together, after every frame of every file is drawn:
            # this is where the last of the encoding is waited for, and doing
            # it here rather than inside the loop keeps the two ffmpegs going
            # side by side to the end.
            for piece in pieces:
                piece.writer.finish()
                piece.writer = None
            self.finished_ok.emit({"files": [str(t) for _, t in self.work],
                                   "frames": done})
        except Exception as error:  # noqa: BLE001 -- surfaced in the window
            self.failed.emit(str(error))
        finally:
            for piece in pieces:
                piece.close()


class NoiseJob(QThread):
    """The dither's threshold maps, built where they cannot freeze the window.

    Three seconds for the two big screens. Short enough to wait for and far
    too long to spend inside a repaint, which is the whole reason this is a
    thread and not a function call.
    """

    # `object` rather than `dict`: a dict signal is marshalled as a map with
    # string keys, and these are keyed by a size -- a pair of numbers. Qt
    # cannot convert that and drops the emit on the floor, silently, which
    # looks exactly like a thread that never finished.
    ready = Signal(object)

    def __init__(self, sizes, parent=None) -> None:
        super().__init__(parent)
        self.sizes = list(sizes)            # (width, height) each

    def run(self) -> None:  # noqa: D102 -- QThread entry point
        made = {}
        for width, height in self.sizes:
            if (width, height) not in made:
                made[(width, height)] = rebake.blue_noise(height, width)
        self.ready.emit(made)
