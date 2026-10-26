"""The stacks of layers the advanced mode lays over the screens.

One stack a screen -- Top, Bottom, Lamels -- bottom first, over the screen's
own source. A layer is a picture or a folder of layers; it is shown or not,
has an opacity and a way of lying on what is under it:

  Norm   over it, as paint
  Mult   multiplied: darkens, white leaves it be
  Scrn   screen: lightens, black leaves it be
  Ovrl   overlay: multiply in the shadows, screen in the lights of what is under
  Add    added light
  Diff   the difference
  Soft   soft light

The sums are the W3C compositing ones on premultiplied colour, the same as
Photoshop, Substance and the browsers: `blend` below is the reference the
graphics card's pass (layer_gpu) is held to. A folder's layers are laid
together first, on nothing, and the folder then lies as one layer.

Kept with the settings as plain data, paths and all.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field

import numpy as np

BLENDS = ("normal", "multiply", "screen", "overlay", "add", "difference", "soft")
SHORT = {"normal": "Norm", "multiply": "Mult", "screen": "Scrn", "overlay": "Ovrl",
         "add": "Add", "difference": "Diff", "soft": "Soft"}
SCREENS = ("Top", "Bottom", "Lamels")
_ids = itertools.count(1)


@dataclass
class Layer:
    kind: str                       # image | folder
    name: str
    path: str = ""
    visible: bool = True
    opacity: float = 1.0
    blend: str = "normal"
    children: list = field(default_factory=list)
    open: bool = True
    # Where a picture lies, from fitted whole and centred: moved by x, y
    # pixels of the frame, scaled about its middle, turned clockwise by
    # `rotation` degrees, mirrored left to right.
    x: float = 0.0
    y: float = 0.0
    scale: float = 1.0
    rotation: float = 0.0
    flip: bool = False
    # Laid on the building as the audience sees it from the file's camera,
    # instead of on the screen's frame; x, y then count pixels of the
    # camera's 9:16 picture, y upwards.
    remap: bool = False
    ident: int = field(default_factory=lambda: next(_ids))

    def fit(self) -> None:
        """Back to fitted whole and centred."""
        self.x = self.y = self.rotation = 0.0
        self.scale = 1.0
        self.flip = False

    def to_dict(self) -> dict:
        out = {"kind": self.kind, "name": self.name, "path": self.path,
               "visible": self.visible, "opacity": round(float(self.opacity), 4),
               "blend": self.blend, "open": self.open}
        if self.kind == "image":
            out.update(x=round(self.x, 3), y=round(self.y, 3), scale=round(self.scale, 5),
                       rotation=round(self.rotation, 4), flip=self.flip, remap=self.remap)
        if self.kind == "folder":
            out["children"] = [one.to_dict() for one in self.children]
        return out

    @classmethod
    def from_dict(cls, raw: dict) -> "Layer":
        kind = raw.get("kind", "image")
        made = cls(kind=kind if kind in ("image", "folder") else "image",
                   name=str(raw.get("name") or ""), path=str(raw.get("path") or ""),
                   visible=bool(raw.get("visible", True)),
                   opacity=float(max(0.0, min(1.0, raw.get("opacity", 1.0)))),
                   blend=raw.get("blend") if raw.get("blend") in BLENDS else "normal",
                   open=bool(raw.get("open", True)),
                   x=float(raw.get("x", 0.0)), y=float(raw.get("y", 0.0)),
                   scale=float(raw.get("scale", 1.0)) or 1.0,
                   rotation=float(raw.get("rotation", 0.0)), flip=bool(raw.get("flip", False)),
                   remap=bool(raw.get("remap", False)))
        if made.kind == "folder":
            made.children = [cls.from_dict(one) for one in raw.get("children") or []]
        return made


class Stacks:
    """Every screen's stack, and the moves made on them."""

    def __init__(self) -> None:
        self.screens = {name: [] for name in SCREENS}

    def stack(self, screen: str) -> list:
        return self.screens.setdefault(screen, [])

    def _walk(self, items):
        for one in items:
            yield one, items
            if one.kind == "folder":
                yield from self._walk(one.children)

    def find(self, layer):
        """(screen, the list it is in) of a layer, or (None, None)."""
        for screen, items in self.screens.items():
            for one, holder in self._walk(items):
                if one is layer:
                    return screen, holder
        return None, None

    def contains(self, folder, layer) -> bool:
        return folder.kind == "folder" and any(one is layer for one, _ in self._walk(folder.children))

    def add(self, screen: str, layer, near=None) -> None:
        """On top of the stack, or just above `near` in its own list."""
        if near is not None:
            _, holder = self.find(near)
            if holder is not None:
                holder.insert(holder.index(near) + 1, layer)
                return
        self.stack(screen).append(layer)

    def remove(self, layer) -> None:
        _, holder = self.find(layer)
        if holder is not None:
            holder.remove(layer)

    def move(self, layer, target, where: str) -> bool:
        """`layer` above, below or into `target` ('above' / 'below' / 'in').
        Not into itself or what it holds; not across screens."""
        if layer is target or self.contains(layer, target):
            return False
        here, _ = self.find(layer)
        there, holder = self.find(target)
        if here is None or here != there:
            return False
        self.remove(layer)
        if where == "in" and target.kind == "folder":
            target.children.append(layer)
            target.open = True
            return True
        _, holder = self.find(target)
        at = holder.index(target) + (1 if where == "above" else 0)
        holder.insert(at, layer)
        return True

    def to_dict(self) -> dict:
        return {name: [one.to_dict() for one in items] for name, items in self.screens.items() if items}

    @classmethod
    def from_dict(cls, raw) -> "Stacks":
        made = cls()
        for name, items in (raw or {}).items():
            if name in SCREENS and isinstance(items, list):
                made.screens[name] = [Layer.from_dict(one) for one in items if isinstance(one, dict)]
        return made

    def shown(self, screen: str) -> list:
        """What is to be drawn: the visible ones, folders and all."""
        def keep(items):
            out = []
            for one in items:
                if not one.visible or one.opacity <= 0.0:
                    continue
                if one.kind == "folder":
                    inner = keep(one.children)
                    if inner:
                        out.append((one, inner))
                elif one.path:
                    out.append((one, None))
            return out
        return keep(self.stack(screen))


# -- the sums, for holding the graphics card to -------------------------------------

def _mix(cb, cs, mode):
    """The blend function B(Cb, Cs) on straight colour."""
    if mode == "multiply":
        return cb * cs
    if mode == "screen":
        return cb + cs - cb * cs
    if mode == "overlay":
        return np.where(cb <= 0.5, 2.0 * cb * cs, 1.0 - 2.0 * (1.0 - cb) * (1.0 - cs))
    if mode == "difference":
        return np.abs(cb - cs)
    if mode == "soft":
        d = np.where(cb <= 0.25, ((16.0 * cb - 12.0) * cb + 4.0) * cb, np.sqrt(np.maximum(cb, 0.0)))
        return np.where(cs <= 0.5, cb - (1.0 - 2.0 * cs) * cb * (1.0 - cb),
                        cb + (2.0 * cs - 1.0) * (d - cb))
    return cs


def blend(base: np.ndarray, top: np.ndarray, mode: str, opacity: float = 1.0) -> np.ndarray:
    """One layer laid over what is under it, on premultiplied (h, w, 4) floats."""
    top = top * opacity
    a_s, a_b = top[..., 3:4], base[..., 3:4]
    cs, cb = top[..., :3], base[..., :3]
    if mode == "add":
        return np.concatenate([cs + cb, np.minimum(a_s + a_b, 1.0)], axis=-1)
    if mode == "normal":
        rgb = cs + cb * (1.0 - a_s)
    else:
        straight_s = np.divide(cs, a_s, out=np.zeros_like(cs), where=a_s > 0)
        straight_b = np.divide(cb, a_b, out=np.zeros_like(cb), where=a_b > 0)
        rgb = cs * (1.0 - a_b) + cb * (1.0 - a_s) + a_s * a_b * _mix(straight_b, straight_s, mode)
    return np.concatenate([rgb, a_s + a_b * (1.0 - a_s)], axis=-1)
