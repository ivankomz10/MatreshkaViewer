"""Re-baking a screen's alpha, so that both readings of the file agree.

A HAP file carries colour and alpha separately, and there are two ways to read
them. Straight multiplies the colour by the alpha, which is how the content is
authored and what the wall shows. Premultiplied lays the colour on whole, which
is the inspection: whatever was left sitting under a transparent alpha appears
instead of being quietly multiplied away.

On the real files that difference lives in exactly two places -- the fade in
and the fade out. Through the body of a piece the alpha is 255 everywhere and
the two readings are the same picture, bit for bit. In the fades up to three
pixels in five carry a partial alpha, and the colour under them runs to four
times that alpha, so the premultiplied reading blooms.

Two ways out, and both are here.

  dither   the alpha becomes 0 or 255 against a fixed threshold, and the colour
           goes with it. With no partial alpha left the two readings cannot
           differ at all: the question stops existing rather than being
           answered. A fade becomes a dissolve, which at seven millimetres a
           pixel reads as a fade from anywhere anybody stands.
  clean    the alpha is left alone and the colour is wiped where the alpha is
           below a threshold. The fade stays a fade and the worst of the bloom
           goes -- the bright colour under a nearly transparent alpha.

The threshold map is blue noise, built once per screen at its own size from a
fixed seed, so a probe and a full run cannot disagree. One map serves both
fades: a pixel lights when the alpha crosses its threshold going up and goes
dark when it crosses going down, which is monotone in both directions and
therefore does not flicker.
"""
from __future__ import annotations

import struct
import subprocess
import threading
from queue import Queue
from pathlib import Path

import cramjam
import numpy as np

import depends

import hapfile

OFF, DITHER, CLEAN = 0, 1, 2
NAMES = {DITHER: "dither", CLEAN: "clean"}

# What Clean does with the colour that is above the threshold.
#
#   keep       nothing. The fade is exactly the author's; the premultiplied
#              reading still blooms wherever the colour is brighter than its
#              own alpha, which on these files is a quarter of the fade.
#   clamp      hold every channel down to the alpha. The bloom stops, at the
#              cost of a knee: a channel is either untouched or cut flat.
#   multiply   fold the colour into its own alpha, which is what premultiplied
#              means. No knee anywhere -- it is a scale, not a ceiling -- and
#              the premultiplied reading becomes the correct one. It costs the
#              other reading: straight applies the alpha a second time, so the
#              fade comes out darker by that factor again.
KEEP, CLAMP, MULTIPLY = 0, 1, 2
COLOUR_NAMES = {KEEP: "keep", CLAMP: "clamp", MULTIPLY: "multiply"}

# What a re-baked file can be written as.
#
# Hap Q Alpha is the format the sources are in, so a re-baked file drops
# straight back into the pipeline. ffmpeg will not write it -- its Hap encoder
# knows hap, hap_alpha and hap_q and none of those carries a separate alpha
# plane -- but it does not have to. Hap Q Alpha is not a different
# compression: it is the YCoCg DXT5 of Hap Q with an RGTC1 alpha plane beside
# it, both wrapped in a container section. So ffmpeg compresses the colour,
# `HapWriter` below compresses the alpha and wraps the two.
#
# ProRes 4444 stays as the second choice, for anywhere that wants an ordinary
# intermediate. Measured: a worst case per-pixel mask through it came back
# with every pixel still 0 or 255, not one flipped, and the colour within two
# parts in 255.
HAPM, PRORES = 0, 1
FORMATS = ((HAPM, "Hap Q Alpha"), (PRORES, "ProRes 4444"))
# What each of them needs ffmpeg to have been built with, so it can be asked
# for before a re-bake starts rather than found out when the pipe breaks on
# the first frame. Hap is the one that goes missing: it wants snappy, and the
# Homebrew build is made without it.
ENCODERS = {HAPM: "hap", PRORES: "prores_ks"}
PRORES_CODEC = ["-c:v", "prores_ks", "-profile:v", "4444",
                "-pix_fmt", "yuva444p10le"]
SUFFIX = "_rebake"
PRORES_SUFFIX = "_prores"
PROBES = "rebake_probes"

# Past this, a chunk offset no longer fits the 32-bit table and the 64-bit one
# has to be written instead. Named rather than spelled out where it is used, so
# that a test can lower it and exercise the wide path without writing four
# gigabytes to find out.
WIDE_OFFSETS = 0xFFFFFFFF


def ffmpeg_here(given: str | None = None, encoder: str = "") -> str:
    """The ffmpeg to run.

    Asked for now rather than settled when this module was imported: a copy
    may have been downloaded since, and on a Mac the one that is there was
    never on this application's PATH to begin with -- an application started
    from Finder gets /usr/bin:/bin and nothing else. Running the bare name is
    what left a re-bake saying "No such file or directory: 'ffmpeg'" on a
    machine whose renders were working, because the render had asked.

    And which ffmpeg, not just any: `encoder` says what this writer needs, and
    a machine can easily have one build that has it and another that does not.
    """
    return given or depends.ffmpeg_for(encoder)


def section(kind: int, body: bytes) -> bytes:
    """A HAP section: its length, its type, and the body.

    Short form -- three bytes of length then the type -- whenever the length
    fits in three bytes, which for these sizes is always. It has to be: ffmpeg
    writes the long form and reads it back happily at the top of a frame, but
    inside a container section its loop steps by four bytes, so a long header
    there puts it four out, it reads the next type as zero and gives up with
    "Invalid texture format 0000". Every real Hap Q Alpha file is short form
    throughout, which is how this was found.
    """
    if len(body) <= 0xFFFFFF:
        return len(body).to_bytes(3, "little") + bytes([kind]) + body
    return (b"\x00\x00\x00" + bytes([kind])
            + len(body).to_bytes(4, "little") + body)


def packed_section(texture: int, blocks: bytes) -> bytes:
    """One image, snappy packed, the way the real files pack them.

    A `complex` body is not texture data but a table of decode instructions --
    how many chunks, what compressed each, how long each is -- with the chunks
    following it. One chunk is the simple case and the one everything reads.
    """
    # Raw snappy blocks, not the framed format. HAP stores the bare stream and
    # the reader here unpacks it with decompress_raw; framed bytes go in
    # looking plausible and come out the wrong length, which ffmpeg reports as
    # "uncompressed size mismatches" and nothing else explains.
    squeezed = bytes(cramjam.snappy.compress_raw(blocks))
    instructions = section(
        hapfile.INSTRUCTIONS,
        section(hapfile.COMPRESSORS, bytes([hapfile.SNAPPY]))
        + section(hapfile.SIZES, len(squeezed).to_bytes(4, "little")))
    return section((hapfile.COMPLEX << 4) | texture, instructions + squeezed)


def rgtc1(plane: np.ndarray) -> bytes:
    """One channel to RGTC1 blocks: two endpoints and sixteen 3-bit indices.

    The eight-value mode, where the two endpoints are the block's own highest
    and lowest and six more are spread between them. On a hard mask -- which
    is what a dithered alpha is -- the two endpoints are 255 and 0 and every
    pixel lands exactly on one of them, so nothing is lost at all.
    """
    down, across = plane.shape
    tall, wide = -(-down // 4), -(-across // 4)
    padded = np.zeros((tall * 4, wide * 4), np.uint8)
    padded[:down, :across] = plane
    tiles = padded.reshape(tall, 4, wide, 4).transpose(0, 2, 1, 3)
    tiles = tiles.reshape(-1, 16).astype(np.int32)
    high, low = tiles.max(axis=1), tiles.min(axis=1)
    # A block of one value still needs two different endpoints, or the eight
    # steps between them are not a scale but a division by zero.
    same = high == low
    high = np.where(same, np.minimum(low + 1, 255), high)
    low = np.where(same & (high == low), np.maximum(high - 1, 0), low)
    span = np.maximum(high - low, 1)
    step = np.clip(np.rint((tiles - low[:, None]) * 7.0 / span[:, None]),
                   0, 7).astype(np.int64)
    # Index 0 is the high endpoint, 1 the low, and 2 to 7 walk down between.
    which = np.where(step == 7, 0, np.where(step == 0, 1, 8 - step))
    bits = np.zeros(len(tiles), np.uint64)
    for pixel in range(16):
        bits |= which[:, pixel].astype(np.uint64) << np.uint64(3 * pixel)
    out = np.zeros((len(tiles), 8), np.uint8)
    out[:, 0], out[:, 1] = high, low
    for byte in range(6):
        out[:, 2 + byte] = (bits >> np.uint64(8 * byte)) & np.uint64(0xFF)
    return out.tobytes()


def _atoms(data, at: int, end: int):
    """Every atom at one level of a QuickTime file."""
    while at + 8 <= end:
        size = struct.unpack_from(">I", data, at)[0]
        name = bytes(data[at + 4:at + 8])
        body = at + 8
        if size == 1:
            size = struct.unpack_from(">Q", data, at + 8)[0]
            body = at + 16
        if size == 0:
            size = end - at
        yield name, at, body, at + size
        at += size


def _top_atoms(fh):
    """The same walk as `_atoms`, over a file too large to hold in memory.

    A source here can reach a hundred and fifty gigabytes, and the temporary
    colour file ffmpeg writes is nearly as large. Only its header is wanted:
    the picture comes back a frame at a time through the demuxer.
    """
    fh.seek(0, 2)
    end = fh.tell()
    found, at = {}, 0
    while at + 8 <= end:
        fh.seek(at)
        header = fh.read(16)
        if len(header) < 8:
            break
        size = struct.unpack_from(">I", header, 0)[0]
        name = header[4:8]
        body = at + 8
        if size == 1:
            size = struct.unpack_from(">Q", header, 8)[0]
            body = at + 16
        if size == 0:
            size = end - at
        if size < 8:
            break
        found.setdefault(name, (at, body, at + size))
        at += size
    return found


def _swap(moov: bytearray, trail, start: int, fresh: bytes) -> bytearray:
    """Put `fresh` where the atom at `start` was, growing every atom around it.

    Built anew rather than spliced in place: a memoryview of this same
    bytearray is still out, and while a view is out no slice may change its
    length.
    """
    was = struct.unpack_from(">I", moov, start)[0]
    moov = bytearray(moov[:start] + fresh + moov[start + was:])
    for outer in trail:
        struct.pack_into(">I", moov, outer,
                         struct.unpack_from(">I", moov, outer)[0]
                         + len(fresh) - was)
    return moov


def _down_to(data, at: int, end: int, path, trail: list | None = None):
    """Walk a path of atom names. `trail` collects where each one begins.

    The trail matters when an atom has to change length: every atom it sits
    inside carries its own size, and a table that grows without them growing
    with it makes a file that nothing will open.
    """
    for name in path:
        for found, start, body, stop in _atoms(data, at, end):
            if found == name:
                if trail is not None:
                    trail.append(start)
                at, end = body, stop
                break
        else:
            raise hapfile.HapError(f"no {name.decode()} in this file")
    return at, end


def blue_noise(height: int, width: int, seed: int = 20260905,
               passes: int = 4) -> np.ndarray:
    """A threshold map, uniform, with its energy at the high frequencies.

    Void and cluster is the usual way and is out of the question at seven
    million pixels. This shapes white noise in the Fourier domain instead and
    ranks the result back to uniform after every pass -- ranking is what makes
    it an exact permutation of the levels, and that is the property that
    matters: a map that is not uniform shifts the average brightness of every
    frame it touches.

    In single precision and through a real transform, which between them take
    a third off and change nothing that can be measured: the same uniformity
    to six parts in a million, the same suppression of the low frequencies to
    0.016 of the average, the same lit fraction. Fewer passes, or ranking only
    at the end, are faster still and do cost -- the clumps come back, from
    0.016 to between 0.045 and 0.077 -- so neither is done.

    Measured on the real sizes: both screens in 3.0 s against 5.0.
    """
    rng = np.random.default_rng(seed)
    field = rng.random((height, width)).astype(np.float32)
    down = np.fft.fftfreq(height).astype(np.float32)[:, None]
    across = np.fft.rfftfreq(width).astype(np.float32)[None, :]
    radius = np.sqrt(down ** 2 + across ** 2)
    keep = (1.0 - np.exp(-(radius / 0.12) ** 2)).astype(np.float32)
    for _ in range(passes):
        field = np.fft.irfft2(np.fft.rfft2(field) * keep, s=(height, width))
        order = np.argsort(field, axis=None)
        ranked = np.empty(field.size, np.float32)
        ranked[order] = np.arange(field.size, dtype=np.float32)
        field = ranked.reshape(field.shape) / field.size
    # To bytes, which is what the card is given. The shader reads a level as
    # (v + 0.5) / 256 so that solid stays solid and clear stays clear.
    return np.clip(field * 256.0, 0, 255).astype(np.uint8)


def named(source: Path, what: int, threshold: int, colour: int = KEEP,
          probe: bool = False, kind: int = HAPM) -> str:
    """What a re-baked file or a probe is called.

    The video takes one suffix whatever was done to it, because its name
    should say what it is and no more. Which suffix depends on where it is
    going. Hap Q Alpha is what the sources already are, so it goes on to take
    the source's place and _rebake is only the name it wears on the way there.
    ProRes is an intermediate for somewhere else -- it is not what the wall
    plays -- so it stays where it was written, says _prores, and leaves the
    source alone.

    A probe says the whole recipe, because probes exist to be put beside each
    other and a nameless one is a probe of nothing.
    """
    source = Path(source)
    if not probe:
        tail = PRORES_SUFFIX if kind == PRORES else SUFFIX
        return f"{source.stem}{tail}.mov"
    recipe = NAMES.get(what, "as-is")
    if what == CLEAN:
        recipe = f"{recipe}{threshold}"
        if colour != KEEP:
            recipe = f"{recipe}_{COLOUR_NAMES[colour]}"
    return f"{source.stem}_{recipe}.png"


def alpha_of(frame) -> bytes | None:
    """A frame's alpha plane, as the blocks it is made of.

    Taken from what the reader already unpacked, not from the pixels. Those
    blocks are the texture itself, so what comes out the far end decodes to
    exactly what went in.

    Copied rather than referred to: the reader takes its frame back as soon as
    the next one is asked for, and by then this is still sitting in a queue
    waiting to be written. Only copied, though -- compressing it again is the
    writing thread's work, and doing it here would put it back on the one
    thread that has the card.
    """
    if frame is None or len(frame.buffers) < 2:
        return None
    return bytes(frame.buffers[-1])


def writer_for(kind: int, path: Path, width: int, height: int, rate: float,
               ffmpeg: str | None = None):
    """Whichever writer the chosen format wants, wearing the same three calls."""
    if kind == HAPM:
        return HapWriter(path, width, height, rate, ffmpeg)
    return Writer(path, width, height, rate, ffmpeg)


class _Hand:
    """A queue between drawing a frame and writing it.

    Everything past the picture -- compressing the alpha, pushing the colour
    down the pipe to ffmpeg -- happens on this thread. Measured on the real
    screens, the card wanted 36 per cent of a re-bake and ffmpeg 55, one
    after the other; overlapped, the cost is the longer of the two rather
    than the sum.

    Bounded on purpose. A frame of the bottom screen is 29 MB, so a queue
    that grew as it liked would be the whole file in memory by the end.
    """

    def __init__(self, work, depth: int = 3) -> None:
        self.work = work
        self.queue: Queue = Queue(maxsize=depth)
        self.trouble: BaseException | None = None
        self.dropping = False
        self.thread = threading.Thread(target=self._turn, daemon=True)
        self.thread.start()

    def _turn(self) -> None:
        while True:
            item = self.queue.get()
            if item is None:
                return
            if self.trouble is None and not self.dropping:
                try:
                    self.work(*item)
                except BaseException as why:   # noqa: BLE001 -- re-raised below
                    # Kept rather than thrown: this thread has nobody to throw
                    # to. It keeps draining so that whoever is handing frames
                    # over cannot block against a queue nothing empties, and
                    # the next hand-over raises it.
                    self.trouble = why

    def give(self, *item) -> None:
        if self.trouble is not None:
            raise self.trouble
        self.queue.put(item)

    def finish(self) -> None:
        """Wait for everything handed over, then let the thread go."""
        self.queue.put(None)
        self.thread.join()
        if self.trouble is not None:
            raise self.trouble

    def stop(self) -> None:
        """Drop whatever is waiting; the file is not going to be kept."""
        self.dropping = True
        self.queue.put(None)
        self.thread.join(timeout=5)


class HapWriter:
    """Hap Q Alpha, written by making ffmpeg do all but the wrapping.

    ffmpeg compresses the colour as Hap Q, which is the same YCoCg DXT5 that
    Hap Q Alpha carries; the alpha is compressed here, to RGTC1, which for one
    channel is short; the two are wrapped in the container section the format
    uses; and the file ffmpeg wrote is rebuilt around the new frames.

    Rebuilt rather than written from nothing on purpose: only three things are
    put right in its `moov` -- the four characters naming the format, the size
    of every sample, and where the chunks start. Everything else there is what
    ffmpeg would have written, because it is what ffmpeg wrote.

    The alpha planes go to a file beside the output while the colour is being
    compressed, and are read back in order to do the wrapping. Held in memory
    they would be six gigabytes for the bottom screen; packed and on disk they
    are a fraction of that, because outside the fades every block of the alpha
    is the same block.
    """

    def __init__(self, path: Path, width: int, height: int, rate: float,
                 ffmpeg: str | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.width, self.height, self.rate = width, height, rate
        # Blocks are four pixels square and ffmpeg's Hap encoder will not open
        # at all on anything else -- it stops with "Could not open encoder"
        # and error 22. Two of the three screens here are 1150 and 110 high,
        # so this is the ordinary case and not a corner of one. The picture is
        # padded up to whole blocks for the encoder and the file is told its
        # real size afterwards, which is exactly what the real files do: the
        # texture covers 1152 rows and the movie says 1150.
        self.padded = (-(-width // 4) * 4, -(-height // 4) * 4)
        self.colour_path = self.path.with_suffix(".colour.tmp.mov")
        self.alpha_path = self.path.with_suffix(".alpha.tmp")
        self.command = [ffmpeg_here(ffmpeg, "hap"),
                        "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "rawvideo", "-pix_fmt", "rgba",
                        "-s", f"{self.padded[0]}x{self.padded[1]}",
                        "-framerate", f"{rate:g}",
                        "-i", "-", "-c:v", "hap", "-format", "hap_q",
                        str(self.colour_path)]
        self.pipe = subprocess.Popen(
            self.command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.alpha_file = open(self.alpha_path, "wb")
        self.alpha_lengths: list[int] = []
        self.room = np.zeros((self.padded[1], self.padded[0], 4), np.uint8)
        self.room[..., 3] = 255
        self.hand = _Hand(self._one)

    def write(self, frame, alpha_blocks: bytes | None = None) -> None:
        """One frame. `alpha_blocks` is the source's own plane, when it fits.

        A recipe that does not touch the alpha -- Clean is one -- can have the
        plane carried across exactly as it was found, compressed bytes and
        all. Encoding it again would cost something for nothing: the round
        trip through eight bits and back moved a fifth of a step on two thirds
        of a percent of the picture, which is small and is still more than
        zero.
        """
        # Handed on rather than done here. Every frame out of the card is its
        # own memory, so there is nothing to copy and nothing to be overwritten
        # while it waits.
        self.hand.give(frame, alpha_blocks)

    def _went(self) -> str:
        """What ffmpeg said before it went, for when the pipe breaks.

        A pipe that breaks on the first frame means the encoder never opened,
        and "Broken pipe" is the least useful way of saying so. What ffmpeg
        wrote to its own error stream says the real thing -- an unknown
        encoder, most often, on a build that has no hap.
        """
        try:
            self.pipe.wait(timeout=5)
        except Exception:  # noqa: BLE001 -- it is going away regardless
            pass
        try:
            said = (self.pipe.stderr.read() or b"").decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 -- as above
            said = ""
        last = [line for line in said.strip().splitlines() if line.strip()]
        return last[-1] if last else f"ffmpeg stopped ({self.pipe.poll()})"

    def _one(self, frame, alpha_blocks: bytes | None) -> None:
        """One frame, on the writing thread."""
        frame = np.ascontiguousarray(frame)
        # The colour goes to ffmpeg with nothing in its alpha: Hap Q has no
        # alpha channel to put anything in, and leaving the real one there
        # would only tempt the encoder into using it. Anything past the edge
        # of the picture is black, and is never sampled.
        self.room[:self.height, :self.width, :3] = frame[..., :3]
        try:
            self.pipe.stdin.write(self.room.tobytes())
        except (BrokenPipeError, OSError) as gone:
            raise RuntimeError(self._went()) from gone
        blocks = packed_section(
            hapfile.RGTC1,
            alpha_blocks if alpha_blocks is not None else rgtc1(frame[..., 3]))
        self.alpha_lengths.append(len(blocks))
        self.alpha_file.write(blocks)

    def finish(self) -> None:
        self.hand.finish()
        self.pipe.stdin.close()
        code = self.pipe.wait()
        self.alpha_file.close()
        if code:
            trouble = self.pipe.stderr.read().decode("utf-8", "replace")
            self._tidy()
            raise RuntimeError(trouble.strip().splitlines()[-1]
                               if trouble.strip() else f"ffmpeg gave up ({code})")
        try:
            self._wrap()
        except Exception:
            # Half a file is worse than none: it is the right size to look
            # finished and the wrong size to be.
            self.path.unlink(missing_ok=True)
            raise
        finally:
            self._tidy()

    def _wrap(self) -> None:
        """Put the alpha beside the colour and rebuild the file around them."""
        with open(self.colour_path, "rb") as fh:
            top = _top_atoms(fh)
            if b"moov" not in top or b"mdat" not in top:
                raise hapfile.HapError(
                    "ffmpeg wrote something this cannot rebuild")
            fh.seek(top[b"moov"][0])
            moov = bytearray(fh.read(top[b"moov"][2] - top[b"moov"][0]))
            fh.seek(0)
            head = fh.read(min(top[b"mdat"][0], top[b"moov"][0]))

        inner = memoryview(moov)
        trail = [0]                       # the moov itself, then each step down
        stbl, stbl_end = _down_to(inner, 8, len(moov),
                                  [b"trak", b"mdia", b"minf", b"stbl"], trail)
        where = {name: body for name, _, body, _ in _atoms(inner, stbl, stbl_end)}
        starts = {name: start for name, start, _, _ in _atoms(inner, stbl, stbl_end)}
        # Either width of chunk table: ffmpeg writes the 32-bit one until its
        # own file needs more, and which it chose says nothing about what this
        # one will need once the alpha is in.
        table = b"co64" if b"co64" in where else b"stco"

        # what the format is called
        entry = where[b"stsd"] + 8
        moov[entry + 4:entry + 8] = b"HapM"

        # and how big it really is. ffmpeg was handed the padded picture and
        # wrote the padded size everywhere; the file has to say the true one,
        # or every reader shows the rows that were only there to fill a block.
        was = struct.unpack_from(">HH", moov, entry + 32)
        if was != self.padded:
            raise hapfile.HapError(
                f"ffmpeg wrote {was[0]}x{was[1]} where {self.padded} was sent")
        struct.pack_into(">HH", moov, entry + 32, self.width, self.height)
        tkhd, tkhd_end = _down_to(inner, 8, len(moov), [b"trak", b"tkhd"])
        struct.pack_into(">II", moov, tkhd + 76,
                         self.width << 16, self.height << 16)

        # how the samples are grouped, so the chunks can be found again
        groups = struct.unpack_from(">I", moov, where[b"stsc"] + 4)[0]
        mapping = [struct.unpack_from(">III", moov, where[b"stsc"] + 8 + 12 * i)
                   for i in range(groups)]
        chunks = struct.unpack_from(">I", moov, where[table] + 4)[0]
        per_chunk = []
        for index in range(chunks):
            take = mapping[0][1]
            for first, samples, _ in mapping:
                if first <= index + 1:
                    take = samples
            per_chunk.append(take)

        counted = struct.unpack_from(">I", moov, where[b"stsz"] + 8)[0]
        if counted != len(self.alpha_lengths):
            raise hapfile.HapError(
                f"{counted} frames of colour against "
                f"{len(self.alpha_lengths)} of alpha")

        # the frames, and how big each has become
        colour_movie, container = hapfile.open_movie(self.colour_path)
        stream = container.streams.video[0]
        alpha_file = open(self.alpha_path, "rb")
        sizes, payloads = [], []
        try:
            frames = (bytes(packet)
                      for packet in container.demux(stream) if packet.size)
            with open(self.path, "wb") as out:
                out.write(head)
                out.write(b"\x00\x00\x00\x01mdat")
                out.write(b"\x00" * 8)          # the 64-bit length, filled in below
                body_at = out.tell()
                for length in self.alpha_lengths:
                    colour = next(frames)
                    kind, packing, at, size = hapfile.images(memoryview(colour))[0]
                    whole = section(
                        hapfile.MULTIPLE,
                        section((packing << 4) | kind, colour[at:at + size])
                        + alpha_file.read(length))
                    out.write(whole)
                    sizes.append(len(whole))
                end = out.tell()
                out.seek(body_at - 8)
                out.write((end - body_at + 16).to_bytes(8, "big"))
                out.seek(end)
                # Where every chunk now begins.
                offsets, at, index = [], body_at, 0
                for chunk in range(chunks):
                    offsets.append(at)
                    for _ in range(per_chunk[chunk]):
                        at += sizes[index]
                        index += 1

                # Both tables are rebuilt whole rather than written over in
                # place, because either can need a size the one ffmpeg wrote
                # has no room for. The chunk table is done first: it sits
                # after the size table, so replacing it leaves the other
                # where it was, and replacing them the other way round would
                # not.
                #
                # Past four gigabytes a 32-bit offset cannot say where
                # anything is, and packing one fails with "argument out of
                # range" -- which is what a five gigabyte source did. Sources
                # here run to a hundred and fifty, so the wide table is the
                # ordinary case, and ffmpeg's choice says nothing about what
                # this file needs: the alpha only ever makes it larger.
                wide = table == b"co64" or offsets[-1] > WIDE_OFFSETS
                form, name = ((">Q", b"co64") if wide else (">I", b"stco"))
                body = b"".join(struct.pack(form, one) for one in offsets)
                moov = _swap(moov, trail, starts[table],
                             struct.pack(">I", 16 + len(body)) + name
                             + bytes(moov[where[table]:where[table] + 8])
                             + body)

                # And the size table, which ffmpeg leaves empty when every
                # frame came out the same length -- a black clip does that.
                # The alpha makes them differ, so the sizes have to be spelled
                # out one by one, and there is nowhere to spell them.
                body = b"".join(struct.pack(">I", one) for one in sizes)
                moov = _swap(moov, trail, starts[b"stsz"],
                             struct.pack(">I", 20 + len(body)) + b"stsz"
                             + bytes(moov[where[b"stsz"]:where[b"stsz"] + 4])
                             + struct.pack(">II", 0, len(sizes)) + body)
                out.write(bytes(moov))
        finally:
            alpha_file.close()
            container.close()

    def _tidy(self) -> None:
        self.colour_path.unlink(missing_ok=True)
        self.alpha_path.unlink(missing_ok=True)

    def cancel(self) -> None:
        self.hand.stop()
        try:
            self.pipe.stdin.close()
        except Exception:  # noqa: BLE001 -- going away regardless
            pass
        self.pipe.terminate()
        self.pipe.wait(timeout=5)
        try:
            self.alpha_file.close()
        except Exception:  # noqa: BLE001 -- the same
            pass
        self._tidy()
        self.path.unlink(missing_ok=True)


class Writer:
    """ProRes 4444, a frame at a time, straight through ffmpeg."""

    def __init__(self, path: Path, width: int, height: int, rate: float,
                 ffmpeg: str | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        command = [ffmpeg_here(ffmpeg, PRORES_CODEC[1]),
                   "-hide_banner", "-loglevel", "error", "-y",
                   "-f", "rawvideo", "-pix_fmt", "rgba",
                   "-s", f"{width}x{height}", "-framerate", f"{rate:g}",
                   "-i", "-", *PRORES_CODEC, str(self.path)]
        self.command = command
        self.pipe = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

        self.hand = _Hand(self._one)

    def write(self, frame, alpha_blocks: bytes | None = None) -> None:
        self.hand.give(frame)

    def _went(self) -> str:
        """What ffmpeg said before it went. See the note on the Hap writer."""
        try:
            self.pipe.wait(timeout=5)
        except Exception:  # noqa: BLE001 -- it is going away regardless
            pass
        try:
            said = (self.pipe.stderr.read() or b"").decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 -- as above
            said = ""
        last = [line for line in said.strip().splitlines() if line.strip()]
        return last[-1] if last else f"ffmpeg stopped ({self.pipe.poll()})"

    def _one(self, frame) -> None:
        # The alpha is inside the picture here, so a section of it from the
        # source has nowhere to go and nothing to say.
        try:
            self.pipe.stdin.write(np.ascontiguousarray(frame).tobytes())
        except (BrokenPipeError, OSError) as gone:
            raise RuntimeError(self._went()) from gone

    def finish(self) -> None:
        self.hand.finish()
        self.pipe.stdin.close()
        code = self.pipe.wait()
        if code:
            trouble = self.pipe.stderr.read().decode("utf-8", "replace")
            raise RuntimeError(trouble.strip().splitlines()[-1]
                               if trouble.strip() else f"ffmpeg gave up ({code})")

    def cancel(self) -> None:
        self.hand.stop()
        try:
            self.pipe.stdin.close()
        except Exception:  # noqa: BLE001 -- going away regardless
            pass
        self.pipe.terminate()
        self.pipe.wait(timeout=5)
        self.path.unlink(missing_ok=True)
