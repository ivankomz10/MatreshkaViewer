"""PROTOTYPE -- throwaway. The timeline for the Matreshka viewer.

One layout now: a row per level, the preview above, everything that is not
the timeline itself down the right-hand column.

  превью        what would be on each screen at this frame, and the keys
  луп           a strip of its own with the LOOP switch at its head
  линейка       the playhead, and the only place it is dragged
  дорожки       a row per level, per screen
  справа        the loop's own controls, then the selected clip's

The mouse:
  left      select a clip; drag it to move it. Empty space deselects.
  right     drag to scroll the timeline, without touching the playhead
  middle    click to teleport the playhead there
  wheel     zoom;  Shift+wheel scroll

Real shows, read from D:\\Content\\_SHOW. Nothing is ever written back: dragging
a clip moves it in memory and the next reload forgets it.

Run:   tool\\proto_timeline\\run.bat
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal   # noqa: E402
from PySide6.QtGui import (QColor, QFont, QFontMetrics,        # noqa: E402
                           QPainter, QPen)
from PySide6.QtWidgets import (QApplication, QComboBox,        # noqa: E402
                               QGridLayout, QHBoxLayout, QLabel, QMainWindow,
                               QPushButton, QSizePolicy, QSpinBox,
                               QVBoxLayout, QWidget)

import show as showfile                                        # noqa: E402

MONO = "Consolas, DejaVu Sans Mono, monospace"

SHEET = """
QWidget { background:#1e1e1e; color:#dcdcdc; font-size:12px; }
QLabel { color:#dcdcdc; }
QPushButton { background:#2d2d2d; border:1px solid #3c3c3c; padding:3px 6px; }
QPushButton:hover { background:#383838; }
QPushButton:checked { background:#c9a227; color:#1a1a1a; border-color:#e0b830; }
QComboBox { background:#2d2d2d; border:1px solid #3c3c3c; padding:2px 6px; }
QComboBox QAbstractItemView { background:#252525; selection-background-color:#3d5a72; }
QSpinBox { background:#2d2d2d; border:1px solid #3c3c3c; padding:1px 3px; }
"""

ROWS = ["Top", "Bottom", "Lamels", "Sound", "Kinetic", "Cue"]
HUE = {"Top": "#4a7ea8", "Bottom": "#4a9c78", "Lamels": "#a88a4a",
       "Sound": "#7a5aa8", "Kinetic": "#a85a5a", "Cue": "#c9a227"}
# Three content levels per screen. The black backdrop that sits on level 3 of
# every show file is not a clip here: the viewer chooses its own backing.
LEVELS = {"Top": 3, "Bottom": 3, "Lamels": 3, "Sound": 2, "Kinetic": 1,
          "Cue": 1}
HEAD = 74            # the width of the labels down the left of every strip

KEYS = [
    ("Space", "играть / пауза"),
    ("← →", "кадр назад / вперёд"),
    ("Shift+← →", "секунда назад / вперёд"),
    ("I / O", "на начало / конец клипа"),
    ("[ / ]", "клип слева / справа от плейхеда"),
    ("L", "лупы держат / отпустить"),
    ("Shift+L", "луп на весь клип"),
    ("Shift+тащить", "перенести луп целиком"),
    ("K", "запереть лупы"),
    ("Home / End", "в начало / в конец"),
    ("F", "вся длина"),
]


class Axis:
    """Where time sits on the screen."""

    origin = 0.0                   # pixels before frame `left` is drawn

    def __init__(self, length: int) -> None:
        self.length = length
        self.left = 0.0
        self.width = 1200
        self.scale = self.width / max(1, length)

    def fit(self, width: int) -> None:
        self.width = max(1, width)
        self.left = 0.0
        self.scale = self.width / max(1, self.length)

    @property
    def fitted(self) -> bool:
        return abs(self.scale - self.width / max(1, self.length)) < 1e-9

    def x_of(self, frame: float) -> float:
        return self.origin + (frame - self.left) * self.scale

    def frame_of(self, x: float) -> float:
        return self.left + (x - self.origin) / max(1e-9, self.scale)

    def zoom_at(self, x: float, factor: float) -> None:
        was = self.frame_of(x)
        lowest = self.width / max(1, self.length)
        self.scale = max(lowest, min(2.0, self.scale * factor))
        self.left = was - (x - self.origin) / self.scale
        self.clamp()

    def slide(self, by_pixels: float) -> None:
        self.left -= by_pixels / self.scale
        self.clamp()

    def clamp(self) -> None:
        span = self.width / self.scale
        self.left = max(0.0, min(max(0.0, self.length - span), self.left))


def _nice_steps(axis: Axis) -> list:
    for step in (1, 2, 5, 10, 15, 30, 60, 120, 300):
        if step * showfile.FPS * axis.scale > 70:
            break
    first = int(axis.left / showfile.FPS / step) * step
    last = int((axis.left + axis.width / axis.scale) / showfile.FPS) + step
    return list(range(first, last + 1, step))


# -- the strips --------------------------------------------------------------

class Ruler(QWidget):
    """The time axis -- and the only place the playhead is dragged."""

    moved = Signal(int)

    def __init__(self, window) -> None:
        super().__init__()
        self.window_ = window
        self.axis = window.axis
        self.setFixedHeight(24)
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self.holding = False

    def paintEvent(self, event) -> None:      # noqa: N802
        brush = QPainter(self)
        brush.fillRect(self.rect(), QColor("#171717"))
        brush.setFont(QFont(MONO, 8))
        for seconds in _nice_steps(self.axis):
            x = self.axis.x_of(seconds * showfile.FPS)
            if not -40 <= x <= self.width() + 40:
                continue
            brush.setPen(QPen(QColor("#4a4a4a")))
            brush.drawLine(int(x), 16, int(x), 24)
            brush.setPen(QPen(QColor("#8a8a8a")))
            brush.drawText(int(x) + 3, 14,
                           showfile.timecode(int(seconds * showfile.FPS))[3:])
        x = int(self.axis.x_of(self.window_.frame))
        brush.setPen(QPen(QColor("#4ec9e0"), 1))
        brush.drawLine(x, 6, x, self.height())
        brush.setPen(Qt.PenStyle.NoPen)
        brush.setBrush(QColor("#4ec9e0"))
        brush.drawPolygon([QPoint(x - 5, 6), QPoint(x + 5, 6), QPoint(x, 14)])
        brush.end()

    def mousePressEvent(self, event) -> None:   # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.holding = True
            self.moved.emit(int(self.axis.frame_of(event.position().x())))

    def mouseMoveEvent(self, event) -> None:    # noqa: N802
        if self.holding:
            self.moved.emit(int(self.axis.frame_of(event.position().x())))

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self.holding = False


class LoopBar(QWidget):
    """The loops, on a strip of their own, with their switch at its head.

    A show cut into blocks waits at every join, so there are several of them
    and they are places on the timeline rather than properties of whatever
    happens to be selected. They are read out of the show file; the strip is
    locked to begin with so a stray drag cannot lose one that is already
    right, and the exact frames are typed in the column on the right.
    """

    changed = Signal(int, int)
    GRIP = 5

    def __init__(self, window) -> None:
        super().__init__()
        self.window_ = window
        self.axis = window.axis
        self.setFixedHeight(20)
        self.holding = None            # low | high | move
        self.grabbed = 0
        self.setMouseTracking(True)

        # The switch lives at the head of the strip it switches.
        self.switch = QPushButton("LOOP", self)
        self.switch.setCheckable(True)
        self.switch.setChecked(True)
        self.switch.setGeometry(2, 1, HEAD - 12, 18)
        self.switch.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.switch.setToolTip(
            "Держат ли лупы. Нажато — доехав до лупа, плейхед крутится в нём "
            "и не идёт дальше, пока не отожмёшь (L). Отжато — едет насквозь.")
        self.switch.setStyleSheet(
            "QPushButton { font-size:10px; padding:0px; }")

    def paintEvent(self, event) -> None:      # noqa: N802
        brush = QPainter(self)
        brush.fillRect(self.rect(), QColor("#141414"))
        on = self.window_.looping
        here = self.window_.loop_here()
        for index, (low, high) in enumerate(self.window_.loops):
            left, right = int(self.axis.x_of(low)), int(self.axis.x_of(high))
            running = on and here is not None and here == (low, high)
            picked = index == self.window_.loop_at
            brush.fillRect(
                QRect(left, 3, max(3, right - left), self.height() - 6),
                QColor("#f0c040") if running
                else QColor("#8a7630") if picked else QColor("#4a411c"))
            for x in (left, right):
                brush.fillRect(QRect(x - 2, 0, 4, self.height()),
                               QColor("#ffe9a0") if picked
                               else QColor("#6a5c2a"))
            if right - left > 70:
                brush.setFont(QFont(MONO, 7, QFont.Weight.Bold))
                brush.setPen(QPen(QColor("#1a1a1a" if running else "#c8b878")))
                brush.drawText(left + 7, self.height() - 6,
                               f"{index + 1}  "
                               f"{(high - low) / showfile.FPS:.1f}с")
            if self.window_.loop_locked:
                brush.setPen(QPen(QColor(0, 0, 0, 80)))
                for x in range(left, right, 5):
                    brush.drawLine(x, 3, x - self.height(), self.height() - 3)
        brush.end()

    # -- mouse ---------------------------------------------------------------

    def shape_at(self, x: int):
        picked = self.window_.loop_region() or (0, 0)
        low, high = int(self.axis.x_of(picked[0])), int(self.axis.x_of(picked[1]))
        if abs(x - low) <= self.GRIP or abs(x - high) <= self.GRIP:
            return Qt.CursorShape.SizeHorCursor
        return Qt.CursorShape.CrossCursor

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self.window_.loop_locked:
            return
        x = event.position().x()
        at = int(self.axis.frame_of(x))
        near = 4 / max(1e-9, self.axis.scale)
        for index, (first, last) in enumerate(self.window_.loops):
            if first - near <= at <= last + near:
                self.window_.choose_loop(index)
                break
        picked = self.window_.loop_region() or (0, 0)
        low, high = int(self.axis.x_of(picked[0])), int(self.axis.x_of(picked[1]))
        sliding = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if abs(x - low) <= self.GRIP:
            self.holding = "low"
        elif abs(x - high) <= self.GRIP:
            self.holding = "high"
        elif sliding and low < x < high:
            self.holding = "move"
            self.grabbed = at - picked[0]
        else:
            self.holding = "high"
            self.changed.emit(at, at + 1)
        self.drag(at)

    def mouseMoveEvent(self, event) -> None:   # noqa: N802
        x = event.position().x()
        if self.holding is None:
            self.setCursor(Qt.CursorShape.ForbiddenCursor
                           if self.window_.loop_locked else self.shape_at(int(x)))
            return
        self.drag(int(self.axis.frame_of(x)))

    def drag(self, at: int) -> None:
        low, high = self.window_.loop_region() or (0, 1)
        if self.holding == "low":
            low = min(at, high - 1)
        elif self.holding == "high":
            high = max(at, low + 1)
        elif self.holding == "move":
            span = high - low
            low = max(0, at - self.grabbed)
            high = low + span
        self.changed.emit(low, high)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self.holding = None


class Preview(QWidget):
    """Where the building would be -- and, bottom left, the keys."""

    def __init__(self, window) -> None:
        super().__init__()
        self.window_ = window
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)

    def paintEvent(self, event) -> None:      # noqa: N802
        brush = QPainter(self)
        brush.fillRect(self.rect(), QColor("#101010"))
        wide, tall = self.width(), self.height()
        box = QRect(int(wide * 0.5 - tall * 0.34), int(tall * 0.06),
                    int(tall * 0.68), int(tall * 0.8))
        brush.setPen(QPen(QColor("#2a2a2a"), 1, Qt.PenStyle.DashLine))
        brush.drawRect(box)
        brush.setPen(QPen(QColor("#3c3c3c")))
        brush.setFont(QFont(MONO, 8))
        brush.drawText(box.left(), box.top() - 4,
                       f"превью (в прототипе не рисуется)   "
                       f"подложка: {self.window_.backing}")

        live = self.window_.show_.live_at(self.window_.frame)
        brush.setFont(QFont(MONO, 9))
        y = box.top() + 20
        for row in ROWS[:5]:
            here = [one for one in live if one.row == row]
            brush.setPen(QPen(QColor(HUE[row])))
            brush.drawText(box.left() + 10, y, f"{row:8}")
            brush.setPen(QPen(QColor("#b4b4b4" if here else "#454545")))
            said = "  +  ".join(f"{one.name[:24]} L{one.level}" for one in here)
            brush.drawText(box.left() + 80, y, said or "— тишина —")
            y += 18
        brush.setPen(QPen(QColor("#6a6a6a")))
        brush.setFont(QFont(MONO, 10))
        brush.drawText(box.left() + 10, box.bottom() - 10,
                       f"{showfile.timecode(self.window_.frame)}    "
                       f"кадр {self.window_.frame} из {self.window_.show_.length}")

        brush.setFont(QFont(MONO, 8))
        y = tall - 10 - len(KEYS) * 13
        brush.setPen(QPen(QColor("#5a5a5a")))
        brush.drawText(10, y - 15, "клавиши")
        for key, what in KEYS:
            brush.setPen(QPen(QColor("#7a7a7a")))
            brush.drawText(10, y, key)
            brush.setPen(QPen(QColor("#4e4e4e")))
            brush.drawText(96, y, what)
            y += 13
        brush.end()


class Tracks(QWidget):
    """A row per level, per screen."""

    LANE = 19
    GAP = 5
    picked = Signal(object)
    jumped = Signal(int)

    def __init__(self, window) -> None:
        super().__init__()
        self.window_ = window
        self.axis = window.axis
        self.dragging = None
        self.grabbed = 0
        self.panning = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def resizeEvent(self, event) -> None:      # noqa: N802
        was = self.axis.fitted
        self.axis.width = max(1, self.width() - HEAD + 6)
        self.axis.origin = HEAD - 6
        if was:
            self.axis.fit(self.axis.width)
        self.axis.clamp()
        super().resizeEvent(event)

    def lanes(self) -> list:
        out, y = [], 2
        for row in ROWS:
            for level in range(LEVELS[row]):
                out.append((row, level, y))
                y += self.LANE
            y += self.GAP
        return out

    def wanted_height(self) -> int:
        return sum(LEVELS[row] * self.LANE + self.GAP for row in ROWS) + 4

    def band_of(self, clip):
        if clip.kind == "cue":
            for row, _level, y in self.lanes():
                if row == "Cue":
                    return QRect(int(self.axis.x_of(clip.tx)) - 4, y,
                                 9, self.LANE - 2)
            return None
        for row, level, y in self.lanes():
            if row == clip.row and level == min(clip.level, LEVELS[row] - 1):
                left = self.axis.x_of(clip.first)
                width = max(3.0, clip.span * self.axis.scale)
                if left + width < HEAD or left > self.width():
                    return None
                return QRect(int(left), y, int(width), self.LANE - 2)
        return None

    def clip_under(self, where: QPoint):
        for clip in reversed(self.window_.show_.clips):
            band = self.band_of(clip)
            if band is not None and band.adjusted(-2, 0, 2, 0).contains(where):
                return clip
        return None

    # -- mouse ---------------------------------------------------------------

    def wheelEvent(self, event) -> None:       # noqa: N802
        steps = event.angleDelta().y() / 120.0
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.axis.slide(steps * 80)
        else:
            self.axis.zoom_at(event.position().x(), 1.25 ** steps)
        self.window_.redraw()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        where = event.position().toPoint()
        if event.button() == Qt.MouseButton.MiddleButton:
            self.jumped.emit(int(self.axis.frame_of(where.x())))
            return
        if event.button() == Qt.MouseButton.RightButton:
            self.panning = where.x()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        clip = self.clip_under(where)
        self.picked.emit(clip)
        if clip is not None and clip.kind != "cue":
            self.dragging = clip
            self.grabbed = int(self.axis.frame_of(where.x())) - clip.tx

    def mouseMoveEvent(self, event) -> None:   # noqa: N802
        where = event.position().toPoint()
        if self.panning is not None:
            self.axis.slide(where.x() - self.panning)
            self.panning = where.x()
            self.window_.redraw()
            return
        if self.dragging is None:
            return
        wanted = max(0, int(self.axis.frame_of(where.x())) - self.grabbed)
        self.dragging.tx = self.window_.snap(self.dragging, wanted, self.axis)
        self.window_.redraw()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self.dragging = None
        if self.panning is not None:
            self.panning = None
            self.setCursor(Qt.CursorShape.ArrowCursor)

    # -- drawing -------------------------------------------------------------

    @staticmethod
    def mark_fade(brush: QPainter, band: QRect, wide: float, frames: int,
                  head: bool = False) -> None:
        """Make a fade legible: a notch where it starts, and the ramp drawn."""
        edge = band.left() + int(wide) if head else band.right() - int(wide)
        pale = QColor("#ffe9a0")
        brush.setPen(QPen(pale, 1))
        if head:
            brush.drawLine(band.left(), band.bottom() - 1, edge, band.top() + 1)
        else:
            brush.drawLine(edge, band.top() + 1, band.right(), band.bottom() - 1)
        brush.setPen(QPen(pale, 2))
        brush.drawLine(edge, band.top() + 1, edge, band.top() + 5)
        brush.drawLine(edge, band.bottom() - 5, edge, band.bottom() - 1)
        if wide > 46 and band.height() > 14:
            brush.setFont(QFont(MONO, 7))
            brush.setPen(QPen(pale))
            brush.drawText(edge + 3, band.center().y() + 3,
                           f"{abs(frames) / showfile.FPS:.1f}с")

    def draw_clip(self, brush: QPainter, clip, band: QRect) -> None:
        colour = QColor("#a03030") if clip.missing else QColor(HUE[clip.row])
        chosen = clip is self.window_.chosen
        body = QColor(colour)
        body.setAlpha(215 if chosen else 130)
        brush.fillRect(band, body)
        if clip.loop:
            brush.setPen(QPen(QColor(255, 255, 255, 45)))
            for x in range(band.left(), band.right(), 7):
                brush.drawLine(x, band.top(), x - band.height(), band.bottom())
        # The motor is still carrying out its last command after the file has
        # run out, so the clip goes on -- hatched, because nothing is read
        # there, the screens are only still arriving.
        if clip.tail:
            over = int(clip.tail * self.axis.scale)
            if over >= 1:
                brush.setPen(QPen(QColor(255, 255, 255, 30)))
                for x in range(band.right() - over, band.right() + 1, 4):
                    brush.drawLine(x, band.top(), x - band.height(),
                                   band.bottom())
                brush.setPen(QPen(QColor("#e0b0b0"), 1, Qt.PenStyle.DashLine))
                brush.drawLine(band.right() - over, band.top(),
                               band.right() - over, band.bottom())
        if clip.fade_end:
            wide = abs(clip.fade_end) * self.axis.scale
            if wide > 2:
                for step in range(int(wide)):
                    x = band.right() - int(wide) + step
                    if band.left() <= x <= band.right():
                        brush.setPen(QPen(QColor(
                            0, 0, 0, int(165 * step / max(1.0, wide)))))
                        brush.drawLine(x, band.top(), x, band.bottom())
                self.mark_fade(brush, band, wide, clip.fade_end)
        if clip.fade_start:
            wide = abs(clip.fade_start) * self.axis.scale
            if wide > 2:
                for step in range(int(wide)):
                    x = band.left() + step
                    if band.left() <= x <= band.right():
                        brush.setPen(QPen(QColor(
                            0, 0, 0, int(165 * (1 - step / max(1.0, wide))))))
                        brush.drawLine(x, band.top(), x, band.bottom())
                self.mark_fade(brush, band, wide, clip.fade_start, head=True)
        if clip.crop_end:
            cut = int(abs(clip.crop_end) * self.axis.scale)
            brush.setPen(QPen(QColor("#d06060"), 1, Qt.PenStyle.DotLine))
            brush.drawLine(band.right(), band.center().y(),
                           band.right() + cut, band.center().y())
            brush.setPen(QPen(QColor("#d06060"), 2))
            brush.drawLine(band.right(), band.top() + 1,
                           band.right(), band.top() + 4)
            brush.drawLine(band.right(), band.bottom() - 4,
                           band.right(), band.bottom() - 1)
        brush.setPen(QPen(QColor("#e8e8e8") if chosen else colour.lighter(130)))
        brush.drawRect(band)
        if band.width() > 34:
            brush.setFont(QFont(MONO, 8))
            brush.setPen(QPen(QColor("#f0f0f0" if chosen else "#c8c8c8")))
            room = band.adjusted(4, 0, -3, 0)
            metrics = QFontMetrics(brush.font())
            brush.drawText(room, Qt.AlignmentFlag.AlignVCenter,
                           metrics.elidedText(clip.name,
                                              Qt.TextElideMode.ElideMiddle,
                                              room.width()))

    def draw_cues(self, brush: QPainter, band: QRect) -> None:
        for clip in self.window_.show_.clips:
            if clip.kind != "cue":
                continue
            x = int(self.axis.x_of(clip.tx))
            chosen = clip is self.window_.chosen
            brush.setPen(QPen(QColor("#f5dd70" if chosen else HUE["Cue"]),
                              3 if chosen else 1))
            brush.drawLine(x, band.top(), x, band.bottom())
            if self.axis.scale > 0.015:
                brush.setFont(QFont(MONO, 7))
                brush.setPen(QPen(QColor("#f5dd70" if chosen else "#9a8420")))
                brush.drawText(x + 4, band.top() + 10,
                               f"u{clip.universe}·ch{clip.channel}·v{clip.value}")

    def draw_loops(self, brush: QPainter) -> None:
        here = self.window_.loop_here()
        on = self.window_.looping
        for index, (low, high) in enumerate(self.window_.loops):
            left, right = int(self.axis.x_of(low)), int(self.axis.x_of(high))
            running = on and here is not None and here == (low, high)
            brush.fillRect(QRect(left, 0, max(2, right - left), self.height()),
                           QColor(201, 162, 39, 34 if running else 12))
            brush.setPen(QPen(QColor("#f0c040" if running else "#5a5030"),
                              2 if running else 1))
            brush.drawLine(left, 0, left, self.height())
            brush.drawLine(right, 0, right, self.height())
            brush.setFont(QFont(MONO, 8, QFont.Weight.Bold))
            brush.setPen(QPen(QColor("#f0c040" if running else "#6a6040")))
            brush.drawText(left + 5, 11, f"LOOP {index + 1}")
            if running:
                for x, way in ((left + 3, 1), (right - 3, -1)):
                    brush.drawLine(x, self.height() - 4,
                                   x + 6 * way, self.height() - 4)
                    brush.drawLine(x, self.height() - 4,
                                   x + 3 * way, self.height() - 7)
                    brush.drawLine(x, self.height() - 4,
                                   x + 3 * way, self.height() - 1)

    def paintEvent(self, event) -> None:       # noqa: N802
        brush = QPainter(self)
        brush.fillRect(self.rect(), QColor("#191919"))
        for row, level, y in self.lanes():
            brush.fillRect(QRect(0, y, self.width(), self.LANE - 2),
                           QColor("#202020" if level % 2 else "#1c1c1c"))
            brush.setFont(QFont(MONO, 8))
            brush.setPen(QPen(QColor(HUE[row]) if level == 0
                              else QColor("#5a5a5a")))
            brush.drawText(6, y + self.LANE - 7,
                           f"{row} L{level}" if LEVELS[row] > 1 else row)
        brush.setPen(QPen(QColor("#2a2a2a")))
        brush.drawLine(HEAD - 6, 0, HEAD - 6, self.height())
        brush.setClipRect(QRect(HEAD - 6, 0,
                                self.width() - HEAD + 6, self.height()))
        self.draw_loops(brush)
        for clip in self.window_.show_.clips:
            if clip.kind == "cue":
                continue
            band = self.band_of(clip)
            if band is not None:
                self.draw_clip(brush, clip, band)
        for row, _level, y in self.lanes():
            if row == "Cue":
                self.draw_cues(brush, QRect(0, y, self.width(), self.LANE - 2))
        x = int(self.axis.x_of(self.window_.frame))
        brush.setPen(QPen(QColor("#4ec9e0"), 1))
        brush.drawLine(x, 0, x, self.height())
        brush.end()


# -- the right-hand column ---------------------------------------------------

class LoopPanel(QWidget):
    """Everything about the loops that is not the strip itself."""

    def __init__(self, window) -> None:
        super().__init__()
        self.window_ = window
        whole = QVBoxLayout(self)
        whole.setContentsMargins(8, 6, 8, 8)
        whole.setSpacing(5)

        title = QLabel("Лупы")
        title.setFont(QFont(MONO, 10, QFont.Weight.Bold))
        whole.addWidget(title)

        self.says = QLabel()
        self.says.setFont(QFont(MONO, 9))
        self.says.setStyleSheet("color:#c9a227;")
        self.says.setWordWrap(True)
        whole.addWidget(self.says)

        frames = QHBoxLayout()
        frames.setSpacing(4)
        frames.addWidget(QLabel("с"))
        self.low = QSpinBox()
        self.low.setRange(0, 10_000_000)
        self.low.setKeyboardTracking(False)
        frames.addWidget(self.low, 1)
        frames.addWidget(QLabel("по"))
        self.high = QSpinBox()
        self.high.setRange(0, 10_000_000)
        self.high.setKeyboardTracking(False)
        frames.addWidget(self.high, 1)
        whole.addLayout(frames)

        line = QHBoxLayout()
        line.setSpacing(4)

        def button(text, what, hint, wide=0):
            one = QPushButton(text)
            if wide:
                one.setFixedWidth(wide)
            one.setToolTip(hint)
            one.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            one.clicked.connect(what)
            line.addWidget(one)
            return one

        button("+", lambda: window.add_loop(),
               "Поставить ещё один луп с того кадра, где плейхед.", 26)
        button("−", lambda: window.drop_loop(), "Убрать выбранный луп.", 26)
        button("по клипу", lambda: window.loop_the_clip(),
               "Луп на весь выбранный клип, и включить (Shift+L).")
        button("из файла", lambda: window.loop_from_file(),
               "Вернуть лупы, записанные в самом шоу: каждый зацикленный "
               "клип от своего кадра и до прихода следующего. Во всех сорока "
               "файлах это один луп, 800..1099.")
        line.addStretch(1)
        # The lock on the right, as asked.
        self.lock = QPushButton("🔒")
        self.lock.setCheckable(True)
        self.lock.setChecked(True)
        self.lock.setFixedWidth(34)
        self.lock.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.lock.setToolTip(
            "Запретить рисовать лупы мышью (K). Числами их всё равно можно "
            "поправить — на 22 минутах один пиксель это 56 кадров, и мышь "
            "тут промахивается по определению.")
        self.lock.toggled.connect(window.lock_loop)
        line.addWidget(self.lock)
        whole.addLayout(line)

        self._saying = False
        self.low.valueChanged.connect(self.typed)
        self.high.valueChanged.connect(self.typed)

    def typed(self, _value: int = 0) -> None:
        if self._saying:
            return
        self.window_.set_loop_range(self.low.value(), self.high.value())

    def refresh(self) -> None:
        picked = self.window_.loop_region()
        self._saying = True
        self.low.setValue(picked[0] if picked else 0)
        self.high.setValue(picked[1] if picked else 0)
        self._saying = False
        self.lock.setText("🔒" if self.window_.loop_locked else "🔓")
        here = self.window_.loop_here()
        said = "лупов нет"
        if picked is not None:
            said = (f"луп {self.window_.loop_at + 1} из "
                    f"{len(self.window_.loops)}   "
                    f"{(picked[1] - picked[0]) / showfile.FPS:.1f}с")
        if here is not None:
            said += ("   ДЕРЖИТ" if self.window_.looping
                     else "   плейхед внутри, но лупы отжаты")
        self.says.setText(said)


class Inspector(QWidget):
    """The selected clip. A cue is a different animal, so it says so."""

    MEDIA = [("Дорожка", "row"), ("Уровень", "level"),
             ("Кадр начала", "tx"), ("Длина", "frames"),
             ("Доезд моторов", "tail"),
             ("Подрезка с хвоста", "crop_end"),
             ("Фейд с хвоста", "fade_end"),
             ("Подрезка с головы", "crop_start"),
             ("Фейд с головы", "fade_start"),
             ("Занимает", "range"), ("Начинается", "at"),
             ("Файл", "path")]
    CUE = [("Кадр", "tx"), ("Время", "range"), ("Universe", "universe"),
           ("Channel", "channel"), ("Value", "value"), ("Уровень", "level")]

    def __init__(self, window) -> None:
        super().__init__()
        self.window_ = window
        self.shown: list = []
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(8, 6, 8, 6)
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(4)
        self.title = QLabel("клип не выбран")
        self.title.setFont(QFont(MONO, 10, QFont.Weight.Bold))
        self.title.setWordWrap(True)
        self.grid.addWidget(self.title, 0, 0, 1, 2)
        self.body: dict = {}
        self.lay_out(self.MEDIA)

    def lay_out(self, names) -> None:
        for widget in self.shown:
            self.grid.removeWidget(widget)
            widget.setParent(None)
        self.shown, self.body = [], {}
        for index, (label, key) in enumerate(names):
            tag = QLabel(label)
            tag.setStyleSheet("color:#8a8a8a;")
            tag.setFixedWidth(126)
            value = QLabel("—")
            value.setFont(QFont(MONO, 9))
            # One line each. A wrapping label here does not make its grid row
            # any taller, so the second line lands on the row below it.
            value.setWordWrap(False)
            value.setAlignment(Qt.AlignmentFlag.AlignLeft
                               | Qt.AlignmentFlag.AlignVCenter)
            self.grid.addWidget(tag, 1 + index, 0)
            self.grid.addWidget(value, 1 + index, 1)
            self.shown += [tag, value]
            self.body[key] = value
        self.grid.setRowStretch(len(names) + 1, 1)
        self.grid.setColumnStretch(1, 1)

    def refresh(self) -> None:
        clip = self.window_.chosen
        if clip is None:
            self.title.setText("клип не выбран")
            for value in self.body.values():
                value.setText("—")
            return
        wanted = self.CUE if clip.kind == "cue" else self.MEDIA
        if [key for _, key in wanted] != list(self.body):
            self.lay_out(wanted)
        self.title.setText(f"кью на кадре {clip.tx}" if clip.kind == "cue"
                           else clip.name)
        got = {
            "row": clip.row, "level": str(clip.level), "tx": str(clip.tx),
            "frames": f"{clip.frames}  ({clip.frames / showfile.FPS:.1f} с)",
            "tail": (f"+{clip.tail}  ({clip.tail / showfile.FPS:.1f} с)"
                     if clip.tail else "—"),
            "crop_end": str(clip.crop_end), "fade_end": str(clip.fade_end),
            "crop_start": str(clip.crop_start),
            "fade_start": str(clip.fade_start),
            "range": (showfile.timecode(clip.tx) if clip.kind == "cue" else
                      f"{clip.first}..{clip.last}"),
            "at": showfile.timecode(clip.first),
            "path": clip.path or "—",
            "universe": str(clip.universe), "channel": str(clip.channel),
            "value": str(clip.value),
        }
        for key, value in self.body.items():
            said = got.get(key, "—")
            if key == "path":
                # The whole path is in the hover; the row shows its tail.
                value.setToolTip(said)
                room = max(120, value.width() or 150)
                metrics = QFontMetrics(value.font())
                said = metrics.elidedText(said, Qt.TextElideMode.ElideLeft,
                                          room)
            value.setText(said)


class Transport(QWidget):
    """The play bar. The loop's own switch lives on the loop strip."""

    def __init__(self, window) -> None:
        super().__init__()
        self.window_ = window
        line = QHBoxLayout(self)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(3)

        def button(text, what, hint, wide=34):
            one = QPushButton(text)
            one.setFixedWidth(wide)
            one.setToolTip(hint)
            one.clicked.connect(what)
            one.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            line.addWidget(one)
            return one

        button("|<", lambda: window.go_to(0), "в начало (Home)")
        button("<<", lambda: window.nudge(-int(showfile.FPS)),
               "секунда назад (Shift+←)")
        button("<|", lambda: window.nudge(-1), "кадр назад (←)")
        self.play = button(">", lambda: window.toggle_play(),
                           "играть / пауза (Space)", 44)
        button("|>", lambda: window.nudge(1), "кадр вперёд (→)")
        button(">>", lambda: window.nudge(int(showfile.FPS)),
               "секунда вперёд (Shift+→)")
        button(">|", lambda: window.go_to(window.show_.length), "в конец (End)")
        line.addSpacing(12)
        button("I", lambda: window.to_edge(False), "на начало клипа (I)", 28)
        button("O", lambda: window.to_edge(True), "на конец клипа (O)", 28)
        button("[", lambda: window.put_clip(False),
               "поставить клип слева от плейхеда ([)", 28)
        button("]", lambda: window.put_clip(True),
               "поставить клип справа от плейхеда (])", 28)
        line.addSpacing(16)
        self.readout = QLabel()
        self.readout.setFont(QFont(MONO, 11))
        line.addWidget(self.readout)
        line.addStretch(1)

    def refresh(self) -> None:
        self.play.setText("||" if self.window_.playing else ">")
        self.readout.setText(
            f"{showfile.timecode(self.window_.frame)}   "
            f"{self.window_.frame} / {self.window_.show_.length}")


class Window(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ПРОТОТИП — таймлайн Matreshka Viewer")
        self.resize(1680, 980)

        self.files = showfile.listing()
        # The clock is a float. An int one loses the 0.96 of a frame that a
        # sixteen millisecond tick is worth, every tick, and the playhead
        # crawls at about three frames a second instead of sixty.
        self.raw = 11742.0
        self.chosen = None
        self.playing = False
        self.looping = True
        self.backing = "Calibration"
        self.loops: list = [[0, 79200]]
        self.loop_at = 0
        self.loop_locked = True
        self.show_ = showfile.read(self.files[0])
        self.loops = [list(one) for one in self.show_.loops]
        self.axis = Axis(self.show_.length)

        central = QWidget()
        self.setCentralWidget(central)
        whole = QVBoxLayout(central)
        whole.setContentsMargins(6, 6, 6, 4)
        whole.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.picker = QComboBox()
        self.picker.addItems([one.stem for one in self.files])
        self.picker.setMinimumWidth(380)
        self.picker.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.picker.currentIndexChanged.connect(self.open_show)
        top.addWidget(QLabel("шоу"))
        top.addWidget(self.picker)
        self.backing_box = QComboBox()
        self.backing_box.addItems(["Calibration", "Black"])
        self.backing_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.backing_box.currentTextChanged.connect(self.set_backing)
        top.addWidget(QLabel("подложка"))
        top.addWidget(self.backing_box)
        fit = QPushButton("вся длина")
        fit.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        fit.clicked.connect(self.fit_axis)
        top.addWidget(fit)
        top.addWidget(QLabel("ЛКМ — выделить и тащить  ·  ПКМ — прокрутка  ·  "
                             "СКМ — плейхед сюда  ·  колесо — зум  ·  "
                             "плейхед — за линейку"))
        top.addStretch(1)
        whole.addLayout(top)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(2)
        left.addWidget(Preview(self), 1)
        self.loopbar = LoopBar(self)
        self.loopbar.changed.connect(self.set_loop_range)
        self.loopbar.switch.toggled.connect(self.set_loop)
        left.addWidget(self.loopbar)
        self.ruler = Ruler(self)
        self.ruler.moved.connect(self.go_to)
        left.addWidget(self.ruler)
        self.tracks = Tracks(self)
        self.tracks.setFixedHeight(self.tracks.wanted_height())
        self.tracks.picked.connect(self.pick)
        self.tracks.jumped.connect(self.go_to)
        left.addWidget(self.tracks)
        body.addLayout(left, 1)

        column = QWidget()
        column.setFixedWidth(290)
        column.setStyleSheet("background:#232323;")
        stack = QVBoxLayout(column)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(0)
        self.loop_panel = LoopPanel(self)
        self.loop_panel.setStyleSheet("background:#282520;")
        stack.addWidget(self.loop_panel)
        self.inspector = Inspector(self)
        stack.addWidget(self.inspector, 1)
        body.addWidget(column)
        whole.addLayout(body, 1)

        self.transport = Transport(self)
        whole.addWidget(self.transport)

        self.state = QLabel()
        self.state.setFont(QFont(MONO, 9))
        self.state.setStyleSheet(
            "color:#8fbf8f; background:#151515; padding:3px;")
        self.state.setWordWrap(True)
        self.state.setFixedHeight(46)
        whole.addWidget(self.state)

        self.beat = QTimer(self)
        self.beat.timeout.connect(self.tick)
        self.last = time.perf_counter()
        self.redraw()

    # -- the clock -----------------------------------------------------------

    @property
    def frame(self) -> int:
        return int(self.raw)

    def toggle_play(self) -> None:
        self.playing = not self.playing
        self.last = time.perf_counter()
        if self.playing:
            self.beat.start(16)
        else:
            self.beat.stop()
        self.redraw()

    def tick(self) -> None:
        now = time.perf_counter()
        gone, self.last = now - self.last, now
        at = self.raw + gone * showfile.FPS
        here = self.loop_here()
        if self.looping and here is not None:
            # Round and round the loop the playhead is standing in, until the
            # switch is let go -- and then on to the next block, and the next
            # wait. That is what a show cut into blocks does.
            low, high = here
            if at >= high or at < low:
                at = low + (at - high) % max(1, high - low)
        elif at >= self.show_.length:
            at = self.show_.length
            self.playing = False
            self.beat.stop()
        self.raw = at
        self.redraw()

    # -- the loops -----------------------------------------------------------

    def loop_here(self):
        """The loop the playhead is standing in, if it is standing in one."""
        for low, high in self.loops:
            if low <= self.raw < high:
                return (int(low), int(high))
        return None

    def loop_region(self):
        """The loop being edited -- what the numbers and the mouse act on."""
        if not self.loops:
            return None
        self.loop_at = max(0, min(self.loop_at, len(self.loops) - 1))
        low, high = self.loops[self.loop_at]
        return (int(low), int(high))

    def choose_loop(self, index: int) -> None:
        self.loop_at = max(0, min(int(index), len(self.loops) - 1))
        self.redraw()

    def set_loop(self, on: bool) -> None:
        self.looping = bool(on)
        self.redraw()

    def set_loop_range(self, low: int, high: int) -> None:
        if not self.loops:
            self.loops = [[0, self.show_.length]]
        low = max(0, min(int(low), self.show_.length - 1))
        high = max(low + 1, min(int(high), self.show_.length))
        self.loops[self.loop_at] = [low, high]
        self.redraw()

    def add_loop(self) -> None:
        low = self.frame
        high = min(self.show_.length, low + int(showfile.FPS) * 5)
        wanted = [low, max(low + 1, high)]
        self.loops.append(wanted)
        self.loops.sort()
        self.loop_at = self.loops.index(wanted)
        self.redraw()

    def drop_loop(self) -> None:
        if not self.loops:
            return
        self.loops.pop(self.loop_at)
        self.loop_at = max(0, min(self.loop_at, len(self.loops) - 1))
        self.redraw()

    def lock_loop(self, on: bool) -> None:
        self.loop_locked = bool(on)
        self.redraw()

    def loop_from_file(self) -> None:
        self.loops = [list(one) for one in self.show_.loops]
        self.loop_at = 0
        self.redraw()

    def loop_the_clip(self) -> None:
        clip = self.chosen
        if clip is None or clip.kind == "cue":
            return
        self.set_loop_range(clip.first, clip.last)
        self.loopbar.switch.setChecked(True)
        self.raw = float(self.loops[self.loop_at][0])
        self.redraw()

    # -- moving about --------------------------------------------------------

    def go_to(self, frame: int) -> None:
        self.raw = float(max(0, min(self.show_.length, int(frame))))
        self.redraw()

    def nudge(self, by: int) -> None:
        self.go_to(self.frame + by)

    def to_edge(self, end: bool) -> None:
        if self.chosen is not None:
            self.go_to(self.chosen.last - 1 if end else self.chosen.first)

    def put_clip(self, right: bool) -> None:
        clip = self.chosen
        if clip is None or clip.kind == "cue":
            return
        clip.tx = max(0, int(self.frame) if right
                      else int(self.frame - clip.span))
        self.redraw()

    def fit_axis(self) -> None:
        self.axis.fit(self.axis.width)
        self.redraw()

    def set_backing(self, which: str) -> None:
        self.backing = which
        self.redraw()

    def open_show(self, index: int) -> None:
        self.show_ = showfile.read(self.files[index])
        self.chosen = None
        self.loops = [list(one) for one in self.show_.loops]
        self.loop_at = 0
        self.axis = Axis(self.show_.length)
        for one in (self.loopbar, self.ruler, self.tracks):
            one.axis = self.axis
        self.tracks.resizeEvent(None)
        self.redraw()

    def pick(self, clip) -> None:
        self.chosen = clip
        self.redraw()

    def snap(self, clip, wanted: int, axis: Axis) -> int:
        close = 8 / max(1e-9, axis.scale)
        edges = [0, self.frame]
        for other in self.show_.clips:
            if other is clip or other.kind == "cue":
                continue
            edges += [other.first, other.last]
        for edge in edges:
            if abs(wanted - edge) < close:
                return int(edge)
            if abs(wanted + clip.span - edge) < close:
                return int(edge - clip.span)
        return int(wanted)

    # -- keys ----------------------------------------------------------------

    def keyPressEvent(self, event) -> None:    # noqa: N802
        key = event.key()
        fast = event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        step = int(showfile.FPS) if fast else 1
        if key == Qt.Key.Key_Space:
            self.toggle_play()
        elif key == Qt.Key.Key_Left:
            self.nudge(-step)
        elif key == Qt.Key.Key_Right:
            self.nudge(step)
        elif key == Qt.Key.Key_Home:
            self.go_to(0)
        elif key == Qt.Key.Key_End:
            self.go_to(self.show_.length)
        elif key == Qt.Key.Key_I:
            self.to_edge(False)
        elif key == Qt.Key.Key_O:
            self.to_edge(True)
        elif key == Qt.Key.Key_BracketLeft:
            self.put_clip(False)
        elif key == Qt.Key.Key_BracketRight:
            self.put_clip(True)
        elif key == Qt.Key.Key_L:
            if fast:
                self.loop_the_clip()
            else:
                self.loopbar.switch.toggle()
        elif key == Qt.Key.Key_K:
            self.loop_panel.lock.toggle()
        elif key == Qt.Key.Key_F:
            self.fit_axis()
        else:
            super().keyPressEvent(event)

    # -- saying what is going on ---------------------------------------------

    def redraw(self) -> None:
        live = self.show_.live_at(self.frame)
        here = self.loop_here()
        said = [f"кадр {self.frame}  {showfile.timecode(self.frame)}"
                f"   {'ИГРАЕТ' if self.playing else 'стоит'}"
                f"{'  В ЛУПЕ' if here is not None and self.looping else ''}"
                f"   на экранах {len(live)}: "
                + ("  |  ".join(f"{one.row} L{one.level} {one.name[:22]}"
                                for one in live) or "ничего")]
        said.append("выбран:  " + (self.chosen.says() if self.chosen
                                   else "ничего"))
        self.state.setText("\n".join(said))
        self.transport.refresh()
        self.loop_panel.refresh()
        self.inspector.refresh()
        self.loopbar.update()
        self.ruler.update()
        self.tracks.update()


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(SHEET)
    window = Window()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
