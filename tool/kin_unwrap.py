"""The honeycomb unrolled: fifty cells round, thirty rings up, all at once.

The 3D view shows the shape; this shows every motor. A cell is drawn where it
stands round the building -- azimuth across, ring up -- so neighbours on the
building are neighbours here, and the half-cell stagger between rings is the
building's own (the rows' origins differ by 18 degrees, two and a half cells).
The seam is put behind the building, so the middle of the strip is what the
file's camera looks at.

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
MARGIN_LEFT = 34
MARGIN = 10


def cell_places(front: float = 0.0) -> np.ndarray:
    """Every cell's (across, up) in cells: across 0..50 with `front`, the
    azimuth the camera looks at, in the middle; up 0 at the lowest ring."""
    azimuth = km.cell_azimuths()
    across = ((front + 180.0 - azimuth) % 360.0) / 360.0 * PER_ROW
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
        self.tool = "brush"            # brush | select
        self.radius = 2.5              # cells
        self.hardness = 0.5
        self.grain = "cell"            # cell | group | ring: what a click takes
        self._pressed = None
        self._box = None
        self._pointer = None

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

    # -- the layout -----------------------------------------------------------

    def _cell(self) -> float:
        """How wide a cell is drawn, in pixels, to fit the widget."""
        wide = (self.width() - MARGIN_LEFT - MARGIN) / (PER_ROW + 0.5)
        tall = (self.height() - 2 * MARGIN) / ((ROWS - 1) * RING_PITCH + 1.155)
        return max(2.0, min(wide, tall))

    def _origin(self, size: float):
        wide = (PER_ROW + 0.5) * size
        tall = ((ROWS - 1) * RING_PITCH + 1.155) * size
        left = MARGIN_LEFT + max(0.0, (self.width() - MARGIN_LEFT - MARGIN - wide) / 2)
        bottom = self.height() - MARGIN - max(
            0.0, (self.height() - 2 * MARGIN - tall) / 2) - 0.577 * size
        return left + 0.5 * size, bottom

    def to_screen(self, across: float, up: float) -> QPointF:
        size = self._cell()
        left, bottom = self._origin(size)
        return QPointF(left + across * size, bottom - up * size)

    def to_cells(self, point: QPointF):
        size = self._cell()
        left, bottom = self._origin(size)
        return ((point.x() - left) / size, (bottom - point.y()) / size)

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
        for row in range(ROWS):
            for which in range(PER_ROW):
                centre = self.to_screen(*self.places[row, which])
                fill = QColor(*colours[row, which])
                weight = over[row, which, 3]
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
                brush.drawPolygon(QPolygonF([centre + one for one in hexagon]))
        # The rings, numbered as the file numbers them, beside the strip --
        # every one when there is room, the first of every five when not.
        brush.setFont(theme.mono(7.5))
        brush.setPen(QPen(QColor(theme.QUIET)))
        left = max(30.0, self.to_screen(0, 0).x() - size)
        crowded = size * RING_PITCH < 12
        for row in range(ROWS):
            if crowded and row % 5 and row != ROWS - 1:
                continue
            y = self.to_screen(0, row * RING_PITCH).y()
            brush.drawText(QRectF(left - 30, y - 7, 26, 14),
                           Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                           str(row + 1))
        if self._box is not None:
            first, last = self._box
            brush.setPen(QPen(QColor(theme.LINE), 1, Qt.PenStyle.DashLine))
            brush.setBrush(QColor(106, 166, 222, 30))
            brush.drawRect(QRectF(first, last).normalized())
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
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = event.position()
        self._pressed = point
        if self.tool == "brush":
            self.stroke_started.emit()
            self.dabbed.emit(self._weights(point))
        else:
            self._box = (point, point)
            self.update()

    def mouseMoveEvent(self, event) -> None:    # noqa: N802
        point = event.position()
        self._pointer = point
        got = self.cell_at(point)
        self.hovered.emit(*(got if got else (-1, -1)))
        if self._pressed is not None:
            if self.tool == "brush":
                self.dabbed.emit(self._weights(point))
            else:
                self._box = (self._pressed, point)
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self._pressed is None:
            return
        point = event.position()
        if self.tool == "brush":
            self.stroke_finished.emit()
        else:
            first = self._pressed
            if (point - first).manhattanLength() < 4:
                cells = np.zeros((ROWS, PER_ROW), bool)
                got = self.cell_at(point)
                if got is not None:
                    cells[got] = True
            else:
                low = self.to_cells(QPointF(min(first.x(), point.x()),
                                            max(first.y(), point.y())))
                high = self.to_cells(QPointF(max(first.x(), point.x()),
                                             min(first.y(), point.y())))
                across, up = self.places[..., 0], self.places[..., 1]
                cells = ((across >= low[0] - 0.5) & (across <= high[0] + 0.5)
                         & (up >= low[1] - 0.5) & (up <= high[1] + 0.5))
            self.selected.emit(self._grain(cells), self._how(event))
            self._box = None
        self._pressed = None
        self.update()

    def leaveEvent(self, event) -> None:         # noqa: N802
        self._pointer = None
        self.hovered.emit(-1, -1)
        self.update()

    def wheelEvent(self, event) -> None:         # noqa: N802
        if self.tool != "brush":
            return
        steps = event.angleDelta().y() / 120.0
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.radius = float(np.clip(self.radius * (1.15 ** steps), 0.5, 25.0))
            self.update()
            self.setToolTip(tr("Кисть {0:.1f} соты", self.radius))
