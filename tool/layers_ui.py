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

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QSlider, QVBoxLayout, QWidget)

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

    def show_screen(self, key: str, row, in_show: bool = False) -> None:
        """Fill the drawer for one screen and colour it. In the show the
        screen is fed by its track's clips, and the card says so."""
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
        if key == "Kinetic":
            return tr("Слои движения — в редакторе кинетики.")
        return tr("Слоёв пока нет. Картинки, видео и кисти над источником экрана — "
                  "следующими шагами.")

    def refresh(self) -> None:
        if self.card is not None:
            self.card.refresh()


class ClickAway(QObject):
    """Puts the drawer away on a press outside it and outside the rail."""

    def __init__(self, drawer: Drawer, rail: ScreenRail, away) -> None:
        super().__init__(drawer)
        self.drawer, self.rail, self.away = drawer, rail, away
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 -- Qt naming
        if (event.type() == QEvent.Type.MouseButtonPress and self.drawer.isVisible()
                and not self.drawer.pinned):
            spot = event.globalPosition().toPoint()
            for keep in (self.drawer, self.rail):
                if keep.isVisible() and keep.rect().contains(keep.mapFromGlobal(spot)):
                    return False
            self.away()
        return False
