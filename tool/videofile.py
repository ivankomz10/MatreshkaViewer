"""Ordinary video beside HAP, described in the same words.

For prototypes there is not always a HAP to hand, and an mp4 at thirty is
enough to look at a layout with. This does decode -- there is no way not to,
the frames are not textures until something turns them into pixels -- so it is
the slow path by construction and says so.

What matters is that it describes itself exactly as `hapfile` does: a movie
with a size, a rate and a list of planes, each with a texture format and a
size. The drawing side then has nothing to decide, and one screen can be fed
HAP while the one beside it is fed an mp4 at half the rate.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import av
import numpy as np


class VideoError(Exception):
    """The file is not something this can read."""


@dataclass
class Plane:
    """The single uncompressed texture a decoded frame becomes."""

    width: int
    height: int
    texture: int = -1                     # no HAP texture kind applies here

    kind = "RGBA"
    gpu_format = "rgba8unorm"
    is_ycocg = False

    @property
    def blocks(self) -> tuple[int, int]:
        return self.width, self.height

    @property
    def frame_bytes(self) -> int:
        return self.width * self.height * 4


@dataclass
class Movie:
    """A decoded movie, wearing the same shape as a HAP one."""

    path: Path
    width: int
    height: int
    frames: int
    rate: float
    planes: list[Plane]

    pixels: bytearray | None = None       # a still keeps its one frame here
    came_as: tuple[int, int] | None = None  # the size a still arrived at

    @property
    def was_fitted(self) -> bool:
        return bool(self.came_as) and self.came_as != (self.width, self.height)

    @property
    def kind(self) -> str:
        return "RGBA still" if self.is_still else "RGBA (decoded)"

    @property
    def is_still(self) -> bool:
        return self.pixels is not None

    @property
    def has_alpha(self) -> bool:
        return True

    # Not a plane of its own, the way Hap Q Alpha has: it is the fourth channel
    # of the picture itself. Opaque sources simply fill it with 255, so this
    # costs nothing and a ProRes 4444 or a PNG keeps the alpha it was made with.
    alpha_in_colour = True

    @property
    def frame_bytes(self) -> int:
        return sum(plane.frame_bytes for plane in self.planes)

    @property
    def duration(self) -> float:
        return self.frames / self.rate if self.rate else 0.0

    def buffers(self) -> list[bytearray]:
        return [bytearray(plane.frame_bytes) for plane in self.planes]


def open_movie(path: str | Path) -> tuple[Movie, av.container.InputContainer]:
    """Open any video PyAV can read, and describe it."""
    path = Path(path)
    container = av.open(str(path))
    try:
        stream = container.streams.video[0]
    except IndexError as error:
        raise VideoError(f"{path.name} has no video in it") from error

    stream.thread_type = "AUTO"           # decoding is the cost here, so spread it
    width, height = stream.codec_context.width, stream.codec_context.height
    if not width or not height:
        raise VideoError(f"{path.name} does not say how big it is")

    rate = float(stream.average_rate or stream.guessed_rate or 0)
    frames = stream.frames
    if not frames and stream.duration and stream.time_base:
        frames = int(round(float(stream.duration * stream.time_base) * rate))
    if not frames:
        raise VideoError(f"{path.name} does not say how long it is")

    return Movie(path, width, height, frames, rate, [Plane(width, height)]), container


STILLS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".tga"}


def is_still(path: str | Path) -> bool:
    return Path(path).suffix.lower() in STILLS


def fit_into(frame: av.VideoFrame, across: int, down: int):
    """One picture centred in a screen, as large as fits, aspect kept.

    A snapshot is rarely the exact shape of the screen it is being tried on,
    and stretching it to the corners answers the wrong question -- the whole
    point of dropping it there is to see where things sit. So it is scaled
    until it touches two sides and centred, and what is left over is left
    transparent so the backing shows through it rather than a black border
    that would read as part of the picture.
    """
    scale = min(across / frame.width, down / frame.height)
    inner_across = max(1, min(across, round(frame.width * scale)))
    inner_down = max(1, min(down, round(frame.height * scale)))

    if (inner_across, inner_down) == (frame.width, frame.height):
        small = frame.to_ndarray(format="rgba")
    else:
        small = frame.reformat(width=inner_across, height=inner_down,
                               format="rgba").to_ndarray(format="rgba")

    out = np.zeros((down, across, 4), dtype=np.uint8)
    left = (across - inner_across) // 2
    top = (down - inner_down) // 2
    out[top:top + inner_down, left:left + inner_across] = small
    return out


def open_picture(path: str | Path, screen=None) -> Movie:
    """One still picture, described as a movie of a single frame.

    A snapshot dropped on a screen is the quickest way to see how a layout
    sits on the geometry, and everything downstream already knows how to draw
    a movie. So it is given the shape of one, decoded once here, and the frame
    it holds is handed out for as long as it is loaded.

    `screen` is how many pixels the screen it is going onto really has. Given
    one, the picture is fitted to it here rather than at the last moment on the
    card: from that point on it *is* a frame of the right size, and nothing
    downstream -- the flat layout, the export, the block grid -- has to know
    that a picture ever had a shape of its own.
    """
    path = Path(path)
    container = av.open(str(path))
    try:
        stream = container.streams.video[0]
        first = None
        for frame in container.decode(stream):
            first = frame
            break
        if first is None:
            raise VideoError(f"there is no picture in {path.name}")

        came_as = (first.width, first.height)
        if screen and min(screen) > 1 and tuple(screen) != came_as:
            picture = fit_into(first, int(screen[0]), int(screen[1]))
        else:
            picture = first.to_ndarray(format="rgba")
    finally:
        container.close()

    height, width = picture.shape[:2]
    movie = Movie(path, width, height, 1, 0.0, [Plane(width, height)])
    movie.pixels = bytearray(picture.tobytes())
    movie.came_as = came_as
    return movie


def frame_into(frame: av.VideoFrame, buffers) -> list[int]:
    """Put one decoded frame into the buffer the caller keeps.

    Through a numpy view rather than bytes, so the pixels are written once
    instead of being copied out of the decoder and then again into place.
    """
    picture = frame.to_ndarray(format="rgba")
    out = np.frombuffer(memoryview(buffers[0]), dtype=np.uint8)
    out = out.reshape(picture.shape)
    out[:] = picture
    return [picture.size]
