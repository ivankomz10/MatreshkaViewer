"""The kinetic editor's timeline: the keys of every motor, as deep as wanted.

Two ways to look, and the window switches between them:

  Простой    three lanes, a family each, and nothing opens: for throwing
             shapes down. It works out only what three lanes show, so it
             stays quick on the longest show
  Подробный  the lanes open like a tree, and each shows where its motors
             move: for working on the keys of a ring, a group, a cell

The ruler with the playhead, the sound's waveform under it -- both held at
the top -- and under them the lanes, which in the detailed view open:

  Подъём    the jacks            -> each ring
  Вынос     the pushers          -> each ring -> each group of five
  Наклон    the tilts            -> each ring -> each group -> each cell

and under them, in both ways, a lane for each primitive with its own keys
(`kin_prims`): where it stands, how big and how strong it is.

A lane shows the keys of the motors under it: a diamond is a key, filled
when it keys every one of them, hollow when only some. The same key of the
piece shows on every lane its motors are under, so a brush stroke across two
rings is a hollow diamond on the family's lane and a full one on each of
those rings' -- and choosing it on a ring's lane takes that ring's part of
the key alone, to move or to delete.

Many keys are the ordinary state of a show that came in from Houdini: a tilt
lane can hold a key every few frames. So a lane never draws more than it can
show. Keys closer together than a few pixels become one pill with their
count on it, which takes all of them at a click; and behind the keys a thin
band marks where the lane's motors are actually moving, which is what the
keys of a busy lane mostly come to.

Time runs on the viewer's `timeline.Axis`, so zoom and scroll feel the same
in both programs. The wheel zooms where it points and Shift+wheel scrolls;
over the names it scrolls the lanes up and down, and the right button drags
the piece along and the lanes up and down, as in the viewer. The middle
button puts the playhead where it is pressed.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QScrollBar, QWidget

import kin_model as km
import show as showfile
import theme
import timeline
from kinetic import PER_PUSHER, PER_ROW, ROWS
from lang import tr

HEAD = 190
INSET = 10
RULER = 32
WAVE = 36
BAR = 10              # the lanes' scroll bar
FAMILY_LANE = 28
SUB_LANE = 20
PRIM_LANE = 24
INDENT = 14
CLUSTER = 7           # keys closer than this, in pixels, are one pill
LONGEST = 60          # and a pill is cut here, so a busy stretch reads as
                      # a row of counts rather than one bar with one number

# The families by the mask colour each is painted in: R, G, B, as in Houdini.
FAMILY_COLOUR = {"lift": "#e0605a", "push": "#5fc27a", "tilt": "#5b93e0"}
FAMILY_NAME = {"lift": "Подъём", "push": "Вынос", "tilt": "Наклон"}
# A primitive's lane by what it does: pushing out, or pressing in.
PRIM_COLOUR = {"positive": "#c792ea", "negative": "#56c1c9"}


# -- the lanes ----------------------------------------------------------------------

@dataclass(frozen=True)
class Lane:
    """One lane: a family, or a ring, group or cell of it.

    `key` names it: (family,), (family, "r", ring), (family, "g", ring,
    group) or (family, "c", ring, cell) -- rings, groups and cells counted
    from zero, a cell by its place round its ring. A primitive's is
    ("prim", index), its place in the piece's list.
    """

    key: tuple

    @property
    def family(self) -> str:
        return self.key[0]

    @property
    def is_prim(self) -> bool:
        return self.key[0] == "prim"

    @property
    def level(self) -> int:
        if self.is_prim:
            return 0
        return {1: 0, 3: 1, 4: 2}[len(self.key)] if self.key[1:2] != ("c",) else 3

    @property
    def height(self) -> int:
        if self.is_prim:
            return PRIM_LANE
        return FAMILY_LANE if self.level == 0 else SUB_LANE

    @property
    def opens(self) -> bool:
        """Whether there is anything under it."""
        if self.is_prim:
            return False
        deepest = {"lift": 1, "push": 2, "tilt": 3}[self.family]
        return self.level < deepest

    def name(self) -> str:
        if self.is_prim:
            return tr("Примитив {0}", self.key[1] + 1)
        if self.level == 0:
            return tr(FAMILY_NAME[self.family])
        ring = self.key[2]
        if self.level == 1:
            return tr("Кольцо {0}", ring + 1)
        if self.level == 2:
            group = self.key[3]
            return tr("Группа {0} · соты {1}–{2}", group + 1,
                      group * PER_PUSHER + 1, group * PER_PUSHER + PER_PUSHER)
        return tr("Сота {0}", self.key[3] + 1)

    def mask(self) -> np.ndarray:
        """Which motors of its family it is, flat."""
        family = self.family
        size = int(np.prod(km.SHAPE[family]))
        out = np.zeros(size, bool)
        if self.level == 0:
            out[:] = True
            return out
        ring = self.key[2]
        per = {"lift": 1, "push": km.GROUPS, "tilt": PER_ROW}[family]
        if self.level == 1:
            out[ring * per:(ring + 1) * per] = True
        elif self.level == 2:
            group = self.key[3]
            if family == "push":
                out[ring * per + group] = True
            else:
                first = ring * per + group * PER_PUSHER
                out[first:first + PER_PUSHER] = True
        else:
            out[ring * per + self.key[3]] = True
        return out

    def cells(self) -> np.ndarray:
        """Which cells it is, (ROWS, PER_ROW): what a click on its name picks."""
        cells = np.zeros((ROWS, PER_ROW), bool)
        if self.level == 0:
            return cells
        ring = self.key[2]
        if self.level == 1:
            cells[ring] = True
        elif self.level == 2:
            group = self.key[3]
            cells[ring, group * PER_PUSHER:(group + 1) * PER_PUSHER] = True
        else:
            cells[ring, self.key[3]] = True
        return cells

    def children(self) -> list:
        family = self.family
        if self.level == 0:
            rings = [ring for ring in reversed(range(ROWS))
                     if not (family == "lift" and ring == km.NO_JACK)]
            return [Lane((family, "r", ring)) for ring in rings]
        ring = self.key[2]
        if self.level == 1:
            return [Lane((family, "g", ring, group)) for group in range(km.GROUPS)]
        group = self.key[3]
        return [Lane((family, "c", ring, cell))
                for cell in range(group * PER_PUSHER, (group + 1) * PER_PUSHER)]


def lane_of(key: tuple) -> Lane:
    return Lane(tuple(key))


# -- what a lane shows, worked out once per change ----------------------------------

def _moves(track: km.Track) -> list:
    """Every motor's moves, (start, end) frames: where its value changes
    from one of its keys to its next."""
    frames, values, keyed, _, _ = track._stacked()
    out = []
    for motor in range(track.size):
        mine = np.nonzero(keyed[:, motor])[0]
        if len(mine) < 2:
            out.append(np.zeros((0, 2), np.int64))
            continue
        vals = values[mine, motor]
        moving = np.abs(np.diff(vals)) > 1e-6
        out.append(np.stack([frames[mine[:-1]][moving], frames[mine[1:]][moving]],
                            axis=1))
    return out


def _merge(spans: np.ndarray) -> np.ndarray:
    if not len(spans):
        return spans
    spans = spans[np.argsort(spans[:, 0])]
    merged = [list(spans[0])]
    for start, end in spans[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return np.array(merged, np.int64)


class KeyTimeline(QWidget):
    seek = Signal(int)
    family_chosen = Signal(str)
    chosen_changed = Signal()
    moved_keys = Signal(object, int)       # [(lane key, frame), ...], by frames
    lane_picked = Signal(object)           # a lane's key
    prim_picked = Signal(int)              # a primitive's lane pressed

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("qa_kin_timeline")
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMinimumHeight(RULER + WAVE + FAMILY_LANE * 3 + 4)
        self.project: km.Project | None = None
        self.axis = timeline.Axis(km.FPS * 60)
        # A little in from the heads, so a key on frame 0 is a whole diamond.
        self.axis.origin = float(HEAD + INSET)
        self.frame = 0
        self.family = "tilt"               # the lane edits go to
        self.prim_active = -1              # the primitive being worked on
        self.detailed = False              # the tree, or three lanes
        self.expanded: set = set()         # lane keys open, in the tree
        self.chosen: set = set()           # (lane key, frame)
        self.warnings: list = []           # (frame, count)
        self.clashes: list = []
        self._dropped = (np.zeros(0, int), np.zeros(0, int), np.zeros(0, int))
        self._late = (np.zeros(0, int), np.zeros(0, int), np.zeros(0, int),
                      np.zeros(0, int))
        self.wave = None
        self.scroll = 0                    # pixels the lanes are scrolled by
        self._cache: dict = {}
        self._moves: dict = {}
        self._hits: list = []              # (rect, lane key, frames) as drawn
        self._drag = None
        self._pan = None
        self.bar = QScrollBar(Qt.Orientation.Vertical, self)
        self.bar.setObjectName("qa_kin_lanes_bar")
        self.bar.valueChanged.connect(self._scrolled)

    # -- what the window hands over --------------------------------------------

    def set_project(self, project: km.Project) -> None:
        self.project = project
        self.axis.stretch(project.length)
        self.chosen = set()
        self._cache.clear()
        self._moves.clear()
        self.clashes = []
        self._dropped = (np.zeros(0, int),) * 3
        self._late = (np.zeros(0, int),) * 4
        self._lay_bar()
        self.update()

    def set_frame(self, frame: int) -> None:
        frame = int(frame)
        if frame != self.frame:
            self.frame = frame
            self.update()

    def set_family(self, family: str) -> None:
        self.family = family
        self.update()

    def set_active_primitive(self, index: int) -> None:
        self.prim_active = int(index)
        self._lay_bar()
        self.update()

    def set_warnings(self, found) -> None:
        self.warnings = list(found)
        self.update()

    def set_simulation(self, result) -> None:
        """What the motors' own motion made of the keys: the commands
        dropped and the moves arriving late, by family and motor, so each
        lane shows its own; and every frame a tilt goes past its gaps."""
        index = {family: n for n, family in enumerate(km.FAMILIES)}
        self._dropped = tuple(np.array(column, int) for column in (
            [index[one.family] for one in result.dropped],
            [one.motor for one in result.dropped],
            [one.frame for one in result.dropped])) if result.dropped else \
            (np.zeros(0, int),) * 3
        self._late = tuple(np.array(column, int) for column in (
            [index[one.family] for one in result.late],
            [one.motor for one in result.late],
            [one.due for one in result.late],
            [one.arrives for one in result.late])) if result.late else \
            (np.zeros(0, int),) * 4
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

    def set_detailed(self, on: bool) -> None:
        """The tree of lanes, or the three families alone. Keys chosen on a
        ring's or a cell's lane are let go of on the way back to three."""
        self.detailed = bool(on)
        if not self.detailed:
            kept = {(key, frame) for key, frame in self.chosen
                    if len(key) == 1 or key[0] == "prim"}
            if kept != self.chosen:
                self.chosen = kept
                self.chosen_changed.emit()
        self.scroll = 0
        self._lay_bar()
        self.update()

    def toggle(self, key: tuple) -> None:
        """Open a lane or close it. What was open under it stays so, and is
        there again the next time it opens."""
        key = tuple(key)
        if key in self.expanded:
            self.expanded.discard(key)
        else:
            self.expanded.add(key)
        self._lay_bar()
        self.update()

    # -- the lanes, laid out ------------------------------------------------------

    def lanes(self) -> list:
        """(lane, top) for every lane showing, top from the first lane's."""
        out = []
        top = 0

        def add(lane: Lane) -> None:
            nonlocal top
            out.append((lane, top))
            top += lane.height
            if self.detailed and lane.key in self.expanded and lane.opens:
                for child in lane.children():
                    add(child)

        for family in km.FAMILIES:
            add(Lane((family,)))
        for index in range(len(getattr(self.project, "primitives", ()) or ())):
            add(Lane(("prim", index)))
        return out

    def _lanes_height(self) -> int:
        lanes = self.lanes()
        return lanes[-1][1] + lanes[-1][0].height if lanes else 0

    def _room(self) -> int:
        return max(0, self.height() - RULER - WAVE)

    def _lay_bar(self) -> None:
        spare = max(0, self._lanes_height() - self._room())
        self.bar.setRange(0, spare)
        self.bar.setPageStep(max(1, self._room()))
        self.bar.setSingleStep(SUB_LANE)
        self.bar.setVisible(spare > 0)
        self.scroll = min(self.scroll, spare)
        self.bar.setValue(self.scroll)

    def _scrolled(self, value: int) -> None:
        self.scroll = int(value)
        self.update()

    def resizeEvent(self, event) -> None:        # noqa: N802
        # A piece seen whole stays whole as the window is dragged wider.
        whole = self.axis.fitted
        self.axis.width = max(1, self.width() - HEAD - 2 * INSET - BAR)
        if whole:
            self.axis.fit()
        else:
            self.axis.clamp()
        self.bar.setGeometry(self.width() - BAR, RULER + WAVE, BAR, self._room())
        self._lay_bar()
        super().resizeEvent(event)

    def _lane_at(self, y: float):
        """(lane, top on screen) under a height on the widget, or None."""
        if y < RULER + WAVE:
            return None
        for lane, top in self.lanes():
            screen = RULER + WAVE + top - self.scroll
            if screen <= y < screen + lane.height:
                return lane, screen
        return None

    # -- what each lane holds -----------------------------------------------------

    def _lane_keys(self, lane: Lane):
        """(frames, full, counts) of the keys on a lane, and its moving
        spans -- each worked out once per change of its family's track."""
        if lane.is_prim:
            one = self.project.primitives[lane.key[1]]
            frames = np.asarray(one.frames, np.int64)
            spans = [(a, b) for a, b, va, vb in zip(one.frames[:-1], one.frames[1:],
                                                    one.values[:-1], one.values[1:])
                     if not np.allclose(va, vb)]
            return (frames, np.ones(len(frames), bool), np.ones(len(frames), int),
                    np.array(spans, np.int64).reshape(-1, 2), 1)
        track = self.project.tracks[lane.family]
        stamp = (track.version, self.detailed)
        got = self._cache.get(lane.key)
        if got is not None and got[0] == stamp:
            return got[1]
        frames, _values, keyed, _, _ = track._stacked()
        mask = lane.mask()
        sub = keyed[:, mask] if len(frames) else np.zeros((0, mask.sum()), bool)
        on = sub.any(axis=1) if len(frames) else np.zeros(0, bool)
        # Where the motors move is every motor's keys walked through: the
        # detailed view's, and left out of the simple one, which is for
        # being quick.
        spans = np.zeros((0, 2), np.int64)
        if self.detailed:
            moves = self._moves.get(lane.family)
            if moves is None or moves[0] != track.version:
                moves = (track.version, _moves(track))
                self._moves[lane.family] = moves
            mine = [moves[1][motor] for motor in np.nonzero(mask)[0]]
            spans = _merge(np.concatenate(mine)) if mine else spans
        held = (frames[on], sub.all(axis=1)[on], sub.sum(axis=1)[on], spans,
                int(mask.sum()))
        self._cache[lane.key] = (stamp, held)
        return held

    # -- drawing ------------------------------------------------------------------

    def paintEvent(self, event) -> None:         # noqa: N802
        brush = QPainter(self)
        brush.setRenderHint(QPainter.RenderHint.Antialiasing)
        brush.fillRect(self.rect(), QColor(theme.PANEL))
        self._hits = []
        brush.save()
        brush.setClipRect(QRect(0, RULER + WAVE, self.width(), self._room()))
        if self.project is not None:
            for lane, top in self.lanes():
                screen = RULER + WAVE + top - self.scroll
                if screen + lane.height < RULER + WAVE or screen > self.height():
                    continue
                self._draw_lane(brush, lane, screen)
                self._draw_head(brush, lane, screen)
        brush.restore()
        self._draw_ruler(brush)
        self._draw_wave(brush)
        if self._drag and self._drag[0] == "box":
            first, last = self._drag[1], self._drag[2]
            brush.setPen(QPen(QColor(theme.LINE), 1, Qt.PenStyle.DashLine))
            brush.setBrush(QColor(106, 166, 222, 30))
            brush.drawRect(QRectF(first, last).normalized())
        brush.setPen(QPen(QColor(theme.SEAM)))
        brush.drawLine(HEAD, 0, HEAD, self.height())
        self._draw_playhead(brush)
        brush.end()

    def _visible(self, x: float) -> bool:
        return HEAD - 10 <= x <= self.width() + 10

    def _draw_ruler(self, brush: QPainter) -> None:
        brush.fillRect(QRect(0, 0, self.width(), RULER), QColor(theme.PANEL))
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
        for frame, _count in self.warnings:
            x = self.axis.x_of(frame)
            if self._visible(x):
                brush.fillRect(QRectF(x - 1.5, RULER - 6, 3, 6), QColor(theme.ERROR))
        brush.fillRect(QRect(0, 0, HEAD, RULER), QColor(theme.PANEL))
        brush.setPen(QPen(QColor(theme.SEAM)))
        brush.drawLine(0, RULER - 1, self.width(), RULER - 1)

    def _draw_wave(self, brush: QPainter) -> None:
        top = RULER
        brush.fillRect(QRect(0, top, self.width(), WAVE), QColor(theme.DEEP))
        brush.setFont(theme.ui(9.5))
        brush.setPen(QPen(QColor(theme.DIM)))
        brush.drawText(QRect(12, top, HEAD - 20, WAVE), Qt.AlignmentFlag.AlignVCenter,
                       tr("Звук"))
        brush.setPen(QPen(QColor(theme.SEAM)))
        brush.drawLine(0, top + WAVE - 1, self.width(), top + WAVE - 1)
        if self.wave is None:
            return
        middle = top + WAVE / 2
        colour = QColor(theme.SCREEN["Sound"])
        colour.setAlpha(200)
        brush.setPen(QPen(colour, 1))
        first = max(0, int(self.axis.frame_of(HEAD)))
        last = min(len(self.wave), int(self.axis.frame_of(self.width())) + 1)
        step = max(1, int(1.0 / max(self.axis.scale, 1e-9)))
        for frame in range(first, last, step):
            peak = float(self.wave[frame:frame + step].max()) * (WAVE / 2 - 3)
            x = self.axis.x_of(frame)
            brush.drawLine(QPointF(x, middle - peak), QPointF(x, middle + peak))

    def _prim(self, lane: Lane):
        return self.project.primitives[lane.key[1]]

    def _colour(self, lane: Lane) -> QColor:
        if lane.is_prim:
            return QColor(PRIM_COLOUR[self._prim(lane).polarity])
        return QColor(FAMILY_COLOUR[lane.family])

    def _draw_head(self, brush: QPainter, lane: Lane, top: float) -> None:
        height = lane.height
        rect = QRectF(0, top, HEAD, height)
        if lane.is_prim:
            self._draw_prim_head(brush, lane, top)
            return
        active = lane.level == 0 and lane.family == self.family
        brush.fillRect(rect, QColor(theme.ACCENT if active else theme.PANEL))
        indent = 8 + lane.level * INDENT
        if lane.opens and self.detailed:
            open_ = lane.key in self.expanded
            brush.setPen(Qt.PenStyle.NoPen)
            brush.setBrush(QColor(theme.SECOND))
            x, y = indent + 4, top + height / 2
            arrow = ([QPointF(x - 3.5, y - 2), QPointF(x + 3.5, y - 2), QPointF(x, y + 2.5)]
                     if open_ else
                     [QPointF(x - 2, y - 3.5), QPointF(x + 2.5, y), QPointF(x - 2, y + 3.5)])
            brush.drawPolygon(QPolygonF(arrow))
        if lane.level == 0:
            brush.setBrush(QColor(FAMILY_COLOUR[lane.family]))
            brush.setPen(Qt.PenStyle.NoPen)
            brush.drawRoundedRect(QRectF(indent + 14, top + height / 2 - 4, 8, 8), 2, 2)
            brush.setFont(theme.ui(9.5))
            brush.setPen(QPen(QColor(theme.TEXT)))
            text_left = indent + 28
        else:
            brush.setFont(theme.ui(8.5))
            brush.setPen(QPen(QColor(theme.SECOND if lane.level == 1 else theme.DIM)))
            text_left = indent + 14
        brush.drawText(QRectF(text_left, top, HEAD - text_left - 36, height),
                       Qt.AlignmentFlag.AlignVCenter, lane.name())
        frames = self._lane_keys(lane)[0]
        brush.setFont(theme.mono(7.5))
        brush.setPen(QPen(QColor(theme.QUIET)))
        brush.drawText(QRectF(HEAD - 40, top, 34, height),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                       str(len(frames)))
        brush.setPen(QPen(QColor(theme.LANE_EDGE)))
        brush.drawLine(QPointF(0, top + height - 0.5), QPointF(HEAD, top + height - 0.5))

    def _draw_prim_head(self, brush: QPainter, lane: Lane, top: float) -> None:
        height = lane.height
        one = self._prim(lane)
        active = lane.key[1] == self.prim_active
        brush.fillRect(QRectF(0, top, HEAD, height),
                       QColor(theme.ACCENT if active else theme.PANEL))
        colour = self._colour(lane)
        brush.setPen(Qt.PenStyle.NoPen)
        brush.setBrush(colour)
        if one.kind == "sphere":
            brush.drawEllipse(QRectF(22, top + height / 2 - 4, 8, 8))
        else:
            brush.drawRect(QRectF(22, top + height / 2 - 4, 8, 8))
        brush.setFont(theme.ui(9))
        brush.setPen(QPen(QColor(theme.TEXT if one.on else theme.QUIET)))
        said = ("+ " if one.polarity == "positive" else "− ") + one.name
        if not one.on:
            said += " · " + tr("выкл")
        brush.drawText(QRectF(36, top, HEAD - 76, height),
                       Qt.AlignmentFlag.AlignVCenter, said)
        brush.setFont(theme.mono(7.5))
        brush.setPen(QPen(QColor(theme.QUIET)))
        brush.drawText(QRectF(HEAD - 40, top, 34, height),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                       str(len(one.frames)))
        brush.setPen(QPen(QColor(theme.LANE_EDGE)))
        brush.drawLine(QPointF(0, top + height - 0.5), QPointF(HEAD, top + height - 0.5))
        # The primitives' lanes start under a line of their own.
        if lane.key[1] == 0:
            brush.setPen(QPen(QColor(theme.SEAM), 2))
            brush.drawLine(QPointF(0, top + 1), QPointF(self.width(), top + 1))

    def _draw_lane(self, brush: QPainter, lane: Lane, top: float) -> None:
        height = lane.height
        shade = [theme.LANE_A, theme.LANE_B, "#1b1c20", "#1e1f23"][lane.level]
        brush.fillRect(QRectF(HEAD, top, self.width() - HEAD, height), QColor(shade))
        if (lane.level == 0 and lane.family == self.family and not lane.is_prim) or (
                lane.is_prim and lane.key[1] == self.prim_active):
            brush.fillRect(QRectF(HEAD, top, self.width() - HEAD, height),
                           QColor(47, 95, 143, 40))
        frames, full, counts, spans, size = self._lane_keys(lane)
        colour = self._colour(lane)
        middle = top + height / 2
        # Where the lane's motors are moving: a band behind the keys.
        band = QColor(colour)
        band.setAlpha(55)
        for start, end in spans:
            left, right = self.axis.x_of(start), self.axis.x_of(end)
            if right < HEAD or left > self.width():
                continue
            brush.fillRect(QRectF(left, middle - 2, max(1.0, right - left), 4), band)
        if not lane.is_prim:
            self._draw_trouble(brush, lane, top)
        # The keys, near ones as one pill.
        moving = self._drag[2] if self._drag and self._drag[0] == "move" else 0
        chosen = {frame for key, frame in self.chosen if key == lane.key}
        if not len(frames):
            self._lane_edge(brush, top, height)
            return
        shifted = np.array([frame + (moving if frame in chosen else 0)
                            for frame in frames], np.float64)
        order = np.argsort(shifted, kind="stable")
        xs = self.axis.origin + (shifted[order] - self.axis.left) * self.axis.scale
        in_view = (xs >= HEAD - 12) & (xs <= self.width() + 12)
        order, xs = order[in_view], xs[in_view]
        size_ = 6.0 if lane.level == 0 else 4.5
        start = 0
        while start < len(order):
            end = start
            while (end + 1 < len(order) and xs[end + 1] - xs[end] < CLUSTER
                   and xs[end + 1] - xs[start] < LONGEST):
                end += 1
            members = order[start:end + 1]
            picked = [int(frames[i]) for i in members]
            anyone = any(frame in chosen for frame in picked)
            x0, x1 = xs[start], xs[end]
            if end == start:
                i = members[0]
                diamond = QPolygonF([QPointF(x0, middle - size_), QPointF(x0 + size_, middle),
                                     QPointF(x0, middle + size_), QPointF(x0 - size_, middle)])
                brush.setPen(QPen(QColor("#ffffff"), 2) if anyone
                             else QPen(colour.darker(150), 1))
                brush.setBrush(colour if full[i] else QColor(theme.DEEP))
                brush.drawPolygon(diamond)
                if not full[i]:
                    brush.setBrush(colour)
                    brush.setPen(Qt.PenStyle.NoPen)
                    small = size_ * 0.42
                    brush.drawPolygon(QPolygonF([
                        QPointF(x0, middle - small), QPointF(x0 + small, middle),
                        QPointF(x0, middle + small), QPointF(x0 - small, middle)]))
                rect = QRectF(x0 - size_ - 1, middle - size_ - 1, 2 * size_ + 2,
                              2 * size_ + 2)
            else:
                rect = QRectF(x0 - size_, middle - size_ + 1, x1 - x0 + 2 * size_,
                              2 * size_ - 2)
                pill = QColor(colour)
                pill.setAlpha(170 if all(full[i] for i in members) else 110)
                brush.setPen(QPen(QColor("#ffffff"), 2) if anyone
                             else QPen(colour.darker(160), 1))
                brush.setBrush(pill)
                brush.drawRoundedRect(rect, size_ - 1, size_ - 1)
                said = str(len(members))
                if rect.width() >= 8 * len(said) + 10:
                    brush.setFont(theme.mono(7))
                    brush.setPen(QPen(QColor("#101113")))
                    brush.drawText(rect, Qt.AlignmentFlag.AlignCenter, said)
            self._hits.append((rect, lane.key, picked))
            start = end + 1
        self._lane_edge(brush, top, height)

    def _lane_edge(self, brush: QPainter, top: float, height: int) -> None:
        brush.setPen(QPen(QColor(theme.LANE_EDGE)))
        brush.drawLine(QPointF(HEAD, top + height - 0.5),
                       QPointF(self.width(), top + height - 0.5))

    def _draw_trouble(self, brush: QPainter, lane: Lane, top: float) -> None:
        """The motion's troubles on the lane's own motors: a move arriving
        late is an orange bar from when it was due to when it got there,
        along the foot; a command dropped is a red tick at the head."""
        height = lane.height
        family = km.FAMILIES.index(lane.family)
        mask = lane.mask()
        which, motor, due, arrives = self._late
        if len(which):
            mine = (which == family) & mask[np.clip(motor, 0, len(mask) - 1)]
            late = QColor(theme.WARN)
            late.setAlpha(150)
            for first, last in _merge(np.stack([due[mine], arrives[mine]], axis=1)) \
                    if mine.any() else ():
                left, right = self.axis.x_of(first), self.axis.x_of(last)
                if right < HEAD or left > self.width():
                    continue
                brush.fillRect(QRectF(left, top + height - 4, max(1.0, right - left), 2),
                               late)
        which, motor, frame = self._dropped
        if len(which):
            mine = (which == family) & mask[np.clip(motor, 0, len(mask) - 1)]
            last = None
            for one in np.unique(frame[mine]):
                x = self.axis.x_of(one)
                if self._visible(x) and (last is None or x - last >= 2):
                    brush.fillRect(QRectF(x - 1, top + 1, 2, 5), QColor(theme.ERROR))
                    last = x

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

    def hit_at(self, point: QPointF):
        """(lane key, frames) of the key or pill under a point, as drawn."""
        for rect, key, frames in reversed(self._hits):
            if rect.adjusted(-2, -2, 2, 2).contains(point):
                return key, frames
        return None

    def wheelEvent(self, event) -> None:         # noqa: N802
        steps = event.angleDelta().y() / 120.0
        if event.position().x() < HEAD:
            self.bar.setValue(self.bar.value() - int(steps * SUB_LANE * 2))
            return
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
            self._panned_y = 0.0
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if point.y() < RULER:
            self._drag = ("seek",)
            self.seek.emit(self._frame_at(point.x()))
            return
        found = self._lane_at(point.y())
        if point.x() < HEAD:
            if found is not None:
                lane, _ = found
                indent = 8 + lane.level * INDENT
                if lane.opens and self.detailed and point.x() <= indent + 12:
                    self.toggle(lane.key)
                else:
                    self.lane_picked.emit(lane.key)
            return
        if found is not None and found[0].is_prim:
            if found[0].key[1] != self.prim_active:
                self.prim_picked.emit(found[0].key[1])
        elif found is not None and found[0].family != self.family:
            self.family_chosen.emit(found[0].family)
        hit = self.hit_at(point)
        mods = event.modifiers()
        if hit is not None:
            key, frames = hit
            picked = {(key, frame) for frame in frames}
            if mods & Qt.KeyboardModifier.ControlModifier:
                self.chosen -= picked
            elif mods & Qt.KeyboardModifier.ShiftModifier:
                self.chosen |= picked
            elif not picked <= self.chosen:
                self.chosen = picked
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
            moved = now - self._pan
            self._pan = now
            self.axis.slide(moved.x())
            self._panned_y += moved.y()
            whole = int(self._panned_y)
            if whole:
                self._panned_y -= whole
                self.bar.setValue(self.bar.value() - whole)
            self.update()
            return
        if not self._drag:
            self._say_under(point)
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

    def _say_under(self, point: QPointF) -> None:
        hit = self.hit_at(point)
        if hit is None or self.project is None:
            self.setToolTip("")
            return
        key, frames = hit
        lane = lane_of(key)
        if lane.is_prim:
            name = self._prim(lane).name
            self.setToolTip(tr("{0}: кадр {1}", name, frames[0]) if len(frames) == 1
                            else tr("{0}: ключей {1}, кадры {2}–{3}", name, len(frames),
                                    min(frames), max(frames)))
            return
        track = self.project.tracks[lane.family]
        mask = lane.mask()
        if len(frames) == 1:
            index = track.index(frames[0])
            count = int((track.keyed[index] & mask).sum()) if index is not None else 0
            self.setToolTip(tr("{0}: кадр {1}, моторов {2} из {3}", lane.name(),
                               frames[0], count, int(mask.sum())))
        else:
            self.setToolTip(tr("{0}: ключей {1}, кадры {2}–{3}", lane.name(),
                               len(frames), min(frames), max(frames)))

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
            box = QRectF(self._drag[1], self._drag[2]).normalized()
            if box.width() > 3:
                found = set()
                for rect, key, frames in self._hits:
                    if box.intersects(rect):
                        found |= {(key, frame) for frame in frames}
                if self._drag[3] & Qt.KeyboardModifier.ControlModifier:
                    self.chosen -= found
                else:
                    self.chosen |= found
                self.chosen_changed.emit()
        self._drag = None
        self.update()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        point = event.position()
        if point.x() < HEAD:
            found = self._lane_at(point.y())
            if found is not None and found[0].opens and self.detailed:
                self.toggle(found[0].key)
            return
        hit = self.hit_at(point)
        if hit is not None:
            self.seek.emit(min(hit[1]))
