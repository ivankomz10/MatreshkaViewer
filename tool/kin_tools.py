"""The kinetic editor's tools, each a panel down the right of the window.

  Кисть     paints one family at a time: the value to paint towards, how
            big, how hard, how strongly; paint, smooth or erase
  Выбор     cells, groups of five or whole rings, and values set on them:
            a ring's height, a group's push, a cell's tilt -- and the
            auto-rotate, which lays the cells along the shape
  Профиль   the vase: a curve from the lowest ring to the top, how far out
            each ring is pushed, and the cells tilted along it
  Кольца    thirty rings, each at one of its jack's four places

A panel does nothing itself. It calls the window (`actions`), which knows
the frame, writes the keys and keeps the undo -- so every tool edits the
piece the same way, and a change from a panel is a change like any other.
"""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDoubleSpinBox,
                               QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QSlider, QSpinBox, QVBoxLayout,
                               QWidget)

import kin_model as km
import kinetic
import theme
from kin_timeline import FAMILY_COLOUR, FAMILY_NAME
from kinetic import ROWS
from lang import tr

LIFT_MM = tuple(int(kinetic.JACK_STATE_MM[state]) for state in range(4))


def heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setFont(theme.heading())
    label.setStyleSheet(f"color:{theme.TEXT}; padding-top:6px;")
    return label


def note(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(f"color:{theme.QUIET}; font-size:11px;")
    return label


def segments(names, name: str, on_pick, checked: int = 0):
    """A row of buttons of which one is on, as the viewer's level switch."""
    holder = QWidget()
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(2)
    group = QButtonGroup(holder)
    group.setExclusive(True)
    buttons = []
    for index, text in enumerate(names):
        button = QPushButton(str(text))
        button.setCheckable(True)
        button.setProperty("segment", True)
        button.setObjectName(f"{name}_{index}")
        button.setChecked(index == checked)
        group.addButton(button, index)
        row.addWidget(button)
        buttons.append(button)
    group.idClicked.connect(on_pick)
    holder.group = group
    holder.buttons = buttons
    return holder


class Slider(QWidget):
    """A slider with its number beside it, in the value's own units.

    `pressed` and `released` bracket a drag, so the window can make one undo
    step of it rather than one a pixel.
    """

    moved = Signal(float)
    pressed = Signal()
    released = Signal()

    def __init__(self, low: float, high: float, value: float, unit: str,
                 name: str, step: float = 1.0, decimals: int = 0) -> None:
        super().__init__()
        self.low, self.high, self.step = low, high, step
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setObjectName(name)
        self.slider.setRange(0, int(round((high - low) / step)))
        self.number = QDoubleSpinBox()
        self.number.setObjectName(name + "_number")
        self.number.setRange(low, high)
        self.number.setDecimals(decimals)
        self.number.setSingleStep(step)
        self.number.setSuffix(f" {unit}" if unit else "")
        self.number.setFixedWidth(96)
        self.number.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        row.addWidget(self.slider, 1)
        row.addWidget(self.number)
        self.set(value)
        self.slider.valueChanged.connect(self._slid)
        self.slider.sliderPressed.connect(self.pressed)
        self.slider.sliderReleased.connect(self.released)
        self.number.editingFinished.connect(self._typed)

    def value(self) -> float:
        return float(self.number.value())

    def set(self, value: float) -> None:
        for widget in (self.slider, self.number):
            widget.blockSignals(True)
        self.slider.setValue(int(round((value - self.low) / self.step)))
        self.number.setValue(value)
        for widget in (self.slider, self.number):
            widget.blockSignals(False)

    def _slid(self, position: int) -> None:
        value = self.low + position * self.step
        self.number.blockSignals(True)
        self.number.setValue(value)
        self.number.blockSignals(False)
        self.moved.emit(value)

    def _typed(self) -> None:
        value = self.value()
        self.slider.blockSignals(True)
        self.slider.setValue(int(round((value - self.low) / self.step)))
        self.slider.blockSignals(False)
        self.pressed.emit()
        self.moved.emit(value)
        self.released.emit()


def labelled(text: str, widget: QWidget) -> QWidget:
    holder = QWidget()
    column = QVBoxLayout(holder)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(3)
    label = QLabel(text)
    label.setStyleSheet(f"color:{theme.DIM}; font-size:11.5px;")
    column.addWidget(label)
    column.addWidget(widget)
    return holder


class Panel(QWidget):
    """A tool's column: its controls stacked, room to spare at the foot."""

    def __init__(self, actions, name: str) -> None:
        super().__init__()
        self.setObjectName(name)
        self.actions = actions
        self.column = QVBoxLayout(self)
        self.column.setContentsMargins(14, 8, 14, 14)
        self.column.setSpacing(10)

    def finish(self) -> None:
        self.column.addStretch(1)

    def refresh(self) -> None:
        """Say again what the piece is at the playhead. Nothing by default."""


# -- the brush ------------------------------------------------------------------

class BrushPanel(Panel):
    FAMILIES = ("Подъём", "Вынос", "Наклон")
    MODES = ("Красить", "Сгладить", "Стереть")
    MODE_KEYS = ("paint", "smooth", "erase")

    def __init__(self, actions) -> None:
        super().__init__(actions, "qa_kin_brush_panel")
        self.column.addWidget(heading(tr("Кисть")))
        self.layer = segments([tr(x) for x in self.FAMILIES], "qa_kin_brush_layer",
                              lambda i: actions.set_family(km.FAMILIES[i]), 2)
        self.column.addWidget(labelled(tr("Слой"), self.layer))

        # What is painted towards, in the family's own units: one of four
        # places for a jack, millimetres for a pusher, degrees for a tilt.
        self.lift = segments([f"{mm}" for mm in LIFT_MM], "qa_kin_brush_lift",
                             lambda i: setattr(actions, "brush_lift", i), 1)
        self.lift_box = labelled(tr("Положение домкрата, мм"), self.lift)
        self.push = Slider(0, 1000, 500, tr("мм"), "qa_kin_brush_push", 10)
        self.push.moved.connect(lambda v: setattr(actions, "brush_push", v / 1000.0))
        self.push_box = labelled(tr("Вынос, мм"), self.push)
        self.tilt = Slider(-30, 30, 10, "°", "qa_kin_brush_tilt", 0.5, 1)
        self.tilt.moved.connect(lambda v: setattr(actions, "brush_tilt", v / 90.0))
        self.tilt_box = labelled(tr("Наклон, градусы"), self.tilt)
        for box in (self.lift_box, self.push_box, self.tilt_box):
            self.column.addWidget(box)

        self.mode = segments([tr(x) for x in self.MODES], "qa_kin_brush_mode",
                             lambda i: setattr(actions, "brush_mode",
                                               self.MODE_KEYS[i]))
        self.column.addWidget(labelled(tr("Как"), self.mode))
        self.radius = Slider(0.5, 15, 2.5, tr("сот"), "qa_kin_brush_radius", 0.5, 1)
        self.radius.moved.connect(actions.set_brush_radius)
        self.column.addWidget(labelled(tr("Размер"), self.radius))
        self.hardness = Slider(0, 100, 50, "%", "qa_kin_brush_hardness", 5)
        self.hardness.moved.connect(actions.set_brush_hardness)
        self.column.addWidget(labelled(tr("Жёсткость"), self.hardness))
        self.strength = Slider(5, 100, 60, "%", "qa_kin_brush_strength", 5)
        self.strength.moved.connect(
            lambda v: setattr(actions, "brush_strength", v / 100.0))
        self.column.addWidget(labelled(tr("Сила"), self.strength))
        self.column.addWidget(note(tr("Красит слой, выбранный выше, на кадре под плейхедом: ключ ставится "
            "только тем моторам, которых коснулась кисть. Пушер слушается самой "
            "закрашенной из своих пяти сот, домкрат — кольца, закрашенного больше "
            "чем наполовину. Ctrl+колесо — размер.")))
        self.finish()
        self.show_family("tilt")

    def show_family(self, family: str) -> None:
        self.layer.buttons[km.FAMILIES.index(family)].setChecked(True)
        self.lift_box.setVisible(family == "lift")
        self.push_box.setVisible(family == "push")
        self.tilt_box.setVisible(family == "tilt")

    def show_radius(self, radius: float) -> None:
        self.radius.set(radius)


# -- the selection ----------------------------------------------------------------

class SelectPanel(Panel):
    GRAINS = ("Сота", "Группа", "Кольцо")
    GRAIN_KEYS = ("cell", "group", "ring")

    def __init__(self, actions) -> None:
        super().__init__(actions, "qa_kin_select_panel")
        self.column.addWidget(heading(tr("Выбор")))
        self.grain = segments([tr(x) for x in self.GRAINS], "qa_kin_grain",
                              lambda i: actions.set_grain(self.GRAIN_KEYS[i]))
        self.column.addWidget(labelled(tr("Щелчок берёт"), self.grain))
        buttons = QWidget()
        row = QHBoxLayout(buttons)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        for text, name, call in (
                (tr("Всё"), "qa_kin_select_all", actions.select_all),
                (tr("Снять"), "qa_kin_select_none", actions.select_none),
                (tr("Обратить"), "qa_kin_select_invert", actions.select_invert)):
            button = QPushButton(text)
            button.setObjectName(name)
            button.clicked.connect(call)
            row.addWidget(button)
        self.column.addWidget(buttons)
        self.count = note()
        self.column.addWidget(self.count)

        self.column.addWidget(heading(tr("Выбранному")))
        self.lift = segments([f"{mm}" for mm in LIFT_MM], "qa_kin_set_lift",
                             lambda i: actions.set_selected("lift", float(i)), 1)
        self.column.addWidget(labelled(tr("Подъём колец, мм"), self.lift))
        self.push = Slider(0, 1000, 0, tr("мм"), "qa_kin_set_push", 10)
        self.push.pressed.connect(actions.begin_edit)
        self.push.moved.connect(lambda v: actions.set_selected("push", v / 1000.0,
                                                               live=True))
        self.push.released.connect(actions.end_edit)
        self.column.addWidget(labelled(tr("Вынос групп, мм"), self.push))
        self.tilt = Slider(-30, 30, 0, "°", "qa_kin_set_tilt", 0.5, 1)
        self.tilt.pressed.connect(actions.begin_edit)
        self.tilt.moved.connect(lambda v: actions.set_selected("tilt", v / 90.0,
                                                               live=True))
        self.tilt.released.connect(actions.end_edit)
        self.column.addWidget(labelled(tr("Наклон сот, градусы"), self.tilt))

        self.column.addWidget(heading(tr("Авторотейт")))
        gain = QWidget()
        line = QHBoxLayout(gain)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)
        self.gain = QSpinBox()
        self.gain.setObjectName("qa_kin_auto_gain")
        self.gain.setRange(10, 300)
        self.gain.setValue(100)
        self.gain.setSuffix(" %")
        self.gain.setFixedWidth(84)
        run = QPushButton(tr("Наклонить по форме"))
        run.setObjectName("qa_kin_auto_rotate")
        run.clicked.connect(lambda: actions.auto_rotate(self.gain.value() / 100.0))
        line.addWidget(self.gain)
        line.addWidget(run, 1)
        self.column.addWidget(gain)
        self.column.addWidget(note(tr("Как rotate_auto в Houdini: каждая сота ложится вдоль поверхности, "
            "которую сейчас составляют подъём и вынос, в пределах своих зазоров. "
            "Без выбора — все соты. 100 % — ровно по поверхности.")))
        self.finish()

    def refresh(self) -> None:
        cells = self.actions.selection
        rings = int(cells.any(axis=1).sum())
        groups = int(km.cell_mask_for("push", cells).sum())
        self.count.setText(tr("Выбрано сот {0}, групп {1}, колец {2}",
                              int(cells.sum()), groups, rings))
        pose = self.actions.pose_now()
        if pose is None or not cells.any():
            return
        rows = cells.any(axis=1)
        lift = pose["lift"][rows]
        if len(set(np.round(lift).astype(int).tolist())) == 1:
            self.lift.buttons[int(round(lift[0]))].setChecked(True)
        push = pose["push"].reshape(-1)[km.cell_mask_for("push", cells)]
        self.push.set(float(np.mean(push)) * 1000.0)
        tilt = pose["tilt"].reshape(-1)[cells.reshape(-1)]
        self.tilt.set(float(np.mean(tilt)) * 90.0)


# -- the vase ------------------------------------------------------------------------

class ProfileCurve(QWidget):
    """The vase's side: ring height up, push across, points to drag.

    Double-click adds a point, right click takes one away; there are always
    at least two. What the rings are pushed to now is drawn faintly behind,
    so a profile can be drawn over the shape that is already there.
    """

    changed = Signal(object, bool)       # points, and whether the drag is over

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("qa_kin_profile_curve")
        self.setMinimumHeight(300)
        self.setMouseTracking(True)
        self.points = [(0.0, 0.0), (0.5, 0.3), (1.0, 0.0)]
        self.now = np.zeros(ROWS, np.float32)     # each ring's push, now
        self._held = None

    def _box(self) -> QRectF:
        return QRectF(28, 10, max(10, self.width() - 40), max(10, self.height() - 34))

    def _to_screen(self, height: float, reach: float) -> QPointF:
        box = self._box()
        return QPointF(box.left() + reach * box.width(),
                       box.bottom() - height * box.height())

    def _from_screen(self, point: QPointF):
        box = self._box()
        reach = (point.x() - box.left()) / box.width()
        height = (box.bottom() - point.y()) / box.height()
        return (min(1.0, max(0.0, height)), min(1.0, max(0.0, reach)))

    def paintEvent(self, event) -> None:          # noqa: N802
        brush = QPainter(self)
        brush.setRenderHint(QPainter.RenderHint.Antialiasing)
        brush.fillRect(self.rect(), QColor(theme.SUNKEN))
        box = self._box()
        brush.setPen(QPen(QColor(theme.SEAM)))
        for step in range(0, 11, 2):
            x = box.left() + box.width() * step / 10
            brush.drawLine(QPointF(x, box.top()), QPointF(x, box.bottom()))
        brush.setFont(theme.mono(7.5))
        brush.setPen(QPen(QColor(theme.QUIET)))
        for step in (0, 500, 1000):
            x = box.left() + box.width() * step / 1000
            brush.drawText(QRectF(x - 30, box.bottom() + 4, 60, 14),
                           Qt.AlignmentFlag.AlignCenter, f"{step}")
        for ring in (1, 10, 20, 30):
            y = box.bottom() - box.height() * (ring - 1) / (ROWS - 1)
            brush.drawText(QRectF(0, y - 7, 24, 14),
                           Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                           str(ring))
        # What the rings are at now.
        brush.setPen(Qt.PenStyle.NoPen)
        brush.setBrush(QColor(95, 194, 122, 60))
        for ring in range(ROWS):
            y = box.bottom() - box.height() * ring / (ROWS - 1)
            brush.drawRect(QRectF(box.left(), y - 2, box.width() * float(self.now[ring]), 4))
        # The curve, sampled at the rings.
        curve = km.profile_curve(self.points)
        brush.setPen(QPen(QColor(FAMILY_COLOUR["push"]), 2))
        line = QPolygonF([self._to_screen(ring / (ROWS - 1), float(curve[ring]))
                          for ring in range(ROWS)])
        brush.drawPolyline(line)
        brush.setBrush(QColor(FAMILY_COLOUR["push"]))
        for ring in range(ROWS):
            brush.drawEllipse(self._to_screen(ring / (ROWS - 1), float(curve[ring])), 2, 2)
        brush.setBrush(QColor("#ffffff"))
        brush.setPen(QPen(QColor(theme.DEEP), 1.5))
        for height, reach in self.points:
            brush.drawEllipse(self._to_screen(height, reach), 5, 5)
        brush.end()

    def _near(self, point: QPointF):
        for index, (height, reach) in enumerate(self.points):
            if (self._to_screen(height, reach) - point).manhattanLength() < 10:
                return index
        return None

    def mousePressEvent(self, event) -> None:     # noqa: N802
        point = event.position()
        hit = self._near(point)
        if event.button() == Qt.MouseButton.RightButton:
            if hit is not None and len(self.points) > 2:
                del self.points[hit]
                self.update()
                self.changed.emit(list(self.points), True)
            return
        if event.button() == Qt.MouseButton.LeftButton and hit is not None:
            self._held = hit

    def mouseDoubleClickEvent(self, event) -> None:   # noqa: N802
        self.points.append(self._from_screen(event.position()))
        self.points.sort()
        self.update()
        self.changed.emit(list(self.points), True)

    def mouseMoveEvent(self, event) -> None:      # noqa: N802
        if self._held is None:
            return
        height, reach = self._from_screen(event.position())
        self.points[self._held] = (height, reach)
        self.update()
        self.changed.emit(list(self.points), False)

    def mouseReleaseEvent(self, event) -> None:   # noqa: N802
        if self._held is not None:
            self._held = None
            order = sorted(range(len(self.points)), key=lambda i: self.points[i])
            self.points = [self.points[i] for i in order]
            self.changed.emit(list(self.points), True)


class ProfilePanel(Panel):
    def __init__(self, actions) -> None:
        super().__init__(actions, "qa_kin_profile_panel")
        self.column.addWidget(heading(tr("Профиль вазы")))
        self.curve = ProfileCurve()
        self.curve.changed.connect(self._changed)
        self.column.addWidget(self.curve, 1)
        self.tangent = QCheckBox(tr("Наклон по касательной"))
        self.tangent.setObjectName("qa_kin_profile_tangent")
        self.tangent.setChecked(True)
        self.column.addWidget(self.tangent)
        self.column.addWidget(note(tr("Кривая от нижнего кольца до верхнего: насколько вынесено каждое "
            "кольцо, все десять его пушеров разом. С выбором — только выбранные "
            "группы. Наклон по касательной кладёт соты вдоль получившейся "
            "поверхности, в пределах их зазоров. Двойной щелчок — точка, правый — "
            "убрать.")))
        self._editing = False
        self.finish()

    def _changed(self, points, done: bool) -> None:
        if not self._editing:
            self.actions.begin_edit()
            self._editing = True
        self.actions.apply_profile(points, self.tangent.isChecked())
        if done:
            self.actions.end_edit()
            self._editing = False

    def refresh(self) -> None:
        pose = self.actions.pose_now()
        if pose is not None:
            self.curve.now = pose["push"].mean(axis=1)
            self.curve.update()
        points = self.actions.profile_here()
        if points and self.curve._held is None:
            self.curve.points = [tuple(p) for p in points]
            self.curve.update()


# -- the rings -----------------------------------------------------------------------

class RingsPanel(Panel):
    """Every ring at one of its jack's four places, top ring first."""

    def __init__(self, actions) -> None:
        super().__init__(actions, "qa_kin_rings_panel")
        self.column.addWidget(heading(tr("Кольца")))
        self.column.addWidget(note(tr(
            "Зазор под кольцом, мм. Домкрат стоит только в четырёх положениях; "
            "между ключами он переходит плавно. Нижнее кольцо стоит на "
            "основании — домкрата под ним нет.")))
        everything = segments([f"{mm}" for mm in LIFT_MM], "qa_kin_rings_all",
                              lambda i: actions.set_rings(np.ones(ROWS, bool), i), 1)
        self.column.addWidget(labelled(tr("Все кольца"), everything))
        grid_holder = QWidget()
        grid = QGridLayout(grid_holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(2)
        grid.setVerticalSpacing(1)
        self.rows = []
        for place, ring in enumerate(reversed(range(ROWS))):
            label = QLabel(str(ring + 1))
            label.setFont(theme.mono(8))
            label.setStyleSheet(f"color:{theme.QUIET};")
            grid.addWidget(label, place, 0)
            # Not exclusive: a jack between two keys is in none of its places,
            # and an exclusive group cannot show that.
            group = QButtonGroup(grid_holder)
            group.setExclusive(False)
            buttons = []
            for state in range(4):
                button = QPushButton(str(LIFT_MM[state]))
                button.setObjectName(f"qa_kin_ring_{ring + 1}_{state}")
                button.setCheckable(True)
                button.setProperty("segment", True)
                button.setFixedHeight(20)
                button.setStyleSheet("padding:0px 4px; font-size:11px;")
                # The lowest ring stands on the base, with no jack under it.
                button.setEnabled(ring != km.NO_JACK)
                group.addButton(button, state)
                grid.addWidget(button, place, state + 1)
                buttons.append(button)
            group.idClicked.connect(
                lambda state, ring=ring: actions.set_rings(
                    np.arange(ROWS) == ring, state))
            self.rows.append((ring, buttons))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(grid_holder)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.column.addWidget(scroll, 1)

    def refresh(self) -> None:
        pose = self.actions.pose_now()
        if pose is None:
            return
        lift = pose["lift"]
        for ring, buttons in self.rows:
            value = float(lift[ring])
            state = int(round(value))
            between = abs(value - state) > 1e-3
            for index, button in enumerate(buttons):
                button.blockSignals(True)
                button.setChecked(index == state and not between)
                button.blockSignals(False)
