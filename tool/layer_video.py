"""Movies in the advanced mode's layers.

A video layer is read the way a track is: `player.Stream`, HAP straight onto
the card and anything else PyAV can read decoded, opened on a thread of its
own (`player._Opening`) so that a file on a slow share never holds the
window. Its frames land in a `screen_gpu.Screen`, and a compositor the movie's
own size makes that into one texture -- YCoCg undone, alpha read the way the
window reads the tracks' -- of light and cover, premultiplied, which the layer
pass then lays like a picture: on the frame, remapped, as a decal or thrown
from a projector.

Its time is the clock's less the layer's `offset`, in seconds: a movie set
two seconds in starts two seconds after the clock's zero. Before that and
past its end it shows nothing, unless it goes round (`loop`).
"""
from __future__ import annotations

import time

import player
import screen_gpu


class LayerMovie:
    """One video layer's reader and its surface on the card."""

    def __init__(self, device, path: str) -> None:
        self.device = device
        self.path = str(path)
        self.error = ""
        self._opening = player._Opening(self.path, None)
        self.stream = None
        self.screen = None
        self.composer = None
        self.held = None              # the frame the reader handed out last
        self.on_card = None           # which frame the surface holds
        self.composed = None          # which frame the texture was made of
        self.showing = False          # whether this instant has a frame of it

    def _opened(self) -> bool:
        if self.stream is not None:
            return True
        if not self._opening.done.is_set():
            return False
        if self._opening.live is None:
            self.error = str(self._opening.error or "the movie does not open")
            return False
        self.stream = self._opening.live
        movie = self.stream.movie
        self.screen = screen_gpu.Screen(self.device, movie)
        self.composer = screen_gpu.Compositor(self.device, movie.width, movie.height)
        return True

    @property
    def size(self):
        return None if self.stream is None else (self.stream.movie.width, self.stream.movie.height)

    def local(self, seconds: float, layer) -> float | None:
        """The movie's own time at the clock's `seconds`, or None where the
        layer shows nothing."""
        if self.stream is None:
            return None
        at = seconds - layer.offset
        length = self.stream.duration
        if length > 0 and layer.loop:
            at %= length
        if at < 0 or (length > 0 and at > length):
            return None
        return at

    def feed(self, seconds: float, layer) -> bool:
        """The reader brought to the clock and the newest frame sent to the
        card. True while the frame wanted is not there yet: draw again."""
        if not self._opened():
            return not self._opening.done.is_set()
        at = self.local(seconds, layer)
        self.showing = at is not None and self.on_card is not None
        if at is None:
            return False
        stream = self.stream
        wanted = stream.index_at(at)
        held = self.held
        # Behind by more than a second, or asked for an earlier frame -- a
        # scrub, a loop coming round: read from there instead of walking.
        if held is not None and (wanted < held.index or wanted - held.index > max(stream.rate, 1.0)):
            stream.seek(wanted)
            stream.give_back(held)
            self.held = held = None
        frame = stream.take(wanted, held)
        if frame is not None:
            if held is not None:
                stream.give_back(held)
            self.held = frame
        standing = self.held
        if standing is not None and self.on_card != standing.index:
            self.screen.upload([memoryview(b) for b in standing.buffers])
            self.on_card = standing.index
        self.showing = self.on_card is not None
        return not stream.at_end and (standing is None or standing.index < wanted)

    def exact(self, seconds: float, layer, timeout: float = 30.0) -> bool:
        """The very frame of `seconds` on the card, waited for: for a render.
        False where the layer shows nothing then."""
        started = time.perf_counter()
        while not self._opened():
            if self._opening.done.is_set() or time.perf_counter() - started > timeout:
                return False
            time.sleep(0.01)
        at = self.local(seconds, layer)
        if at is None:
            self.showing = False
            return False
        stream = self.stream
        wanted = stream.index_at(at)
        if self.on_card != wanted:
            frame = stream.exact(wanted, self.held, timeout=timeout)
            if frame is not None:
                if self.held is not None and self.held is not frame:
                    stream.give_back(self.held)
                self.held = frame
                self.screen.upload([memoryview(b) for b in frame.buffers])
                self.on_card = frame.index
        self.showing = self.on_card is not None
        return self.showing

    def texture(self, encoder, premultiplied: bool):
        """The frame on the card as light and cover, or None before there is one."""
        if not self.showing or self.composer is None:
            return None
        if self.composed != (self.on_card, premultiplied):
            self.composer.compose([(self.screen, 1.0)], premultiplied=premultiplied,
                                  encoder=encoder)
            self.composed = (self.on_card, premultiplied)
        return self.composer.texture

    def close(self) -> None:
        if self.stream is not None:
            player.let_go([self.stream])
            self.stream = None
        else:
            self._opening.cancel()


class Movies:
    """Every video layer's movie, opened when first shown and let go of when
    its layer is gone or shows another file."""

    def __init__(self, device) -> None:
        self.device = device
        self._held: dict = {}

    def get(self, layer):
        key = (layer.ident, layer.path)
        movie = self._held.get(key)
        if movie is None:
            movie = self._held[key] = LayerMovie(self.device, layer.path)
        return movie

    def feed(self, timed) -> bool:
        """Every layer of `timed` -- (layer, seconds of its own clock) -- brought
        to its time; the others let go of. True while one still waits for its
        frame. In the quick look every layer goes by the window's clock, in a
        show by its clip's: from where the clip comes on."""
        timed = list(timed)
        alive = {(one.ident, one.path) for one, _ in timed}
        for key in [key for key in self._held if key not in alive]:
            self._held.pop(key).close()
        waiting = False
        for layer, seconds in timed:
            waiting |= self.get(layer).feed(seconds, layer)
        return waiting

    def exact(self, timed) -> None:
        for layer, seconds in timed:
            self.get(layer).exact(seconds, layer)

    def close(self) -> None:
        for movie in self._held.values():
            movie.close()
        self._held.clear()


from layers import MOVIES  # noqa: E402 -- the files a video layer takes


def thumbnail(path: str, side: int = 34):
    """A small RGBA array of a movie's first frame, or None."""
    import av
    import numpy as np
    try:
        with av.open(str(path)) as container:
            for frame in container.decode(video=0):
                small = frame.to_image().convert("RGBA")
                small.thumbnail((side, side))
                return np.asarray(small, dtype=np.uint8)
    except Exception:  # noqa: BLE001 -- a row without a picture is still a row
        return None
    return None
