"""The show on a timeline: the strips under the picture and the column beside it.

Read only, this far. A show opened here is looked at and played, not
changed: nothing is dragged, no field writes into a clip and no loop is drawn,
so what goes to the site cannot be nudged by accident from a viewer. The
editor comes later and unlocks all of it at once.

What is here came out of the prototype on the `proto/timeline` branch, as it
was when it was signed off:

  LoopBar    the loops, on a strip of their own, with LOOP at its head
  Ruler      the time axis, and the only place the playhead is dragged
  Tracks     a row per level, per screen: Cue, Kinetic, Top x3, Bottom x3,
             Lamels x3, Sound x2 -- what triggers first is highest
  LoopPanel  the loops in numbers, down the right
  Inspector  the chosen clip, and its path in full

and `ShowView`, which is what they all share: the show, where the playhead
is, which clip is chosen, the loops and whether one is holding. The window
owns the clock; this is told where it has got to and asks to go elsewhere.

The mouse, the same on every strip:
  left     choose a clip. Empty space lets go, and never moves the playhead
  right    drag to scroll, without touching the playhead
  middle   the playhead here
  wheel    zoom;  Shift+wheel scroll
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (QGridLayout, QLabel, QPushButton, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

import show as showfile

MONO = "Consolas, DejaVu Sans Mono, monospace"

# Top to bottom: what triggers first is highest.
ROWS = ["Cue", "Kinetic", "Top", "Bottom", "Lamels", "Sound"]
HUE = {"Top": "#4a7ea8", "Bottom": "#4a9c78", "Lamels": "#a88a4a",
       "Sound": "#7a5aa8", "Kinetic": "#a85a5a", "Cue": "#c9a227"}
# Three content levels per screen, two sounds. The black still on the level
# behind every show is not a clip here: the viewer chooses its own backing.
LEVELS = {"Top": 3, "Bottom": 3, "Lamels": 3, "Sound": 2, "Kinetic": 1,
          "Cue": 1}
HEAD = 74            # the width of the labels down the left of every strip
SIDE = 290           # the right-hand column

# What the keys do here, for the card over the picture. Only what works in a
# show opened to be looked at: the ones that change a show are the editor's.
KEYS = [
    ("Пробел", "играть / пауза"),
    ("← →", "кадр назад / вперёд"),
    ("Shift+← →", "секунда назад / вперёд"),
    ("Ctrl+← →", "в начало / в конец"),
    ("Home / End", "в начало / в конец"),
    ("I / O", "на начало / конец клипа"),
    ("L", "отпустить луп / держать"),
    ("F", "вся длина"),
    ("?", "эта подсказка"),
    ("ЛКМ", "выбрать клип"),
    ("ПКМ", "прокрутка"),
    ("СКМ", "плейхед сюда"),
    ("колесо", "зум, с Shift — прокрутка"),
]


def keys_text() -> str:
    width = max(len(key) for key, _ in KEYS) + 2
    return "\n".join(f"{key:<{width}}{what}" for key, what in KEYS)


class Axis:
    """Where time sits across the strips. One for all of them, so they agree."""

    def __init__(self, length: int) -> None:
        self.length = max(1, int(length))
        self.origin = float(HEAD - 6)  # pixels before frame `left` is drawn
        self.left = 0.0
        self.width = 1200
        self.scale = self.width / self.length

    def fit(self, width: int | None = None) -> None:
        if width is not None:
            self.width = max(1, int(width))
        self.left = 0.0
        self.scale = self.width / self.length

    @property
    def fitted(self) -> bool:
        return abs(self.scale - self.width / self.length) < 1e-9

    def x_of(self, frame: float) -> float:
        return self.origin + (frame - self.left) * self.scale

    def frame_of(self, x: float) -> float:
        return self.left + (x - self.origin) / max(1e-9, self.scale)

    def zoom_at(self, x: float, factor: float) -> None:
        was = self.frame_of(x)
        lowest = self.width / self.length
        self.scale = max(lowest, min(4.0, self.scale * factor))
        self.left = was - (x - self.origin) / self.scale
        self.clamp()

    def slide(self, by_pixels: float) -> None:
        self.left -= by_pixels / self.scale
        self.clamp()

    def clamp(self) -> None:
        span = self.width / self.scale
        self.left = max(0.0, min(max(0.0, self.length - span), self.left))


def _nice_steps(axis: Axis) -> list:
    """Seconds to put a tick on: as close together as stays readable."""
    for step in (1, 2, 5, 10, 15, 30, 60, 120, 300, 600):
        if step * showfile.FPS * axis.scale > 70:
            break
    first = int(axis.left / showfile.FPS / step) * step
    last = int((axis.left + axis.width / axis.scale) / showfile.FPS) + step
    return list(range(first, last + 1, step))


class ShowView(QObject):
    """The show being looked at, and where in it. What the strips share.

    The loops are read out of the show file and there may be several: a show
    cut into blocks waits at every join. LOOP is off to begin with. The
    playhead crossing a loop's start from the left lights it and from then
    the loop holds; only a hand puts it out, and the loop it was let out of
    lets the playhead go on. Starting inside one does not light it -- that is
    the show being scrubbed into the middle of a wait, not arriving at it.
    """

    jumped = Signal(float)          # asked to put the playhead at a frame
    changed = Signal()              # something the strips draw is different
    moved = Signal()                # only the playhead: sixty times a second
    looping_changed = Signal(bool)  # the switch went on or off, either way

    def __init__(self) -> None:
        super().__init__()
        self.show = showfile.Show(length=1)
        self.axis = Axis(1)
        self.frame = 0.0
        self.chosen = None
        self.loops: list = []
        self.loop_at = 0               # which loop the numbers are about
        self.looping = False
        self.let_go = None             # the loop the playhead was let out of
        self.caught = None             # the loop that last caught it

    def open(self, show) -> None:
        self.show = show
        self.loops = [(int(low), int(high)) for low, high in show.loops]
        self.loop_at = 0
        was, self.looping = self.looping, False
        self.let_go = None
        self.chosen = None
        width = self.axis.width
        self.axis = Axis(show.length)
        self.axis.fit(width)
        self.frame = 0.0
        if was:
            self.looping_changed.emit(False)
        self.changed.emit()

    # -- the playhead --------------------------------------------------------

    def set_frame(self, frame: float) -> None:
        if frame == self.frame:
            return
        self.frame = float(frame)
        self.moved.emit()

    def go_to(self, frame: float) -> None:
        self.jumped.emit(float(max(0, min(self.show.length, frame))))

    # -- the loops -----------------------------------------------------------

    def loop_over(self, frame: float):
        """The loop covering a frame. Named apart from `loop_at`, the index
        into the list: one name for both was a number being called."""
        for low, high in self.loops:
            if low <= frame < high:
                return (low, high)
        return None

    def loop_here(self):
        return self.loop_over(self.frame)

    def loop_region(self):
        """The loop the numbers on the right are about."""
        if not self.loops:
            return None
        self.loop_at = max(0, min(self.loop_at, len(self.loops) - 1))
        return self.loops[self.loop_at]

    def choose_loop(self, index: int) -> None:
        if self.loops:
            self.loop_at = max(0, min(int(index), len(self.loops) - 1))
            self.changed.emit()

    def set_looping(self, on: bool, by_hand: bool = True) -> None:
        on = bool(on)
        if by_hand:
            # Let go of this loop in particular: the playhead has to be able
            # to leave it without being caught again on the very next tick.
            self.let_go = None if on else self.loop_here()
        if on == self.looping:
            return
        self.looping = on
        self.looping_changed.emit(on)
        self.changed.emit()

    def step(self, was: float, now: float):
        """Where the playhead has to be, having gone from `was` to `now`.

        None when it can stay where it got to. The loop is looked up where the
        playhead WAS, not where it is going: looking it up at the new place
        lets a single tick step over the far edge, and from outside there is
        nothing left to catch it.
        """
        over = self.loop_over(was)
        if self.let_go is not None and over != self.let_go:
            self.let_go = None           # clear of it; it may catch us again
        holding = over if (self.looping and over is not None) else None
        if holding is None:
            for low, high in self.loops:
                if was < low <= now and (low, high) != self.let_go:
                    holding = self.caught = (low, high)
                    self.set_looping(True, by_hand=False)
                    break
        if holding is None:
            return None
        low, high = holding
        if now >= high or now < low:
            return low + (now - high) % max(1, high - low)
        return None

    # -- the clip ------------------------------------------------------------

    def pick(self, clip) -> None:
        if clip is not self.chosen:
            self.chosen = clip
            self.changed.emit()

    def to_edge(self, end: bool) -> None:
        clip = self.chosen
        if clip is None:
            return
        self.go_to(clip.last - 1 if end else clip.first)


# -- the strips --------------------------------------------------------------

class _Strip(QWidget):
    """What every strip does with the mouse that is not its own business."""

    def __init__(self, view: ShowView) -> None:
        super().__init__()
        self.view = view
        self.panning = None
        self._drawn_at = None
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        view.changed.connect(self.update)
        view.moved.connect(self._follow)

    def _follow(self) -> None:
        """Redrawn when the playhead has moved a pixel, not every frame: on
        the whole show a pixel is about sixty frames, a second of playing."""
        x = int(self.axis.x_of(self.view.frame))
        if x != self._drawn_at:
            self._drawn_at = x
            self.update()

    @property
    def axis(self) -> Axis:
        return self.view.axis

    def wheelEvent(self, event) -> None:       # noqa: N802 -- Qt naming
        steps = event.angleDelta().y() / 120.0
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.axis.slide(steps * 80)
        else:
            self.axis.zoom_at(event.position().x(), 1.25 ** steps)
        self.view.changed.emit()

    def _common_press(self, event) -> bool:
        """Middle and right. True when the press was one of them."""
        x = event.position().x()
        if event.button() == Qt.MouseButton.MiddleButton:
            self.view.go_to(int(self.axis.frame_of(x)))
            return True
        if event.button() == Qt.MouseButton.RightButton:
            self.panning = x
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return True
        return False

    def _common_move(self, event) -> bool:
        if self.panning is None:
            return False
        x = event.position().x()
        self.axis.slide(x - self.panning)
        self.panning = x
        self.view.changed.emit()
        return True

    def _common_release(self) -> None:
        if self.panning is not None:
            self.panning = None
            self.unsetCursor()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._common_release()

    def draw_playhead(self, brush: QPainter, top: int = 0) -> None:
        x = int(self.axis.x_of(self.view.frame))
        brush.setPen(QPen(QColor("#4ec9e0"), 1))
        brush.drawLine(x, top, x, self.height())


class Ruler(_Strip):
    """The time axis -- and the only place the playhead is dragged."""

    def __init__(self, view: ShowView) -> None:
        super().__init__(view)
        self.setObjectName("qa_show_ruler")
        self.setFixedHeight(24)
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self.holding = False

    def _follow(self) -> None:
        self.update()           # it says the time at its head, to the frame

    def paintEvent(self, event) -> None:      # noqa: N802
        brush = QPainter(self)
        brush.fillRect(self.rect(), QColor("#171717"))
        brush.setFont(QFont(MONO, 8))
        for seconds in _nice_steps(self.axis):
            x = self.axis.x_of(seconds * showfile.FPS)
            if not HEAD - 10 <= x <= self.width() + 40:
                continue
            brush.setPen(QPen(QColor("#4a4a4a")))
            brush.drawLine(int(x), 16, int(x), 24)
            brush.setPen(QPen(QColor("#8a8a8a")))
            brush.drawText(int(x) + 3, 14,
                           showfile.timecode(seconds * showfile.FPS)[3:])
        brush.fillRect(QRect(0, 0, HEAD - 6, self.height()), QColor("#171717"))
        brush.setPen(QPen(QColor("#6a6a6a")))
        brush.drawText(6, 15, showfile.timecode(self.view.frame)[3:])
        x = int(self.axis.x_of(self.view.frame))
        brush.setPen(QPen(QColor("#4ec9e0"), 1))
        brush.drawLine(x, 6, x, self.height())
        brush.setPen(Qt.PenStyle.NoPen)
        brush.setBrush(QColor("#4ec9e0"))
        brush.drawPolygon([QPoint(x - 5, 6), QPoint(x + 5, 6), QPoint(x, 14)])
        brush.end()

    def mousePressEvent(self, event) -> None:   # noqa: N802
        if self._common_press(event):
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.holding = True
            self.view.go_to(int(self.axis.frame_of(event.position().x())))

    def mouseMoveEvent(self, event) -> None:    # noqa: N802
        if self._common_move(event):
            return
        if self.holding:
            self.view.go_to(int(self.axis.frame_of(event.position().x())))

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self.holding = False
        self._common_release()


class LoopBar(_Strip):
    """The loops, on a strip of their own, with their switch at its head."""

    def __init__(self, view: ShowView) -> None:
        super().__init__(view)
        self.setObjectName("qa_show_loopbar")
        self.setFixedHeight(20)

        self.switch = QPushButton("LOOP", self)
        self.switch.setObjectName("qa_show_loop")
        self.switch.setCheckable(True)
        self.switch.setGeometry(2, 1, HEAD - 12, 18)
        self.switch.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.switch.setToolTip(
            "Загорается сам, когда плейхед въезжает в луп слева: с этого "
            "момента луп держит. Нажми, чтобы отпустить — плейхед поедет "
            "дальше, до следующего лупа (L).")
        self.switch.setStyleSheet(
            "QPushButton { font-size:10px; padding:0px; }"
            "QPushButton:checked { background:#c9a227; color:#1a1a1a;"
            " border-color:#e0b830; }")
        # By hand only: the playhead lighting it is told the other way round.
        self.switch.clicked.connect(lambda on: view.set_looping(on))
        view.looping_changed.connect(self._shown)

    def _shown(self, on: bool) -> None:
        self.switch.blockSignals(True)
        self.switch.setChecked(bool(on))
        self.switch.blockSignals(False)

    def paintEvent(self, event) -> None:      # noqa: N802
        brush = QPainter(self)
        brush.fillRect(self.rect(), QColor("#141414"))
        brush.setClipRect(QRect(HEAD - 6, 0, self.width(), self.height()))
        here = self.view.loop_here()
        for index, (low, high) in enumerate(self.view.loops):
            left, right = int(self.axis.x_of(low)), int(self.axis.x_of(high))
            running = self.view.looping and here == (low, high)
            picked = index == self.view.loop_at
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
        brush.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._common_press(event):
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        # Choosing which loop the numbers are about. Nothing is drawn: in a
        # show opened to be looked at, the loops are the file's.
        at = self.axis.frame_of(event.position().x())
        near = 4 / max(1e-9, self.axis.scale)
        for index, (low, high) in enumerate(self.view.loops):
            if low - near <= at <= high + near:
                self.view.choose_loop(index)
                break

    def mouseMoveEvent(self, event) -> None:   # noqa: N802
        self._common_move(event)


class Tracks(_Strip):
    """A row per level, per screen."""

    LANE = 19
    GAP = 5

    def __init__(self, view: ShowView) -> None:
        super().__init__(view)
        self.setObjectName("qa_show_tracks")
        self.setMouseTracking(True)
        self.setFixedHeight(self.wanted_height())

    def resizeEvent(self, event) -> None:      # noqa: N802
        was = self.axis.fitted
        self.axis.width = max(1, self.width() - HEAD + 6)
        if was:
            self.axis.fit()
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

    @classmethod
    def wanted_height(cls) -> int:
        return sum(LEVELS[row] * cls.LANE + cls.GAP for row in ROWS) + 4

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
                ends = min(clip.last, self.view.show.length)
                width = max(3.0, (ends - clip.first) * self.axis.scale)
                if left + width < HEAD or left > self.width():
                    return None
                return QRect(int(left), y, int(width), self.LANE - 2)
        return None

    def clip_under(self, where: QPoint):
        for clip in reversed(self.view.show.clips):
            band = self.band_of(clip)
            if band is not None and band.adjusted(-2, 0, 2, 0).contains(where):
                return clip
        return None

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._common_press(event):
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.view.pick(self.clip_under(event.position().toPoint()))

    def mouseMoveEvent(self, event) -> None:   # noqa: N802
        if self._common_move(event):
            return
        clip = self.clip_under(event.position().toPoint())
        self.setToolTip(_says(clip) if clip is not None else "")

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

    @staticmethod
    def _shade(brush: QPainter, band: QRect, wide: float, head: bool) -> None:
        for step in range(int(wide)):
            x = band.left() + step if head else band.right() - int(wide) + step
            if band.left() <= x <= band.right():
                much = (1 - step / max(1.0, wide)) if head \
                    else step / max(1.0, wide)
                brush.setPen(QPen(QColor(0, 0, 0, int(165 * much))))
                brush.drawLine(x, band.top(), x, band.bottom())

    def draw_clip(self, brush: QPainter, clip, band: QRect) -> None:
        colour = QColor("#a03030") if clip.missing else QColor(HUE[clip.row])
        chosen = clip is self.view.chosen
        body = QColor(colour)
        body.setAlpha(215 if chosen else 130)
        brush.fillRect(band, body)
        # The motor is still carrying out its last command after the file has
        # run out, so the clip goes on -- hatched, because nothing is read
        # there: the screens are only still arriving.
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
        tail_px = int(clip.tail * self.axis.scale) if clip.tail else 0
        faded = band.adjusted(0, 0, -tail_px, 0)
        if clip.fade_end:
            wide = abs(clip.fade_end) * self.axis.scale
            if wide > 2:
                self._shade(brush, faded, wide, head=False)
                self.mark_fade(brush, faded, wide, clip.fade_end)
        if clip.fade_start:
            wide = abs(clip.fade_start) * self.axis.scale
            if wide > 2:
                self._shade(brush, band, wide, head=True)
                self.mark_fade(brush, band, wide, clip.fade_start, head=True)
        if clip.crop_end:
            cut = int(abs(clip.crop_end) * self.axis.scale)
            brush.setPen(QPen(QColor("#d06060"), 1, Qt.PenStyle.DotLine))
            brush.drawLine(faded.right(), faded.center().y(),
                           faded.right() + cut, faded.center().y())
            brush.setPen(QPen(QColor("#d06060"), 2))
            brush.drawLine(faded.right(), faded.top() + 1,
                           faded.right(), faded.top() + 4)
            brush.drawLine(faded.right(), faded.bottom() - 4,
                           faded.right(), faded.bottom() - 1)
        brush.setPen(QPen(QColor("#e8e8e8") if chosen else colour.lighter(130)))
        brush.drawRect(band)
        if band.width() > 34:
            brush.setFont(QFont(MONO, 8))
            brush.setPen(QPen(QColor("#f0f0f0" if chosen else "#c8c8c8")))
            room = band.adjusted(4, 0, -3, 0)
            room.setLeft(max(room.left(), HEAD - 2))
            metrics = QFontMetrics(brush.font())
            brush.drawText(room, Qt.AlignmentFlag.AlignVCenter,
                           metrics.elidedText(clip.name,
                                              Qt.TextElideMode.ElideMiddle,
                                              max(0, room.width())))

    def draw_cues(self, brush: QPainter, band: QRect) -> None:
        for clip in self.view.show.clips:
            if clip.kind != "cue":
                continue
            x = int(self.axis.x_of(clip.tx))
            chosen = clip is self.view.chosen
            brush.setPen(QPen(QColor("#f5dd70" if chosen else HUE["Cue"]),
                              3 if chosen else 1))
            brush.drawLine(x, band.top(), x, band.bottom())
            if self.axis.scale > 0.015:
                brush.setFont(QFont(MONO, 7))
                brush.setPen(QPen(QColor("#f5dd70" if chosen else "#9a8420")))
                brush.drawText(x + 4, band.top() + 10,
                               f"u{clip.universe}·ch{clip.channel}·v{clip.value}")

    def draw_loops(self, brush: QPainter) -> None:
        here = self.view.loop_here()
        for low, high in self.view.loops:
            left, right = int(self.axis.x_of(low)), int(self.axis.x_of(high))
            running = self.view.looping and here == (low, high)
            brush.fillRect(QRect(left, 0, max(2, right - left), self.height()),
                           QColor(201, 162, 39, 34 if running else 12))
            brush.setPen(QPen(QColor("#f0c040" if running else "#5a5030"),
                              2 if running else 1))
            brush.drawLine(left, 0, left, self.height())
            brush.drawLine(right, 0, right, self.height())

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
        for clip in self.view.show.clips:
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


def _says(clip) -> str:
    """One line about a clip, for its tooltip."""
    if clip.kind == "cue":
        return (f"кью  кадр {clip.tx}  universe {clip.universe}  "
                f"channel {clip.channel}  value {clip.value}")
    said = f"{clip.name}\n{clip.row} L{clip.level}   {clip.first}..{clip.last}"
    if clip.missing:
        said += "\nфайла нет на этой машине"
    return said


class TimelinePane(QWidget):
    """Everything under the picture: a line of what is where, then the strips."""

    def __init__(self, view: ShowView) -> None:
        super().__init__()
        self.setObjectName("qa_show_pane")
        self.view = view
        whole = QVBoxLayout(self)
        whole.setContentsMargins(0, 2, 0, 0)
        whole.setSpacing(2)

        self.state = QLabel()
        self.state.setObjectName("qa_show_state")
        self.state.setFont(QFont(MONO, 9))
        self.state.setStyleSheet("color:#8fbf8f;")
        self.state.setTextFormat(Qt.TextFormat.PlainText)
        whole.addWidget(self.state)

        self.loopbar = LoopBar(view)
        whole.addWidget(self.loopbar)
        self.ruler = Ruler(view)
        whole.addWidget(self.ruler)
        self.tracks = Tracks(view)
        # Scrolled rather than squeezed, so the boundary above can give the
        # picture its height back on a small monitor.
        scroller = QScrollArea()
        scroller.setObjectName("qa_show_scroll")
        scroller.setWidget(self.tracks)
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QScrollArea.Shape.NoFrame)
        scroller.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroller.setMinimumHeight(60)
        whole.addWidget(scroller, 1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        self._said = None
        view.changed.connect(self.refresh)
        view.moved.connect(self.refresh)

    def wanted_height(self) -> int:
        return Tracks.wanted_height() + 20 + 24 + 22 + 8

    def refresh(self) -> None:
        view = self.view
        at = int(view.frame)
        live = view.show.live_at(at)
        here = view.loop_here()
        said = (f"{showfile.timecode(at)}   кадр {at} / {view.show.length}"
                + ("   В ЛУПЕ" if here is not None and view.looping else "")
                + "   на экранах: "
                + ("  |  ".join(f"{one.row} L{one.level} {one.name[:24]}"
                                for one in live) or "ничего"))
        if said != self._said:
            self._said = said
            self.state.setText(said)


# -- the right-hand column ---------------------------------------------------

class LoopPanel(QWidget):
    """The loops in numbers: on 22 minutes a pixel is 56 frames."""

    def __init__(self, view: ShowView) -> None:
        super().__init__()
        self.setObjectName("qa_show_loops")
        self.view = view
        whole = QVBoxLayout(self)
        whole.setContentsMargins(8, 6, 8, 8)
        whole.setSpacing(4)
        title = QLabel("Лупы")
        title.setFont(QFont(MONO, 10, QFont.Weight.Bold))
        whole.addWidget(title)
        self.says = QLabel()
        self.says.setObjectName("qa_show_loop_says")
        self.says.setFont(QFont(MONO, 9))
        self.says.setStyleSheet("color:#c9a227;")
        self.says.setWordWrap(True)
        whole.addWidget(self.says)
        self.frames = QLabel()
        self.frames.setObjectName("qa_show_loop_frames")
        self.frames.setFont(QFont(MONO, 9))
        self.frames.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        whole.addWidget(self.frames)
        self.setStyleSheet("background:#282520;")
        view.changed.connect(self.refresh)
        view.moved.connect(self.refresh)

    def refresh(self) -> None:
        view = self.view
        picked = view.loop_region()
        here = view.loop_here()
        said = "лупов нет"
        if picked is not None:
            said = (f"луп {view.loop_at + 1} из {len(view.loops)}   "
                    f"{(picked[1] - picked[0]) / showfile.FPS:.1f}с")
        if here is not None:
            said += ("   ДЕРЖИТ" if view.looping
                     else "   плейхед внутри, луп отпущен")
        self.says.setText(said)
        self.frames.setText("\n".join(
            f"{'>' if index == view.loop_at else ' '} {index + 1}  "
            f"с {low}  по {high}"
            for index, (low, high) in enumerate(view.loops)) or "—")


class Inspector(QWidget):
    """The chosen clip. Shown, not offered: in this mode nothing is typed in."""

    MEDIA = [("Дорожка", "row"), ("Уровень", "level"), ("Кадр начала", "tx"),
             ("Длина", "frames"), ("Доезд моторов", "tail"),
             ("Подрезка с хвоста", "crop_end"), ("Фейд с хвоста", "fade_end"),
             ("Подрезка с головы", "crop_start"),
             ("Фейд с головы", "fade_start"), ("Занимает", "range"),
             ("Начинается", "at")]
    CUE = [("Кадр", "tx"), ("Время", "range"), ("Universe", "universe"),
           ("Channel", "channel"), ("Value", "value"), ("Уровень", "level")]

    def __init__(self, view: ShowView) -> None:
        super().__init__()
        self.setObjectName("qa_show_inspector")
        self.view = view
        self.shown: list = []
        self.body: dict = {}
        whole = QVBoxLayout(self)
        whole.setContentsMargins(0, 0, 0, 0)
        whole.setSpacing(2)
        self.title = QLabel("клип не выбран")
        self.title.setObjectName("qa_show_clip")
        self.title.setFont(QFont(MONO, 10, QFont.Weight.Bold))
        self.title.setWordWrap(True)
        self.title.setContentsMargins(8, 6, 8, 0)
        whole.addWidget(self.title)
        holder = QWidget()
        self.grid = QGridLayout(holder)
        self.grid.setContentsMargins(8, 4, 8, 4)
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(3)
        whole.addWidget(holder)
        # The path gets a block of its own, across the whole column, because
        # it has to be readable in full and a grid row will not grow for it.
        tag = QLabel("Файл")
        tag.setStyleSheet("color:#8a8a8a;")
        tag.setContentsMargins(8, 6, 8, 0)
        whole.addWidget(tag)
        self.path = QLabel("—")
        self.path.setObjectName("qa_show_path")
        self.path.setFont(QFont(MONO, 9))
        self.path.setWordWrap(True)
        self.path.setContentsMargins(8, 0, 8, 6)
        self.path.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.path.setStyleSheet("color:#b4b4b4;")
        whole.addWidget(self.path)
        whole.addStretch(1)
        self._lay_out(self.MEDIA)
        view.changed.connect(self.refresh)
        self._for = object()

    def _lay_out(self, names) -> None:
        for widget in self.shown:
            self.grid.removeWidget(widget)
            widget.setParent(None)
        self.shown, self.body = [], {}
        for index, (label, key) in enumerate(names):
            tag = QLabel(label)
            tag.setStyleSheet("color:#8a8a8a;")
            tag.setFixedWidth(126)
            field = QLabel("—")
            field.setObjectName(f"qa_show_field_{key}")
            field.setFont(QFont(MONO, 9))
            self.grid.addWidget(tag, index, 0)
            self.grid.addWidget(field, index, 1)
            self.shown += [tag, field]
            self.body[key] = field
        self.grid.setColumnStretch(1, 1)

    def refresh(self) -> None:
        clip = self.view.chosen
        if clip is self._for:
            return
        self._for = clip
        wanted = self.CUE if (clip is not None and clip.kind == "cue") \
            else self.MEDIA
        if [one[1] for one in wanted] != list(self.body):
            self._lay_out(wanted)
        if clip is None:
            self.title.setText("клип не выбран")
            self.path.setText("—")
            for field in self.body.values():
                field.setText("—")
            return
        self.title.setText(f"кью на кадре {clip.tx}" if clip.kind == "cue"
                           else clip.name + ("   (нет файла)"
                                             if clip.missing else ""))
        self.path.setText(clip.path or "—")
        fps = showfile.FPS
        length = "—"
        if clip.still:
            length = "картинка"
        elif clip.frames:
            length = f"{clip.frames}  ({clip.frames / fps:.1f} с)"
        said = {
            "row": clip.row,
            "level": str(clip.level),
            "tx": str(clip.tx),
            "frames": length,
            "tail": (f"+{clip.tail}  ({clip.tail / fps:.1f} с)"
                     if clip.tail else "—"),
            "range": (showfile.timecode(clip.tx) if clip.kind == "cue"
                      else f"{clip.first}..{min(clip.last, self.view.show.length)}"),
            "at": showfile.timecode(clip.first),
            "universe": str(clip.universe),
            "channel": str(clip.channel),
            "value": str(clip.value),
        }
        for key in ("crop_end", "fade_end", "crop_start", "fade_start"):
            value = int(getattr(clip, key, 0) or 0)
            said[key] = f"{value}  ({abs(value) / fps:.1f} с)" if value else "0"
        for key, field in self.body.items():
            field.setText(said.get(key, "—"))


class SidePane(QWidget):
    """The right-hand column: the loops, then the chosen clip."""

    def __init__(self, view: ShowView) -> None:
        super().__init__()
        self.setObjectName("qa_show_side")
        self.setFixedWidth(SIDE)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("#qa_show_side { background:#262626; }")
        stack = QVBoxLayout(self)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(0)
        self.loops = LoopPanel(view)
        stack.addWidget(self.loops)
        self.inspector = Inspector(view)
        stack.addWidget(self.inspector, 1)
