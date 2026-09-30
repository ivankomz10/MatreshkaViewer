"""The kinetic editor's panel: what is chosen, and the tool's own settings.

Down the right of the window, in three parts:

  Выбрано      always there: what is chosen -- rings, groups, cells -- and
               where its motors stand at the playhead, a row a family: the
               jack's four places, the pusher's millimetres, the tilt's
               degrees with the stretch its gaps allow painted on the
               slider. Changing a row keys the chosen motors of that family
               there; ◆ keys them where they stand
  Позы         the pose library: the piece as it stands, saved under a name
               and put back as a key -- on the chosen cells, or all of them
  Маска        the masks of the piece, and the one edits are kept to
  the tool     the brush's paint, the selection's size, the vase's options,
               the motors' pace and what went wrong, the primitives

Numbers are dragged as well as typed: press on one and pull left or right,
Shift for fine steps, as in Blender. A panel does nothing itself; it calls
the window (`actions`), which knows the frame, writes the keys and keeps the
undo -- so a change from here is a change like any other.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox,
                               QDoubleSpinBox, QGridLayout, QHBoxLayout,
                               QLabel, QListWidget, QListWidgetItem,
                               QPushButton, QSlider, QVBoxLayout, QWidget)

import kin_model as km
import kinetic
import theme
from kin_timeline import FAMILY_COLOUR, FAMILY_NAME
from kinetic import PER_PUSHER, PER_ROW, ROWS
from lang import tr

LIFT_MM = tuple(int(kinetic.JACK_STATE_MM[state]) for state in range(4))


def heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setFont(theme.heading())
    label.setStyleSheet(f"color:{theme.TEXT}; padding-top:4px;")
    return label


def note(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(f"color:{theme.QUIET}; font-size:11px;")
    return label


def segments(names, name: str, on_pick, checked: int = 0, exclusive: bool = True):
    """A row of buttons of which one is on, as the viewer's level switch."""
    holder = QWidget()
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(2)
    group = QButtonGroup(holder)
    group.setExclusive(exclusive)
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


# -- numbers pulled by the mouse --------------------------------------------------

class Scrub(QDoubleSpinBox):
    """A number that is dragged as well as typed.

    Press on it and pull sideways: a step a few pixels, a tenth of one with
    Shift. A press that does not move is a click, and the number is there
    to type into. `pressed` and `released` bracket a drag -- and a typed
    number, which is a change of one step -- so it makes one undo step.
    """

    pressed = Signal()
    released = Signal()
    moved = Signal(float)

    PIXELS_A_STEP = 3.0

    def __init__(self, low: float, high: float, value: float, unit: str,
                 name: str, step: float = 1.0, decimals: int = 0) -> None:
        super().__init__()
        self.setObjectName(name)
        self.setRange(low, high)
        self.setDecimals(decimals)
        self.setSingleStep(step)
        self.setSuffix(f" {unit}" if unit else "")
        self.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self.setValue(value)
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self.lineEdit().setCursor(Qt.CursorShape.SizeHorCursor)
        self.lineEdit().installEventFilter(self)
        self._from = None
        self._scrubbing = False
        self.editingFinished.connect(self._typed)

    def eventFilter(self, watched, event):          # noqa: N802
        kind = event.type()
        if kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self._from = (event.globalPosition().x(), self.value())
            self._scrubbing = False
            return False
        if kind == QEvent.Type.MouseMove and self._from is not None:
            moved = event.globalPosition().x() - self._from[0]
            if not self._scrubbing and abs(moved) > 3:
                self._scrubbing = True
                self.pressed.emit()
                self.lineEdit().deselect()
            if self._scrubbing:
                fine = event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                steps = moved / self.PIXELS_A_STEP * (0.1 if fine else 1.0)
                value = self._from[1] + steps * self.singleStep()
                self.blockSignals(True)
                self.setValue(value)
                self.blockSignals(False)
                self.moved.emit(self.value())
                return True
        if kind == QEvent.Type.MouseButtonRelease and self._from is not None:
            self._from = None
            if self._scrubbing:
                self._scrubbing = False
                self.clearFocus()
                self.released.emit()
                return True
        return super().eventFilter(watched, event)

    def _typed(self) -> None:
        if self._scrubbing:
            return
        self.pressed.emit()
        self.moved.emit(self.value())
        self.released.emit()

    def set(self, value: float) -> None:
        self.blockSignals(True)
        self.setValue(value)
        self.blockSignals(False)


class RangeSlider(QSlider):
    """A slider that paints the stretch a value may take: outside it,
    darkened -- a tilt's slider shows how far the gaps let the chosen cells
    go, down and up."""

    def __init__(self) -> None:
        super().__init__(Qt.Orientation.Horizontal)
        self.allowed = None              # (low, high) in the slider's units

    def paintEvent(self, event) -> None:          # noqa: N802
        super().paintEvent(event)
        if self.allowed is None or self.maximum() == self.minimum():
            return
        brush = QPainter(self)
        span = self.maximum() - self.minimum()
        inset = 7.0
        wide = self.width() - 2 * inset
        low, high = self.allowed

        def x_of(value):
            return inset + (value - self.minimum()) / span * wide

        shade = QColor(theme.ERROR)
        shade.setAlpha(70)
        middle = self.height() / 2
        left, right = x_of(low), x_of(high)
        if left > inset:
            brush.fillRect(QRectF(inset, middle - 3, left - inset, 6), shade)
        if right < inset + wide:
            brush.fillRect(QRectF(right, middle - 3, inset + wide - right, 6), shade)
        brush.end()


class Slider(QWidget):
    """A slider with its number beside it, in the value's own units; the
    number is dragged too. `pressed` and `released` bracket a drag, so the
    window makes one undo step of it rather than one a pixel."""

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
        self.slider = RangeSlider()
        self.slider.setObjectName(name)
        self.slider.setRange(0, int(round((high - low) / step)))
        self.number = Scrub(low, high, value, unit, name + "_number", step, decimals)
        self.number.setFixedWidth(88)
        row.addWidget(self.slider, 1)
        row.addWidget(self.number)
        self.set(value)
        self.slider.valueChanged.connect(self._slid)
        self.slider.sliderPressed.connect(self.pressed)
        self.slider.sliderReleased.connect(self.released)
        self.number.pressed.connect(self.pressed)
        self.number.released.connect(self.released)
        self.number.moved.connect(self._scrubbed)

    def value(self) -> float:
        return float(self.number.value())

    def set(self, value: float) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(int(round((value - self.low) / self.step)))
        self.slider.blockSignals(False)
        self.number.set(value)

    def set_allowed(self, low, high) -> None:
        """The stretch the value may take, or None for all of it."""
        self.slider.allowed = (None if low is None else
                               ((low - self.low) / self.step, (high - self.low) / self.step))
        self.slider.update()

    def _slid(self, position: int) -> None:
        value = self.low + position * self.step
        self.number.set(value)
        self.moved.emit(value)

    def _scrubbed(self, value: float) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(int(round((value - self.low) / self.step)))
        self.slider.blockSignals(False)
        self.moved.emit(value)


class Panel(QWidget):
    """A column of controls, room to spare at the foot."""

    def __init__(self, actions, name: str) -> None:
        super().__init__()
        self.setObjectName(name)
        self.actions = actions
        self.column = QVBoxLayout(self)
        self.column.setContentsMargins(14, 8, 14, 10)
        self.column.setSpacing(8)

    def finish(self) -> None:
        self.column.addStretch(1)

    def refresh(self) -> None:
        """Say again what the piece is at the playhead. Nothing by default."""


def _key_button(name: str, call) -> QPushButton:
    button = QPushButton("◆")
    button.setObjectName(name)
    button.setFixedSize(28, 26)
    button.setStyleSheet("padding:0px;")
    button.setProperty("fixed_words", True)
    button.setToolTip(tr("Ключ выбранным моторам слоя там, где они стоят"))
    button.clicked.connect(call)
    return button


# -- what is chosen -------------------------------------------------------------------

class Inspector(Panel):
    """What is chosen, and where its motors stand at the playhead."""

    def __init__(self, actions) -> None:
        super().__init__(actions, "qa_kin_inspector")
        self.column.setContentsMargins(14, 10, 14, 8)
        self.title = QLabel()
        self.title.setObjectName("qa_kin_chosen")
        self.title.setFont(theme.heading())
        self.title.setWordWrap(True)
        self.column.addWidget(self.title)

        grid_holder = QWidget()
        grid = QGridLayout(grid_holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        self.names = {}
        for row, family in enumerate(km.FAMILIES):
            name = QLabel(tr(FAMILY_NAME[family]))
            name.setStyleSheet(f"color:{FAMILY_COLOUR[family]};")
            grid.addWidget(name, row * 2, 0)
            self.names[family] = name
        self.lift = segments([str(mm) for mm in LIFT_MM], "qa_kin_set_lift",
                             lambda i: actions.set_selected("lift", float(i)),
                             checked=-1, exclusive=False)
        grid.addWidget(self.lift, 0, 1)
        grid.addWidget(_key_button("qa_kin_key_lift",
                                   lambda: actions.key_selected("lift")), 0, 2)
        self.push = Slider(0, 1000, 0, tr("мм"), "qa_kin_set_push", 10)
        self.push.pressed.connect(actions.begin_edit)
        self.push.moved.connect(
            lambda v: actions.set_selected("push", v / 1000.0, live=True))
        self.push.released.connect(actions.end_edit)
        grid.addWidget(self.push, 2, 1)
        grid.addWidget(_key_button("qa_kin_key_push",
                                   lambda: actions.key_selected("push")), 2, 2)
        self.push_note = note()
        grid.addWidget(self.push_note, 3, 1)
        self.tilt = Slider(-45, 45, 0, "°", "qa_kin_set_tilt", 0.5, 1)
        self.tilt.pressed.connect(actions.begin_edit)
        self.tilt.moved.connect(
            lambda v: actions.set_selected("tilt", v / 90.0, live=True))
        self.tilt.released.connect(actions.end_edit)
        grid.addWidget(self.tilt, 4, 1)
        grid.addWidget(_key_button("qa_kin_key_tilt",
                                   lambda: actions.key_selected("tilt")), 4, 2)
        self.tilt_note = note()
        grid.addWidget(self.tilt_note, 5, 1)
        grid.setColumnStretch(1, 1)
        self.column.addWidget(grid_holder)

        auto = QWidget()
        line = QHBoxLayout(auto)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)
        run = QPushButton(tr("Авторотейт"))
        run.setObjectName("qa_kin_auto_rotate")
        run.setToolTip(tr(
            "Как rotate_auto в Houdini: каждая сота ложится вдоль поверхности, "
            "которую сейчас составляют подъём и вынос, в пределах своих зазоров. "
            "Без выбора — все соты. 100 % — ровно по поверхности."))
        self.gain = Scrub(10, 300, 100, "%", "qa_kin_auto_gain", 5)
        self.gain.setFixedWidth(76)
        run.clicked.connect(lambda: actions.auto_rotate(self.gain.value() / 100.0))
        line.addWidget(run, 1)
        line.addWidget(self.gain)
        self.column.addWidget(auto)
        self.rows = [self.lift, self.push, self.tilt]

    def refresh(self) -> None:
        cells = self.actions.selection
        rings = int(cells.any(axis=1).sum())
        groups = int(km.cell_mask_for("push", cells).sum())
        count = int(cells.sum())
        if not count:
            self.title.setText(tr("Ничего не выбрано — 1 кольца, 2 группы, 3 соты"))
        else:
            self.title.setText(tr("Выбрано: колец {0} · групп {1} · сот {2}",
                                  rings, groups, count))
        for family, name in self.names.items():
            active = family == self.actions.family
            name.setStyleSheet(f"color:{FAMILY_COLOUR[family]};"
                               + (" font-weight:600;" if active else ""))
        pose = self.actions.pose_now()
        for widget in self.rows:
            widget.setEnabled(bool(count))
        if pose is None or not count:
            for button in self.lift.buttons:
                button.setChecked(False)
            self.push_note.setText("")
            self.tilt_note.setText("")
            self.tilt.set_allowed(None, None)
            return
        # The jacks of the chosen rings: one of the four lit when they agree.
        rows = cells.any(axis=1)
        lift = np.round(pose["lift"][rows]).astype(int)
        agreed = int(lift[0]) if len(set(lift.tolist())) == 1 else None
        for index, button in enumerate(self.lift.buttons):
            button.blockSignals(True)
            button.setChecked(bool(agreed == index))
            button.blockSignals(False)
        push = pose["push"].reshape(-1)[km.cell_mask_for("push", cells)] * 1000.0
        self.push.set(float(np.mean(push)))
        self.push_note.setText("" if np.ptp(push) < 1 else
                               tr("разные: {0:.0f}–{1:.0f} мм", push.min(), push.max()))
        tilt = pose["tilt"][cells] * 90.0
        self.tilt.set(float(np.mean(tilt)))
        low, high = km.tilt_bounds(pose["lift"], pose["push"])
        down = float(high[cells].min()) * 90.0
        up = float(-low[cells].max()) * 90.0
        self.tilt.set_allowed(-up, down)
        spread = "" if np.ptp(tilt) < 0.1 else tr(
            "разные: {0:+.1f}…{1:+.1f}° · ", tilt.min(), tilt.max())
        self.tilt_note.setText(spread + tr("можно: вниз до {0:.0f}°, вверх до {1:.0f}°",
                                           down, up))


# -- the pose library -----------------------------------------------------------------

class Poses(Panel):
    """Poses saved under a name and put back as keys."""

    def __init__(self, actions) -> None:
        super().__init__(actions, "qa_kin_poses")
        self.column.setContentsMargins(14, 2, 14, 8)
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(6)
        label = QLabel(tr("Позы"))
        label.setStyleSheet(f"color:{theme.DIM}; font-size:11.5px;")
        line.addWidget(label)
        self.choice = QComboBox()
        self.choice.setObjectName("qa_kin_pose_choice")
        line.addWidget(self.choice, 1)
        for text, name, call, hint in (
                (tr("Поставить"), "qa_kin_pose_put", actions.put_pose,
                 tr("Ключ позой на плейхеде: выбранным сотам или всем")),
                ("+", "qa_kin_pose_save", actions.save_pose,
                 tr("Сохранить, как стоит сейчас")),
                ("−", "qa_kin_pose_drop", actions.drop_pose,
                 tr("Убрать позу из библиотеки"))):
            button = QPushButton(text)
            button.setObjectName(name)
            button.setToolTip(hint)
            if text in "+−":
                button.setFixedWidth(30)
                button.setStyleSheet("padding:4px 0px;")
                button.setProperty("fixed_words", True)
            button.clicked.connect(call)
            line.addWidget(button)
        self.column.addWidget(row)

    def refresh(self) -> None:
        names = self.actions.pose_names()
        current = self.choice.currentText()
        self.choice.blockSignals(True)
        self.choice.clear()
        self.choice.addItems(names)
        if current in names:
            self.choice.setCurrentText(current)
        self.choice.blockSignals(False)


# -- the tools ------------------------------------------------------------------------

class BrushPanel(Panel):
    MODES = ("Красить", "Сгладить", "Стереть")
    MODE_KEYS = ("paint", "smooth", "erase")
    # What the brush paints: the keys of the layer, or the mask being edited.
    TARGETS = ("Ключи", "Маску")
    TARGET_KEYS = ("keys", "mask")

    def __init__(self, actions) -> None:
        super().__init__(actions, "qa_kin_brush_panel")
        self.title = heading("")
        self.column.addWidget(self.title)
        self.target = segments([tr(x) for x in self.TARGETS], "qa_kin_brush_target",
                               lambda i: actions.set_brush_target(self.TARGET_KEYS[i]))
        self.target.setToolTip(tr(
            "Маску — кисть рисует маску правки: красить добавляет, стереть "
            "убирает; без маски сначала заводится новая"))
        self.column.addWidget(labelled(tr("Кисть красит"), self.target))
        # What is painted towards, in the active layer's own units: one of
        # four places for a jack, millimetres for a pusher, degrees for a tilt.
        self.lift = segments([str(mm) for mm in LIFT_MM], "qa_kin_brush_lift",
                             lambda i: setattr(actions, "brush_lift", i), 1)
        self.push = Slider(0, 1000, 500, tr("мм"), "qa_kin_brush_push", 10)
        self.push.moved.connect(lambda v: setattr(actions, "brush_push", v / 1000.0))
        self.tilt = Slider(-45, 45, 10, "°", "qa_kin_brush_tilt", 0.5, 1)
        self.tilt.moved.connect(lambda v: setattr(actions, "brush_tilt", v / 90.0))
        self.weights = {"lift": labelled(tr("Вес: положение домкрата, мм"), self.lift),
                        "push": labelled(tr("Вес: вынос, мм"), self.push),
                        "tilt": labelled(tr("Вес: наклон, градусы"), self.tilt)}
        for box in self.weights.values():
            self.column.addWidget(box)
        self.mode = segments([tr(x) for x in self.MODES], "qa_kin_brush_mode",
                             lambda i: setattr(actions, "brush_mode",
                                               self.MODE_KEYS[i]))
        self.column.addWidget(self.mode)
        grid_holder = QWidget()
        grid = QGridLayout(grid_holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        self.radius = Scrub(0.5, 15, 2.5, tr("сот"), "qa_kin_brush_radius", 0.5, 1)
        self.radius.moved.connect(actions.set_brush_radius)
        self.hardness = Scrub(0, 100, 50, "%", "qa_kin_brush_hardness", 5)
        self.hardness.moved.connect(actions.set_brush_hardness)
        self.strength = Scrub(5, 100, 60, "%", "qa_kin_brush_strength", 5)
        self.strength.moved.connect(
            lambda v: setattr(actions, "brush_strength", v / 100.0))
        for column, (text, box) in enumerate(((tr("Размер"), self.radius),
                                              (tr("Жёсткость"), self.hardness),
                                              (tr("Сила"), self.strength))):
            label = QLabel(text)
            label.setStyleSheet(f"color:{theme.DIM}; font-size:11.5px;")
            grid.addWidget(label, 0, column)
            grid.addWidget(box, 1, column)
        self.column.addWidget(grid_holder)
        self.inside = QCheckBox(tr("Только выбранное"))
        self.inside.setObjectName("qa_kin_brush_inside")
        self.inside.setToolTip(tr(
            "Кисть красит лишь выбранные соты, как paint по группе в Houdini"))
        self.inside.toggled.connect(lambda on: setattr(actions, "brush_inside", on))
        self.column.addWidget(self.inside)
        self.column.addWidget(note(tr(
            "Ключ ставится только тем моторам, которых коснулась кисть. Пушер "
            "слушается самой закрашенной из своих пяти сот, домкрат — кольца, "
            "закрашенного больше чем наполовину. Ctrl+колесо — размер.")))
        self.finish()
        self.show_family("tilt")

    def show_family(self, family: str) -> None:
        masking = getattr(self.actions, "brush_target", "keys") == "mask"
        if masking:
            self.title.setText(tr("Кисть · маска «{0}»",
                                  self.actions.edit_mask or tr("новая")))
        else:
            self.title.setText(tr("Кисть · {0}", tr(FAMILY_NAME[family])))
        self.target.buttons[1 if masking else 0].setChecked(True)
        for one, box in self.weights.items():
            box.setVisible(one == family and not masking)

    def show_radius(self, radius: float) -> None:
        self.radius.set(radius)


class SelectPanel(Panel):
    GRAINS = ("Сота", "Группа", "Кольцо")
    GRAIN_KEYS = ("cell", "group", "ring")

    def __init__(self, actions) -> None:
        super().__init__(actions, "qa_kin_select_panel")
        self.column.addWidget(heading(tr("Выбор")))
        self.grain = segments([tr(x) for x in self.GRAINS], "qa_kin_grain",
                              lambda i: actions.set_grain(self.GRAIN_KEYS[i]))
        self.grain.setToolTip(tr("3 — соты, 2 — группы, 1 — кольца"))
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
        masking = QWidget()
        row = QHBoxLayout(masking)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        for text, name, call, hint in (
                (tr("В маску"), "qa_kin_mask_add", lambda: actions.selection_to_mask(True),
                 tr("Добавить выбранное в маску правки; без неё — новая маска")),
                (tr("Из маски"), "qa_kin_mask_take", lambda: actions.selection_to_mask(False),
                 tr("Убрать выбранное из маски правки"))):
            button = QPushButton(text)
            button.setObjectName(name)
            button.setToolTip(hint)
            button.clicked.connect(call)
            row.addWidget(button)
        self.column.addWidget(masking)
        self.column.addWidget(note(tr(
            "Щелчок — выбрать, рамка — несколько, Shift — добавить, Ctrl — убрать. "
            "Значения выбранного — в блоке «Выбрано» наверху.")))
        self.finish()


class ProfilePanel(Panel):
    def __init__(self, actions) -> None:
        super().__init__(actions, "qa_kin_profile_panel")
        self.column.addWidget(heading(tr("Профиль вазы")))
        self.tangent = QCheckBox(tr("Наклон по касательной"))
        self.tangent.setObjectName("qa_kin_profile_tangent")
        self.tangent.setChecked(True)
        self.column.addWidget(self.tangent)
        self.column.addWidget(note(tr(
            "Кривая — рядом с картой, кольцо к кольцу: насколько вынесено каждое "
            "кольцо, все десять его пушеров разом; с выбором — только выбранные "
            "группы. Двойной щелчок — точка, правый — убрать.")))
        self.finish()


class MotorsPanel(Panel):
    """The simulation: how fast each family goes and rests, which of the two
    is the ghost, what went wrong -- a list to click through -- and putting
    the motion onto the keys."""

    GHOSTS = ("Ключи", "Симуляция")
    GHOST_KEYS = ("keys", "sim")
    LISTED = 400

    def __init__(self, actions) -> None:
        super().__init__(actions, "qa_kin_motors_panel")
        import kin_sim
        self.column.addWidget(heading(tr("Моторы")))
        grid_holder = QWidget()
        grid = QGridLayout(grid_holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        for column, text in ((1, tr("ход, с")), (2, tr("отдых, с"))):
            label = QLabel(text)
            label.setStyleSheet(f"color:{theme.DIM}; font-size:11.5px;")
            grid.addWidget(label, 0, column)
        self.boxes = {}
        for row, family in enumerate(km.FAMILIES, start=1):
            name = QLabel(tr(FAMILY_NAME[family]))
            name.setStyleSheet(f"color:{FAMILY_COLOUR[family]};")
            grid.addWidget(name, row, 0)
            travel, rest = kin_sim.PACE[family]
            pair = []
            for column, value in ((1, travel), (2, rest)):
                box = Scrub(0.0 if column == 2 else 0.05, 120.0, value, "",
                            f"qa_kin_pace_{family}_{column}", 0.05, 2)
                box.setFixedWidth(76)
                box.released.connect(self._paced)
                grid.addWidget(box, row, column)
                pair.append(box)
            self.boxes[family] = pair
        grid_holder.setToolTip(tr(
            "Как их считает Cinema 4D: ход не быстрее мотора — полный ход за "
            "столько секунд, половина за половину; после каждого хода отдых; "
            "команда, пришедшая во время хода или отдыха, пропускается."))
        self.column.addWidget(grid_holder)
        self.ghost = segments([tr(x) for x in self.GHOSTS], "qa_kin_ghost",
                              lambda i: actions.set_ghost(self.GHOST_KEYS[i]), 0)
        self.column.addWidget(labelled(tr("Призраком в «Оба»"), self.ghost))
        self.summary = note()
        self.summary.setObjectName("qa_kin_sim_summary")
        self.summary.setStyleSheet(f"color:{theme.SECOND}; font-size:11.5px;")
        self.column.addWidget(self.summary)
        self.problems = QListWidget()
        self.problems.setObjectName("qa_kin_problems")
        self.problems.setStyleSheet(
            f"QListWidget {{ background:{theme.SUNKEN}; border:1px solid {theme.EDGE};"
            f" font-size:11.5px; }} QListWidget::item {{ padding:2px 4px; }}"
            f" QListWidget::item:selected {{ background:{theme.ACCENT}; }}")
        self.problems.itemClicked.connect(self._picked)
        self.column.addWidget(self.problems, 1)
        self.bake = QPushButton(tr("Перенести симуляцию в ключи"))
        self.bake.setObjectName("qa_kin_bake")
        self.bake.setToolTip(tr(
            "Ключи встанут там, где моторы на самом деле начинают и заканчивают "
            "ход; пропущенные команды уйдут. Экспорт после этого — то, что "
            "сыграет площадка. Отменяется Ctrl+Z."))
        self.bake.clicked.connect(actions.bake_simulation)
        self.column.addWidget(self.bake)
        self._shown = None

    def pace(self) -> dict:
        return {family: (boxes[0].value(), boxes[1].value())
                for family, boxes in self.boxes.items()}

    def _paced(self) -> None:
        self.actions.set_pace(self.pace())

    def _picked(self, item) -> None:
        self.actions.show_problem(item.data(Qt.ItemDataRole.UserRole))

    def refresh(self) -> None:
        result = self.actions.simulation()
        if result is None:
            self.summary.setText(tr("Симуляция считается…"))
            return
        counts = result.by_family()
        dropped = sum(one["dropped"] for one in counts.values())
        late = sum(one["late"] for one in counts.values())
        self.summary.setText(tr(
            "Пропущено {0} · опоздали {1} · наклон сверх зазоров на {2} кадрах",
            dropped, late, len(result.clashes)))
        self.bake.setEnabled(bool(dropped or late))
        if self._shown is result:
            return
        self._shown = result
        self.problems.clear()
        found = []
        for one in result.dropped:
            found.append((one.frame, ("dropped", one.family, one.motor, one.frame)))
        for one in result.late:
            found.append((one.due, ("late", one.family, one.motor, one.due,
                                    one.arrives)))
        for frame, count in result.clashes:
            found.append((frame, ("clash", frame, count)))
        found.sort(key=lambda pair: pair[0])
        for _, problem in found[:self.LISTED]:
            item = QListWidgetItem(self._say(problem))
            item.setData(Qt.ItemDataRole.UserRole, problem)
            self.problems.addItem(item)
        if len(found) > self.LISTED:
            self.problems.addItem(tr("…и ещё {0}", len(found) - self.LISTED))

    @staticmethod
    def _say(problem) -> str:
        kind = problem[0]
        if kind == "clash":
            return tr("кадр {0} · наклон сверх зазоров · сот {1}", problem[1], problem[2])
        family, motor = problem[1], problem[2]
        row, which = km.motor_address(family, motor)
        where = (tr("кольцо {0}", row + 1) if family == "lift"
                 else tr("кольцо {0}, мотор {1}", row + 1, which + 1))
        if kind == "dropped":
            return tr("кадр {0} · {1} · {2} · команда пропущена", problem[3],
                      tr(FAMILY_NAME[family]), where)
        return tr("кадр {0} · {1} · {2} · опоздал на {3:.1f} с", problem[3],
                  tr(FAMILY_NAME[family]), where, (problem[4] - problem[3]) / km.FPS)


# -- the vase, beside the strip ---------------------------------------------------------

class ProfileStrip(QWidget):
    """The vase's side, standing beside the strip of cells ring for ring:
    push across, the rings up at the very heights the strip draws them.

    Double-click adds a point, right click takes one away; there are always
    at least two. What the rings are pushed to now is drawn faintly behind,
    so a profile can be drawn over the shape that is already there.
    """

    changed = Signal(object, bool)       # points, and whether the drag is over

    WIDTH = 170

    def __init__(self, strip) -> None:
        super().__init__()
        self.setObjectName("qa_kin_profile_curve")
        self.setFixedWidth(self.WIDTH)
        self.setMouseTracking(True)
        self.strip = strip
        self.points = [(0.0, 0.0), (0.5, 0.3), (1.0, 0.0)]
        self.now = np.zeros(ROWS, np.float32)     # each ring's push, now
        self._held = None

    def _ring_y(self, ring: float) -> float:
        """The height the strip draws a ring at, on this widget."""
        from kin_unwrap import RING_PITCH
        return self.strip.to_screen(0.0, ring * RING_PITCH).y()

    def _to_screen(self, height: float, reach: float) -> QPointF:
        left, wide = 10.0, self.width() - 20.0
        return QPointF(left + reach * wide, self._ring_y(height * (ROWS - 1)))

    def _from_screen(self, point: QPointF):
        left, wide = 10.0, self.width() - 20.0
        bottom, top = self._ring_y(0), self._ring_y(ROWS - 1)
        height = (point.y() - bottom) / (top - bottom) if top != bottom else 0.0
        reach = (point.x() - left) / wide
        return (min(1.0, max(0.0, height)), min(1.0, max(0.0, reach)))

    def paintEvent(self, event) -> None:          # noqa: N802
        brush = QPainter(self)
        brush.setRenderHint(QPainter.RenderHint.Antialiasing)
        brush.fillRect(self.rect(), QColor(theme.DEEP))
        brush.setPen(QPen(QColor(theme.SEAM)))
        brush.drawLine(0, 0, 0, self.height())
        left, wide = 10.0, self.width() - 20.0
        for step in range(0, 11, 5):
            x = left + wide * step / 10
            brush.drawLine(QPointF(x, 0), QPointF(x, self.height()))
        brush.setFont(theme.mono(7))
        brush.setPen(QPen(QColor(theme.QUIET)))
        for step in (0, 500, 1000):
            x = left + wide * step / 1000
            brush.drawText(QRectF(x - 30, self.height() - 16, 60, 14),
                           Qt.AlignmentFlag.AlignCenter, f"{step}")
        # What the rings are pushed to now.
        brush.setPen(Qt.PenStyle.NoPen)
        brush.setBrush(QColor(95, 194, 122, 60))
        for ring in range(ROWS):
            y = self._ring_y(ring)
            brush.drawRect(QRectF(left, y - 2, wide * float(self.now[ring]), 4))
        curve = km.profile_curve(self.points)
        brush.setPen(QPen(QColor(FAMILY_COLOUR["push"]), 2))
        brush.drawPolyline(QPolygonF([self._to_screen(ring / (ROWS - 1), float(curve[ring]))
                                      for ring in range(ROWS)]))
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
        self.points[self._held] = self._from_screen(event.position())
        self.update()
        self.changed.emit(list(self.points), False)

    def mouseReleaseEvent(self, event) -> None:   # noqa: N802
        if self._held is not None:
            self._held = None
            self.points.sort()
            self.changed.emit(list(self.points), True)


# -- masks ------------------------------------------------------------------------------

class Masks(Panel):
    """The masks of the piece, and the one every edit is kept to."""

    ALL_CELLS = "все соты"

    def __init__(self, actions) -> None:
        super().__init__(actions, "qa_kin_masks")
        self.column.setContentsMargins(14, 0, 14, 8)
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(6)
        label = QLabel(tr("Маска"))
        label.setStyleSheet(f"color:{theme.DIM}; font-size:11.5px;")
        line.addWidget(label)
        self.choice = QComboBox()
        self.choice.setObjectName("qa_kin_mask_choice")
        self.choice.setToolTip(tr(
            "Маска правки: всё, что делается на плейхеде — кисть, значения, "
            "ручки, G R H, позы, профиль, K, — касается только её сот"))
        self.choice.currentIndexChanged.connect(self._chosen)
        line.addWidget(self.choice, 1)
        for text, name, call, hint in (
                ("+", "qa_kin_mask_new", actions.new_mask,
                 tr("Новая маска из выбранного; без выбора — пустая, чтобы "
                    "нарисовать кистью")),
                ("◎", "qa_kin_mask_select", actions.select_mask,
                 tr("Выбрать соты маски")),
                ("−", "qa_kin_mask_drop", actions.drop_mask, tr("Удалить маску"))):
            button = QPushButton(text)
            button.setObjectName(name)
            button.setToolTip(hint)
            button.setFixedWidth(30)
            button.setStyleSheet("padding:4px 0px;")
            button.setProperty("fixed_words", True)
            button.clicked.connect(lambda _=False, call=call: call())
            line.addWidget(button)
        self.column.addWidget(row)

    def _chosen(self, index: int) -> None:
        self.actions.set_edit_mask("" if index <= 0 else self.choice.itemText(index))

    def refresh(self) -> None:
        names = self.actions.mask_names()
        self.choice.blockSignals(True)
        self.choice.clear()
        self.choice.addItem(tr(self.ALL_CELLS))
        self.choice.addItems(names)
        current = self.actions.edit_mask
        self.choice.setCurrentIndex(names.index(current) + 1 if current in names else 0)
        self.choice.blockSignals(False)


# -- primitives --------------------------------------------------------------------------

class PrimsPanel(Panel):
    """The solids the honeycomb wraps: which there are, and the chosen one's
    ways and keys. A change keys it at the playhead, as every edit does."""

    POLARITIES = ("Позитив", "Негатив")
    POLARITY_KEYS = ("positive", "negative")
    SAME_MASK = "как у действия"

    def __init__(self, actions) -> None:
        super().__init__(actions, "qa_kin_prims_panel")
        import kin_prims as kp
        self.kp = kp
        self._filling = False
        self.column.addWidget(heading(tr("Примитивы")))
        adding = QWidget()
        row = QHBoxLayout(adding)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        for text, name, kind in ((tr("+ Сфера"), "qa_kin_prim_sphere", "sphere"),
                                 (tr("+ Куб"), "qa_kin_prim_box", "box")):
            button = QPushButton(text)
            button.setObjectName(name)
            button.clicked.connect(lambda _=False, kind=kind: actions.add_primitive(kind))
            row.addWidget(button, 1)
        drop = QPushButton("−")
        drop.setObjectName("qa_kin_prim_drop")
        drop.setFixedWidth(30)
        drop.setStyleSheet("padding:4px 0px;")
        drop.setProperty("fixed_words", True)
        drop.setToolTip(tr("Удалить примитив"))
        drop.clicked.connect(lambda: actions.drop_primitive())
        row.addWidget(drop)
        self.column.addWidget(adding)
        self.list = QListWidget()
        self.list.setObjectName("qa_kin_prim_list")
        self.list.setFixedHeight(64)
        self.list.setStyleSheet(
            f"QListWidget {{ background:{theme.SUNKEN}; border:1px solid {theme.EDGE};"
            f" font-size:11.5px; }} QListWidget::item {{ padding:1px 4px; }}"
            f" QListWidget::item:selected {{ background:{theme.ACCENT}; }}")
        self.list.currentRowChanged.connect(
            lambda row_: None if self._filling else actions.choose_primitive(row_))
        self.column.addWidget(self.list)

        self.body = QWidget()
        form = QVBoxLayout(self.body)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(6)
        ways = QWidget()
        line = QHBoxLayout(ways)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)
        self.polarity = segments([tr(x) for x in self.POLARITIES], "qa_kin_prim_polarity",
                                 lambda i: actions.set_prim_property(
                                     "polarity", self.POLARITY_KEYS[i]))
        self.polarity.setToolTip(tr(
            "Позитив выталкивает соты на свою поверхность — выпуклость; негатив "
            "вдавливает их до своей поверхности — отпечаток"))
        line.addWidget(self.polarity)
        self.on = QCheckBox(tr("Вкл"))
        self.on.setObjectName("qa_kin_prim_on")
        self.on.toggled.connect(lambda on: actions.set_prim_property("on", bool(on)))
        line.addWidget(self.on)
        line.addStretch(1)
        form.addWidget(ways)
        self.tilt = QCheckBox(tr("Наклон по нормали"))
        self.tilt.setObjectName("qa_kin_prim_tilt")
        self.tilt.setToolTip(tr(
            "Задетые соты ложатся вдоль поверхности примитива, насколько "
            "позволяют зазоры"))
        self.tilt.toggled.connect(lambda on: actions.set_prim_property("tilt", bool(on)))
        form.addWidget(self.tilt)
        masks = QWidget()
        grid = QGridLayout(masks)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        self.mask = QComboBox()
        self.mask.setObjectName("qa_kin_prim_mask")
        self.mask.currentIndexChanged.connect(
            lambda i: self._masked("mask", self.mask, i))
        self.tilt_mask = QComboBox()
        self.tilt_mask.setObjectName("qa_kin_prim_tilt_mask")
        self.tilt_mask.currentIndexChanged.connect(
            lambda i: self._masked("tilt_mask", self.tilt_mask, i))
        for place, (text, box) in enumerate(((tr("Действует на"), self.mask),
                                             (tr("Наклон на"), self.tilt_mask))):
            label = QLabel(text)
            label.setStyleSheet(f"color:{theme.DIM}; font-size:11.5px;")
            grid.addWidget(label, place, 0)
            grid.addWidget(box, place, 1)
        grid.setColumnStretch(1, 1)
        form.addWidget(masks)

        numbers = QWidget()
        grid = QGridLayout(numbers)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)
        self.boxes = {}
        self.labels = {}
        # Two to a row, a name and its number: where it stands, then how big.
        spec = ((kp.AZIMUTH, tr("Азимут"), -360, 720, "°", 1.0, 1,
                 tr("Где вокруг здания, градусы")),
                (kp.HEIGHT, tr("Кольцо"), -5, ROWS + 5, "", 0.1, 1,
                 tr("На какой высоте, в кольцах от нижнего")),
                (kp.OFFSET, tr("Отступ"), -3, 3, tr("м"), 0.02, 2,
                 tr("Центр от поверхности сот, метры; минус — внутрь")),
                (kp.STRENGTH, tr("Сила"), 0, 100, "%", 5, 0,
                 tr("Насколько соты идут к его поверхности")),
                (kp.WIDTH, tr("Радиус"), 0.05, 6, tr("м"), 0.02, 2,
                 tr("Радиус сферы; у куба — половина ширины вокруг здания")),
                (kp.TALL, tr("Высота"), 0.05, 6, tr("м"), 0.02, 2,
                 tr("Половина высоты куба")),
                (kp.DEPTH, tr("Глубина"), 0.05, 6, tr("м"), 0.02, 2,
                 tr("Половина глубины куба, от здания наружу")))
        for place, (param, text, low, high, unit, step, decimals, hint) in enumerate(spec):
            label = QLabel(text)
            label.setStyleSheet(f"color:{theme.DIM}; font-size:11.5px;")
            label.setToolTip(hint)
            box = Scrub(low, high, low, unit, f"qa_kin_prim_{kp.PARAMS[param]}", step,
                        decimals)
            box.setToolTip(hint)
            box.setMinimumWidth(70)
            box.pressed.connect(actions.begin_edit)
            box.moved.connect(lambda v, param=param: actions.set_prim_value(
                param, v / 100.0 if param == kp.STRENGTH else v, live=True))
            box.released.connect(actions.end_edit)
            grid.addWidget(label, place // 2, (place % 2) * 2)
            grid.addWidget(box, place // 2, (place % 2) * 2 + 1)
            self.boxes[param] = box
            self.labels[param] = label
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        form.addWidget(numbers)
        keys = QWidget()
        line = QHBoxLayout(keys)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(6)
        key = QPushButton(tr("◆ Ключ"))
        key.setObjectName("qa_kin_prim_key")
        key.setToolTip(tr("Ключ примитиву на плейхеде, там, где он сейчас"))
        key.clicked.connect(lambda: actions.key_primitive())
        line.addWidget(key, 1)
        unkey = QPushButton(tr("Снять ключ"))
        unkey.setObjectName("qa_kin_prim_unkey")
        unkey.setToolTip(tr("Убрать ключ примитива на плейхеде"))
        unkey.clicked.connect(lambda: actions.unkey_primitive())
        line.addWidget(unkey, 1)
        form.addWidget(keys)
        self.column.addWidget(self.body)

        step = QWidget()
        line = QHBoxLayout(step)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)
        label = QLabel(tr("Шаг ключей"))
        label.setStyleSheet(f"color:{theme.DIM}; font-size:11.5px;")
        line.addWidget(label)
        self.step = Scrub(1, 600, km.PRIM_STEP, tr("кадров"), "qa_kin_prim_step", 1)
        self.step.setFixedWidth(96)
        self.step.setToolTip(tr(
            "Как часто движущийся примитив даёт моторам ключ: они ходят от ключа "
            "к ключу, так что это то, насколько точно они за ним следуют"))
        self.step.released.connect(lambda: actions.set_prim_step(int(self.step.value())))
        line.addWidget(self.step)
        line.addStretch(1)
        self.column.addWidget(step)
        self.bake = QPushButton(tr("Запечь примитивы в ключи"))
        self.bake.setObjectName("qa_kin_prim_bake")
        self.bake.setToolTip(tr(
            "Что делают включённые примитивы — в ключи моторов, а сами они "
            "выключаются. Отменяется Ctrl+Z."))
        self.bake.clicked.connect(lambda: actions.bake_primitives())
        self.column.addWidget(self.bake)
        self.column.addWidget(note(tr(
            "Примитивы лежат поверх ключей: позитив берёт больший вынос, негатив — "
            "меньший. Симуляция и экспорт видят результат. Щелчок по карте или по "
            "3D ставит выбранный примитив в эту точку.")))
        self.finish()

    def _masked(self, which: str, box: QComboBox, index: int) -> None:
        if not self._filling:
            self.actions.set_prim_property(which, "" if index <= 0 else box.itemText(index))

    def refresh(self) -> None:
        project = self.actions.project
        kp = self.kp
        self._filling = True
        try:
            self.list.clear()
            for one in project.primitives:
                sign = "+" if one.polarity == "positive" else "−"
                self.list.addItem(f"{sign} {one.name}"
                                  + ("" if one.on else "  · " + tr("выкл")))
            self.list.setCurrentRow(self.actions.prim_index)
            one = self.actions.primitive()
            self.body.setEnabled(one is not None)
            self.step.set(project.prim_step)
            self.bake.setEnabled(any(p.on for p in project.primitives))
            names = self.actions.mask_names()
            for box, first in ((self.mask, tr(Masks.ALL_CELLS)),
                               (self.tilt_mask, tr(self.SAME_MASK))):
                box.clear()
                box.addItem(first)
                box.addItems(names)
            if one is None:
                return
            self.polarity.buttons[self.POLARITY_KEYS.index(one.polarity)].setChecked(True)
            for box, on in ((self.on, one.on), (self.tilt, one.tilt)):
                box.blockSignals(True)
                box.setChecked(on)
                box.blockSignals(False)
            for box, name in ((self.mask, one.mask), (self.tilt_mask, one.tilt_mask)):
                box.setCurrentIndex(names.index(name) + 1 if name in names else 0)
            box_like = one.kind == "box"
            self.labels[kp.WIDTH].setText(tr("Ширина") if box_like else tr("Радиус"))
            for param in (kp.TALL, kp.DEPTH):
                self.boxes[param].setVisible(box_like)
                self.labels[param].setVisible(box_like)
            values = one.at(self.actions.frame)
            keyed = self.actions.frame in one.frames
            for param, box in self.boxes.items():
                value = float(values[param])
                box.set(value * 100.0 if param == kp.STRENGTH else value)
                # A number keyed on this very frame, as Blender colours it.
                box.setStyleSheet(f"color:{theme.WARN};" if keyed else "")
        finally:
            self._filling = False
