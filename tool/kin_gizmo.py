"""Handles on what is chosen, in the 3D picture, and what dragging them does.

Which handles there are follows selection's size, 1 2 3:

  a ring      its jack (an arrow up), its pushers (an arrow out) and its
              tilts (an arc)
  a group     its pusher and its five tilts
  a cell      its tilt

A handle stands on the most frontal cell of what it moves -- a ring's shows
where the ring faces the camera -- and only there, so the far side of the
building gives none. Dragging one moves its own ring, group or cell; with
Shift, every one chosen by the same amount. The arrows go the way their
motor moves the cells on screen, up for a jack and out for a pusher; a
pusher pointing straight at the camera has no way on screen, and its arrow
then leans down and to the right, which is the way to pull it.

Everything is in the canvas's logical pixels, as the pointer's events are.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

import kin_model as km
from kinetic import PER_PUSHER, PER_ROW, ROWS

ARROW = 38.0                  # pixels
ARC_RADIUS = 20.0
ARC_SWEEP = np.radians(140.0)
REACH = 7.0                   # how near a handle a press has to be

# What a pixel of drag is worth, along its handle.
PIXELS_A_STATE = 45.0         # a jack moves a place every this many pixels
PUSH_A_PIXEL = 0.004          # 4 mm a pixel of a pusher's arrow
FALLBACK = np.array([0.70710678, 0.70710678])    # down and to the right

COLOUR = {"lift": (0.88, 0.38, 0.35, 0.95), "push": (0.37, 0.76, 0.48, 0.95),
          "tilt": (0.36, 0.58, 0.88, 0.95)}


@dataclass
class Handle:
    family: str                    # which motor it moves
    element: tuple                 # ("ring", r) / ("group", r, g) / ("cell", r, c)
    anchor: np.ndarray             # where it stands on screen
    way: np.ndarray = field(default_factory=lambda: np.zeros(2))  # arrow's unit
    tip: np.ndarray = field(default_factory=lambda: np.zeros(2))

    def near(self, point) -> bool:
        point = np.asarray(point, float)
        if self.family == "tilt":
            gap = point - self.anchor
            distance = float(np.hypot(*gap))
            angle = np.arctan2(-gap[1], gap[0])
            within = -ARC_SWEEP / 2 - 0.2 <= angle <= ARC_SWEEP / 2 + 0.2
            return abs(distance - ARC_RADIUS) <= REACH and within
        start, end = self.anchor, self.tip
        along = end - start
        t = float(np.clip(np.dot(point - start, along) / max(np.dot(along, along), 1e-9),
                          0.0, 1.0))
        return float(np.hypot(*(start + along * t - point))) <= REACH


def elements(cells: np.ndarray, grain: str) -> list:
    """The rings, groups or cells chosen, as elements."""
    cells = np.asarray(cells, bool).reshape(ROWS, PER_ROW)
    if grain == "ring":
        return [("ring", int(r)) for r in np.nonzero(cells.any(axis=1))[0]]
    if grain == "group":
        groups = cells.reshape(ROWS, -1, PER_PUSHER).any(axis=2)
        return [("group", int(r), int(g)) for r, g in zip(*np.nonzero(groups))]
    return [("cell", int(r), int(c)) for r, c in zip(*np.nonzero(cells))]


def element_cells(element: tuple) -> np.ndarray:
    cells = np.zeros((ROWS, PER_ROW), bool)
    if element[0] == "ring":
        cells[element[1]] = True
    elif element[0] == "group":
        _, ring, group = element
        cells[ring, group * PER_PUSHER:(group + 1) * PER_PUSHER] = True
    else:
        cells[element[1], element[2]] = True
    return cells


def families_of(element: tuple) -> tuple:
    return {"ring": ("lift", "push", "tilt"), "group": ("push", "tilt"),
            "cell": ("tilt",)}[element[0]]


def build(cells, grain: str, places, faces, frontal, radial_screen, index_of,
          most: int = 60) -> list:
    """The handles for what is chosen.

    `places` (N, 2) every cell's centre on screen and `faces` whether it
    faces the camera, in the renderer's order; `frontal` (N,) how squarely
    it does; `radial_screen` (N, 2) the way out from the building on screen,
    as long as it looks for a metre; `index_of` (ROWS, PER_ROW) -> renderer
    index. At most `most` elements get handles, the most frontal first.
    """
    handles = []
    chosen = elements(cells, grain)
    scored = []
    for element in chosen:
        mine = element_cells(element)
        if element[0] == "group":           # a group stands on its middle cell
            ring, group = element[1], element[2]
            mine = np.zeros_like(mine)
            mine[ring, group * PER_PUSHER + PER_PUSHER // 2] = True
        which = index_of[mine]
        which = which[faces[which]]
        if not len(which):
            continue
        best = int(which[np.argmax(frontal[which])])
        scored.append((float(frontal[best]), element, best))
    scored.sort(key=lambda one: -one[0])
    for _, element, best in scored[:most]:
        anchor = np.asarray(places[best], float)
        for family in families_of(element):
            if family == "lift":
                if element[1] == km.NO_JACK:
                    continue
                way = np.array([0.0, -1.0])
            elif family == "push":
                out = np.asarray(radial_screen[best], float)
                length = float(np.hypot(*out))
                way = out / length if length > 18.0 else FALLBACK
            else:
                handles.append(Handle("tilt", element, anchor))
                continue
            # Side by side, so the two arrows of a ring are both to hand.
            start = anchor + (np.array([-6.0, 0.0]) if family == "lift"
                              else np.array([6.0, 0.0]))
            handles.append(Handle(family, element, start, way, start + way * ARROW))
    return handles


def picked(handles: list, point):
    """The handle under a point, or None; the nearest one's family wins
    over a tilt's arc lying under an arrow."""
    for handle in handles:
        if handle.family != "tilt" and handle.near(point):
            return handle
    for handle in handles:
        if handle.family == "tilt" and handle.near(point):
            return handle
    return None


def amount(handle: Handle, start, now, fine: bool = False) -> float:
    """What a drag from `start` to `now` is worth, in the motor's own units:
    jack places, pusher travel, tilt value."""
    start, now = np.asarray(start, float), np.asarray(now, float)
    scale = 0.1 if fine else 1.0
    if handle.family == "lift":
        return float(np.round((start[1] - now[1]) / PIXELS_A_STATE))
    if handle.family == "push":
        return float(np.dot(now - start, handle.way)) * PUSH_A_PIXEL * scale
    # A tilt: the angle swept round the handle, as the hand turns it. Down
    # the arc -- clockwise on screen -- turns the face down, which is plus.
    a = np.arctan2(-(start - handle.anchor)[1], (start - handle.anchor)[0])
    b = np.arctan2(-(now - handle.anchor)[1], (now - handle.anchor)[0])
    turned = (b - a + np.pi) % (2 * np.pi) - np.pi
    return float(-np.degrees(turned)) * scale / 90.0


def draw(shapes, handles: list, hot=None) -> None:
    """The handles into an overlay's shapes; the one under the hand lit."""
    for handle in handles:
        colour = COLOUR[handle.family]
        if hot is not None and hot is handle:
            colour = (1.0, 1.0, 1.0, 1.0)
        if handle.family == "tilt":
            shapes.arc(handle.anchor, ARC_RADIUS, -ARC_SWEEP / 2, ARC_SWEEP, 3.0,
                       (0.0, 0.0, 0.0, 0.55))
            shapes.arc(handle.anchor, ARC_RADIUS, -ARC_SWEEP / 2, ARC_SWEEP, 2.0, colour)
            continue
        shapes.arrow(handle.anchor, handle.tip, 4.0, (0.0, 0.0, 0.0, 0.55), 11.0)
        shapes.arrow(handle.anchor, handle.tip, 2.2, colour, 9.0)
    for handle in handles:
        if handle.family == "tilt":
            shapes.disc(handle.anchor, 3.0, (1.0, 1.0, 1.0, 0.9))
