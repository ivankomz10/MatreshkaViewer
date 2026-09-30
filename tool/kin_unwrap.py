"""The honeycomb unrolled: fifty cells round, thirty rings up, all at once.

The 3D view shows the shape; this shows every motor. A cell is drawn where it
stands round the building -- azimuth across, ring up -- so neighbours on the
building are neighbours here, and the half-cell stagger between rings is the
building's own (the rows' origins differ by 18 degrees, two and a half cells).
The seam is put behind the building, so the middle of the strip is what the
file's camera looks at.

Down the left, by each ring's number, its jack: four steps, as many lit as
the gap under the ring is open. Click one to put the jack there, or draw
down the column to put a run of rings there at once. The lowest ring stands
on the base and has none.

With the primitives' tool, a press puts the chosen primitive where it is
pressed, and a drag carries it; its centre is ringed.

Distances are in cells: across, one cell is 7.2 degrees; up, one ring is
0.866 of that, the honeycomb's own pitch (27.8 cm over 31.8 cm on the
building). The brush and the selection are both measured in them, which is
what lets the 3D view hand its dabs to the same arithmetic.
"""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

import kin_model as km
import theme
from kinetic import PER_PUSHER, PER_ROW, ROWS
from lang import tr

RING_PITCH = math.sqrt(3.0) / 2.0     # one ring, in cells across
FAMILY_COLOUR_LIFT = "#e0605a"        # the jacks' red, as on the timeline
NUMBERS = 24                          # the rings' numbers
JACKS = (28, 76)                      # the jacks' column, left to right
MARGIN_LEFT = 84
MARGIN = 10


def cell_places(front: float = 0.0) -> np.ndarray:
    """Every cell's (across, up) in cells: across 0..50 with `front`, the
    azimuth the camera looks at, in the middle; up 0 at the lowest ring.
    Across runs the way the azimuth does -- left to right as the building
    is seen from outside, and as its picture runs -- not mirrored as from
    within."""
    azimuth = km.cell_azimuths()
    across = ((azimuth - front + 180.0) % 360.0) / 360.0 * PER_ROW
    up = np.repeat(np.arange(ROWS, dtype=np.float64)[:, None], PER_ROW,
                   axis=1) * RING_PITCH
    return np.stack([across, up], axis=-1)


def brush_weights(places: np.ndarray, centre, radius: float,
                  hardness: float = 0.5) -> np.ndarray:
    """How much of a round brush each cell is under, 0..1, (ROWS, PER_ROW).

    Across wraps: the strip is a ring, and a brush on its edge reaches round.
    Full strength inside `hardness` of the radius, easing to nothing at it.
    """
    across = places[..., 0] - centre[0]
    across = (across + PER_ROW / 2.0) % PER_ROW - PER_ROW / 2.0
    up = places[..., 1] - centre[1]
    distance = np.hypot(across, up) / max(radius, 1e-6)
    core = min(max(hardness, 0.0), 0.99)
    fall = np.clip((distance - core) / (1.0 - core), 0.0, 1.0)
    weight = 1.0 - fall * fall * (3.0 - 2.0 * fall)
    return np.where(distance <= 1.0, weight, 0.0).astype(np.float32)


class Unwrap(QWidget):
    """The strip: painted cells, a brush and a selection, and the mouse."""

    stroke_started = Signal()
    dabbed = Signal(object)            # (ROWS, PER_ROW) weights
    stroke_finished = Signal()
    selected = Signal(object, str)     # (ROWS, PER_ROW) bool, how: set/add/take
    hovered = Signal(int, int)         # row, id -- or -1, -1
    radius_changed = Signal(float)     # the brush, sized with Ctrl+wheel here
    jacks_started = Signal()
    jack_set = Signal(int, int)        # ring, state
    jacks_finished = Signal()
    view_changed = Signal()            # zoomed or moved: the vase follows
    placed = Signal(float, float)      # the primitives' tool: azimuth, ring

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("qa_unwrap")
        self.setMouseTracking(True)
        self.setMinimumHeight(180)
        self.front = 0.0
        self.places = cell_places(self.front)
        self.colours = np.full((ROWS, PER_ROW, 3), 0.25, np.float32)
        self.over = np.zeros((ROWS, PER_ROW, 4), np.float32)
        self.selection = np.zeros((ROWS, PER_ROW), bool)
        self.warn = np.zeros((ROWS, PER_ROW), bool)
        self.lag = np.zeros((ROWS, PER_ROW), bool)
        self.tool = "brush"            # brush | select | place
        self.marker = None             # the chosen primitive's centre, (across, up)
        self.picture = None            # the video on the cells, a QImage, or None
        self.radius = 2.5              # cells
        self.hardness = 0.5
        self.grain = "cell"            # cell | group | ring: what a click takes
        # The view: how far in, and which point of the strip is in the middle,
        # in cells. Across it wraps -- the strip is a ring, and dragging it
        # along goes on round the building for as long as the hand does.
        self.zoom = 1.0
        self.centre = self._home()
        self._pressed = None
        self._box = None
        self._pointer = None
        self._panning = None
        self.lift = np.full(ROWS, km.REST["lift"], np.float32)
        self._jacking = None               # the state a drag down the column puts

    # -- what the window hands over ------------------------------------------

    def set_front(self, azimuth: float) -> None:
        self.front = float(azimuth)
        self.places = cell_places(self.front)
        self.update()

    def set_colours(self, colours, over=None, warn=None, lag=None) -> None:
        """What each cell is painted, what is laid over it, which are past
        their limit (ringed red), and which the motors have left behind the
        keys (ringed orange)."""
        self.colours = np.asarray(colours, np.float32).reshape(ROWS, PER_ROW, 3)
        if over is not None:
            self.over = np.asarray(over, np.float32).reshape(ROWS, PER_ROW, 4)
        if warn is not None:
            self.warn = np.asarray(warn, bool).reshape(ROWS, PER_ROW)
        self.lag = (np.zeros((ROWS, PER_ROW), bool) if lag is None
                    else np.asarray(lag, bool).reshape(ROWS, PER_ROW))
        self.update()

    def set_selection(self, cells) -> None:
        self.selection = np.asarray(cells, bool).reshape(ROWS, PER_ROW)
        self.update()

    def set_picture(self, image) -> None:
        """The cells as the video paints them -- each its own patch of the
        picture -- drawn under the outlines; None for the flat colours."""
        self.picture = image
        self.update()

    def view(self) -> tuple:
        """What a picture of the strip is drawn for: (centre, middle, pixels
        a cell, width, height), in the widget's own pixels."""
        middle = self._middle()
        return ((float(self.centre[0]), float(self.centre[1])),
                (middle.x(), middle.y()), self._cell(), self.width(), self.height())

    def set_marker(self, azimuth=None, ring=None) -> None:
        """Where the chosen primitive stands, drawn as a ring; None for none."""
        if azimuth is None:
            self.marker = None
        else:
            across = ((azimuth - self.front + 180.0) % 360.0) / 360.0 * PER_ROW
            self.marker = (across, float(ring) * RING_PITCH)
        self.update()

    def spot(self, point: QPointF):
        """(azimuth in degrees, ring) of a point on the widget: where a
        primitive put there stands."""
        across, up = self.to_cells(point)
        return ((self.front - 180.0 + across / PER_ROW * 360.0) % 360.0,
                up / RING_PITCH)

    def set_lift(self, lift) -> None:
        """Where each ring's jack stands now, for its column."""
        self.lift = np.asarray(lift, np.float32).reshape(ROWS)
        self.update()

    # -- the layout -----------------------------------------------------------

    @staticmethod
    def _home() -> list:
        """The middle of the strip: the front across, half way up."""
        return [PER_ROW / 2.0, (ROWS - 1) * RING_PITCH / 2.0]

    def _fit(self) -> float:
        """How wide a cell is when the whole strip fits the widget."""
        wide = (self.width() - MARGIN_LEFT - MARGIN) / (PER_ROW + 0.5)
        tall = (self.height() - 2 * MARGIN) / ((ROWS - 1) * RING_PITCH + 1.155)
        return max(2.0, min(wide, tall))

    def _cell(self) -> float:
        """How wide a cell is drawn, in pixels, at this zoom."""
        return self._fit() * self.zoom

    def _middle(self) -> QPointF:
        """Where on the widget the view's centre is drawn."""
        return QPointF(MARGIN_LEFT + (self.width() - MARGIN_LEFT - MARGIN) / 2.0,
                       self.height() / 2.0)

    def _hold(self) -> None:
        """Keep the view on the strip: round and round across, but up and
        down no further than its first and last rings."""
        self.centre[0] %= PER_ROW
        size = self._cell()
        half = (self.height() / 2.0 - MARGIN) / size
        top = (ROWS - 1) * RING_PITCH
        low, high = half - 0.6, top - half + 0.6
        mid = top / 2.0
        self.centre[1] = mid if low > high else min(high, max(low, self.centre[1]))

    def to_screen(self, across: float, up: float) -> QPointF:
        """A point of the strip on the widget, at its copy nearest the view."""
        size = self._cell()
        middle = self._middle()
        gap = (across - self.centre[0] + PER_ROW / 2.0) % PER_ROW - PER_ROW / 2.0
        return QPointF(middle.x() + gap * size,
                       middle.y() - (up - self.centre[1]) * size)

    def to_cells(self, point: QPointF):
        size = self._cell()
        middle = self._middle()
        across = (self.centre[0] + (point.x() - middle.x()) / size) % PER_ROW
        return (across, self.centre[1] - (point.y() - middle.y()) / size)

    def screen_places(self) -> np.ndarray:
        """Every cell's middle on the widget, (ROWS, PER_ROW, 2)."""
        size = self._cell()
        middle = self._middle()
        gap = ((self.places[..., 0] - self.centre[0] + PER_ROW / 2.0) % PER_ROW
               - PER_ROW / 2.0)
        return np.stack([middle.x() + gap * size,
                         middle.y() - (self.places[..., 1] - self.centre[1]) * size],
                        axis=-1)

    def reset_view(self) -> None:
        self.zoom = 1.0
        self.centre = self._home()
        self.update()
        self.view_changed.emit()

    def zoom_at(self, point: QPointF, factor: float) -> None:
        """In or out, keeping the cell under the pointer where it is."""
        held = self.to_cells(point)
        self.zoom = float(min(10.0, max(1.0, self.zoom * factor)))
        size = self._cell()
        middle = self._middle()
        self.centre = [held[0] - (point.x() - middle.x()) / size,
                       held[1] + (point.y() - middle.y()) / size]
        if self.zoom == 1.0:
            self.centre[1] = self._home()[1]
        self._hold()
        self.update()
        self.view_changed.emit()

    def _ring_at(self, y: float):
        """The ring drawn at a height on the widget, or None."""
        ring = int(round(self.to_cells(QPointF(MARGIN_LEFT, y))[1] / RING_PITCH))
        return ring if 0 <= ring < ROWS else None

    def cell_at(self, point: QPointF):
        """(row, id) under a point, or None."""
        across, up = self.to_cells(point)
        row = int(round(up / RING_PITCH))
        if not 0 <= row < ROWS:
            return None
        gaps = (self.places[row, :, 0] - across + PER_ROW / 2) % PER_ROW - PER_ROW / 2
        which = int(np.argmin(np.abs(gaps)))
        if abs(gaps[which]) > 0.6 or abs(up - row * RING_PITCH) > 0.6:
            return None
        return row, which

    # -- drawing -----------------------------------------------------------------

    def paintEvent(self, event) -> None:      # noqa: N802
        brush = QPainter(self)
        brush.setRenderHint(QPainter.RenderHint.Antialiasing)
        brush.fillRect(self.rect(), QColor(theme.DEEP))
        size = self._cell()
        radius = size * 0.577 * 0.94
        hexagon = [QPointF(radius * math.cos(math.radians(90 + 60 * k)),
                           radius * math.sin(math.radians(90 + 60 * k)))
                   for k in range(6)]
        colours = np.clip(self.colours * 255.0, 0, 255).astype(int)
        over = self.over
        screen = self.screen_places()
        reach_x, reach_y = self.width() + size, self.height() + size
        pictured = self.picture is not None
        if pictured:
            brush.drawImage(QRectF(0, 0, self.width(), self.height()), self.picture)
        for row in range(ROWS):
            for which in range(PER_ROW):
                x, y = screen[row, which]
                if x < MARGIN_LEFT - size or x > reach_x or y < -size or y > reach_y:
                    continue
                centre = QPointF(x, y)
                weight = over[row, which, 3]
                if pictured:
                    # The picture is there already: only what lies over it.
                    if weight > 0.0:
                        lay = np.clip(over[row, which, :3] * 255.0, 0, 255).astype(int)
                        brush.setBrush(QColor(*lay, int(weight * 255)))
                    else:
                        brush.setBrush(Qt.BrushStyle.NoBrush)
                else:
                    fill = QColor(*colours[row, which])
                    if weight > 0.0:
                        lay = over[row, which, :3]
                        mixed = colours[row, which] * (1 - weight) + lay * 255.0 * weight
                        fill = QColor(*np.clip(mixed, 0, 255).astype(int))
                    brush.setBrush(fill)
                if self.selection[row, which]:
                    brush.setPen(QPen(QColor("#ffffff"), max(1.0, size * 0.1)))
                elif self.warn[row, which]:
                    brush.setPen(QPen(QColor(theme.ERROR), max(1.0, size * 0.12)))
                elif self.lag[row, which]:
                    brush.setPen(QPen(QColor(theme.WARN), max(1.0, size * 0.1)))
                else:
                    brush.setPen(Qt.PenStyle.NoPen)
                    if pictured and weight <= 0.0:
                        continue
                brush.drawPolygon(QPolygonF([centre + one for one in hexagon]))
        # The rings, numbered as the file numbers them, down a column of their
        # own that stays put however the strip is moved -- every one when
        # there is room, the first of every five when not.
        brush.fillRect(QRectF(0, 0, MARGIN_LEFT - 4, self.height()), QColor(theme.DEEP))
        brush.setFont(theme.mono(7.5))
        crowded = size * RING_PITCH < 12
        tall = max(3.0, min(size * RING_PITCH * 0.72, 11.0))
        lit = QColor(FAMILY_COLOUR_LIFT)
        dim = QColor(theme.RAISED)
        step = (JACKS[1] - JACKS[0]) / 4.0
        for row in range(ROWS):
            y = self.to_screen(0, row * RING_PITCH).y()
            if not -8 <= y <= self.height() + 8:
                continue
            if not crowded or row % 5 == 0 or row == ROWS - 1:
                brush.setPen(QPen(QColor(theme.QUIET)))
                brush.drawText(QRectF(0, y - 7, NUMBERS, 14),
                               Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                               str(row + 1))
            # The jack: four steps, as many lit as it stands at -- part of
            # one between two places, while it moves.
            brush.setPen(Qt.PenStyle.NoPen)
            state = float(self.lift[row])
            for place in range(4):
                box = QRectF(JACKS[0] + place * step + 0.5, y - tall / 2,
                             step - 1.5, tall)
                if row == km.NO_JACK:
                    brush.setBrush(QColor(theme.LANE_EDGE))
                    brush.drawRect(box)
                    continue
                brush.setBrush(dim)
                brush.drawRect(box)
                share = min(1.0, max(0.0, state - place + 1.0)) if place else 0.0
                if place == 0 and state >= 0:
                    share = 1.0 if state < 0.5 else 0.0
                    if share:
                        brush.setBrush(QColor(theme.QUIET))
                        brush.drawRect(box)
                    continue
                if share > 0:
                    brush.setBrush(lit)
                    brush.drawRect(QRectF(box.left(), box.top(),
                                          box.width() * share, box.height()))
        if self.zoom > 1.001:
            brush.setFont(theme.mono(7.5))
            brush.setPen(QPen(QColor(theme.DIM)))
            brush.drawText(QRectF(self.width() - 90, self.height() - 18, 84, 14),
                           Qt.AlignmentFlag.AlignRight, f"×{self.zoom:.1f}")
        if self._box is not None:
            first, last = self._box
            brush.setPen(QPen(QColor(theme.LINE), 1, Qt.PenStyle.DashLine))
            brush.setBrush(QColor(106, 166, 222, 30))
            brush.drawRect(QRectF(first, last).normalized())
        if self.marker is not None:
            centre = self.to_screen(*self.marker)
            reach = max(6.0, size * 0.9)
            brush.setBrush(Qt.BrushStyle.NoBrush)
            brush.setPen(QPen(QColor(0, 0, 0, 160), 4))
            brush.drawEllipse(centre, reach, reach)
            brush.setPen(QPen(QColor("#ffffff"), 2))
            brush.drawEllipse(centre, reach, reach)
            brush.drawLine(QPointF(centre.x() - reach * 0.5, centre.y()),
                           QPointF(centre.x() + reach * 0.5, centre.y()))
            brush.drawLine(QPointF(centre.x(), centre.y() - reach * 0.5),
                           QPointF(centre.x(), centre.y() + reach * 0.5))
        if self.tool == "brush" and self._pointer is not None:
            brush.setPen(QPen(QColor(255, 255, 255, 200), 1))
            brush.setBrush(Qt.BrushStyle.NoBrush)
            reach = self.radius * size
            brush.drawEllipse(self._pointer, reach, reach)
            brush.setPen(QPen(QColor(255, 255, 255, 90), 1, Qt.PenStyle.DotLine))
            core = reach * min(max(self.hardness, 0.0), 0.99)
            if core > 2:
                brush.drawEllipse(self._pointer, core, core)
        brush.end()

    # -- the mouse ------------------------------------------------------------------

    def _weights(self, point: QPointF) -> np.ndarray:
        return brush_weights(self.places, self.to_cells(point), self.radius,
                             self.hardness)

    def _grain(self, cells: np.ndarray) -> np.ndarray:
        """A click's cells grown to what it takes: a group, or a ring."""
        if self.grain == "ring":
            return np.repeat(cells.any(axis=1, keepdims=True), PER_ROW, axis=1)
        if self.grain == "group":
            groups = cells.reshape(ROWS, -1, PER_PUSHER).any(axis=2)
            return np.repeat(groups, PER_PUSHER, axis=1)
        return cells

    def _how(self, event) -> str:
        mods = event.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            return "take"
        if mods & Qt.KeyboardModifier.ShiftModifier:
            return "add"
        return "set"

    def mousePressEvent(self, event) -> None:   # noqa: N802
        if event.button() == Qt.MouseButton.RightButton:
            # The right hand moves the strip, as it moves the timeline.
            self._panning = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = event.position()
        if JACKS[0] - 2 <= point.x() <= JACKS[1] + 2:
            ring = self._ring_at(point.y())
            if ring is not None and ring != km.NO_JACK:
                step = (JACKS[1] - JACKS[0]) / 4.0
                self._jacking = int(min(3, max(0, (point.x() - JACKS[0]) // step)))
                self._jacked = {ring}
                self.jacks_started.emit()
                self.jack_set.emit(ring, self._jacking)
            return
        self._pressed = point
        if self.tool == "brush":
            self.stroke_started.emit()
            self.dabbed.emit(self._weights(point))
        elif self.tool == "place":
            self.stroke_started.emit()
            self.placed.emit(*self.spot(point))
        else:
            self._box = (point, point)
            self.update()

    def mouseMoveEvent(self, event) -> None:    # noqa: N802
        point = event.position()
        if self._panning is not None:
            size = self._cell()
            moved = point - self._panning
            self._panning = point
            self.centre[0] -= moved.x() / size
            self.centre[1] += moved.y() / size
            self._hold()
            self.update()
            self.view_changed.emit()
            return
        if self._jacking is not None:
            ring = self._ring_at(point.y())
            if ring is not None and ring != km.NO_JACK and ring not in self._jacked:
                self._jacked.add(ring)
                self.jack_set.emit(ring, self._jacking)
            return
        self._pointer = point
        got = self.cell_at(point)
        self.hovered.emit(*(got if got else (-1, -1)))
        if self._pressed is not None:
            if self.tool == "brush":
                self.dabbed.emit(self._weights(point))
            elif self.tool == "place":
                self.placed.emit(*self.spot(point))
            else:
                self._box = (self._pressed, point)
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.RightButton and self._panning is not None:
            self._panning = None
            self.unsetCursor()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._jacking is not None:
            self._jacking = None
            self.jacks_finished.emit()
            return
        if event.button() != Qt.MouseButton.LeftButton or self._pressed is None:
            return
        point = event.position()
        if self.tool in ("brush", "place"):
            self.stroke_finished.emit()
        else:
            first = self._pressed
            if (point - first).manhattanLength() < 4:
                cells = np.zeros((ROWS, PER_ROW), bool)
                got = self.cell_at(point)
                if got is not None:
                    cells[got] = True
            else:
                # On the widget rather than on the strip: a box may straddle
                # the seam, and the cells either side of it are neighbours.
                box = QRectF(first, point).normalized()
                reach = self._cell() * 0.5
                screen = self.screen_places()
                cells = ((screen[..., 0] >= box.left() - reach)
                         & (screen[..., 0] <= box.right() + reach)
                         & (screen[..., 1] >= box.top() - reach)
                         & (screen[..., 1] <= box.bottom() + reach))
            self.selected.emit(self._grain(cells), self._how(event))
            self._box = None
        self._pressed = None
        self.update()

    def leaveEvent(self, event) -> None:         # noqa: N802
        self._pointer = None
        self.hovered.emit(-1, -1)
        self.update()

    def wheelEvent(self, event) -> None:         # noqa: N802
        steps = event.angleDelta().y() / 120.0
        if (event.modifiers() & Qt.KeyboardModifier.ControlModifier
                and self.tool == "brush"):
            self.radius = float(np.clip(self.radius * (1.15 ** steps), 0.5, 25.0))
            self.radius_changed.emit(self.radius)
            self.update()
            self.setToolTip(tr("Кисть {0:.1f} соты", self.radius))
            return
        if steps:
            self.zoom_at(event.position(), 1.2 ** steps)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.RightButton:
            self.reset_view()
            return
        super().mouseDoubleClickEvent(event)

    def resizeEvent(self, event) -> None:        # noqa: N802
        self._hold()
        super().resizeEvent(event)
        self.view_changed.emit()
