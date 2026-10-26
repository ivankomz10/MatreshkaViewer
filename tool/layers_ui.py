"""The advanced mode's own pieces of the window: the column of screens to the
right of the picture and the drawer each of them slides out.

Laid out as in the prototype the technical director chose (the "Слои и кисти
Матрёшки" page): square buttons in each screen's colour -- TOP, BOT, LAM, SND,
KIN -- and a drawer over the right edge of the picture, edged in the colour of
the button that opened it. At the top of a drawer is the screen's source as
its row on the left has it -- the file, what it is, the brightness, the same
slider moved from either place -- and under it the stack of layers.

One drawer at a time. A click anywhere else puts it away, unless it is
pinned. Nothing here draws a picture; the window is asked through `source_of`
for the row a screen is fed by.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import (QApplication, QComboBox, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QSizePolicy, QSlider, QSpinBox, QVBoxLayout,
                               QWidget)

import layers as stacks
import theme
from lang import tr

# The screens down the column, as the rows on the left call them, and the
# three letters a square has room for.
SCREENS = (("Top", "TOP"), ("Bottom", "BOT"), ("Lamels", "LAM"), ("Sound", "SND"),
           ("Kinetic", "KIN"))
RAIL_WIDE = 62
DRAWER_WIDE = 340


def _dark(colour: str) -> str:
    """Ink for a square of the screen's colour: near black, as the prototype."""
    return "#111111"


class ScreenRail(QWidget):
    """The column of screens. `chosen` says which drawer is wanted, or ""."""

    chosen = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("qa_screen_rail")
        self.setFixedWidth(RAIL_WIDE)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"QWidget#qa_screen_rail {{ background:{theme.BAR};"
                           f" border-left:1px solid {theme.SEAM}; }}")
        column = QVBoxLayout(self)
        column.setContentsMargins(6, 8, 6, 8)
        column.setSpacing(6)
        self.buttons = {}
        for key, short in SCREENS:
            colour = theme.SCREEN[key]
            button = QPushButton(short)
            button.setObjectName(f"qa_rail_{key.lower()}")
            button.setCheckable(True)
            button.setFixedSize(50, 50)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setToolTip(tr("Шторка этого экрана: источник и слои над ним"))
            button.setStyleSheet(
                f"QPushButton {{ background:{colour}; color:{_dark(colour)};"
                f" border:2px solid {colour}; border-radius:0; padding:0;"
                f" font-weight:700; font-size:15px; }}"
                f"QPushButton:checked {{ border:2px solid #ffffff; }}")
            button.clicked.connect(lambda _=False, key=key: self._pressed(key))
            column.addWidget(button)
            self.buttons[key] = button
        column.addStretch(1)
        self.open = ""

    def _pressed(self, key: str) -> None:
        self.show_open("" if self.open == key else key)
        self.chosen.emit(self.open)

    def show_open(self, key: str) -> None:
        self.open = key
        for name, button in self.buttons.items():
            button.setChecked(name == key)


class SourceCard(QFrame):
    """A screen's source at the top of its drawer: the row on the left, again.

    Mirrors the row rather than keeping a copy: the file and what is known of
    it are read from the row's own labels, and the brightness is the row's
    own slider, moved from here or from there.
    """

    def __init__(self, row, colour: str, parent=None, in_show: bool = False) -> None:
        super().__init__(parent)
        self.row = row
        self.in_show = in_show
        self.setObjectName("qa_drawer_source")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"QFrame#qa_drawer_source {{ background:{theme.RAISED};"
                           f" border-bottom:2px solid {colour}; }}")
        whole = QVBoxLayout(self)
        whole.setContentsMargins(10, 6, 10, 8)
        whole.setSpacing(2)
        self.file = QLabel()
        self.file.setObjectName("qa_drawer_file")
        self.file.setFont(theme.mono(9.5))
        self.file.setTextFormat(Qt.TextFormat.PlainText)
        self.file.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        whole.addWidget(self.file)
        self.note = QLabel()
        self.note.setObjectName("qa_drawer_note")
        self.note.setFont(theme.mono(8.5))
        self.note.setStyleSheet(f"color:{theme.META};")
        self.note.setTextFormat(Qt.TextFormat.PlainText)
        self.note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        # Its row's words, said again here: the row is what puts them in the
        # language chosen, and the card follows it (see refresh).
        self.note.setProperty("fixed_words", True)
        self.file.setProperty("fixed_words", True)
        whole.addWidget(self.note)
        self.gain = None
        if row is not None and row.gain is not None:
            line = QHBoxLayout()
            line.setSpacing(10)
            said = QLabel(tr("Громкость") if row.sound else tr("Яркость"))
            said.setStyleSheet(f"color:{theme.QUIET}; font-size:12px;")
            line.addWidget(said)
            self.gain = QSlider(Qt.Orientation.Horizontal)
            self.gain.setObjectName("qa_drawer_gain")
            self.gain.setRange(row.gain.minimum(), row.gain.maximum())
            self.gain.setValue(row.gain.value())
            self.gain.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            line.addWidget(self.gain, 1)
            self.value = QLabel(f"{row.gain.value() / 100.0:.2f}")
            self.value.setFont(theme.mono(9))
            self.value.setFixedWidth(36)
            self.value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            line.addWidget(self.value)
            whole.addLayout(line)
            # Either slider moves the other; the row's is the one that counts.
            self.gain.valueChanged.connect(row.gain.setValue)
            row.gain.valueChanged.connect(self._row_moved)
        self.refresh()

    def _row_moved(self, value: int) -> None:
        if self.gain is not None and self.gain.value() != value:
            self.gain.blockSignals(True)
            self.gain.setValue(value)
            self.gain.blockSignals(False)
        self.value.setText(f"{value / 100.0:.2f}")

    def refresh(self) -> None:
        row = self.row
        if self.in_show:
            self.file.setText(tr("в шоу — ролики своей дорожки"))
            self.note.setText(tr("слои у роликов шоу — последним шагом плана"))
            self.note.setVisible(True)
            return
        name = row.file.text() if row is not None else ""
        self.file.setText(name or tr("файла нет"))
        self.file.setToolTip(row.field.text() if row is not None else "")
        self.note.setText(row.note.text() if row is not None else "")
        self.note.setVisible(bool(self.note.text()))

    def let_go(self) -> None:
        """Off the row's signal, before the card goes."""
        if self.row is not None and self.row.gain is not None:
            try:
                self.row.gain.valueChanged.disconnect(self._row_moved)
            except (RuntimeError, TypeError):
                pass


class Drawer(QFrame):
    """One screen's drawer: its source and its stack, edged in its colour."""

    closed = Signal()

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setObjectName("qa_drawer")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(DRAWER_WIDE)
        self.key = ""
        self.pinned = False
        self.card = None
        self.whole = QVBoxLayout(self)
        self.whole.setContentsMargins(2, 0, 2, 2)
        self.whole.setSpacing(0)
        self.head = QWidget()
        self.head.setObjectName("qa_drawer_head")
        self.head.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        line = QHBoxLayout(self.head)
        line.setContentsMargins(8, 0, 4, 0)
        line.setSpacing(6)
        self.title = QLabel()
        self.title.setObjectName("qa_drawer_title")
        line.addWidget(self.title, 1)
        self.pin = QPushButton(tr("Закрепить"))
        self.pin.setObjectName("qa_drawer_pin")
        self.pin.setCheckable(True)
        self.pin.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.pin.setToolTip(tr("Не прятать шторку при клике мимо"))
        self.pin.toggled.connect(lambda on: setattr(self, "pinned", bool(on)))
        line.addWidget(self.pin)
        shut = QPushButton("×")
        shut.setObjectName("qa_drawer_close")
        shut.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        shut.setToolTip(tr("Убрать шторку"))
        shut.clicked.connect(self.closed.emit)
        line.addWidget(shut)
        self.head.setFixedHeight(24)
        self.whole.addWidget(self.head)
        self.body = QWidget()
        self.body.setObjectName("qa_drawer_body")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(0)
        self.whole.addWidget(self.body, 1)
        self.hide()

    def show_screen(self, key: str, row, in_show: bool = False, stack=None) -> None:
        """Fill the drawer for one screen and colour it. In the show the
        screen is fed by its track's clips, and the card says so. `stack`, a
        StackView, is the screen's layers; without one the drawer says why
        there are none."""
        self.key = key
        colour = theme.SCREEN[key]
        ink = _dark(colour)
        self.setStyleSheet(
            f"QFrame#qa_drawer {{ background:{theme.PANEL}; border:2px solid {colour}; }}"
            f"QWidget#qa_drawer_head {{ background:{colour}; }}"
            f"QWidget#qa_drawer_head QLabel {{ color:{ink}; font-weight:700; font-size:12px; }}"
            f"QWidget#qa_drawer_head QPushButton {{ color:{ink}; background:rgba(0,0,0,0.18);"
            f" border:0; padding:1px 8px; font-weight:600; font-size:11px; }}"
            f"QWidget#qa_drawer_head QPushButton:checked {{ background:{ink}; color:{colour}; }}")
        short = dict(SCREENS)[key]
        self.title.setText(f"{short} · {key}")
        while self.body_layout.count():
            item = self.body_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        if self.card is not None:
            self.card.let_go()
        self.card = SourceCard(row, colour, in_show=in_show)
        self.body_layout.addWidget(self.card)
        self.stack = stack
        if stack is not None:
            self.body_layout.addWidget(stack, 1)
            return
        self.stack_note = QLabel(self._empty_words(key))
        self.stack_note.setObjectName("qa_drawer_stack")
        self.stack_note.setWordWrap(True)
        self.stack_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stack_note.setStyleSheet(
            f"QLabel {{ color:{theme.FAINT}; font-size:11px; border:1px dashed {theme.EDGE};"
            f" margin:8px; padding:8px; }}")
        self.body_layout.addWidget(self.stack_note)
        self.body_layout.addStretch(1)

    @staticmethod
    def _empty_words(key: str) -> str:
        if key == "Sound":
            return tr("У звука нет слоёв: дорожки складываются, у каждой своя громкость.")
        return tr("Слои движения — в редакторе кинетики.")

    def refresh(self) -> None:
        if self.card is not None:
            self.card.refresh()
        if getattr(self, "stack", None) is not None:
            self.stack.rebuild()


# -- the stack ------------------------------------------------------------------------

LAYER_MIME = "application/x-matreshka-layer"
PICTURES = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp")


class LayerRow(QFrame):
    """One layer: shown or not, what it is, its name, how it lies and how much."""

    def __init__(self, view, layer, depth: int) -> None:
        super().__init__()
        self.view, self.layer = view, layer
        self.setObjectName(f"qa_layer_{layer.ident}")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAcceptDrops(True)
        chosen = view.chosen is layer
        self.setStyleSheet(
            f"QFrame#qa_layer_{layer.ident} {{ background:{'#303438' if chosen else theme.RAISED};"
            f" border:1px solid {theme.LINE if chosen else theme.SEAM}; }}")
        line = QHBoxLayout(self)
        line.setContentsMargins(4 + depth * 16, 4, 6, 4)
        line.setSpacing(6)
        self.eye = QPushButton("●" if layer.visible else "○")
        self.eye.setObjectName("qa_layer_eye")
        self.eye.setFixedSize(20, 20)
        self.eye.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.eye.setToolTip(tr("Показать или скрыть слой"))
        self.eye.setStyleSheet(f"QPushButton {{ border:0; background:transparent; font-size:14px;"
                               f" color:{theme.SECOND if layer.visible else theme.FAINT}; }}")
        self.eye.clicked.connect(self._eye)
        line.addWidget(self.eye)
        self.thumb = QLabel()
        self.thumb.setFixedSize(34, 34)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if layer.kind == "folder":
            self.thumb.setText("▾▭" if layer.open else "▸▭")
            self.thumb.setStyleSheet(f"color:{theme.DIM}; font-size:13px;")
            self.thumb.mousePressEvent = lambda _e: self._fold()
        else:
            picture = view.thumbnail(layer.path)
            if picture is not None:
                self.thumb.setPixmap(picture)
            else:
                self.thumb.setText("?")
                self.thumb.setToolTip(tr("Картинка не открывается: {0}", layer.path))
            self.thumb.setStyleSheet(self._aimed(layer.target == "content"))
            self.thumb.mousePressEvent = lambda event: self._aim("content", event)
        line.addWidget(self.thumb)
        self.mask_thumb = None
        if layer.mask:
            self.mask_thumb = QLabel()
            self.mask_thumb.setObjectName("qa_layer_mask")
            self.mask_thumb.setFixedSize(34, 34)
            self.mask_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            small = view.mask_thumbnail(layer)
            if small is not None:
                self.mask_thumb.setPixmap(small)
            self.mask_thumb.setToolTip(tr("Маска: белое видно, чёрное нет. Щелчок — рисовать по маске, "
                                          "Shift+щелчок — выключить маску"))
            self.mask_thumb.setStyleSheet(self._aimed(layer.target == "mask", layer.mask_visible))
            self.mask_thumb.mousePressEvent = lambda event: self._aim("mask", event)
            line.addWidget(self.mask_thumb)
        self.name = QLabel(layer.name)
        self.name.setObjectName("qa_layer_name")
        self.name.setProperty("fixed_words", True)       # a layer's own name
        self.name.setToolTip(layer.path or tr("Двойной щелчок — переименовать"))
        self.name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        line.addWidget(self.name, 1)
        right = QVBoxLayout()
        right.setSpacing(2)
        self.blend = QComboBox()
        self.blend.setObjectName("qa_layer_blend")
        self.blend.setProperty("fixed_items", True)     # Norm, Add... in both languages
        for key in stacks.BLENDS:
            self.blend.addItem(stacks.SHORT[key], key)
        self.blend.setCurrentIndex(stacks.BLENDS.index(layer.blend))
        self.blend.setToolTip(tr("Как слой ложится на то, что под ним"))
        self.blend.currentIndexChanged.connect(self._blend)
        right.addWidget(self.blend)
        self.opacity = QSpinBox()
        self.opacity.setObjectName("qa_layer_opacity")
        self.opacity.setRange(0, 100)
        self.opacity.setValue(round(layer.opacity * 100))
        self.opacity.setToolTip(tr("Непрозрачность слоя, %"))
        self.opacity.valueChanged.connect(self._opacity)
        right.addWidget(self.opacity)
        line.addLayout(right)
        self._pressed_at = None

    @staticmethod
    def _aimed(on: bool, lit: bool = True) -> str:
        """A thumbnail's look: the orange line under the one a brush paints."""
        line = theme.TARGET if on else "transparent"
        return (f"background:{theme.DEEP if lit else theme.SUNKEN};"
                f" border-bottom:2px solid {line};")

    def _aim(self, what: str, event) -> None:
        self.view.choose(self.layer)
        if what == "mask" and event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.layer.mask_visible = not self.layer.mask_visible
            self.view.changed_rows()
            return
        if self.layer.target != what:
            self.layer.target = what
            self.view.changed_rows(picture=False)

    def _eye(self) -> None:
        self.layer.visible = not self.layer.visible
        self.view.changed_rows()

    def _fold(self) -> None:
        self.layer.open = not self.layer.open
        self.view.changed_rows(picture=False)

    def _blend(self, index: int) -> None:
        self.layer.blend = stacks.BLENDS[index]
        self.view.changed_picture()

    def _opacity(self, value: int) -> None:
        self.layer.opacity = value / 100.0
        self.view.changed_picture()

    def mousePressEvent(self, event) -> None:  # noqa: N802 -- Qt naming
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed_at = event.position().toPoint()
            self.view.choose(self.layer)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 -- Qt naming
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, tr("Имя слоя"), tr("Имя слоя"), text=self.layer.name)
        if ok and name.strip():
            self.layer.name = name.strip()
            self.view.changed_rows(picture=False)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 -- Qt naming
        if self._pressed_at is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if (event.position().toPoint() - self._pressed_at).manhattanLength() < 8:
            return
        from PySide6.QtCore import QMimeData
        from PySide6.QtGui import QDrag
        drag = QDrag(self)
        data = QMimeData()
        data.setData(LAYER_MIME, str(self.layer.ident).encode())
        drag.setMimeData(data)
        self._pressed_at = None
        drag.exec(Qt.DropAction.MoveAction)

    def where(self, y: float) -> str:
        """Above, below or into this row, by where in it the drop falls."""
        part = y / max(1, self.height())
        if self.layer.kind == "folder" and 0.3 < part < 0.7:
            return "in"
        return "above" if part < 0.5 else "below"

    def dragEnterEvent(self, event) -> None:  # noqa: N802 -- Qt naming
        if event.mimeData().hasFormat(LAYER_MIME) or event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802 -- Qt naming
        event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802 -- Qt naming
        where = self.where(event.position().y())
        self.view.dropped(event.mimeData(), self.layer, where)
        event.acceptProposedAction()


class EffectRow(QFrame):
    """One effect of a layer, under it: shown or not, what it is, away."""

    def __init__(self, view, layer, effect, depth: int) -> None:
        super().__init__()
        self.view, self.layer, self.effect = view, layer, effect
        self.setObjectName(f"qa_effect_{effect.key}")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        aimed = effect.kind == "paint" and layer.target == f"paint:{effect.key}"
        chosen = view.chosen_effect is effect
        self.setStyleSheet(
            f"QFrame#qa_effect_{effect.key} {{ background:{'#303438' if chosen else theme.PANEL};"
            f" border-left:2px solid {theme.TARGET if aimed else theme.SEAM}; }}")
        line = QHBoxLayout(self)
        line.setContentsMargins(28 + depth * 16, 2, 6, 2)
        line.setSpacing(6)
        eye = QPushButton("●" if effect.visible else "○")
        eye.setObjectName("qa_effect_eye")
        eye.setFixedSize(18, 18)
        eye.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        eye.setToolTip(tr("Показать или скрыть эффект"))
        eye.setStyleSheet(f"QPushButton {{ border:0; background:transparent; font-size:12px;"
                          f" color:{theme.SECOND if effect.visible else theme.FAINT}; }}")
        eye.clicked.connect(self._eye)
        line.addWidget(eye)
        mark = QLabel("fx")
        mark.setStyleSheet(f"color:{theme.FAINT}; font-size:10px;")
        line.addWidget(mark)
        name = QLabel(tr("Кисть") if effect.kind == "paint" else "HSL")
        name.setObjectName("qa_effect_name")
        name.setStyleSheet(f"color:{theme.SECOND if effect.visible else theme.FAINT}; font-size:11px;")
        line.addWidget(name, 1)
        drop = QPushButton("✕")
        drop.setObjectName("qa_effect_drop")
        drop.setFixedSize(18, 18)
        drop.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        drop.setToolTip(tr("Убрать эффект"))
        drop.setStyleSheet(f"QPushButton {{ border:0; background:transparent; color:{theme.QUIET}; }}")
        drop.clicked.connect(self._drop)
        line.addWidget(drop)

    def _eye(self) -> None:
        self.effect.visible = not self.effect.visible
        self.view.changed_rows()

    def _drop(self) -> None:
        self.layer.drop_effect(self.effect)
        if self.view.chosen_effect is self.effect:
            self.view.chosen_effect = None
        self.view.changed_rows()

    def mousePressEvent(self, event) -> None:  # noqa: N802 -- Qt naming
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.view.chosen = self.layer
        self.view.chosen_effect = self.effect
        if self.effect.kind == "paint":
            self.layer.target = f"paint:{self.effect.key}"
        self.view.changed_rows(picture=False)


class EffectPanel(QFrame):
    """The chosen HSL effect's three numbers."""

    def __init__(self, view) -> None:
        super().__init__()
        self.view = view
        self.effect = None
        self.setObjectName("qa_effect_panel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"QFrame#qa_effect_panel {{ background:{theme.DEEP};"
                           f" border-top:1px solid {theme.SEAM}; }}")
        from PySide6.QtWidgets import QDoubleSpinBox, QGridLayout
        grid = QGridLayout(self)
        grid.setContentsMargins(10, 6, 10, 8)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        head = QLabel(tr("Эффект HSL"))
        head.setStyleSheet(f"color:{theme.DIM}; font-size:11px;")
        grid.addWidget(head, 0, 0, 1, 4)
        self.fields = {}
        for at, (key, label, low, high) in enumerate((
                ("hue", tr("Тон, °"), -180, 180), ("saturation", tr("Насыщенность, %"), -100, 100),
                ("lightness", tr("Светлота, %"), -100, 100))):
            name = QLabel(label)
            name.setStyleSheet(f"color:{theme.QUIET}; font-size:11px;")
            field = QDoubleSpinBox()
            field.setObjectName(f"qa_effect_{key}")
            field.setRange(low, high)
            field.setDecimals(1)
            field.valueChanged.connect(lambda value, key=key: self._typed(key, value))
            grid.addWidget(name, 1 + at, 0)
            grid.addWidget(field, 1 + at, 1)
            self.fields[key] = field
        self._saying = False
        self.show_effect(None)

    def show_effect(self, effect) -> None:
        self.effect = effect if effect is not None and effect.kind == "hsl" else None
        self.setVisible(self.effect is not None)
        if self.effect is None:
            return
        self._saying = True
        try:
            self.fields["hue"].setValue(self.effect.hue)
            self.fields["saturation"].setValue(self.effect.saturation * 100.0)
            self.fields["lightness"].setValue(self.effect.lightness * 100.0)
        finally:
            self._saying = False

    def _typed(self, key: str, value: float) -> None:
        if self._saying or self.effect is None:
            return
        setattr(self.effect, key, value if key == "hue" else value / 100.0)
        self.view.changed_picture()


class BrushPanel(QFrame):
    """How the brush paints: where it lies, how big, how hard, how much, which
    colour, and the eraser; and the stroke before taken back."""

    MODES = (("flat", "По развертке"), ("model", "По модели"), ("camera", "По камере"))

    def __init__(self, view) -> None:
        super().__init__()
        self.view = view
        self.setObjectName("qa_brush")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"QFrame#qa_brush {{ background:{theme.DEEP};"
                           f" border-top:1px solid {theme.SEAM}; }}")
        from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox, QGridLayout
        # Sizes each in its own units: frame pixels, centimetres, view pixels.
        self.sizes = {"flat": 40.0, "model": 30.0, "camera": 30.0}
        self.mode = "model"
        self.hardness = 0.5
        self.flow = 1.0
        self.colour = (255, 255, 255)
        self.erase = False
        grid = QGridLayout(self)
        grid.setContentsMargins(10, 6, 10, 8)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        self.modes = QComboBox()
        self.modes.setObjectName("qa_brush_mode")
        for key, text in self.MODES:
            self.modes.addItem(tr(text), key)
        self.modes.setToolTip(tr("Как кисть ложится: на развертку, на здание по нормали "
                                 "или кругом в кадре вида"))
        self.modes.setCurrentIndex(self.modes.findData(self.mode))
        self.modes.currentIndexChanged.connect(self._mode)
        grid.addWidget(self.modes, 0, 0, 1, 2)
        self.erase_box = QCheckBox(tr("Ластик"))
        self.erase_box.setObjectName("qa_brush_erase")
        self.erase_box.setToolTip(tr("Стирать краску; на маске — возвращать белое"))
        self.erase_box.toggled.connect(lambda on: setattr(self, "erase", bool(on)))
        grid.addWidget(self.erase_box, 0, 2)
        self.colour_button = QPushButton()
        self.colour_button.setObjectName("qa_brush_colour")
        self.colour_button.setFixedSize(28, 22)
        self.colour_button.setToolTip(tr("Цвет кисти для эффекта «Кисть»; маска рисуется чёрным"))
        self.colour_button.clicked.connect(self._pick_colour)
        grid.addWidget(self.colour_button, 0, 3)
        self.size_label = QLabel()
        self.size_label.setStyleSheet(f"color:{theme.QUIET}; font-size:11px;")
        self.size = QDoubleSpinBox()
        self.size.setObjectName("qa_brush_size")
        self.size.setRange(1, 5000)
        self.size.setDecimals(0)
        self.size.valueChanged.connect(self._size)
        grid.addWidget(self.size_label, 1, 0)
        grid.addWidget(self.size, 1, 1)
        hard_label = QLabel(tr("Жёсткость, %"))
        hard_label.setStyleSheet(f"color:{theme.QUIET}; font-size:11px;")
        self.hard = QDoubleSpinBox()
        self.hard.setObjectName("qa_brush_hardness")
        self.hard.setRange(0, 99)
        self.hard.setDecimals(0)
        self.hard.setValue(self.hardness * 100)
        self.hard.valueChanged.connect(lambda value: setattr(self, "hardness", value / 100.0))
        grid.addWidget(hard_label, 1, 2)
        grid.addWidget(self.hard, 1, 3)
        flow_label = QLabel(tr("Сила, %"))
        flow_label.setStyleSheet(f"color:{theme.QUIET}; font-size:11px;")
        self.flow_field = QDoubleSpinBox()
        self.flow_field.setObjectName("qa_brush_flow")
        self.flow_field.setRange(1, 100)
        self.flow_field.setDecimals(0)
        self.flow_field.setValue(self.flow * 100)
        self.flow_field.valueChanged.connect(lambda value: setattr(self, "flow", value / 100.0))
        grid.addWidget(flow_label, 2, 0)
        grid.addWidget(self.flow_field, 2, 1)
        undo = QPushButton(tr("Отменить"))
        undo.setObjectName("qa_brush_undo")
        undo.setToolTip(tr("Убрать последний мазок (Ctrl+Z)"))
        undo.clicked.connect(view.undo_wanted.emit)
        grid.addWidget(undo, 2, 2, 1, 2)
        self._say()
        self.hide()

    @property
    def radius(self) -> float:
        """The size in the mode's own units, as a radius."""
        return self.sizes[self.mode] / 2.0

    def _say(self) -> None:
        self.size_label.setText({"flat": tr("Размер, px кадра"), "model": tr("Размер, см"),
                                 "camera": tr("Размер, px вида")}[self.mode])
        self.size.blockSignals(True)
        self.size.setValue(self.sizes[self.mode])
        self.size.blockSignals(False)
        r, g, b = self.colour
        self.colour_button.setStyleSheet(f"background:rgb({r},{g},{b}); border:1px solid {theme.EDGE};")

    def _mode(self, index: int) -> None:
        self.mode = self.modes.itemData(index) or "model"
        self._say()

    def _size(self, value: float) -> None:
        self.sizes[self.mode] = float(value)

    def _pick_colour(self) -> None:
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QColorDialog
        chosen = QColorDialog.getColor(QColor(*self.colour), self, tr("Цвет кисти"))
        if chosen.isValid():
            self.colour = (chosen.red(), chosen.green(), chosen.blue())
            self._say()


class TransformPanel(QFrame):
    """Where the chosen picture lies: moved, scaled, turned, mirrored."""

    def __init__(self, view) -> None:
        super().__init__()
        self.view = view
        self.layer = None
        self.setObjectName("qa_transform")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"QFrame#qa_transform {{ background:{theme.DEEP};"
                           f" border-top:1px solid {theme.SEAM}; }}")
        from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox, QGridLayout
        grid = QGridLayout(self)
        grid.setContentsMargins(10, 6, 10, 8)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        self.head = QLabel(tr("Трансформ · пиксели кадра экрана"))
        self.head.setObjectName("qa_transform_head")
        self.head.setStyleSheet(f"color:{theme.DIM}; font-size:11px;")
        grid.addWidget(self.head, 0, 0, 1, 3)
        from PySide6.QtWidgets import QComboBox
        self.bind = QComboBox()
        self.bind.setObjectName("qa_transform_bind")
        for key, text, hint in (
                ("frame", tr("Кадр"), tr("Картинка в пикселях кадра экрана")),
                ("camera", tr("Ремап"), tr("Картинка ложится на здание так, как её видит камера зрителя")),
                ("decal", tr("Декаль"), tr("Картинка наклеена на поверхность без искажений; соты несут её на себе")),
                ("view", tr("Проектор"), tr("Картинка брошена на здание с камеры вида, как проектором"))):
            self.bind.addItem(text, key)
            self.bind.setItemData(self.bind.count() - 1, hint, Qt.ItemDataRole.ToolTipRole)
        self.bind.setToolTip(tr("Как картинка привязана: к кадру экрана или к зданию"))
        self.bind.currentIndexChanged.connect(self._bound)
        grid.addWidget(self.bind, 0, 3)
        self.aim = QPushButton(tr("С вида"))
        self.aim.setObjectName("qa_transform_aim")
        self.aim.setToolTip(tr("Поставить проектор туда, где сейчас камера вида"))
        self.aim.clicked.connect(lambda: self.view.bound.emit(self.layer))
        self.fields = {}
        for at, (key, label, low, high, step) in enumerate((
                ("x", "X", -100000, 100000, 1), ("y", "Y", -100000, 100000, 1),
                ("scale", tr("Масштаб, %"), 1, 100000, 1), ("rotation", tr("Поворот, °"), -3600, 3600, 0.5))):
            name = QLabel(label)
            name.setStyleSheet(f"color:{theme.QUIET}; font-size:11px;")
            field = QDoubleSpinBox()
            field.setObjectName(f"qa_transform_{key}")
            field.setRange(low, high)
            field.setSingleStep(step)
            field.setDecimals(1)
            field.valueChanged.connect(lambda value, key=key: self._typed(key, value))
            grid.addWidget(name, 1 + at // 2, (at % 2) * 2)
            grid.addWidget(field, 1 + at // 2, (at % 2) * 2 + 1)
            self.fields[key] = field
        self.flip = QCheckBox(tr("Отразить"))
        self.flip.setObjectName("qa_transform_flip")
        self.flip.toggled.connect(lambda on: self._typed("flip", on))
        grid.addWidget(self.flip, 3, 0, 1, 2)
        fit = QPushButton(tr("Вписать"))
        fit.setObjectName("qa_transform_fit")
        fit.setToolTip(tr("Картинка целиком по центру кадра, без поворота"))
        fit.clicked.connect(self._fit)
        grid.addWidget(fit, 3, 2)
        grid.addWidget(self.aim, 3, 3)
        # A movie's place on the clock.
        self.start_label = QLabel(tr("Старт, с"))
        self.start_label.setStyleSheet(f"color:{theme.QUIET}; font-size:11px;")
        self.start = QDoubleSpinBox()
        self.start.setObjectName("qa_transform_offset")
        self.start.setRange(-36000, 36000)
        self.start.setDecimals(2)
        self.start.setSingleStep(0.1)
        self.start.setToolTip(tr("Когда видео начинается по часам вьюера, в секундах"))
        self.start.valueChanged.connect(lambda value: self._typed("offset", value))
        self.loop = QCheckBox(tr("По кругу"))
        self.loop.setObjectName("qa_transform_loop")
        self.loop.setToolTip(tr("Видео идёт заново, дойдя до конца"))
        self.loop.toggled.connect(lambda on: self._typed("loop", on))
        grid.addWidget(self.start_label, 4, 0)
        grid.addWidget(self.start, 4, 1)
        grid.addWidget(self.loop, 4, 2, 1, 2)
        self._saying = False
        self.show_layer(None)

    def show_layer(self, layer) -> None:
        self.layer = layer if layer is not None and layer.kind in stacks.PICTURED else None
        self.setVisible(self.layer is not None)
        self.refresh()

    def refresh(self) -> None:
        if self.layer is None:
            return
        self._saying = True
        try:
            values = {"x": self.layer.x, "y": self.layer.y, "scale": self.layer.scale * 100.0,
                      "rotation": self.layer.rotation}
            for key, field in self.fields.items():
                if not field.hasFocus():
                    field.setValue(values[key])
            self.flip.setChecked(self.layer.flip)
            self.bind.setCurrentIndex(max(0, self.bind.findData(self.layer.bind)))
            self.aim.setVisible(self.layer.bind == "view")
            moving = self.layer.kind == "video"
            for widget in (self.start_label, self.start, self.loop):
                widget.setVisible(moving)
            if not self.start.hasFocus():
                self.start.setValue(self.layer.offset)
            self.loop.setChecked(self.layer.loop)
            self.head.setText({
                "camera": tr("Трансформ · по камере, как видит зритель"),
                "decal": tr("Трансформ · сантиметры по поверхности"),
                "view": tr("Трансформ · пиксели камеры вида"),
            }.get(self.layer.bind) or tr("Трансформ · пиксели кадра экрана"))
        finally:
            self._saying = False

    def _typed(self, key: str, value) -> None:
        if self._saying or self.layer is None:
            return
        if key == "scale":
            self.layer.scale = max(0.01, value / 100.0)
        elif key in ("flip", "loop"):
            setattr(self.layer, key, bool(value))
        else:
            setattr(self.layer, key, float(value))
        self.view.changed_picture()

    def _bound(self, index: int) -> None:
        """Bound another way: the numbers mean something else there, so the
        picture starts again fitted, and the window is asked for a place to
        put a decal or a projector."""
        key = self.bind.itemData(index)
        if self._saying or self.layer is None or key is None or self.layer.bind == key:
            return
        self.layer.bind = key
        self.layer.fit()
        if key in ("decal", "view"):
            self.view.bound.emit(self.layer)
        self.refresh()
        self.view.changed_picture()

    def _fit(self) -> None:
        if self.layer is not None:
            self.layer.fit()
            self.refresh()
            self.view.changed_picture()


class StackView(QWidget):
    """A screen's stack in its drawer: a row a layer, the top one first.

    The window is asked through `changed` to draw again and keep the stack
    with the settings, and through `moving` whether the picture under the
    hand is to be dragged rather than the view; nothing here touches a
    picture.
    """

    changed = Signal()
    moving = Signal(bool)
    painting = Signal(bool)     # the hand paints in the viewport
    undo_wanted = Signal()
    bound = Signal(object)      # a layer wanting a place for its decal or projector

    def __init__(self, stacks_, screen: str, thumbnail, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("qa_stack")
        self.setAcceptDrops(True)
        self.stacks, self.screen, self._thumbnail = stacks_, screen, thumbnail
        self.chosen = None
        self.chosen_effect = None
        self.mask_thumbnail = lambda layer: None     # the window knows the masks
        self._thumbs: dict = {}
        whole = QVBoxLayout(self)
        whole.setContentsMargins(0, 0, 0, 0)
        whole.setSpacing(0)
        tools = QWidget()
        tools.setObjectName("qa_stack_tools")
        tools.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        tools.setStyleSheet(f"QWidget#qa_stack_tools {{ background:{theme.BAR};"
                            f" border-bottom:1px solid {theme.SEAM}; }}"
                            f"QWidget#qa_stack_tools QPushButton {{ padding:3px 8px; font-size:11px; }}")
        row = QHBoxLayout(tools)
        row.setContentsMargins(4, 4, 4, 4)
        row.setSpacing(2)
        for name, text, hint, act in (
                ("picture", tr("+ Файл…"), tr("Картинка или видео с диска новым слоем"), self._pick),
                ("folder", tr("+ Папка"), tr("Папка: её слои ложатся вместе, как один"), self._folder),
                ("mask", tr("Маска"), tr("Белая маска выбранному слою, или убрать её"), self._mask),
                ("effect", tr("Эффект"), tr("Эффект выбранному слою: HSL или Кисть"), self._effect),
                ("delete", "✕", tr("Удалить выбранный слой"), self._delete)):
            button = QPushButton(text)
            button.setObjectName(f"qa_stack_{name}")
            button.setToolTip(hint)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(act)
            row.addWidget(button)
        row.addStretch(1)
        whole.addWidget(tools)
        # What the hand does in the viewport: the view, the picture, or paint.
        hands = QWidget()
        hands.setObjectName("qa_stack_hands")
        hands.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        hands.setStyleSheet(f"QWidget#qa_stack_hands {{ background:{theme.BAR};"
                            f" border-bottom:1px solid {theme.SEAM}; }}"
                            f"QWidget#qa_stack_hands QPushButton {{ padding:3px 10px; font-size:11px; }}")
        hand_row = QHBoxLayout(hands)
        hand_row.setContentsMargins(4, 0, 4, 4)
        hand_row.setSpacing(2)
        self.move_button = QPushButton(tr("Двигать"))
        self.move_button.setObjectName("qa_stack_move")
        self.move_button.setCheckable(True)
        self.move_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.move_button.setToolTip(tr("Тащить выбранную картинку прямо во вьюпорте: тащить — двигать, "
                                       "колесо — масштаб, Shift+тащить — поворот"))
        self.move_button.toggled.connect(self._moving)
        hand_row.addWidget(self.move_button)
        self.brush_button = QPushButton(tr("Кисть"))
        self.brush_button.setObjectName("qa_stack_brush")
        self.brush_button.setCheckable(True)
        self.brush_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.brush_button.setToolTip(tr("Рисовать во вьюпорте по цели слоя: маске или эффекту «Кисть»"))
        self.brush_button.toggled.connect(self._painting)
        hand_row.addWidget(self.brush_button)
        hand_row.addStretch(1)
        whole.addWidget(hands)
        from PySide6.QtWidgets import QScrollArea
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        whole.addWidget(self.scroll, 1)
        self.effect_panel = EffectPanel(self)
        whole.addWidget(self.effect_panel)
        self.brush = BrushPanel(self)
        whole.addWidget(self.brush)
        self.transform = TransformPanel(self)
        whole.addWidget(self.transform)
        self.rebuild()

    # -- what the rows say -------------------------------------------------------

    def thumbnail(self, path: str):
        if path not in self._thumbs:
            self._thumbs[path] = self._thumbnail(path)
        return self._thumbs[path]

    def rows(self) -> list:
        """The rows as they stand, top first: for the tests."""
        holder = self.scroll.widget()
        return holder.findChildren(LayerRow) if holder is not None else []

    def rebuild(self) -> None:
        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(1)

        def walk(items, depth):
            for layer in reversed(items):
                column.addWidget(LayerRow(self, layer, depth))
                for effect in reversed(layer.effects):
                    column.addWidget(EffectRow(self, layer, effect, depth))
                if layer.kind == "folder" and layer.open:
                    walk(layer.children, depth + 1)

        walk(self.stacks.stack(self.screen), 0)
        hint = QLabel(tr("Перетащите картинку с диска сюда: будет новый слой"))
        hint.setObjectName("qa_stack_hint")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet(f"QLabel {{ color:{theme.FAINT}; font-size:11px;"
                           f" border:1px dashed {theme.EDGE}; margin:6px; padding:6px; }}")
        column.addWidget(hint)
        column.addStretch(1)
        self.scroll.setWidget(holder)
        if hasattr(self, "transform"):
            if self.chosen_effect is not None and (self.chosen is None
                                                   or self.chosen_effect not in self.chosen.effects):
                self.chosen_effect = None
            self.transform.show_layer(self.chosen)
            self.effect_panel.show_effect(self.chosen_effect)

    # -- what changes ----------------------------------------------------------------

    def choose(self, layer) -> None:
        if self.chosen is not layer or self.chosen_effect is not None:
            self.chosen = layer
            self.chosen_effect = None
            self.rebuild()

    def changed_rows(self, picture: bool = True) -> None:
        self.rebuild()
        if picture:
            self.changed.emit()

    def changed_picture(self) -> None:
        self.changed.emit()

    def add_pictures(self, paths, near=None) -> list:
        made = []
        for path in paths:
            suffix = Path(path).suffix.lower()
            if suffix not in PICTURES and suffix not in stacks.MOVIES:
                continue
            layer = stacks.Layer("video" if suffix in stacks.MOVIES else "image",
                                 Path(path).stem, path=str(path))
            self.stacks.add(self.screen, layer, near=near if near is not None else None)
            near = layer
            made.append(layer)
        if made:
            self.chosen = made[-1]
            self.changed_rows()
        return made

    def _pick(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        chosen, _ = QFileDialog.getOpenFileNames(
            self, tr("Картинка или видео новым слоем"), "",
            tr("Картинки и видео (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp "
               "*.mov *.mp4 *.m4v *.mkv *.avi *.mxf);;Все файлы (*)"))
        if chosen:
            self.add_pictures(chosen, near=self.chosen)

    def _moving(self, on: bool) -> None:
        if on and self.brush_button.isChecked():
            self.brush_button.setChecked(False)
        self.moving.emit(on)

    def _painting(self, on: bool) -> None:
        if on and self.move_button.isChecked():
            self.move_button.setChecked(False)
        self.brush.setVisible(on)
        self.painting.emit(on)

    def _mask(self) -> None:
        if self.chosen is None:
            return
        if self.chosen.mask:
            self.chosen.drop_mask()
        else:
            self.chosen.add_mask()
        self.changed_rows()

    def _effect(self) -> None:
        if self.chosen is None:
            return
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setObjectName("qa_stack_effect_menu")
        for kind, text in (("hsl", "HSL"), ("paint", tr("Кисть"))):
            action = menu.addAction(text)
            action.triggered.connect(lambda _=False, kind=kind: self.add_effect(kind))
        button = self.findChild(QPushButton, "qa_stack_effect")
        menu.popup(button.mapToGlobal(button.rect().bottomLeft()))

    def add_effect(self, kind: str):
        """An effect on top of the chosen layer's, chosen in its turn."""
        if self.chosen is None:
            return None
        made = self.chosen.add_effect(kind)
        self.chosen_effect = made
        self.changed_rows()
        return made

    def _folder(self) -> None:
        folder = stacks.Layer("folder", tr("папка"))
        self.stacks.add(self.screen, folder, near=self.chosen)
        self.chosen = folder
        self.changed_rows(picture=False)

    def _delete(self) -> None:
        if self.chosen is None:
            return
        self.stacks.remove(self.chosen)
        self.chosen = None
        self.changed_rows()

    def dropped(self, data, target, where: str) -> None:
        if data.hasUrls():
            paths = [url.toLocalFile() for url in data.urls() if url.isLocalFile()]
            made = self.add_pictures(paths, near=target if where != "in" else None)
            if target is not None and where in ("below", "in"):
                for layer in made:
                    self.stacks.move(layer, target, where)
                self.changed_rows()
            return
        if data.hasFormat(LAYER_MIME):
            ident = int(bytes(data.data(LAYER_MIME)).decode() or 0)
            moving = next((one for one, _ in self.stacks._walk(self.stacks.stack(self.screen))
                           if one.ident == ident), None)
            if moving is not None and target is not None and self.stacks.move(moving, target, where):
                self.changed_rows()

    def dragEnterEvent(self, event) -> None:  # noqa: N802 -- Qt naming
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802 -- Qt naming
        if event.mimeData().hasUrls():
            self.dropped(event.mimeData(), None, "above")
            event.acceptProposedAction()


class ClickAway(QObject):
    """Puts the drawer away on a press outside it and outside the rail."""

    def __init__(self, drawer: Drawer, rail: ScreenRail, away) -> None:
        super().__init__(drawer)
        self.drawer, self.rail, self.away = drawer, rail, away
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 -- Qt naming
        if (event.type() == QEvent.Type.MouseButtonPress and self.drawer.isVisible()
                and not self.drawer.pinned
                # A press in a window of its own -- the file dialog the
                # drawer opened -- is not a press beside the drawer.
                and isinstance(watched, QWidget) and watched.window() is self.drawer.window()):
            spot = event.globalPosition().toPoint()
            for keep in (self.drawer, self.rail):
                if keep.isVisible() and keep.rect().contains(keep.mapFromGlobal(spot)):
                    return False
            self.away()
        return False
