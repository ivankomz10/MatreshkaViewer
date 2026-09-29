"""The kinetic editor's timeline: three tracks of keys, and the sound.

One strip, drawn whole: the ruler with the playhead, a lane a family --
Подъём, Вынос, Наклон -- and the sound's waveform under them. Time runs on the
viewer's own `timeline.Axis`, so zoom and scroll feel the same in both
programs, and the hand does the same things: the wheel zooms where it points,
Shift+wheel scrolls, the right button drags the piece along, the middle
button puts the playhead where it is pressed.

A key is a diamond on its family's lane. Filled when it keys every motor of
the family, hollow when only some -- a brush stroke's key is hollow, a pose
keyed with K is full. Keys are chosen by clicking (Shift adds, Ctrl takes
away) or by drawing a box, and dragged along to move; the window applies the
move so it can be undone.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

import kin_model as km
import show as showfile
import theme
import timeline
from lang import tr

HEAD = 132
INSET = 10
RULER = 32
LANE = 30
WAVE = 46

# The families by the mask colour each is painted in: R, G, B, as in Houdini.
FAMILY_COLOUR = {"lift": "#e0605a", "push": "#5fc27a", "tilt": "#5b93e0"}
FAMILY_NAME = {"lift": "Подъём", "push": "Вынос", "tilt": "Наклон"}


class KeyTimeline(QWidget):
    seek = Signal(int)
    family_chosen = Signal(str)
    chosen_changed = Signal()
    moved_keys = Signal(object, int)       # [(family, frame), ...], by frames

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("qa_kin_timeline")
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMinimumHeight(RULER + LANE * 3 + WAVE + 4)
        self.project: km.Project | None = None
        self.axis = timeline.Axis(km.FPS * 60)
        # A little in from the heads, so a key on frame 0 is a whole diamond.
        self.axis.origin = float(HEAD + INSET)
        self.frame = 0
        self.family = "tilt"               # the lane edits go to
        self.chosen: set = set()           # (family, frame)
        self.warnings: list = []           # (frame, count)
        self.dropped = {family: np.array([]) for family in km.FAMILIES}
        self.late = {family: [] for family in km.FAMILIES}
        self.clashes: list = []
        self.wave = None                   # (peaks, frames each peak covers)
        self._drag = None                  # what the left button is doing
        self._pan = None

    # -- what the window hands over --------------------------------------------

    def set_project(self, project: km.Project) -> None:
        self.project = project
        self.axis.stretch(project.length)
        self.chosen = set()
        self.dropped = {family: np.array([]) for family in km.FAMILIES}
        self.late = {family: [] for family in km.FAMILIES}
        self.clashes = []
        self.update()

    def set_frame(self, frame: int) -> None:
        frame = int(frame)
        if frame != self.frame:
            self.frame = frame
            self.update()

    def set_family(self, family: str) -> None:
        self.family = family
        self.update()

    def set_warnings(self, found) -> None:
        self.warnings = list(found)
        self.update()

    def set_simulation(self, result) -> None:
        """What the motors' own motion made of the keys: per family, the
        commands dropped (frames) and the moves arriving late (due, arrived);
        and every frame a tilt goes past its gaps on the way."""
        self.dropped = {family: np.array(sorted(one.frame for one in result.dropped
                                                if one.family == family))
                        for family in km.FAMILIES}
        self.late = {family: sorted((one.due, one.arrives) for one in result.late
                                    if one.family == family)
                     for family in km.FAMILIES}
        self.clashes = [frame for frame, _ in result.clashes]
        self.update()

    def set_sound(self, track) -> None:
        """A WAV's loudness, a peak for every frame of the piece."""
        if track is None:
            self.wave = None
            self.update()
            return
        samples = np.frombuffer(track.pcm, dtype="<i2").reshape(-1, track.channels)
        loud = np.abs(samples.astype(np.int32)).max(axis=1)
        per = max(1, int(round(track.rate / km.FPS)))
        count = len(loud) // per
        peaks = loud[:count * per].reshape(count, per).max(axis=1) / 32768.0
        self.wave = peaks.astype(np.float32)
        self.update()

    # -- geometry -----------------------------------------------------------------

    def lane_top(self, family: str) -> int:
        return RULER + km.FAMILIES.index(family) * LANE

    def family_at(self, y: float):
        if RULER <= y < RULER + LANE * 3:
            return km.FAMILIES[int((y - RULER) // LANE)]
        return None

    def resizeEvent(self, event) -> None:        # noqa: N802
        # A piece seen whole stays whole as the window is dragged wider.
        whole = self.axis.fitted
        self.axis.width = max(1, self.width() - HEAD - 2 * INSET)
        if whole:
            self.axis.fit()
        else:
            self.axis.clamp()
        super().resizeEvent(event)

    def key_at(self, point: QPointF):
        family = self.family_at(point.y())
        if family is None or self.project is None:
            return None
        track = self.project.tracks[family]
        if not len(track):
            return None
        xs = np.array([self.axis.x_of(f) for f in track.frames])
        nearest = int(np.argmin(np.abs(xs - point.x())))
        if abs(xs[nearest] - point.x()) <= 6:
            return family, track.frames[nearest]
        return None

    # -- drawing ------------------------------------------------------------------

    def paintEvent(self, event) -> None:         # noqa: N802
        brush = QPainter(self)
        brush.setRenderHint(QPainter.RenderHint.Antialiasing)
        brush.fillRect(self.rect(), QColor(theme.PANEL))
        self._draw_ruler(brush)
        for family in km.FAMILIES:
            self._draw_lane(brush, family)
        self._draw_wave(brush)
        self._draw_heads(brush)
        if self._drag and self._drag[0] == "box":
            first, last = self._drag[1], self._drag[2]
            brush.setPen(QPen(QColor(theme.LINE), 1, Qt.PenStyle.DashLine))
            brush.setBrush(QColor(106, 166, 222, 30))
            brush.drawRect(QRectF(first, last).normalized())
        self._draw_playhead(brush)
        brush.end()

    def _visible(self, x: float) -> bool:
        return HEAD - 10 <= x <= self.width() + 10

    def _draw_ruler(self, brush: QPainter) -> None:
        brush.setFont(theme.mono(8))
        for seconds in timeline._nice_steps(self.axis):
            x = self.axis.x_of(seconds * km.FPS)
            if not self._visible(x):
                continue
            brush.setPen(QPen(QColor("#4a4d54")))
            brush.drawLine(int(x), RULER - 10, int(x), RULER)
            brush.setPen(QPen(QColor(theme.DIM)))
            brush.drawText(int(x) + 5, 15, showfile.timecode(seconds * km.FPS))
        # The end of the piece.
        end = self.axis.x_of(self.project.length if self.project else 0)
        brush.fillRect(QRectF(end, RULER, max(0.0, self.width() - end),
                              self.height() - RULER), QColor(0, 0, 0, 70))
        # The motion going past the gaps, in orange under the keys' own red.
        last = None
        for frame in self.clashes:
            x = self.axis.x_of(frame)
            if self._visible(x) and (last is None or x - last >= 1):
                brush.fillRect(QRectF(x - 1, RULER - 3, 2, 3), QColor(theme.WARN))
                last = x
        # Keys over the limit, in red along the ruler's foot.
        for frame, _count in self.warnings:
            x = self.axis.x_of(frame)
            if self._visible(x):
                brush.fillRect(QRectF(x - 1.5, RULER - 6, 3, 6), QColor(theme.ERROR))
        brush.setPen(QPen(QColor(theme.SEAM)))
        brush.drawLine(0, RULER - 1, self.width(), RULER - 1)

    def _draw_lane(self, brush: QPainter, family: str) -> None:
        top = self.lane_top(family)
        shade = theme.LANE_A if km.FAMILIES.index(family) % 2 == 0 else theme.LANE_B
        brush.fillRect(QRect(HEAD, top, self.width() - HEAD, LANE), QColor(shade))
        if family == self.family:
            brush.fillRect(QRect(HEAD, top, self.width() - HEAD, LANE),
                           QColor(47, 95, 143, 40))
        if self.project is None:
            return
        # The motion's troubles first, under the keys: a move arriving late
        # is an orange bar from when it was due to when it got there, along
        # the lane's foot; a command dropped is a red tick at its head.
        late = QColor(theme.WARN)
        late.setAlpha(150)
        for due, arrives in self.late.get(family, ()):
            left, right = self.axis.x_of(due), self.axis.x_of(arrives)
            if right < HEAD or left > self.width():
                continue
            brush.fillRect(QRectF(left, top + LANE - 5, max(1.0, right - left), 3), late)
        last = None
        for frame in self.dropped.get(family, ()):
            x = self.axis.x_of(frame)
            if self._visible(x) and (last is None or x - last >= 2):
                brush.fillRect(QRectF(x - 1, top + 1, 2, 6), QColor(theme.ERROR))
                last = x
        track = self.project.tracks[family]
        colour = QColor(FAMILY_COLOUR[family])
        middle = top + LANE / 2
        last_x = None
        # Chosen keys being dragged are drawn where they would land.
        moving = (self._drag[2] if self._drag and self._drag[0] == "move" else 0)
        for index, frame in enumerate(track.frames):
            shift = moving if (family, frame) in self.chosen else 0
            x = self.axis.x_of(frame + shift)
            if not self._visible(x):
                continue
            # Keys closer than a few pixels are one diamond: at a whole show's
            # zoom there can be a key every frame.
            if last_x is not None and abs(x - last_x) < 3 \
                    and (family, frame) not in self.chosen:
                continue
            last_x = x
            full = track.keyed_count(index) == track.size
            size = 6.0
            diamond = QPolygonF([QPointF(x, middle - size), QPointF(x + size, middle),
                                 QPointF(x, middle + size), QPointF(x - size, middle)])
            if (family, frame) in self.chosen:
                brush.setPen(QPen(QColor("#ffffff"), 2))
            else:
                brush.setPen(QPen(colour.darker(150), 1))
            brush.setBrush(colour if full else QColor(theme.DEEP))
            brush.drawPolygon(diamond)
            if not full:
                brush.setBrush(colour)
                brush.setPen(Qt.PenStyle.NoPen)
                small = 2.5
                brush.drawPolygon(QPolygonF([
                    QPointF(x, middle - small), QPointF(x + small, middle),
                    QPointF(x, middle + small), QPointF(x - small, middle)]))
        brush.setPen(QPen(QColor(theme.LANE_EDGE)))
        brush.drawLine(HEAD, top + LANE - 1, self.width(), top + LANE - 1)

    def _draw_wave(self, brush: QPainter) -> None:
        top = RULER + LANE * 3
        brush.fillRect(QRect(HEAD, top, self.width() - HEAD, WAVE), QColor(theme.DEEP))
        if self.wave is None:
            return
        middle = top + WAVE / 2
        colour = QColor(theme.SCREEN["Sound"])
        colour.setAlpha(200)
        brush.setPen(QPen(colour, 1))
        first = max(0, int(self.axis.frame_of(HEAD)))
        last = min(len(self.wave), int(self.axis.frame_of(self.width())) + 1)
        if last <= first:
            return
        step = max(1, int(1.0 / max(self.axis.scale, 1e-9)))
        for frame in range(first, last, step):
            peak = float(self.wave[frame:frame + step].max()) * (WAVE / 2 - 3)
            x = self.axis.x_of(frame)
            brush.drawLine(QPointF(x, middle - peak), QPointF(x, middle + peak))

    def _draw_heads(self, brush: QPainter) -> None:
        brush.fillRect(QRect(0, 0, HEAD, self.height()), QColor(theme.PANEL))
        brush.setFont(theme.ui(9.5))
        for family in km.FAMILIES:
            top = self.lane_top(family)
            if family == self.family:
                brush.fillRect(QRect(0, top, HEAD, LANE), QColor(theme.ACCENT))
            brush.setBrush(QColor(FAMILY_COLOUR[family]))
            brush.setPen(Qt.PenStyle.NoPen)
            brush.drawRoundedRect(QRectF(12, top + LANE / 2 - 4, 8, 8), 2, 2)
            brush.setPen(QPen(QColor(theme.TEXT)))
            brush.drawText(QRect(28, top, HEAD - 60, LANE),
                           Qt.AlignmentFlag.AlignVCenter, tr(FAMILY_NAME[family]))
            if self.project is not None:
                brush.setPen(QPen(QColor(theme.QUIET)))
                brush.setFont(theme.mono(8))
                brush.drawText(QRect(HEAD - 44, top, 38, LANE),
                               Qt.AlignmentFlag.AlignVCenter
                               | Qt.AlignmentFlag.AlignRight,
                               str(len(self.project.tracks[family])))
                brush.setFont(theme.ui(9.5))
        top = RULER + LANE * 3
        brush.setPen(QPen(QColor(theme.DIM)))
        brush.drawText(QRect(28, top, HEAD - 30, WAVE), Qt.AlignmentFlag.AlignVCenter,
                       tr("Звук"))
        brush.setPen(QPen(QColor(theme.SEAM)))
        brush.drawLine(HEAD, 0, HEAD, self.height())

    def _draw_playhead(self, brush: QPainter) -> None:
        x = self.axis.x_of(self.frame)
        if not self._visible(x):
            return
        brush.fillRect(QRectF(x - 2, RULER, 4, self.height() - RULER),
                       QColor(0, 0, 0, 215))
        brush.fillRect(QRectF(x - 1, 0, 2, self.height()), QColor("#ffffff"))
        white = QColor("#ffffff")
        brush.setFont(theme.mono(8, True))
        said = tr("{0} · кадр {1}", showfile.timecode(self.frame)[3:], self.frame)
        wide = QFontMetrics(brush.font()).horizontalAdvance(said) + 14
        box = QRectF(x + 10, 6, wide, 19)
        if box.right() > self.width() - 4:
            box.moveRight(x - 10)
        brush.setPen(Qt.PenStyle.NoPen)
        brush.setBrush(white)
        # The head is a triangle, as it is in the viewer.
        brush.drawPolygon(QPolygonF([QPointF(x - 6, 2), QPointF(x + 6, 2),
                                     QPointF(x, 12)]))
        brush.drawRoundedRect(box, 4, 4)
        brush.setPen(QPen(QColor("#111111")))
        brush.drawText(box, Qt.AlignmentFlag.AlignCenter, said)

    # -- the mouse ------------------------------------------------------------------

    def _frame_at(self, x: float) -> int:
        top = self.project.length - 1 if self.project else 0
        return int(max(0, min(top, round(self.axis.frame_of(x)))))

    def wheelEvent(self, event) -> None:         # noqa: N802
        steps = event.angleDelta().y() / 120.0
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.axis.slide(steps * 80)
        else:
            self.axis.zoom_at(max(HEAD, event.position().x()), 1.25 ** steps)
        self.update()

    def mousePressEvent(self, event) -> None:    # noqa: N802
        point = event.position()
        if event.button() == Qt.MouseButton.MiddleButton:
            self.seek.emit(self._frame_at(point.x()))
            return
        if event.button() == Qt.MouseButton.RightButton:
            self._pan = event.globalPosition()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if point.x() < HEAD:
            family = self.family_at(point.y())
            if family is not None:
                self.family_chosen.emit(family)
            return
        if point.y() < RULER:
            self._drag = ("seek",)
            self.seek.emit(self._frame_at(point.x()))
            return
        family = self.family_at(point.y())
        if family is not None and family != self.family:
            self.family_chosen.emit(family)
        hit = self.key_at(point)
        mods = event.modifiers()
        if hit is not None:
            if mods & Qt.KeyboardModifier.ControlModifier:
                self.chosen.discard(hit)
            elif mods & Qt.KeyboardModifier.ShiftModifier:
                self.chosen.add(hit)
            elif hit not in self.chosen:
                self.chosen = {hit}
            self.chosen_changed.emit()
            self._drag = ("move", point.x(), 0)
        else:
            if not mods & (Qt.KeyboardModifier.ShiftModifier
                           | Qt.KeyboardModifier.ControlModifier):
                self.chosen = set()
                self.chosen_changed.emit()
            self._drag = ("box", point, point, mods)
        self.update()

    def mouseMoveEvent(self, event) -> None:     # noqa: N802
        point = event.position()
        if self._pan is not None:
            now = event.globalPosition()
            self.axis.slide(now.x() - self._pan.x())
            self._pan = now
            self.update()
            return
        if not self._drag:
            hit = self.key_at(point)
            if hit is not None and self.project is not None:
                track = self.project.tracks[hit[0]]
                count = track.keyed_count(track.index(hit[1]))
                self.setToolTip(tr("{0}: кадр {1}, моторов {2} из {3}",
                                   tr(FAMILY_NAME[hit[0]]), hit[1], count, track.size))
            else:
                self.setToolTip("")
            return
        kind = self._drag[0]
        if kind == "seek":
            self.seek.emit(self._frame_at(point.x()))
        elif kind == "move":
            by = int(round((point.x() - self._drag[1]) / max(self.axis.scale, 1e-9)))
            self._drag = ("move", self._drag[1], by)
            self.update()
        elif kind == "box":
            self._drag = ("box", self._drag[1], point, self._drag[3])
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.RightButton and self._pan is not None:
            self._pan = None
            self.unsetCursor()
            return
        if not self._drag:
            return
        kind = self._drag[0]
        if kind == "move" and self._drag[2]:
            self.moved_keys.emit(sorted(self.chosen), self._drag[2])
        elif kind == "box" and self.project is not None:
            first, last = self._drag[1], self._drag[2]
            box = QRectF(first, last).normalized()
            if box.width() > 3:
                found = set()
                for family in km.FAMILIES:
                    top = self.lane_top(family)
                    if box.bottom() < top or box.top() > top + LANE:
                        continue
                    for frame in self.project.tracks[family].frames:
                        if box.left() <= self.axis.x_of(frame) <= box.right():
                            found.add((family, frame))
                if self._drag[3] & Qt.KeyboardModifier.ControlModifier:
                    self.chosen -= found
                else:
                    self.chosen |= found
                self.chosen_changed.emit()
        self._drag = None
        self.update()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        hit = self.key_at(event.position())
        if hit is not None:
            self.seek.emit(hit[1])
