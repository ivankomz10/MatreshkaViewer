"""The pictures a layer's mask and paint effects are made of.

Each is a picture of the screen's frame, pixel for pixel, kept in memory as
an array and on the card as a texture, and written to a PNG beside the
settings when it has changed (`save`). A mask starts white -- the whole
layer shows -- and paint starts clear. Read back from its file at another
size, a picture is stretched to the frame it is asked for at: the frame is
the screen's, and a screen does not change its pixels.

The brushes (the next step) change `array` and call `touch`.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import wgpu


class Raster:
    def __init__(self, device, name: str, size: tuple, fill) -> None:
        self.name = name
        self.width, self.height = int(size[0]), int(size[1])
        self.array = np.empty((self.height, self.width, 4), np.uint8)
        self.array[...] = fill
        self.texture = device.create_texture(
            size=(self.width, self.height, 1), format="rgba8unorm",
            usage=wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.COPY_DST)
        self.device = device
        self.dirty = False
        self.version = 0
        self.upload()

    def upload(self) -> None:
        self.device.queue.write_texture(
            {"texture": self.texture}, np.ascontiguousarray(self.array),
            {"bytes_per_row": self.width * 4, "rows_per_image": self.height},
            (self.width, self.height, 1))

    def touch(self, box=None) -> None:
        """The array was changed -- all of it, or the (y0, y1, x0, x1) of it a
        brush went over: up to the card, and to be saved."""
        if box is None:
            self.upload()
        else:
            y0, y1, x0, x1 = (int(v) for v in box)
            y0, x0 = max(0, y0), max(0, x0)
            y1, x1 = min(self.height, y1), min(self.width, x1)
            if y1 > y0 and x1 > x0:
                self.device.queue.write_texture(
                    {"texture": self.texture, "origin": (x0, y0, 0)},
                    np.ascontiguousarray(self.array[y0:y1, x0:x1]),
                    {"bytes_per_row": (x1 - x0) * 4, "rows_per_image": y1 - y0},
                    (x1 - x0, y1 - y0, 1))
        self.dirty = True
        self.version += 1


class Rasters:
    """Every mask and paint of the stacks, by file name."""

    WHITE = (255, 255, 255, 255)
    CLEAR = (0, 0, 0, 0)

    def __init__(self, device, folder) -> None:
        self.device = device
        self.folder = Path(folder)
        self._held: dict = {}

    def get(self, name: str, size: tuple, fill) -> Raster:
        held = self._held.get(name)
        if held is not None and (held.width, held.height) == tuple(int(v) for v in size):
            return held
        made = Raster(self.device, name, size, fill)
        source = self.folder / name
        if source.exists():
            from PIL import Image
            try:
                with Image.open(source) as opened:
                    picture = opened.convert("RGBA")
                    if picture.size != (made.width, made.height):
                        picture = picture.resize((made.width, made.height), Image.BILINEAR)
                    made.array[...] = np.asarray(picture, np.uint8)
                    made.upload()
            except Exception:  # noqa: BLE001 -- a file that will not read starts afresh
                pass
        elif held is not None:
            from PIL import Image
            stretched = Image.fromarray(held.array).resize((made.width, made.height), Image.BILINEAR)
            made.array[...] = np.asarray(stretched, np.uint8)
            made.upload()
        self._held[name] = made
        return made

    def mask(self, layer, size: tuple) -> Raster:
        return self.get(layer.mask_raster, size, self.WHITE)

    def paint(self, effect, size: tuple) -> Raster:
        return self.get(effect.raster, size, self.CLEAR)

    def held(self, name: str):
        return self._held.get(name)

    def save(self) -> list:
        """Every changed one written to its file; their names."""
        written = []
        for name, raster in self._held.items():
            if not raster.dirty:
                continue
            from PIL import Image
            self.folder.mkdir(parents=True, exist_ok=True)
            Image.fromarray(raster.array).save(self.folder / name)
            raster.dirty = False
            written.append(name)
        return written
