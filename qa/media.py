"""The small files the tests feed the viewer, made once and kept.

Small on purpose: a second of video at a few hundred pixels across renders in
a moment, so a test can write a whole clip and look at the result rather than
at a progress bar. They are made with the viewer's own writer, so they are
the same kind of file the real sources are -- Hap Q Alpha, blocks and all --
and a quarter of every frame is transparent, which is what the tests about
alpha are looking at.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
MEDIA = HERE / "media"
TOOL = HERE.parent / "tool"
sys.path.insert(0, str(TOOL))

# Shaped like the real screens, a tenth of the size. Every side is a multiple
# of four, which is what a block-compressed picture is made of.
CLIPS = {
    "top": ("qa_top.mov", 256, 120),
    "bottom": ("qa_bottom.mov", 464, 160),
    "lamels": ("qa_lamels.mov", 136, 28),
}
FRAMES = 60
FPS = 60.0


def _paint(index: int, wide: int, tall: int) -> np.ndarray:
    """A frame that says which frame it is, and is transparent down one side."""
    frame = np.zeros((tall, wide, 4), np.uint8)
    frame[..., 0] = np.linspace(20, 240, wide, dtype=np.uint8)[None, :]
    frame[..., 1] = np.linspace(20, 240, tall, dtype=np.uint8)[:, None]
    # A band that walks across as the clip runs: two frames are never alike,
    # so a test can see the picture change without knowing what it shows.
    frame[..., 2] = (index * 255) // max(1, FRAMES - 1)
    frame[..., 3] = 255
    frame[:, : wide // 4, 3] = 0
    return frame


def build(force: bool = False) -> dict:
    """Every clip, made if it is not there already."""
    import rebake                       # noqa: PLC0415 -- needs the path above
    MEDIA.mkdir(parents=True, exist_ok=True)
    made = {}
    for row, (name, wide, tall) in CLIPS.items():
        where = MEDIA / name
        if force or not where.exists():
            writer = rebake.writer_for(rebake.HAPM, where, wide, tall, FPS)
            for index in range(FRAMES):
                writer.write(_paint(index, wide, tall))
            writer.finish()
        made[row] = where
    return made


if __name__ == "__main__":
    for row, where in build(force="--force" in sys.argv).items():
        print(f"{row:8} {where}  {where.stat().st_size / 1024:.0f} KB")
