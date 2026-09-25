"""PROTOTYPE -- throwaway. Three timelines for the Matreshka viewer.

The question: which shape of timeline is comfortable to work a 22 minute show
in, before any of it is built for real.

Three variants, switchable from the floating bar at the bottom (or the Left and
Right arrow keys, or `--variant=B` on the command line):

  A  «Как в оригинале»  -- a row per level, inspector down the right side.
                           Eleven rows. Faithful to the tool they know.
  B  «Лестница»         -- a row per screen, the level drawn as the step's
                           height, which is what the original actually does.
                           Five rows, inspector as a strip under the tracks.
  C  «Секции»           -- the show as a table of sections: rows are screens,
                           columns are the instants the show is cut at. Time
                           becomes secondary; what lines up becomes obvious.

Real shows, read from D:\\Content\\_SHOW. Nothing is ever written back: dragging
a clip moves it in memory and the next reload forgets it.

Run:   tool\\proto_timeline\\run.bat        or  python proto.py --variant=C
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from PySide6.QtCore import QPoint, QRect, Qt, Signal          # noqa: E402
from PySide6.QtGui import (QColor, QFont, QFontMetrics,       # noqa: E402
                           QPainter, QPen)
from PySide6.QtWidgets import (QApplication, QComboBox,       # noqa: E402
                               QGridLayout, QHBoxLayout, QLabel, QMainWindow,
                               QPushButton, QScrollArea, QSizePolicy,
                               QVBoxLayout, QWidget)

import show as showfile                                       # noqa: E402

MONO = "Consolas, DejaVu Sans Mono, monospace"

# Close enough to the viewer's own palette that density reads honestly.
SHEET = """
QWidget { background:#1e1e1e; color:#dcdcdc; font-size:12px; }
QLabel { color:#dcdcdc; }
QPushButton { background:#2d2d2d; border:1px solid #3c3c3c; padding:3px 8px; }
QPushButton:hover { background:#383838; }
QComboBox { background:#2d2d2d; border:1px solid #3c3c3c; padding:2px 6px; }
QComboBox QAbstractItemView { background:#252525; selection-background-color:#3d5a72; }
"""

ROWS = ["Top", "Bottom", "Lamels", "Sound", "Kinetic", "Cue"]
HUE = {"Top": "#4a7ea8", "Bottom": "#4a9c78", "Lamels": "#a88a4a",
       "Sound": "#7a5aa8", "Kinetic": "#a85a5a", "Cue": "#c9a227"}
LEVELS = {"Top": 4, "Bottom": 4, "Lamels": 4, "Sound": 2, "Kinetic": 1,
          "Cue": 1}


class Axis:
    """Where time sits on the screen. Shared maths, not shared layout."""

    def __init__(self, length: int) -> None:
        self.length = length
        self.left = 0.0                # first visible frame
        self.scale = 0.017             # pixels per frame
        self.width = 1200

    def fit(self, width: int) -> None:
        self.width = max(1, width)
        self.left = 0.0
        self.scale = self.width / max(1, self.length)

    origin = 0.0                   # pixels before frame `left` is drawn

    def x_of(self, frame: float) -> float:
        return self.origin + (frame - self.left) * self.scale

    def frame_of(self, x: float) -> float:
        return self.left + (x - self.origin) / max(1e-9, self.scale)

    def zoom_at(self, x: float, factor: float) -> None:
        was = self.frame_of(x)
        lowest = self.width / max(1, self.length)      # never zoom out past fit
        self.scale = max(lowest, min(2.0, self.scale * factor))
        self.left = was - x / self.scale
        self.clamp()

    def slide(self, by_pixels: float) -> None:
        self.left -= by_pixels / self.scale
        self.clamp()

    def clamp(self) -> None:
        span = self.width / self.scale
        self.left = max(0.0, min(self.length - span, self.left))


# -- the pieces every variant is free to use or ignore -----------------------

class Ruler(QWidget):
    """A time axis with a playhead that can be dragged."""

    moved = Signal(int)

    def __init__(self, axis: Axis, frame_now) -> None:
        super().__init__()
        self.axis = axis
        self.frame_now = frame_now
        self.setFixedHeight(22)
        self.setCursor(Qt.CursorShape.SizeHorCursor)

    def paintEvent(self, event) -> None:      # noqa: N802
        brush = QPainter(self)
        brush.fillRect(self.rect(), QColor("#171717"))
        brush.setFont(QFont(MONO, 8))
        # A label every so often, on a round number of seconds.
        for seconds in _nice_steps(self.axis):
            x = self.axis.x_of(seconds * showfile.FPS)
            if not -40 <= x <= self.width() + 40:
                continue
            brush.setPen(QPen(QColor("#4a4a4a")))
            brush.drawLine(int(x), 14, int(x), 22)
            brush.setPen(QPen(QColor("#8a8a8a")))
            brush.drawText(int(x) + 3, 12,
                           showfile.timecode(int(seconds * showfile.FPS))[3:])
        x = self.axis.x_of(self.frame_now())
        brush.setPen(QPen(QColor("#4ec9e0"), 1))
        brush.drawLine(int(x), 0, int(x), self.height())
        brush.end()

    def mousePressEvent(self, event) -> None:   # noqa: N802
        self.moved.emit(int(self.axis.frame_of(event.position().x())))

    def mouseMoveEvent(self, event) -> None:    # noqa: N802
        self.moved.emit(int(self.axis.frame_of(event.position().x())))


def _nice_steps(axis: Axis) -> list:
    """Seconds to label, so the ruler never crowds."""
    for step in (1, 2, 5, 10, 15, 30, 60, 120, 300):
        if step * showfile.FPS * axis.scale > 70:
            break
    first = int(axis.left / showfile.FPS / step) * step
    last = int((axis.left + axis.width / axis.scale) / showfile.FPS) + step
    return list(range(first, last + 1, step))


class Preview(QWidget):
    """Where the building would be. A prototype has nothing to render, so it
    says what would be on each screen instead -- which is the more useful
    thing to look at while judging a timeline anyway."""

    def __init__(self, window) -> None:
        super().__init__()
        self.window_ = window
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)

    def paintEvent(self, event) -> None:      # noqa: N802
        brush = QPainter(self)
        brush.fillRect(self.rect(), QColor("#101010"))
        wide, tall = self.width(), self.height()
        box = QRect(int(wide * 0.5 - tall * 0.35), int(tall * 0.08),
                    int(tall * 0.7), int(tall * 0.84))
        brush.setPen(QPen(QColor("#2a2a2a"), 1, Qt.PenStyle.DashLine))
        brush.drawRect(box)
        brush.setPen(QPen(QColor("#3c3c3c")))
        brush.setFont(QFont(MONO, 8))
        brush.drawText(box.left(), box.top() - 4, "превью (в прототипе не рисуется)")

        live = self.window_.show_.live_at(self.window_.frame)
        brush.setFont(QFont(MONO, 9))
        y = box.top() + 18
        for row in ROWS[:5]:
            here = [one for one in live if one.row == row]
            brush.setPen(QPen(QColor(HUE[row])))
            brush.drawText(box.left() + 10, y, f"{row:8}")
            brush.setPen(QPen(QColor("#b4b4b4" if here else "#454545")))
            said = "  +  ".join(f"{one.name[:26]} L{one.level}" for one in here)
            brush.drawText(box.left() + 80, y, said or "— тишина —")
            y += 18
        brush.setPen(QPen(QColor("#6a6a6a")))
        brush.setFont(QFont(MONO, 10))
        brush.drawText(box.left() + 10, box.bottom() - 10,
                       f"{showfile.timecode(self.window_.frame)}    "
                       f"кадр {self.window_.frame} из {self.window_.show_.length}")
        brush.end()


class Inspector(QWidget):
    """The selected clip's settings. Same fields either variant puts it in."""

    def __init__(self, window, across: bool = False) -> None:
        super().__init__()
        self.window_ = window
        self.across = across
        self.fields: dict = {}
        grid = QGridLayout(self)
        grid.setContentsMargins(8, 6, 8, 6)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)

        self.title = QLabel("клип не выбран")
        self.title.setFont(QFont(MONO, 10, QFont.Weight.Bold))
        self.title.setWordWrap(not across)
        grid.addWidget(self.title, 0, 0, 1, 4 if across else 2)

        names = [("Дорожка", "row"), ("Уровень", "level"),
                 ("Кадр начала", "tx"), ("Длина", "frames"),
                 ("Подрезка с хвоста", "crop_end"),
                 ("Фейд с хвоста", "fade_end"),
                 ("Подрезка с головы", "crop_start"),
                 ("Фейд с головы", "fade_start"),
                 ("Луп", "loop"), ("Свой луп", "loop_range"),
                 ("Занимает", "range"), ("Файл", "path")]
        for index, (label, key) in enumerate(names):
            tag = QLabel(label)
            tag.setStyleSheet("color:#8a8a8a;")
            tag.setFixedWidth(126 if not across else 108)
            value = QLabel("—")
            value.setFont(QFont(MONO, 9))
            value.setWordWrap(True)
            value.setAlignment(Qt.AlignmentFlag.AlignLeft
                               | Qt.AlignmentFlag.AlignVCenter)
            self.fields[key] = value
            if across:
                column = (index % 4) * 2
                grid.addWidget(tag, 1 + index // 4, column)
                grid.addWidget(value, 1 + index // 4, column + 1)
            else:
                grid.addWidget(tag, 1 + index, 0)
                grid.addWidget(value, 1 + index, 1)
        if not across:
            grid.setRowStretch(len(names) + 1, 1)
            grid.setColumnStretch(1, 1)
        else:
            for column in (1, 3, 5, 7):
                grid.setColumnStretch(column, 1)

    def refresh(self) -> None:
        clip = self.window_.chosen
        if clip is None:
            self.title.setText("клип не выбран")
            for value in self.fields.values():
                value.setText("—")
            return
        self.title.setText(clip.name)
        got = {
            "row": clip.row, "level": str(clip.level), "tx": str(clip.tx),
            "frames": f"{clip.frames}  ({clip.frames / showfile.FPS:.1f} с)",
            "crop_end": str(clip.crop_end), "fade_end": str(clip.fade_end),
            "crop_start": str(clip.crop_start),
            "fade_start": str(clip.fade_start),
            "loop": "да" if clip.loop else "нет",
            "loop_range": str(list(clip.loop_range)),
            "range": f"{clip.first}..{clip.last}  "
                     f"{showfile.timecode(clip.first)}",
            "path": clip.path or "—",
        }
        for key, value in self.fields.items():
            value.setText(got.get(key, "—"))


class Clips(QWidget):
    """Common behaviour for the two variants that draw clips against time:
    pick one, drag it, zoom, scrub. Each variant lays its rows out itself."""

    picked = Signal(object)
    scrubbed = Signal(int)

    HEAD = 74

    def __init__(self, window, axis: Axis) -> None:
        super().__init__()
        self.window_ = window
        self.axis = axis
        self.dragging = None
        self.grabbed = 0
        self.setMouseTracking(True)

    def resizeEvent(self, event) -> None:      # noqa: N802
        # The axis has to be as wide as the place clips are actually drawn in,
        # or "the whole show" stops short of the right edge -- which is what
        # the first look at variant B showed.
        was_fitted = abs(self.axis.scale
                         - self.axis.width / max(1, self.axis.length)) < 1e-9
        self.axis.width = max(1, self.width() - self.HEAD + 6)
        self.axis.origin = self.HEAD - 6
        if was_fitted:
            self.axis.fit(self.axis.width)
        self.axis.clamp()
        super().resizeEvent(event)

    def rows_here(self) -> list:
        raise NotImplementedError

    def band_of(self, clip):
        """The rectangle a clip occupies. Variants differ only in this."""
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
        clip = self.clip_under(where)
        if event.button() == Qt.MouseButton.MiddleButton or clip is None:
            self.scrubbed.emit(int(self.axis.frame_of(where.x())))
            self.dragging = "time"
            return
        self.picked.emit(clip)
        if clip.kind != "cue":
            self.dragging = clip
            self.grabbed = int(self.axis.frame_of(where.x())) - clip.tx

    def mouseMoveEvent(self, event) -> None:   # noqa: N802
        if self.dragging is None:
            return
        at = int(self.axis.frame_of(event.position().x()))
        if self.dragging == "time":
            self.scrubbed.emit(at)
            return
        wanted = max(0, at - self.grabbed)
        self.dragging.tx = self.window_.snap(self.dragging, wanted, self.axis)
        self.window_.touch_state()
        self.window_.redraw()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self.dragging = None

    # -- drawing helpers -----------------------------------------------------

    def draw_clip(self, brush: QPainter, clip, band: QRect,
                  with_name: bool = True) -> None:
        colour = QColor(HUE[clip.row])
        if clip.missing:
            colour = QColor("#a03030")
        chosen = clip is self.window_.chosen
        body = QColor(colour)
        body.setAlpha(210 if chosen else 130)
        brush.fillRect(band, body)
        if clip.loop:
            # A looped clip is hatched, so the one that holds all show is not
            # mistaken for a very long file.
            brush.setPen(QPen(QColor(255, 255, 255, 40)))
            for x in range(band.left(), band.right(), 7):
                brush.drawLine(x, band.top(), x - band.height(), band.bottom())
        # The fade out, as a wedge -- this is the thing the show actually uses.
        if clip.fade_end:
            wide = abs(clip.fade_end) * self.axis.scale
            if wide > 2:
                brush.setPen(QPen(QColor(0, 0, 0, 120)))
                for step in range(int(wide)):
                    part = step / max(1.0, wide)
                    x = band.right() - int(wide) + step
                    if band.left() <= x <= band.right():
                        shade = QColor(0, 0, 0, int(160 * part))
                        brush.setPen(QPen(shade))
                        brush.drawLine(x, band.top(), x, band.bottom())
        if clip.crop_end:
            brush.setPen(QPen(QColor("#c04040"), 1, Qt.PenStyle.DotLine))
            cut = band.right() + int(abs(clip.crop_end) * self.axis.scale)
            brush.drawLine(band.right(), band.center().y(),
                           cut, band.center().y())
        brush.setPen(QPen(QColor("#e8e8e8") if chosen else colour.lighter(130)))
        brush.drawRect(band)
        if with_name and band.width() > 34:
            brush.setFont(QFont(MONO, 8))
            brush.setPen(QPen(QColor("#f0f0f0" if chosen else "#c8c8c8")))
            room = band.adjusted(4, 0, -3, 0)
            metrics = QFontMetrics(brush.font())
            brush.drawText(room, Qt.AlignmentFlag.AlignVCenter,
                           metrics.elidedText(clip.name,
                                              Qt.TextElideMode.ElideMiddle,
                                              room.width()))

    def draw_playhead(self, brush: QPainter) -> None:
        x = int(self.axis.x_of(self.window_.frame))
        brush.setPen(QPen(QColor("#4ec9e0"), 1))
        brush.drawLine(x, 0, x, self.height())

    def draw_cues(self, brush: QPainter, band: QRect) -> None:
        brush.setPen(QPen(QColor(HUE["Cue"]), 1))
        for clip in self.window_.show_.clips:
            if clip.kind != "cue":
                continue
            x = int(self.axis.x_of(clip.tx))
            brush.drawLine(x, band.top(), x, band.bottom())
            if self.axis.scale > 0.05:
                brush.setFont(QFont(MONO, 7))
                brush.drawText(x + 3, band.top() + 9, f"ch{clip.channel}")


# -- variant A: a row per level ---------------------------------------------

class LevelTracks(Clips):
    LANE = 19
    GAP = 5
    HEAD = 74

    def lanes(self) -> list:
        """(row, level, y) for every lane, in order down the widget."""
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
            band = QRect(0, y, self.width(), self.LANE - 2)
            brush.fillRect(band, QColor("#202020" if level % 2 else "#1c1c1c"))
            brush.setFont(QFont(MONO, 8))
            brush.setPen(QPen(QColor(HUE[row]) if level == 0
                              else QColor("#5a5a5a")))
            label = f"{row} L{level}" if LEVELS[row] > 1 else row
            brush.drawText(6, y + self.LANE - 7, label)
        brush.setPen(QPen(QColor("#2a2a2a")))
        brush.drawLine(self.HEAD - 6, 0, self.HEAD - 6, self.height())

        brush.setClipRect(QRect(self.HEAD - 6, 0,
                                self.width() - self.HEAD + 6, self.height()))
        for clip in self.window_.show_.clips:
            if clip.kind == "cue":
                continue
            band = self.band_of(clip)
            if band is not None:
                self.draw_clip(brush, band=band, clip=clip)
        for row, level, y in self.lanes():
            if row == "Cue":
                self.draw_cues(brush, QRect(0, y, self.width(), self.LANE - 2))
        self.draw_playhead(brush)
        brush.end()


class VariantA(QWidget):
    NAME = "Как в оригинале — дорожка на уровень"

    def __init__(self, window) -> None:
        super().__init__()
        self.window_ = window
        axis = window.axis
        whole = QHBoxLayout(self)
        whole.setContentsMargins(0, 0, 0, 0)
        whole.setSpacing(0)

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(2)
        left.addWidget(Preview(window), 1)

        self.ruler = Ruler(axis, lambda: window.frame)
        self.ruler.moved.connect(window.go_to)
        left.addWidget(self.ruler)

        self.tracks = LevelTracks(window, axis)
        self.tracks.setFixedHeight(self.tracks.wanted_height())
        self.tracks.picked.connect(window.pick)
        self.tracks.scrubbed.connect(window.go_to)
        left.addWidget(self.tracks)
        whole.addLayout(left, 1)

        self.inspector = Inspector(window)
        self.inspector.setFixedWidth(270)
        holder = QVBoxLayout()
        holder.setContentsMargins(0, 0, 0, 0)
        holder.addWidget(self.inspector)
        board = QWidget()
        board.setLayout(holder)
        board.setStyleSheet("background:#232323;")
        whole.addWidget(board)

    def refresh(self) -> None:
        self.inspector.refresh()
        self.ruler.update()
        self.tracks.update()


# -- variant B: a row per screen, the level as a step ------------------------

class StairTracks(Clips):
    BAND = 46
    GAP = 6
    HEAD = 74

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

    def band_of(self, clip):
        for row, y, tall in self.bands():
            if row != clip.row:
                continue
            steps = LEVELS[row]
            high = max(10, (tall - 6) // max(1, steps))
            # The step's height is the level number, which is how the show
            # editor itself draws it -- and why nothing there implies a depth.
            top = y + 2 + (steps - 1 - min(clip.level, steps - 1)) * \
                ((tall - 6 - high) // max(1, steps - 1)) if steps > 1 else y + 2
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
                    high = max(10, (tall - 6) // LEVELS[row])
                    top = y + 2 + (LEVELS[row] - 1 - level) * \
                        ((tall - 6 - high) // (LEVELS[row] - 1))
                    brush.drawText(52, top + high - 2, f"{level}")
        brush.setPen(QPen(QColor("#2a2a2a")))
        brush.drawLine(self.HEAD - 6, 0, self.HEAD - 6, self.height())

        brush.setClipRect(QRect(self.HEAD - 6, 0,
                                self.width() - self.HEAD + 6, self.height()))
        for clip in self.window_.show_.clips:
            if clip.kind == "cue":
                continue
            band = self.band_of(clip)
            if band is not None:
                self.draw_clip(brush, band=band, clip=clip)
        for row, y, tall in self.bands():
            if row == "Cue":
                self.draw_cues(brush, QRect(0, y, self.width(), tall))
        self.draw_playhead(brush)
        brush.end()


class VariantB(QWidget):
    NAME = "Лестница — дорожка на экран, уровень это высота ступени"

    def __init__(self, window) -> None:
        super().__init__()
        self.window_ = window
        whole = QVBoxLayout(self)
        whole.setContentsMargins(0, 0, 0, 0)
        whole.setSpacing(2)
        whole.addWidget(Preview(window), 1)

        self.ruler = Ruler(window.axis, lambda: window.frame)
        self.ruler.moved.connect(window.go_to)
        whole.addWidget(self.ruler)

        self.tracks = StairTracks(window, window.axis)
        self.tracks.setFixedHeight(self.tracks.wanted_height())
        self.tracks.picked.connect(window.pick)
        self.tracks.scrubbed.connect(window.go_to)
        whole.addWidget(self.tracks)

        self.inspector = Inspector(window, across=True)
        self.inspector.setStyleSheet("background:#232323;")
        whole.addWidget(self.inspector)

    def refresh(self) -> None:
        self.inspector.refresh()
        self.ruler.update()
        self.tracks.update()


# -- variant C: the show as a table of sections ------------------------------

class SectionStrip(QWidget):
    """A thin proportional map of the whole show, to keep time in sight."""

    picked = Signal(int)

    def __init__(self, window) -> None:
        super().__init__()
        self.window_ = window
        self.setFixedHeight(34)

    def paintEvent(self, event) -> None:       # noqa: N802
        brush = QPainter(self)
        brush.fillRect(self.rect(), QColor("#161616"))
        whole = max(1, self.window_.show_.length)
        marks = self.window_.show_.sections()
        for index, (at, holds) in enumerate(marks):
            stop = marks[index + 1][0] if index + 1 < len(marks) else whole
            left = int(at / whole * self.width())
            width = max(2, int((stop - at) / whole * self.width()) - 1)
            chosen = index == self.window_.section
            colour = QColor("#3d6a8a" if chosen else "#2a2a2a")
            brush.fillRect(QRect(left, 6, width, 20), colour)
            brush.setPen(QPen(QColor("#5a5a5a")))
            brush.drawRect(QRect(left, 6, width, 20))
            if width > 46:
                brush.setFont(QFont(MONO, 7))
                brush.setPen(QPen(QColor("#c8c8c8" if chosen else "#7a7a7a")))
                brush.drawText(left + 3, 20,
                               showfile.timecode(at)[3:8])
        x = int(self.window_.frame / whole * self.width())
        brush.setPen(QPen(QColor("#4ec9e0"), 1))
        brush.drawLine(x, 0, x, self.height())
        brush.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.picked.emit(int(event.position().x() / max(1, self.width())
                             * self.window_.show_.length))


class SectionTable(QWidget):
    """Rows are screens, columns are the instants the show is cut at."""

    picked = Signal(object)
    chose = Signal(int)

    COLUMN = 148
    LANE = 26
    HEAD = 74

    def __init__(self, window) -> None:
        super().__init__()
        self.window_ = window

    def wanted(self) -> tuple:
        marks = self.window_.show_.sections()
        return (self.HEAD + len(marks) * self.COLUMN + 20,
                len(ROWS) * self.LANE + 34)

    def cell_of(self, index: int, row: str) -> QRect:
        return QRect(self.HEAD + index * self.COLUMN,
                     30 + ROWS.index(row) * self.LANE,
                     self.COLUMN - 3, self.LANE - 3)

    def paintEvent(self, event) -> None:       # noqa: N802
        brush = QPainter(self)
        brush.fillRect(self.rect(), QColor("#191919"))
        marks = self.window_.show_.sections()
        brush.setFont(QFont(MONO, 9))
        for index, (at, holds) in enumerate(marks):
            chosen = index == self.window_.section
            head = QRect(self.HEAD + index * self.COLUMN, 4,
                         self.COLUMN - 3, 22)
            brush.fillRect(head, QColor("#2d4a5e" if chosen else "#222222"))
            brush.setPen(QPen(QColor("#dcdcdc" if chosen else "#8a8a8a")))
            brush.drawText(head.adjusted(5, 0, 0, 0),
                           Qt.AlignmentFlag.AlignVCenter,
                           f"{index + 1}.  {showfile.timecode(at)[3:8]}")
        for row in ROWS:
            brush.setFont(QFont(MONO, 9))
            brush.setPen(QPen(QColor(HUE[row])))
            brush.drawText(6, 30 + ROWS.index(row) * self.LANE + 17, row)
        for index, (at, holds) in enumerate(marks):
            for row in ROWS:
                cell = self.cell_of(index, row)
                here = [one for one in holds if one.row == row]
                brush.fillRect(cell, QColor("#1e1e1e"))
                brush.setPen(QPen(QColor("#262626")))
                brush.drawRect(cell)
                if not here:
                    continue
                clip = here[0]
                colour = QColor("#a03030" if clip.missing else HUE[row])
                body = QColor(colour)
                body.setAlpha(200 if clip is self.window_.chosen else 120)
                brush.fillRect(cell, body)
                brush.setFont(QFont(MONO, 8))
                brush.setPen(QPen(QColor("#f0f0f0")))
                metrics = QFontMetrics(brush.font())
                text = clip.name
                if len(here) > 1:
                    text += f"  +{len(here) - 1}"
                brush.drawText(cell.adjusted(4, 0, -3, 0),
                               Qt.AlignmentFlag.AlignVCenter,
                               metrics.elidedText(text,
                                                  Qt.TextElideMode.ElideMiddle,
                                                  cell.width() - 8))
                if clip.kind != "cue":
                    brush.setFont(QFont(MONO, 7))
                    brush.setPen(QPen(QColor("#00000090")))
                    brush.drawText(cell.adjusted(4, 0, -4, 0),
                                   Qt.AlignmentFlag.AlignRight
                                   | Qt.AlignmentFlag.AlignVCenter,
                                   f"{clip.span / showfile.FPS:.0f}с")
        brush.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        where = event.position().toPoint()
        marks = self.window_.show_.sections()
        for index, (at, holds) in enumerate(marks):
            for row in ROWS:
                if self.cell_of(index, row).contains(where):
                    here = [one for one in holds if one.row == row]
                    self.chose.emit(index)
                    if here:
                        self.picked.emit(here[0])
                    return
            head = QRect(self.HEAD + index * self.COLUMN, 4,
                         self.COLUMN - 3, 22)
            if head.contains(where):
                self.chose.emit(index)
                return


class VariantC(QWidget):
    NAME = "Секции — таблица: строки экраны, колонки секции шоу"

    def __init__(self, window) -> None:
        super().__init__()
        self.window_ = window
        whole = QHBoxLayout(self)
        whole.setContentsMargins(0, 0, 0, 0)
        whole.setSpacing(0)

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(2)
        left.addWidget(Preview(window), 1)

        self.strip = SectionStrip(window)
        self.strip.picked.connect(window.go_to)
        left.addWidget(self.strip)

        self.table = SectionTable(window)
        self.table.picked.connect(window.pick)
        self.table.chose.connect(window.choose_section)
        scroller = QScrollArea()
        scroller.setWidget(self.table)
        scroller.setWidgetResizable(False)
        scroller.setFixedHeight(len(ROWS) * SectionTable.LANE + 52)
        left.addWidget(scroller)
        self.scroller = scroller
        whole.addLayout(left, 1)

        self.inspector = Inspector(window)
        self.inspector.setFixedWidth(270)
        board = QWidget()
        holder = QVBoxLayout(board)
        holder.setContentsMargins(0, 0, 0, 0)
        holder.addWidget(self.inspector)
        board.setStyleSheet("background:#232323;")
        whole.addWidget(board)

    def refresh(self) -> None:
        self.inspector.refresh()
        wide, tall = self.table.wanted()
        self.table.setMinimumSize(wide, tall)
        self.table.resize(wide, tall)
        self.strip.update()
        self.table.update()


# -- the switcher and the window --------------------------------------------

VARIANTS = [("A", VariantA), ("B", VariantB), ("C", VariantC)]


class Switcher(QWidget):
    """Deliberately unlike the rest: this bar is not part of the design."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self.window_ = window
        # A plain QWidget paints no background of its own from a stylesheet
        # unless it is told to, which is why the bar came out invisible.
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
        back.clicked.connect(lambda: window.cycle(-1))
        line.addWidget(back)
        self.label = QLabel()
        line.addWidget(self.label)
        on = QPushButton("→")
        on.setFixedSize(22, 20)
        on.clicked.connect(lambda: window.cycle(1))
        line.addWidget(on)

    def refresh(self) -> None:
        key, made = VARIANTS[self.window_.variant]
        self.label.setText(f"вариант {key} — {made.NAME}"
                           f"    (←/→ или стрелки)")
        self.adjustSize()


class Window(QMainWindow):
    def __init__(self, first: str = "A") -> None:
        super().__init__()
        self.setWindowTitle("ПРОТОТИП — таймлайн Matreshka Viewer")
        self.resize(1680, 980)

        self.files = showfile.listing()
        self.frame = 11742          # inside the crossfade the document is about
        self.chosen = None
        self.section = 0
        self.variant = next((n for n, (key, _) in enumerate(VARIANTS)
                             if key == first.upper()), 0)
        self.show_ = showfile.read(self.files[0])
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
        self.picker.setMinimumWidth(420)
        self.picker.currentIndexChanged.connect(self.open_show)
        top.addWidget(QLabel("шоу"))
        top.addWidget(self.picker)
        fit = QPushButton("вся длина")
        fit.clicked.connect(self.fit_axis)
        top.addWidget(fit)
        top.addWidget(QLabel("колесо — зум, Shift+колесо — прокрутка, "
                             "средняя кнопка или пустое место — плейхед, "
                             "клип тащится мышью"))
        top.addStretch(1)
        whole.addLayout(top)

        self.holder = QWidget()
        self.stack = QVBoxLayout(self.holder)
        self.stack.setContentsMargins(0, 0, 0, 0)
        whole.addWidget(self.holder, 1)

        self.state = QLabel()
        self.state.setFont(QFont(MONO, 9))
        self.state.setStyleSheet("color:#8fbf8f; background:#151515; padding:3px;")
        self.state.setWordWrap(True)
        self.state.setFixedHeight(46)
        whole.addWidget(self.state)

        self.switcher = Switcher(self)
        self.view = None
        self.build()

    # -- the variant ---------------------------------------------------------

    def build(self) -> None:
        if self.view is not None:
            self.view.setParent(None)
            self.view.deleteLater()
        key, made = VARIANTS[self.variant]
        self.view = made(self)
        self.stack.addWidget(self.view)
        self.axis.fit(max(400, self.width() - 300))
        self.switcher.refresh()
        self.place_switcher()
        self.redraw()

    def cycle(self, by: int) -> None:
        self.variant = (self.variant + by) % len(VARIANTS)
        self.build()

    def place_switcher(self) -> None:
        # Over the preview, which is empty in every variant. At the bottom
        # it sat on variant B's inspector and on variant C's scroll bar.
        self.switcher.adjustSize()
        self.switcher.move((self.width() - self.switcher.width()) // 2, 44)
        self.switcher.raise_()

    def resizeEvent(self, event) -> None:      # noqa: N802
        super().resizeEvent(event)
        self.place_switcher()

    def keyPressEvent(self, event) -> None:    # noqa: N802
        if event.key() == Qt.Key.Key_Left:
            self.cycle(-1)
        elif event.key() == Qt.Key.Key_Right:
            self.cycle(1)
        elif event.key() == Qt.Key.Key_F:
            self.fit_axis()
        else:
            super().keyPressEvent(event)

    # -- the show ------------------------------------------------------------

    def open_show(self, index: int) -> None:
        self.show_ = showfile.read(self.files[index])
        self.chosen = None
        self.section = 0
        self.axis = Axis(self.show_.length)
        self.build()

    def fit_axis(self) -> None:
        self.axis.fit(self.axis.width)
        self.redraw()

    def go_to(self, frame: int) -> None:
        self.frame = max(0, min(self.show_.length, int(frame)))
        self.touch_state()
        self.redraw()

    def pick(self, clip) -> None:
        self.chosen = clip
        self.touch_state()
        self.redraw()

    def choose_section(self, index: int) -> None:
        self.section = index
        marks = self.show_.sections()
        if 0 <= index < len(marks):
            self.frame = marks[index][0]
        self.touch_state()
        self.redraw()

    def snap(self, clip, wanted: int, axis: Axis) -> int:
        """Stick to a neighbour's edge, and to zero, within eight pixels."""
        close = 8 / max(1e-9, axis.scale)
        edges = [0]
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

    def touch_state(self) -> None:
        live = self.show_.live_at(self.frame)
        said = [f"кадр {self.frame}  {showfile.timecode(self.frame)}"
                f"   играет {len(live)}: "
                + ("  |  ".join(f"{one.row} L{one.level} {one.name[:22]}"
                                for one in live) or "ничего")]
        said.append("выбран:  " + (self.chosen.says() if self.chosen
                                   else "ничего"))
        self.state.setText("\n".join(said))

    def redraw(self) -> None:
        self.touch_state()
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
