"""Writing the preview out as a file.

The frames come from whatever the window is drawing; this only has to encode
them. ffmpeg does that in a process of its own, fed down a pipe, because the
work either side of the pipe genuinely runs at the same time.

Almost everything here is carried over from the renderer next door, and the
parts that look fussy are the parts that were paid for in debugging:

  * The encoder is asked whether it will take the job rather than looked up in
    a table. Hardware encoders refuse for reasons written down nowhere -- a
    width past some ceiling, a quality knob the platform never implemented, a
    session another application is holding -- and two of those were found the
    hard way on two different machines.
  * Both processes' stderr is read by a thread of its own. An unread pipe is
    not only evidence discarded, it is a process that stops once it fills.
  * `-nostats`, because the progress line goes to stderr and builds disagree
    about whether `-loglevel error` silences it.
  * Nothing waits without a way out, and on cancel the processes are killed
    before anything is joined -- the writing thread may be stuck on a pipe
    nobody is reading.
  * A render that produced no frames is a failure however calmly it ended.
"""
from __future__ import annotations

import queue
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import depends

# Without this every ffmpeg would flash a console window over the interface.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

FFMPEG = depends.ffmpeg_command()

FORMATS = [
    ("H.264 mp4", "h264", ".mp4"),
    ("HEVC mp4", "hevc", ".mp4"),
    ("PNG sequence", "png", ".png"),
    ("ProRes mov", "prores", ".mov"),
]

# Offered only where an alpha means anything. A render of the building clears
# to opaque black, so there it would always come out a solid one; the flat
# strips are the screens themselves, and what is transparent in them is the
# content.
ALPHA_FORMATS = [
    ("ProRes 4444 alpha", "prores_alpha", ".mov"),
    ("PNG alpha", "png_alpha", ".png"),
]
CARRY_ALPHA = {kind for _, kind, _ in ALPHA_FORMATS}

_ENCODERS: set[str] | None = None
_ACCEPTED: dict[tuple, bool] = {}


def refresh_ffmpeg() -> str:
    """Look again -- a copy may have arrived since this module was imported."""
    global FFMPEG, _ENCODERS
    FFMPEG = depends.ffmpeg_command()
    _ENCODERS = None
    _ACCEPTED.clear()
    return FFMPEG


def available_encoders() -> set[str]:
    global _ENCODERS
    if _ENCODERS is None:
        try:
            listing = subprocess.run(
                [FFMPEG, "-hide_banner", "-encoders"],
                capture_output=True, text=True, timeout=20,
                creationflags=NO_WINDOW).stdout
            _ENCODERS = {line.split()[1] for line in listing.splitlines()
                         if line.startswith(" V") and len(line.split()) > 1}
        except Exception:  # noqa: BLE001 -- absence is the answer
            _ENCODERS = set()
    return _ENCODERS


def encoder_takes(arguments: list[str], width: int, height: int) -> bool:
    """Whether this encoder will really take a frame of this size.

    Asked rather than assumed, and about this machine rather than about a
    table someone wrote after trying two of them.
    """
    if width <= 0 or height <= 0:
        return False
    key = (tuple(arguments), width, height)
    known = _ACCEPTED.get(key)
    if known is None:
        try:
            attempt = subprocess.run(
                [FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                 "-i", f"color=black:s={width}x{height}:r=30", "-frames:v", "1"]
                + arguments + ["-f", "null", "-"],
                capture_output=True, timeout=60, creationflags=NO_WINDOW)
            known = attempt.returncode == 0
        except Exception:  # noqa: BLE001 -- an unanswered question is a no
            known = False
        _ACCEPTED[key] = known
    return known


@dataclass
class Output:
    """How the finished frames are written."""

    kind: str = "h264"
    path: Path = Path("out.mp4")
    fps: int = 60
    crf: int = 18
    preset: str = "medium"
    encoder: str = "auto"          # auto | medium | veryfast
    width: int = 0
    height: int = 0
    png_depth: int = 8
    prores_profile: str = "3"      # 3 = 422 HQ
    sound: Path | None = None      # a WAV to lay under it
    sound_from: float = 0.0        # where in that WAV this render starts

    # What to try before falling back, fastest first. ProRes is here because
    # Apple's own chips from the M1 Pro up carry an engine for it, and the
    # software encoder beside it is one of the slowest things ffmpeg does.
    HARDWARE = {
        "h264": ("h264_nvenc", "h264_videotoolbox"),
        "hevc": ("hevc_nvenc", "hevc_videotoolbox"),
        "prores": ("prores_videotoolbox",),
    }
    SOFTWARE = {"h264": "libx264", "hevc": "libx265", "prores": "prores_ks"}

    @property
    def chosen_encoder(self) -> str:
        if self.kind not in self.HARDWARE:
            return self.kind
        if self.encoder == "auto":
            for name in self.HARDWARE[self.kind]:
                if name not in available_encoders():
                    continue
                # Asked, not assumed: every one of these refuses something --
                # a width past some ceiling, a profile it never implemented --
                # and the refusal is cheaper to find here than in a render.
                if encoder_takes(self.codec_arguments(name), self.width, self.height):
                    return name
        return self.SOFTWARE[self.kind]

    def codec_arguments(self, encoder: str) -> list[str]:
        """Everything about the encoding, and nothing about the destination."""
        if self.kind in ("h264", "hevc"):
            if encoder.endswith("_nvenc"):
                return ["-c:v", encoder, "-preset", "p4", "-rc", "vbr",
                        "-cq", "26", "-pix_fmt", "yuv420p"]
            if encoder.endswith("_videotoolbox"):
                # Deliberately not -allow_sw: its software encoder is slower
                # than libx264, so a refusal should fail where it can be seen
                # rather than become a render nobody can wait out.
                return ["-c:v", encoder, "-q:v", "60", "-pix_fmt", "yuv420p"]
            preset = self.preset if self.encoder == "auto" else self.encoder
            return ["-c:v", encoder, "-crf", str(self.crf), "-preset", preset,
                    "-pix_fmt", "yuv420p"]
        if self.kind == "png":
            return ["-c:v", "png",
                    "-pix_fmt", "rgb48be" if self.png_depth == 16 else "rgb24"]
        if self.kind == "png_alpha":
            return ["-c:v", "png",
                    "-pix_fmt", "rgba64be" if self.png_depth == 16 else "rgba"]
        if self.kind == "prores_alpha":
            # prores_ks and nothing else. The hardware engine takes a 4444
            # profile but its pixel format has nowhere to put an alpha, so
            # asking it for one writes a file that claims one and has none.
            # This is the encoder the re-bake writes its ProRes with.
            return ["-c:v", "prores_ks", "-profile:v", "4444",
                    "-pix_fmt", "yuva444p10le"]
        if self.kind == "prores":
            if encoder.endswith("_videotoolbox"):
                # The hardware engine names its profiles rather than numbering
                # them, and it wants the 10-bit format Apple's own tools use.
                named = {"0": "proxy", "1": "lt", "2": "standard",
                         "3": "hq", "4": "4444", "5": "4444xq"}
                return ["-c:v", encoder,
                        "-profile:v", named.get(self.prores_profile, "hq"),
                        "-pix_fmt", "p210le"]
            return ["-c:v", "prores_ks", "-profile:v", self.prores_profile,
                    "-pix_fmt", "yuv422p10le"]
        raise ValueError(f"unknown output kind {self.kind!r}")

    @property
    def takes_sound(self) -> bool:
        # A sequence of stills has nowhere to put it.
        return self.sound is not None and not self.kind.startswith("png")

    def sound_input(self) -> list[str]:
        """The second input, seeked to where this render begins."""
        if not self.takes_sound:
            return []
        return ["-ss", f"{max(0.0, self.sound_from):.6f}", "-i", str(self.sound)]

    def sound_arguments(self) -> list[str]:
        """How the sound is written, and that it must not outlast the picture.

        PCM into a mov because that is what everything downstream of a ProRes
        expects; AAC into an mp4 because that is what an mp4 is for.
        """
        if not self.takes_sound:
            return []
        codec = (["-c:a", "pcm_s16le"]
                 if self.kind.startswith("prores")
                 else ["-c:a", "aac", "-b:a", "192k"])
        # Mapped by hand: with two inputs the default is a guess, and a guess
        # that silently picks nothing is a file nobody notices is silent.
        return ["-map", "0:v:0", "-map", "1:a:0"] + codec + ["-shortest"]

    def arguments(self) -> list[str]:
        return (self.codec_arguments(self.chosen_encoder)
                + self.sound_arguments() + [str(self.path)])


@dataclass
class Progress:
    frames_done: int = 0
    total: int = 0
    started_at: float = field(default_factory=time.monotonic)

    @property
    def fps(self) -> float:
        elapsed = time.monotonic() - self.started_at
        return self.frames_done / elapsed if elapsed > 0 else 0.0

    @property
    def eta(self) -> float:
        rate = self.fps
        return (self.total - self.frames_done) / rate if rate > 0 else 0.0


def write(frames, count: int, output: Output, on_progress=None,
          should_stop=None) -> dict:
    """Encode `count` frames, each produced by calling `frames(index)`.

    `frames` returns RGBA bytes of exactly output.width x output.height, or
    None when it cannot -- which ends the render as a failure rather than
    quietly writing a shorter file.
    """
    output.path.parent.mkdir(parents=True, exist_ok=True)
    arguments = ([FFMPEG, "-hide_banner", "-loglevel", "error", "-nostats", "-y",
                  "-f", "rawvideo", "-pix_fmt", "rgba",
                  "-s", f"{output.width}x{output.height}",
                  "-framerate", str(output.fps), "-i", "-"]
                 + output.sound_input() + output.arguments())
    encoder = subprocess.Popen(arguments, stdin=subprocess.PIPE,
                               stderr=subprocess.PIPE, creationflags=NO_WINDOW)

    complaints: list[bytes] = []
    gone = threading.Event()

    def listen() -> None:
        for line in iter(encoder.stderr.readline, b""):
            complaints.append(line)

    outgoing: queue.Queue = queue.Queue(maxsize=3)

    def push() -> None:
        while True:
            item = outgoing.get()
            if item is None:
                break
            try:
                encoder.stdin.write(item)
            except (BrokenPipeError, OSError):
                gone.set()
                break

    ear = threading.Thread(target=listen, daemon=True)
    writer = threading.Thread(target=push, daemon=True)
    ear.start()
    writer.start()

    progress = Progress(total=count)
    cancelled = False
    missing = -1

    def stopping() -> bool:
        return should_stop is not None and should_stop()

    try:
        for index in range(count):
            if stopping():
                cancelled = True
                break
            picture = frames(index)
            if picture is None:
                missing = index
                break
            while not gone.is_set():
                if stopping():
                    cancelled = True
                    break
                try:
                    outgoing.put(picture, timeout=0.2)
                    break
                except queue.Full:
                    continue
            if cancelled or gone.is_set():
                break
            progress.frames_done += 1
            if on_progress is not None and progress.frames_done % 4 == 0:
                on_progress(progress)
    finally:
        if cancelled:
            encoder.kill()
        while True:
            try:
                outgoing.put(None, timeout=0.2)
                break
            except queue.Full:
                try:
                    outgoing.get_nowait()
                except queue.Empty:
                    pass
        writer.join(timeout=30)
        try:
            encoder.stdin.close()
        except OSError:
            pass
        encoder.wait()
        ear.join(timeout=5)

    said = b"".join(complaints).decode("utf-8", "replace").strip()
    code = encoder.returncode
    if code is not None and code > (1 << 31):
        code -= 1 << 32

    if not cancelled and progress.frames_done == 0:
        raise RuntimeError(f"nothing was encoded.\nffmpeg exited {code}: "
                           f"{said or '(silent)'}\ncommand: {' '.join(arguments)}")
    if not cancelled and missing >= 0:
        raise RuntimeError(f"the source ran out at frame {missing} of {count}")
    if not cancelled and code not in (0, None):
        raise RuntimeError(f"ffmpeg exited {code}: {said or '(silent)'}")

    return {
        "frames": progress.frames_done,
        "seconds": time.monotonic() - progress.started_at,
        "fps": progress.fps,
        "cancelled": cancelled,
        "output": output.path,
        "encoder": output.chosen_encoder,
        "complaints": said,
    }
