"""Reading HAP without decoding it.

The point of HAP is that its frames are already in the form a graphics card
wants: DXT blocks. Decoding one to RGBA and uploading that would move nearly
three times the bytes and throw away the reason to use the format at all. So
nothing here decodes. A frame is demuxed, its second-stage compression undone,
and what comes out goes to the card as a compressed texture.

The layout, read off files rather than remembered:

    3 bytes   section length, little endian; zero means the long form
    1 byte    section type -- low nibble the texture, high nibble the packing
    4 bytes   the real length, when the short one was zero
    ...       the body

A frame is usually one image. Hap Q Alpha is two: the colour as YCoCg DXT5 and
the alpha as a separate one-channel plane, wrapped in a container section. So a
frame is modelled here as a list of planes even when there is only one -- the
alternative is a special case, and it is the case the real files turned out to
be in.

Packed as `complex` a body is not texture data but a container of decode
instructions: how many chunks, how each was compressed, how long each is. The
chunks follow it back to back, which is what lets them be undone side by side.
"""
from __future__ import annotations

from concurrent.futures import Executor
from dataclasses import dataclass
from pathlib import Path

import av
import cramjam

# Low nibble of a section type: what the blocks are.
RGTC1 = 0x01        # one channel; the alpha plane of Hap Q Alpha
DXT1 = 0x0B         # RGB, half a byte per pixel
BPTC = 0x0C         # BC7, RGBA
DXT5 = 0x0E         # RGBA, one byte per pixel
YCOCG_DXT5 = 0x0F   # Hap Q: luma in alpha, chroma in red and green

# A section holding several images rather than texture data.
MULTIPLE = 0x0D

# High nibble: how the blocks were packed for storage.
RAW = 0xA
SNAPPY = 0xB
COMPLEX = 0xC

# Sections inside the decode instructions.
INSTRUCTIONS = 0x01
COMPRESSORS = 0x02
SIZES = 0x03
OFFSETS = 0x04

TEXTURES = {
    RGTC1: ("RGTC1", "bc4-r-unorm", 8),
    DXT1: ("RGB_DXT1", "bc1-rgba-unorm", 8),
    BPTC: ("RGBA_BC7", "bc7-rgba-unorm", 16),
    DXT5: ("RGBA_DXT5", "bc3-rgba-unorm", 16),
    YCOCG_DXT5: ("YCoCg_DXT5", "bc3-rgba-unorm", 16),
}


class HapError(Exception):
    """The file is not something this can read."""


def _section(data: memoryview, at: int) -> tuple[int, int, int]:
    """Length, type and where the body starts, for the section at `at`."""
    if at + 4 > len(data):
        raise HapError("a section header runs past the end of the frame")
    length = int.from_bytes(data[at:at + 3], "little")
    kind = data[at + 3]
    if length:
        return length, kind, at + 4
    if at + 8 > len(data):
        raise HapError("a long section header runs past the end of the frame")
    return int.from_bytes(data[at + 4:at + 8], "little"), kind, at + 8


def images(frame: memoryview | bytes) -> list[tuple[int, int, int, int]]:
    """Each image in a frame: texture, packing, where it starts, how long.

    One entry for an ordinary frame, two for Hap Q Alpha.
    """
    data = memoryview(frame)
    length, kind, body = _section(data, 0)
    if kind != MULTIPLE:
        return [(kind & 0x0F, kind >> 4, body, length)]

    found = []
    at, end = body, body + length
    while at < end:
        inner_length, inner_kind, inner = _section(data, at)
        found.append((inner_kind & 0x0F, inner_kind >> 4, inner, inner_length))
        at = inner + inner_length
    if not found:
        raise HapError("a container of images with no images in it")
    return found


def _chunks(body: memoryview, at: int, end: int) -> tuple[list[int], list[int],
                                                          list[int] | None]:
    """The compressor, length and position of each chunk of a complex image."""
    compressors: list[int] = []
    sizes: list[int] = []
    offsets: list[int] | None = None

    while at < end:
        length, kind, start = _section(body, at)
        values = body[start:start + length]
        if kind == COMPRESSORS:
            # Plain bytes here, not nibbles. The section type packs the
            # compressor into its high nibble; this table does not, and
            # carrying the shift across from there costs an afternoon.
            compressors = list(values)
        elif kind == SIZES:
            sizes = [int.from_bytes(values[i:i + 4], "little")
                     for i in range(0, len(values), 4)]
        elif kind == OFFSETS:
            offsets = [int.from_bytes(values[i:i + 4], "little")
                       for i in range(0, len(values), 4)]
        at = start + length

    if not compressors or not sizes:
        raise HapError("a complex image without a compressor or size table")
    if len(compressors) != len(sizes):
        raise HapError(f"{len(compressors)} compressors against {len(sizes)} sizes")
    return compressors, sizes, offsets


def _undone_length(compressor: int, data: memoryview) -> int:
    """How much this chunk becomes, without doing the work.

    Read rather than divided out. Chunks are near enough equal slices of the
    finished texture, but "near enough" is not a thing to build on when the
    last one can differ, and snappy writes its own length in its first bytes.
    """
    if compressor == RAW:
        return len(data)
    if compressor == SNAPPY:
        return cramjam.snappy.decompress_raw_len(bytes(data))
    raise HapError(f"unknown second-stage compressor 0x{compressor:x}")


def _undo_into(compressor: int, data: memoryview, out: memoryview) -> None:
    if compressor == RAW:
        out[:] = data
    elif compressor == SNAPPY:
        cramjam.snappy.decompress_raw_into(bytes(data), out)
    else:
        raise HapError(f"unknown second-stage compressor 0x{compressor:x}")


def _image_into(data: memoryview, packing: int, body: int, length: int,
                out: memoryview, executor: Executor | None) -> int:
    """Undo one image's packing into `out`; returns how much it filled."""
    if packing in (RAW, SNAPPY):
        piece = data[body:body + length]
        filled = _undone_length(packing, piece)
        if filled > len(out):
            raise HapError(f"an image of {filled:,} bytes into {len(out):,}")
        _undo_into(packing, piece, out[:filled])
        return filled

    if packing != COMPLEX:
        raise HapError(f"unknown packing 0x{packing:x}")

    inner_length, inner_kind, inner = _section(data, body)
    if inner_kind != INSTRUCTIONS:
        raise HapError(f"expected decode instructions, found 0x{inner_kind:x}")
    compressors, sizes, offsets = _chunks(data, inner, inner + inner_length)

    start = inner + inner_length
    if offsets is None:
        offsets, running = [], 0
        for size in sizes:
            offsets.append(running)
            running += size

    pieces = [data[start + offset:start + offset + size]
              for offset, size in zip(offsets, sizes)]
    lengths = [_undone_length(compressor, piece)
               for compressor, piece in zip(compressors, pieces)]
    filled = sum(lengths)
    if filled > len(out):
        raise HapError(f"an image of {filled:,} bytes into {len(out):,}")

    landings, at = [], 0
    for size in lengths:
        landings.append(out[at:at + size])
        at += size

    if executor is None:
        for compressor, piece, landing in zip(compressors, pieces, landings):
            _undo_into(compressor, piece, landing)
    else:
        list(executor.map(_undo_into, compressors, pieces, landings))
    return filled


def unpack_into(frame: bytes, buffers, executor: Executor | None = None) -> list[int]:
    """Fill one buffer per image with texture blocks; says how much each took.

    Straight into buffers the caller keeps, on purpose. Joining the chunks into
    fresh bytes objects instead costs six times as much -- 4.2 ms a frame
    against 0.7 at 4608x1584 -- because the work is not the decompression, it
    is copying seven megabytes twice more than needed.
    """
    data = memoryview(frame)
    found = images(data)
    if not isinstance(buffers, (list, tuple)):
        buffers = [buffers]
    if len(buffers) < len(found):
        raise HapError(f"{len(found)} images into {len(buffers)} buffers")

    return [_image_into(data, packing, body, length, memoryview(out), executor)
            for (_, packing, body, length), out in zip(found, buffers)]


@dataclass
class Plane:
    """One texture of a frame: the colour, or the alpha beside it."""

    texture: int
    width: int
    height: int

    @property
    def kind(self) -> str:
        return TEXTURES[self.texture][0]

    @property
    def gpu_format(self) -> str:
        return TEXTURES[self.texture][1]

    @property
    def is_ycocg(self) -> bool:
        return self.texture == YCOCG_DXT5

    @property
    def blocks(self) -> tuple[int, int]:
        return (self.width + 3) // 4, (self.height + 3) // 4

    @property
    def frame_bytes(self) -> int:
        """Blocks of four by four pixels, so an odd size rounds up to them.

        Two of the three real screens are not multiples of four -- 1150 and 110
        high -- so this rounding is the ordinary case, not a corner of one.
        """
        across, down = self.blocks
        return across * down * TEXTURES[self.texture][2]


@dataclass
class Movie:
    """A HAP file, open and described.

    Every HAP frame stands alone -- the format has no inter-frame compression --
    so seeking is exact and costs one read. Scrubbing this is nothing like
    scrubbing H.264.
    """

    path: Path
    width: int
    height: int
    frames: int
    rate: float
    planes: list[Plane]

    @property
    def kind(self) -> str:
        return " + ".join(plane.kind for plane in self.planes)

    @property
    def has_alpha(self) -> bool:
        return len(self.planes) > 1

    @property
    def frame_bytes(self) -> int:
        return sum(plane.frame_bytes for plane in self.planes)

    @property
    def duration(self) -> float:
        return self.frames / self.rate if self.rate else 0.0

    def buffers(self) -> list[bytearray]:
        """One reusable buffer per plane, each the size that plane needs."""
        return [bytearray(plane.frame_bytes) for plane in self.planes]


def open_movie(path: str | Path) -> tuple[Movie, av.container.InputContainer]:
    """Open a HAP file and read enough of one frame to describe it.

    The first frame is looked at rather than trusted from the container: what
    the textures are lives in the frame, not in the stream header.
    """
    path = Path(path)
    container = av.open(str(path))
    try:
        stream = container.streams.video[0]
    except IndexError as error:
        raise HapError(f"{path.name} has no video in it") from error

    if stream.codec_context.name != "hap":
        raise HapError(f"{path.name} is {stream.codec_context.name}, not HAP")

    first = next((packet for packet in container.demux(stream) if packet.size), None)
    if first is None:
        raise HapError(f"{path.name} has no frames in it")

    width = stream.codec_context.width
    height = stream.codec_context.height
    planes = []
    for texture, _, _, _ in images(bytes(first)):
        if texture not in TEXTURES:
            raise HapError(f"{path.name} holds an unknown texture 0x{texture:02x}")
        planes.append(Plane(texture, width, height))

    rate = float(stream.average_rate or stream.guessed_rate or 0)
    frames = stream.frames
    if not frames and stream.duration and stream.time_base:
        frames = int(round(float(stream.duration * stream.time_base) * rate))

    container.seek(0)
    return Movie(path, width, height, frames, rate, planes), container
