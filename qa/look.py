"""Small readings the tests take: of a label, of a picture, of a written file."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


def frame_now(app) -> tuple[int, int]:
    """Where the timeline stands, off the label beside it: (here, last)."""
    said = app.says("qa_frame_label")
    numbers = re.findall(r"-?\d+", said)
    if len(numbers) < 2:
        raise AssertionError(f"the frame label says {said!r}")
    return int(numbers[0]), int(numbers[1])


def _grey(picture):
    import numpy as np
    return np.asarray(picture.convert("L"), dtype=np.float32)


def spread(picture) -> float:
    """How much of anything is in a picture: nothing flat scores above zero."""
    return float(_grey(picture).std())


def difference(one, other) -> float:
    """Mean difference per pixel between two pictures of the same size."""
    import numpy as np
    assert one.size == other.size, f"{one.size} against {other.size}"
    return float(np.abs(_grey(one) - _grey(other)).mean())


def halves(picture):
    """A picture cut down the middle, which is how ReBake shows a file."""
    wide, tall = picture.size
    return (picture.crop((0, 0, wide // 2, tall)),
            picture.crop((wide // 2, 0, wide, tall)))


def probe(path: Path) -> dict:
    """What ffprobe says about a written file: sizes, format, frame count."""
    got = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
         "-show_entries", "stream=width,height,pix_fmt,nb_read_frames,codec_name",
         "-of", "json", str(path)], capture_output=True, text=True)
    if got.returncode:
        raise AssertionError(f"ffprobe would not read {path}: {got.stderr[:200]}")
    streams = json.loads(got.stdout).get("streams") or [{}]
    said = streams[0]
    return {"width": int(said.get("width", 0)),
            "height": int(said.get("height", 0)),
            "pix_fmt": said.get("pix_fmt", ""),
            "codec": said.get("codec_name", ""),
            "frames": int(said.get("nb_read_frames", 0) or 0)}


def clear_share(path: Path, frame: int = 0) -> float:
    """How much of a written file's first frame is transparent, 0 to 1."""
    import numpy as np
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vframes", str(frame + 1),
         "-pix_fmt", "rgba", "-f", "rawvideo", "-"],
        capture_output=True).stdout
    if not raw:
        raise AssertionError(f"nothing decoded out of {path}")
    picture = np.frombuffer(raw, np.uint8).reshape(-1, 4)
    return float((picture[:, 3] < 8).sum()) / len(picture)
