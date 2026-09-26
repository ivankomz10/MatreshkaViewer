"""PROTOTYPE -- throwaway. Two timelines for the Matreshka viewer.

The question: which shape of timeline is comfortable to work a 22 minute show
in, before any of it is built for real.

  A  «Как в оригинале»  -- a row per level, inspector down the right side.
  B  «Лестница»         -- a row per screen, the level drawn as the step's
                           height, which is what the show editor itself does.
                           Fewer rows, inspector as a strip underneath.

Switch with the yellow bar at the top, Tab, or `--variant=B`.

The mouse, as asked for:
  left      select a clip; drag it to move it. Empty space deselects.
  right     drag to scroll the timeline, without touching the playhead
  middle    click to teleport the playhead there
  wheel     zoom;  Shift+wheel scroll
The playhead is dragged only by the ruler along the top of the tracks.

Real shows, read from D:\\Content\\_SHOW. Nothing is ever written back: dragging
a clip moves it in memory and the next reload forgets it.

Run:   tool\\proto_timeline\\run.bat        or  python proto.py --variant=B
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
"""

ROWS = ["Top", "Bottom", "Lamels", "Sound", "Kinetic", "Cue"]
HUE = {"Top": "#4a7ea8", "Bottom": "#4a9c78", "Lamels": "#a88a4a",
       "Sound": "#7a5aa8", "Kinetic": "#a85a5a", "Cue": "#c9a227"}
# Three content levels per screen. The black backdrop that sits on level 3 of
# every show file is not a clip here at all: the viewer already has its own
# backing -- black, or the calibration picture -- and taking a second answer
# out of the show file would only be a way for the two to disagree.
LEVELS = {"Top": 3, "Bottom": 3, "Lamels": 3, "Sound": 2, "Kinetic": 1,
          "Cue": 1}

KEYS = [
    ("Space", "играть / пауза"),
    ("← →", "кадр назад / вперёд"),
    ("Shift+← →", "секунда назад / вперёд"),
    ("I / O", "на начало / конец клипа"),
    ("[ / ]", "клип слева / справа от плейхеда"),
    ("L", "луп"),
    ("Shift+L", "луп на весь клип"),
    ("Shift+тащить", "перенести луп целиком"),
    ("K", "запереть лупы"),
    ("Home / End", "в начало / в конец"),
    ("F", "вся длина"),
    ("Tab", "другой вариант"),
]


class Axis:
    """Where time sits on the screen. Shared maths, not shared layout."""

    origin = 0.0                   # pixels before frame `left` is drawn

    def __init__(self, length: int) -> None:
        self.length = length
        self.left = 0.0
        self.width = 1200
        # Fitted from the start: an arbitrary scale here reads as "fitted is
        # false", so the first resize refused to fit and the ruler ran on
        # past the end of the show.
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


# -- the pieces every variant is free to use or ignore -----------------------

class Ruler(QWidget):
    """The time axis -- and the only place the playhead is dragged.

    Asked for explicitly: inside the tracks the left button belongs to
    selecting clips, so the playhead gets a strip of its own along the top.
    The loop, when there is one, is a bar across the same strip.
    """

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
        # A list, not three arguments: three loose QPoints land on another
        # overload of drawPolygon and take the process down with them.
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
    """The loop as a range of its own, on a strip of its own.

    A row above the ruler, the way the show editor does it: the loop is a
    place on the timeline, not a property of whatever happens to be selected.
    Drag the ends to trim it; drag anywhere else to draw a new one; hold
    Shift to slide the whole loop without changing its length -- unless the
    strip is locked, which it is to begin with, because the loop that matters
    comes out of the show file and a stray drag should not be able to lose it.

    Drawing wins over sliding on purpose. The loop opens on the whole show,
    so there is no empty strip left over -- when sliding had priority, every
    attempt to draw a new loop dragged the old one instead, and there was no
    way to make a short loop at all.
    """

    changed = Signal(int, int)
    GRIP = 5

    def __init__(self, window) -> None:
        super().__init__()
        self.window_ = window
        self.axis = window.axis
        self.setFixedHeight(13)
        self.holding = None            # low | high | move | new
        self.grabbed = 0
        self.setMouseTracking(True)

    # -- drawing -------------------------------------------------------------

    def paintEvent(self, event) -> None:      # noqa: N802
        brush = QPainter(self)
        brush.fillRect(self.rect(), QColor("#141414"))
        on = self.window_.looping
        here = self.window_.loop_here()
        for index, (low, high) in enumerate(self.window_.loops):
            left, right = int(self.axis.x_of(low)), int(self.axis.x_of(high))
            running = on and here is not None and here == (low, high)
            picked = index == self.window_.loop_at
            body = (QColor("#f0c040") if running
                    else QColor("#8a7630") if picked else QColor("#4a411c"))
            brush.fillRect(QRect(left, 2, max(3, right - left),
                                 self.height() - 4), body)
            for x in (left, right):
                brush.fillRect(QRect(x - 2, 0, 4, self.height()),
                               QColor("#ffe9a0") if picked
                               else QColor("#6a5c2a"))
            if right - left > 70:
                brush.setFont(QFont(MONO, 7, QFont.Weight.Bold))
                brush.setPen(QPen(QColor("#1a1a1a" if running else "#c8b878")))
                brush.drawText(left + 7, self.height() - 3,
                               f"{index + 1}  {(high - low) / showfile.FPS:.1f}с")
        low, high = self.window_.loop_region() or (0, 0)
        left, right = int(self.axis.x_of(low)), int(self.axis.x_of(high))
        brush.setPen(QPen(QColor("#3a3a3a")))
        brush.drawText(4, self.height() - 3, "луп")
        if self.window_.loop_locked:
            # Hatched, so a strip that will not take a drag says so before
            # the drag rather than after it.
            brush.setPen(QPen(QColor(0, 0, 0, 90)))
            for x in range(left, right, 5):
                brush.drawLine(x, 2, x - self.height(), self.height() - 2)
            if right - left > 120:
                brush.setFont(QFont(MONO, 7))
                brush.setPen(QPen(QColor("#1a1a1a" if on else "#8a7a3a")))
                brush.drawText(left + 76, self.height() - 3, "заперт")
        elif right - left > 240:
            brush.setFont(QFont(MONO, 7))
            brush.setPen(QPen(QColor("#1a1a1a" if on else "#6a5f30")))
            brush.drawText(left + 76, self.height() - 3,
                           "тащи — новый луп, за край — подрезать, "
                           "Shift — перенести")
        brush.end()

    # -- mouse ---------------------------------------------------------------

    def cursorShape(self, x: int):            # noqa: N802
        picked = self.window_.loop_region() or (0, 0)
        low = int(self.axis.x_of(picked[0]))
        high = int(self.axis.x_of(picked[1]))
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
        # Clicking a loop picks it up first: with several on the strip, the
        # one being edited has to be the one under the hand.
        for index, (first, last) in enumerate(self.window_.loops):
            if first - 4 / max(1e-9, self.axis.scale) <= at \
                    <= last + 4 / max(1e-9, self.axis.scale):
                self.window_.choose_loop(index)
                break
        picked = self.window_.loop_region() or (0, 0)
        low = int(self.axis.x_of(picked[0]))
        high = int(self.axis.x_of(picked[1]))
        sliding = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if abs(x - low) <= self.GRIP:
            self.holding = "low"
        elif abs(x - high) <= self.GRIP:
            self.holding = "high"
        elif sliding and low < x < high:
            self.holding = "move"
            self.grabbed = at - self.window_.loop_in
        else:
            self.holding = "high"
            self.changed.emit(at, at + 1)
        self.drag(at)

    def mouseMoveEvent(self, event) -> None:   # noqa: N802
        x = event.position().x()
        if self.holding is None:
            self.setCursor(Qt.CursorShape.ForbiddenCursor
                           if self.window_.loop_locked
                           else self.cursorShape(int(x)))
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


def _nice_steps(axis: Axis) -> list:
    for step in (1, 2, 5, 10, 15, 30, 60, 120, 300):
        if step * showfile.FPS * axis.scale > 70:
            break
    first = int(axis.left / showfile.FPS / step) * step
    last = int((axis.left + axis.width / axis.scale) / showfile.FPS) + step
    return list(range(first, last + 1, step))


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

        # The keys, bottom left of the preview, as asked.
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


class Inspector(QWidget):
    """The selected clip. A cue is a different animal, so it says so."""

    MEDIA = [("Дорожка", "row"), ("Уровень", "level"),
             ("Кадр начала", "tx"), ("Длина", "frames"),
             ("Подрезка с хвоста", "crop_end"),
             ("Фейд с хвоста", "fade_end"),
             ("Подрезка с головы", "crop_start"),
             ("Фейд с головы", "fade_start"),
             ("Луп", "loop"), ("Свой луп", "loop_range"),
             ("Занимает", "range"), ("Файл", "path")]
    CUE = [("Кадр", "tx"), ("Время", "range"), ("Universe", "universe"),
           ("Channel", "channel"), ("Value", "value"), ("Уровень", "level")]

    def __init__(self, window, across: bool = False) -> None:
        super().__init__()
        self.window_ = window
        self.across = across
        self.shown: list = []
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(8, 6, 8, 6)
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(4)
        self.title = QLabel("клип не выбран")
        self.title.setFont(QFont(MONO, 10, QFont.Weight.Bold))
        self.title.setWordWrap(not across)
        self.grid.addWidget(self.title, 0, 0, 1, 8 if across else 2)
        self.body: dict = {}
        self.lay_out(self.MEDIA)

    def lay_out(self, names) -> None:
        for widget in self.shown:
            self.grid.removeWidget(widget)
            widget.setParent(None)
        self.shown, self.body = [], {}
        per = 4 if self.across else 1
        for index, (label, key) in enumerate(names):
            tag = QLabel(label)
            tag.setStyleSheet("color:#8a8a8a;")
            tag.setFixedWidth(126 if not self.across else 112)
            value = QLabel("—")
            value.setFont(QFont(MONO, 9))
            value.setWordWrap(True)
            value.setAlignment(Qt.AlignmentFlag.AlignLeft
                               | Qt.AlignmentFlag.AlignVCenter)
            column = (index % per) * 2
            self.grid.addWidget(tag, 1 + index // per, column)
            self.grid.addWidget(value, 1 + index // per, column + 1)
            self.shown += [tag, value]
            self.body[key] = value
        if not self.across:
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
            "crop_end": str(clip.crop_end), "fade_end": str(clip.fade_end),
            "crop_start": str(clip.crop_start),
            "fade_start": str(clip.fade_start),
            "loop": "да" if clip.loop else "нет",
            "loop_range": str(list(clip.loop_range)),
            "range": (showfile.timecode(clip.tx) if clip.kind == "cue" else
                      f"{clip.first}..{clip.last}  "
                      f"{showfile.timecode(clip.first)}"),
            "path": clip.path or "—",
            "universe": str(clip.universe), "channel": str(clip.channel),
            "value": str(clip.value),
        }
        for key, value in self.body.items():
            value.setText(got.get(key, "—"))


class Clips(QWidget):
    """What both variants do with the mouse. Each lays its rows out itself."""

    HEAD = 74
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
        self.axis.width = max(1, self.width() - self.HEAD + 6)
        self.axis.origin = self.HEAD - 6
        if was:
            self.axis.fit(self.axis.width)
        self.axis.clamp()
        super().resizeEvent(event)

    def band_of(self, clip):
        raise NotImplementedError

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
        self.picked.emit(clip)          # None deselects; it never scrubs
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
        # A motor is still carrying out its last command after the file has
        # run out, so the clip goes on -- hatched, because nothing is being
        # read there, the screens are only still arriving.
        if clip.tail:
            over = int(clip.tail * self.axis.scale)
            if over >= 1:
                strip = QRect(band.right() - over, band.top(), over,
                              band.height())
                brush.setPen(QPen(QColor(255, 255, 255, 30)))
                for x in range(strip.left(), strip.right() + 1, 4):
                    brush.drawLine(x, strip.top(), x - strip.height(),
                                   strip.bottom())
                brush.setPen(QPen(QColor("#e0b0b0"), 1, Qt.PenStyle.DashLine))
                brush.drawLine(strip.left(), band.top(),
                               strip.left(), band.bottom())
        # The fade: a wedge of shade, and over it the marks that make it
        # readable at a glance -- a notch where it begins, the ramp itself,
        # and the length when there is room to print it.
        if clip.fade_end:
            wide = abs(clip.fade_end) * self.axis.scale
            if wide > 2:
                for step in range(int(wide)):
                    x = band.right() - int(wide) + step
                    if band.left() <= x <= band.right():
                        brush.setPen(QPen(QColor(0, 0, 0,
                                                 int(165 * step / max(1.0, wide)))))
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
            # A notch at the cut, so a trimmed end is not just a shorter box.
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

    @staticmethod
    def mark_fade(brush: QPainter, band: QRect, wide: float, frames: int,
                  head: bool = False) -> None:
        """Make a fade legible: a notch where it starts, and the ramp drawn."""
        edge = band.left() + int(wide) if head else band.right() - int(wide)
        pale = QColor("#ffe9a0")
        brush.setPen(QPen(pale, 1))
        # The ramp, as a line from full at one end to nothing at the other.
        if head:
            brush.drawLine(band.left(), band.bottom() - 1, edge, band.top() + 1)
        else:
            brush.drawLine(edge, band.top() + 1, band.right(), band.bottom() - 1)
        # The notch: a bracket at the frame the fade begins.
        brush.setPen(QPen(pale, 2))
        brush.drawLine(edge, band.top() + 1, edge, band.top() + 5)
        brush.drawLine(edge, band.bottom() - 5, edge, band.bottom() - 1)
        if wide > 46 and band.height() > 14:
            brush.setFont(QFont(MONO, 7))
            brush.setPen(QPen(pale))
            said = f"{abs(frames) / showfile.FPS:.1f}с"
            brush.drawText(edge + 3 if head else edge + 3,
                           band.center().y() + 3, said)

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

    def draw_loop(self, brush: QPainter) -> None:
        """The loop, over every row, so there is no doubt what is going round.

        A tint plus a line down each end plus a hatched shoulder outside it:
        on the ruler alone it was a thin bar nobody noticed.
        """
        here = self.window_.loop_here()
        on = self.window_.looping
        for index, (low, high) in enumerate(self.window_.loops):
            left = int(self.axis.x_of(low))
            right = int(self.axis.x_of(high))
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

    def draw_playhead(self, brush: QPainter) -> None:
        x = int(self.axis.x_of(self.window_.frame))
        brush.setPen(QPen(QColor("#4ec9e0"), 1))
        brush.drawLine(x, 0, x, self.height())


# -- variant A: a row per level ---------------------------------------------

class LevelTracks(Clips):
    LANE = 19
    GAP = 5

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
                if left + width < self.HEAD or left > self.width():
                    return None
                return QRect(int(left), y, int(width), self.LANE - 2)
        return None

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
        brush.drawLine(self.HEAD - 6, 0, self.HEAD - 6, self.height())
        brush.setClipRect(QRect(self.HEAD - 6, 0,
                                self.width() - self.HEAD + 6, self.height()))
        self.draw_loop(brush)
        for clip in self.window_.show_.clips:
            if clip.kind == "cue":
                continue
            band = self.band_of(clip)
            if band is not None:
                self.draw_clip(brush, clip, band)
        for row, _level, y in self.lanes():
            if row == "Cue":
                self.draw_cues(brush, QRect(0, y, self.width(), self.LANE - 2))
        self.draw_playhead(brush)
        brush.end()


class VariantA(QWidget):
    NAME = "Как в оригинале — дорожка на уровень"

    def __init__(self, window) -> None:
        super().__init__()
        whole = QHBoxLayout(self)
        whole.setContentsMargins(0, 0, 0, 0)
        whole.setSpacing(0)
        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(2)
        left.addWidget(Preview(window), 1)
        self.loopbar = LoopBar(window)
        self.loopbar.changed.connect(window.set_loop_range)
        left.addWidget(self.loopbar)
        self.ruler = Ruler(window)
        self.ruler.moved.connect(window.go_to)
        left.addWidget(self.ruler)
        self.tracks = LevelTracks(window)
        self.tracks.setFixedHeight(self.tracks.wanted_height())
        self.tracks.picked.connect(window.pick)
        self.tracks.jumped.connect(window.go_to)
        left.addWidget(self.tracks)
        whole.addLayout(left, 1)

        self.inspector = Inspector(window)
        board = QWidget()
        holder = QVBoxLayout(board)
        holder.setContentsMargins(0, 0, 0, 0)
        holder.addWidget(self.inspector)
        board.setFixedWidth(270)
        board.setStyleSheet("background:#232323;")
        whole.addWidget(board)

    def refresh(self) -> None:
        self.inspector.refresh()
        self.loopbar.update()
        self.ruler.update()
        self.tracks.update()


# -- variant B: a row per screen, the level as a step ------------------------

class StairTracks(Clips):
    BAND = 44
    GAP = 6

    def bands(self) -> list:
        out, y = [], 2
        for row in ROWS:
            tall = self.BAND if LEVELS[row] > 1 else 22
            out.append((row, y, tall))
            y += tall + self.GAP
        return out

    def wanted_height(self) -> int:
        return sum((self.BAND if LEVELS[row] > 1 else 22) + self.GAP
                   for row in ROWS) + 4

    def step(self, row: str, y: int, tall: int, level: int) -> tuple:
        steps = LEVELS[row]
        high = max(10, (tall - 4) // steps)
        if steps == 1:
            return y + 2, high
        gap = (tall - 4 - high) // (steps - 1)
        return y + 2 + (steps - 1 - min(level, steps - 1)) * gap, high

    def band_of(self, clip):
        for row, y, tall in self.bands():
            if clip.kind == "cue":
                if row == "Cue":
                    return QRect(int(self.axis.x_of(clip.tx)) - 4, y, 9, tall)
                continue
            if row != clip.row:
                continue
            top, high = self.step(row, y, tall, clip.level)
            left = self.axis.x_of(clip.first)
            width = max(3.0, clip.span * self.axis.scale)
            if left + width < self.HEAD or left > self.width():
                return None
            return QRect(int(left), int(top), int(width), high)
        return None

    def paintEvent(self, event) -> None:       # noqa: N802
        brush = QPainter(self)
        brush.fillRect(self.rect(), QColor("#191919"))
        for row, y, tall in self.bands():
            brush.fillRect(QRect(0, y, self.width(), tall), QColor("#1d1d1d"))
            brush.setFont(QFont(MONO, 9))
            brush.setPen(QPen(QColor(HUE[row])))
            brush.drawText(6, y + 13, row)
            if LEVELS[row] > 1:
                brush.setFont(QFont(MONO, 7))
                brush.setPen(QPen(QColor("#4a4a4a")))
                for level in range(LEVELS[row]):
                    top, high = self.step(row, y, tall, level)
                    brush.drawText(56, top + high - 2, f"{level}")
        brush.setPen(QPen(QColor("#2a2a2a")))
        brush.drawLine(self.HEAD - 6, 0, self.HEAD - 6, self.height())
        brush.setClipRect(QRect(self.HEAD - 6, 0,
                                self.width() - self.HEAD + 6, self.height()))
        self.draw_loop(brush)
        for clip in self.window_.show_.clips:
            if clip.kind == "cue":
                continue
            band = self.band_of(clip)
            if band is not None:
                self.draw_clip(brush, clip, band)
        for row, y, tall in self.bands():
            if row == "Cue":
                self.draw_cues(brush, QRect(0, y, self.width(), tall))
        self.draw_playhead(brush)
        brush.end()


class VariantB(QWidget):
    NAME = "Лестница — дорожка на экран, уровень это высота ступени"

    def __init__(self, window) -> None:
        super().__init__()
        whole = QVBoxLayout(self)
        whole.setContentsMargins(0, 0, 0, 0)
        whole.setSpacing(2)
        whole.addWidget(Preview(window), 1)
        self.loopbar = LoopBar(window)
        self.loopbar.changed.connect(window.set_loop_range)
        whole.addWidget(self.loopbar)
        self.ruler = Ruler(window)
        self.ruler.moved.connect(window.go_to)
        whole.addWidget(self.ruler)
        self.tracks = StairTracks(window)
        self.tracks.setFixedHeight(self.tracks.wanted_height())
        self.tracks.picked.connect(window.pick)
        self.tracks.jumped.connect(window.go_to)
        whole.addWidget(self.tracks)
        self.inspector = Inspector(window, across=True)
        self.inspector.setStyleSheet("background:#232323;")
        whole.addWidget(self.inspector)

    def refresh(self) -> None:
        self.inspector.refresh()
        self.loopbar.update()
        self.ruler.update()
        self.tracks.update()


VARIANTS = [("A", VariantA), ("B", VariantB)]


class Switcher(QWidget):
    """Deliberately unlike the rest: this bar is not part of the design."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self.window_ = window
        self.setObjectName("switcher")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "#switcher { background:#f0c040; border-radius:13px; }"
            "QLabel { color:#1a1a1a; font-weight:bold; background:transparent; }"
            "QPushButton { background:#1a1a1a; color:#f0c040; border:none;"
            " border-radius:10px; font-weight:bold; padding:0px; }")
        line = QHBoxLayout(self)
        line.setContentsMargins(6, 4, 6, 4)
        line.setSpacing(8)
        back = QPushButton("←")
        back.setFixedSize(22, 20)
        back.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        back.clicked.connect(lambda: window.cycle(-1))
        line.addWidget(back)
        self.label = QLabel()
        line.addWidget(self.label)
        on = QPushButton("→")
        on.setFixedSize(22, 20)
        on.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        on.clicked.connect(lambda: window.cycle(1))
        line.addWidget(on)

    def refresh(self) -> None:
        key, made = VARIANTS[self.window_.variant]
        self.label.setText(f"вариант {key} — {made.NAME}    (Tab)")
        self.adjustSize()


class Transport(QWidget):
    """The play bar: the buttons, the loop, and where we are."""

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
        # Through a lambda: `clicked` hands its handler a bool, and
        # `toggle_play` takes no argument -- so the button raised every time
        # and the playhead never moved. Space calls the method directly,
        # which is why it worked and the button did not.
        self.play = button(">", lambda: window.toggle_play(),
                           "играть / пауза (Space)", 44)
        button("|>", lambda: window.nudge(1), "кадр вперёд (→)")
        button(">>", lambda: window.nudge(int(showfile.FPS)),
               "секунда вперёд (Shift+→)")
        button(">|", lambda: window.go_to(window.show_.length),
               "в конец (End)")

        line.addSpacing(12)
        self.loop = QPushButton("LOOP")
        self.loop.setCheckable(True)
        self.loop.setFixedWidth(58)
        self.loop.setToolTip(
            "Гонять плейхед по лупу и не выпускать, пока не отожмёшь (L).\n"
            "Сам луп — полоска над линейкой: тащи концы и середину.")
        self.loop.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.loop.toggled.connect(window.set_loop)
        line.addWidget(self.loop)

        whole_clip = QPushButton("по клипу")
        whole_clip.setFixedWidth(74)
        whole_clip.setToolTip(
            "Поставить луп на весь выбранный клип и включить его (Shift+L).")
        whole_clip.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        whole_clip.clicked.connect(lambda: window.loop_the_clip())
        line.addWidget(whole_clip)

        more = QPushButton("+")
        more.setFixedWidth(26)
        more.setToolTip("Поставить ещё один луп с того кадра, где плейхед.")
        more.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        more.clicked.connect(lambda: window.add_loop())
        line.addWidget(more)

        less = QPushButton("−")
        less.setFixedWidth(26)
        less.setToolTip("Убрать выбранный луп.")
        less.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        less.clicked.connect(lambda: window.drop_loop())
        line.addWidget(less)

        from_file = QPushButton("из файла")
        from_file.setFixedWidth(72)
        from_file.setToolTip(
            "Вернуть лупы, записанные в самом шоу: каждый зацикленный клип "
            "от своего кадра и до прихода следующего. Во всех сорока файлах "
            "это один луп, 800..1099.")
        from_file.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        from_file.clicked.connect(lambda: window.loop_from_file())
        line.addWidget(from_file)

        self.lock = QPushButton("замок")
        self.lock.setCheckable(True)
        self.lock.setChecked(True)
        self.lock.setFixedWidth(58)
        self.lock.setToolTip(
            "Запретить рисовать луп мышью. Числами его всё равно можно "
            "поправить — мышь тут и промахивается.")
        self.lock.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.lock.toggled.connect(window.lock_loop)
        line.addWidget(self.lock)

        # The exact control: two frame numbers, typed.
        line.addSpacing(6)
        line.addWidget(QLabel("с"))
        self.loop_low = QSpinBox()
        self.loop_low.setRange(0, 10_000_000)
        self.loop_low.setFixedWidth(78)
        self.loop_low.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.loop_low.setKeyboardTracking(False)
        line.addWidget(self.loop_low)
        line.addWidget(QLabel("по"))
        self.loop_high = QSpinBox()
        self.loop_high.setRange(0, 10_000_000)
        self.loop_high.setFixedWidth(78)
        self.loop_high.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.loop_high.setKeyboardTracking(False)
        line.addWidget(self.loop_high)
        self._saying = False
        self.loop_low.valueChanged.connect(self.typed)
        self.loop_high.valueChanged.connect(self.typed)

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

    def typed(self, _value: int = 0) -> None:
        """A number was typed into one of the boxes."""
        if self._saying:
            return
        self.window_.set_loop_range(self.loop_low.value(),
                                    self.loop_high.value())

    def say_loop(self) -> None:
        """Put the loop being edited into the boxes without hearing it back."""
        picked = self.window_.loop_region()
        self._saying = True
        self.loop_low.setValue(picked[0] if picked else 0)
        self.loop_high.setValue(picked[1] if picked else 0)
        self._saying = False

    def refresh(self) -> None:
        self.play.setText("||" if self.window_.playing else ">")
        self.say_loop()
        picked = self.window_.loop_region()
        here = self.window_.loop_here()
        said = "лупов нет"
        if picked is not None:
            said = (f"луп {self.window_.loop_at + 1} из "
                    f"{len(self.window_.loops)}: {picked[0]}..{picked[1]}"
                    f"  ({(picked[1] - picked[0]) / showfile.FPS:.1f}с)")
        if here is not None:
            said += "   плейхед внутри лупа"
        self.readout.setText(
            f"{showfile.timecode(self.window_.frame)}   "
            f"{self.window_.frame} / {self.window_.show_.length}    {said}")


class Window(QMainWindow):
    def __init__(self, first: str = "A") -> None:
        super().__init__()
        self.setWindowTitle("ПРОТОТИП — таймлайн Matreshka Viewer")
        self.resize(1680, 980)

        self.files = showfile.listing()
        self.frame = 11742
        self.chosen = None
        self.playing = False
        self.looping = False
        # Places on the timeline, not properties of the selection, and not
        # something to be invented here: the show file says where they are.
        # Several, because a show cut into blocks waits at every join.
        self.loops: list = [[0, 79200]]
        self.loop_at = 0               # the one the numbers and the mouse edit
        self.loop_locked = True
        self.backing = "Calibration"
        self.variant = next((n for n, (key, _) in enumerate(VARIANTS)
                             if key == first.upper()), 0)
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
                             "плейхед — за линейку, луп рисуется на полоске над ней"))
        top.addStretch(1)
        whole.addLayout(top)

        self.holder = QWidget()
        self.stack = QVBoxLayout(self.holder)
        self.stack.setContentsMargins(0, 0, 0, 0)
        whole.addWidget(self.holder, 1)

        self.transport = Transport(self)
        whole.addWidget(self.transport)

        self.state = QLabel()
        self.state.setFont(QFont(MONO, 9))
        self.state.setStyleSheet(
            "color:#8fbf8f; background:#151515; padding:3px;")
        self.state.setWordWrap(True)
        self.state.setFixedHeight(46)
        whole.addWidget(self.state)

        self.switcher = Switcher(self)
        self.view = None
        self.beat = QTimer(self)
        self.beat.timeout.connect(self.tick)
        self.last = time.perf_counter()
        self.build()

    # -- the variant ---------------------------------------------------------

    def build(self) -> None:
        if self.view is not None:
            self.view.setParent(None)
            self.view.deleteLater()
        _key, made = VARIANTS[self.variant]
        self.view = made(self)
        self.stack.addWidget(self.view)
        self.switcher.refresh()
        self.place_switcher()
        self.redraw()

    def cycle(self, by: int) -> None:
        self.variant = (self.variant + by) % len(VARIANTS)
        self.build()

    def place_switcher(self) -> None:
        self.switcher.adjustSize()
        self.switcher.move((self.width() - self.switcher.width()) // 2, 44)
        self.switcher.raise_()

    def resizeEvent(self, event) -> None:      # noqa: N802
        super().resizeEvent(event)
        self.place_switcher()

    # -- playing -------------------------------------------------------------

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
        at = self.frame + gone * showfile.FPS
        here = self.loop_here()
        if self.looping and here is not None:
            # Round and round the loop the playhead is standing in, until the
            # button is let go -- and then on to the next block, and the next
            # wait. That is what a show cut into blocks does.
            low, high = here
            if at >= high or at < low:
                at = low + (at - high) % max(1, high - low)
        elif at >= self.show_.length:
            at = self.show_.length
            self.playing = False
            self.beat.stop()
        self.frame = int(at)
        self.redraw()

    def set_loop(self, on: bool) -> None:
        self.looping = bool(on)
        # Nothing is moved: the loop that holds is the one the playhead is
        # already in, and if it is in none, the show simply plays on.
        self.redraw()

    def loop_here(self):
        """The loop the playhead is standing in, if it is standing in one.

        This is what playing obeys. A show cut into blocks waits at each join
        and goes on when the loop is let go, so which loop is running is a
        question about where the playhead is, not about what is selected.
        """
        for low, high in self.loops:
            if low <= self.frame < high:
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
        if hasattr(self, "transport"):
            self.transport.say_loop()
        self.redraw()

    def set_loop_range(self, low: int, high: int) -> None:
        if not self.loops:
            self.loops = [[0, self.show_.length]]
        low = max(0, min(int(low), self.show_.length - 1))
        high = max(low + 1, min(int(high), self.show_.length))
        self.loops[self.loop_at] = [low, high]
        here = self.loop_here()
        if self.looping and here is None:
            self.frame = low
        if hasattr(self, "transport"):
            self.transport.say_loop()
        self.redraw()

    def add_loop(self) -> None:
        """Another wait, starting where the playhead is."""
        low = int(self.frame)
        high = min(self.show_.length, low + int(showfile.FPS) * 5)
        self.loops.append([low, max(low + 1, high)])
        self.loops.sort()
        self.loop_at = self.loops.index([low, max(low + 1, high)])
        if hasattr(self, "transport"):
            self.transport.say_loop()
        self.redraw()

    def drop_loop(self) -> None:
        if len(self.loops) <= 0:
            return
        self.loops.pop(self.loop_at)
        self.loop_at = max(0, min(self.loop_at, len(self.loops) - 1))
        if hasattr(self, "transport"):
            self.transport.say_loop()
        self.redraw()

    def lock_loop(self, on: bool) -> None:
        """Stop the strip taking a drag, so a loop that is right stays right."""
        self.loop_locked = bool(on)
        self.redraw()

    def loop_from_file(self) -> None:
        self.loops = [list(one) for one in self.show_.loops]
        self.loop_at = 0
        if hasattr(self, "transport"):
            self.transport.say_loop()
        self.redraw()

    def loop_the_clip(self) -> None:
        """Put the loop round the whole of the selected clip, and switch it on.

        Its own button because it is the common case -- watch this block over
        and over -- while the strip is for the case the block does not cover.
        """
        clip = self.chosen
        if clip is None or clip.kind == "cue":
            return
        self.set_loop_range(clip.first, clip.last)
        self.transport.loop.setChecked(True)
        self.frame = self.loops[self.loop_at][0]
        self.redraw()

    # -- moving about --------------------------------------------------------

    def go_to(self, frame: int) -> None:
        self.frame = max(0, min(self.show_.length, int(frame)))
        self.redraw()

    def nudge(self, by: int) -> None:
        self.go_to(self.frame + by)

    def to_edge(self, end: bool) -> None:
        if self.chosen is not None:
            self.go_to(self.chosen.last - 1 if end else self.chosen.first)

    def put_clip(self, right: bool) -> None:
        """Stand the selected clip against the playhead, on one side or the other."""
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
        self.build()

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
                self.transport.loop.toggle()
        elif key == Qt.Key.Key_K:
            self.transport.lock.toggle()
        elif key == Qt.Key.Key_F:
            self.fit_axis()
        elif key == Qt.Key.Key_Tab:
            self.cycle(1)
        else:
            super().keyPressEvent(event)

    # -- saying what is going on ---------------------------------------------

    def redraw(self) -> None:
        live = self.show_.live_at(self.frame)
        said = [f"кадр {self.frame}  {showfile.timecode(self.frame)}"
                f"   {'ИГРАЕТ' if self.playing else 'стоит'}"
                f"{'  ЛУП' if self.looping else ''}"
                f"   на экранах {len(live)}: "
                + ("  |  ".join(f"{one.row} L{one.level} {one.name[:22]}"
                                for one in live) or "ничего")]
        said.append("выбран:  " + (self.chosen.says() if self.chosen
                                   else "ничего"))
        self.state.setText("\n".join(said))
        self.transport.refresh()
        if self.view is not None:
            self.view.refresh()
            self.view.update()


def main() -> int:
    first = "A"
    for word in sys.argv[1:]:
        if word.startswith("--variant="):
            first = word.split("=", 1)[1]
    app = QApplication(sys.argv)
    app.setStyleSheet(SHEET)
    window = Window(first)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
