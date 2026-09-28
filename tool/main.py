"""Three HAP screens on one clock, drawn without ever unpacking a frame.

The prototype: flat rectangles rather than geometry, which is the order agreed
on, because the risky part is the video and not the layout. Every number the
machine is managing is on screen from the first run -- this has to work on
machines nobody here will ever see, and a program that cannot be asked what it
is doing costs more than any feature it might have instead.
"""
from __future__ import annotations

import html
import math
import subprocess
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QIcon, QImage, QKeySequence,
                           QPainter, QPen, QPixmap, QShortcut)
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox,
                               QComboBox, QDialog, QFileDialog, QFrame,
                               QMessageBox,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QMainWindow, QMenu, QProgressBar, QListView,
                               QPushButton, QSizePolicy, QSlider, QSpinBox,
                               QAbstractButton,
                               QScrollArea, QSplitter, QToolButton,
                               QWidgetAction,
                               QStyle, QStyleFactory, QToolTip, QVBoxLayout,
                               QWidget)
from rendercanvas.pyside6 import RenderCanvas

import numpy as np
import wgpu

import depends
import draft as drafts
import export
import jobs
import logfile
import player
import rebake
import renderer3d
import scene3d
import kinetic
import show as showfile
import screen_gpu
import sound
import theme
import timeline
import lang
from lang import tr

BAKED = "baked"
SNAPSHOTS = "snapshots"   # single frames go beside the videos, not among them

# The mode the building is framed in. It was called Geometry, which named
# what it draws rather than what it is for: this is the preview the content
# gets judged on. WAS_CALLED keeps a settings file written before the rename
# opening on the mode it names.
PREVIEW = "Превью"
WAS_CALLED = {"Geometry": PREVIEW}

# What counts as an extension already on the name. Anything else after a dot
# belongs to the name itself: a piece called "Velofest.2026.09.03" has no
# extension, whatever the last four characters look like to `Path.suffix`.
SUFFIXES = {".mp4", ".mov", ".png", ".mkv", ".avi", ".mxf"}

# Where the show files live on the machines this was made for. Only where
# the dialog opens the first time; nothing is ever written there.
SHOW_FOLDER = Path(r"D:\Content\_SHOW")
# The show's screens, as the rows call them and as the scene does.
SHOW_SCREENS = (("Top", "Screen_Top"), ("Bottom", "Screen_Bottom"),
                ("Lamels", "Lamel_screen"))
# What a show draws the building with. ReBake is about one source file and
# its alpha; a show's screen is several files at once, already added up.
SHOW_MODES = (PREVIEW, "Flat", "Inspection")

APP_NAME = "Matreshka Viewer"
APP_VERSION = "0.4"
MONO = "IBM Plex Mono, Cascadia Mono, Consolas, DejaVu Sans Mono, Menlo, monospace"

# How the building is drawn: the key each mode is known by in the code and
# in a settings file, and what the tab says. Named by what is on the screen.
MODE_LABEL = {PREVIEW: "Превью", "Flat": "Развертка",
              "Inspection": "Инспектор", "ReBake": "Перепечка"}
MODE_TAG = {PREVIEW: "preview", "Flat": "flat", "Inspection": "inspection",
            "ReBake": "rebake"}
# The pieces of the building, as the Слои menu calls them.
LAYER_LABEL = {"Body": "Корпус", "Shell": "Оболочка", "Blank": "Заглушка"}
# Lines of the lists as they were called before they were Russian, so that a
# settings file written then still opens on what it says.
OLD_WORDS = {"Fit": "Вписать", "Stretch": "Растянуть",
             "Calibration": "Калибровка", "Black": "Чёрный",
             "Clean": "Чистка", "Dither": "Дизер", "Multiply": "Умножить",
             "Keep": "Оставить", "Clamp": "Прижать",
             "60 fps": "60 к/с", "30 fps": "30 к/с"}


def choose_saved(box, value) -> None:
    """Put a list back on what a settings file says, in either language."""
    value = str(value)
    wanted = lang.either(value) | lang.either(OLD_WORDS.get(value, value))
    for index in range(box.count()):
        if box.itemText(index) in wanted or str(box.itemData(index)) == value:
            box.setCurrentIndex(index)
            return


def assign_files(paths, taken: dict) -> dict:
    """Which row each of several files goes to, by its ending and its name.

    What the exporters name things: `_top`, `_bottom` or `main`, `lamel`. A
    movie that says nothing goes to the first screen with nothing on it.
    `taken` is what each row holds already.
    """
    wanted: dict = {}
    for path in paths:
        name, ending = Path(path).stem.lower(), Path(path).suffix.lower()
        if ending == ".wav":
            title = "Sound"
        elif ending == ".json":
            title = "Kinetic"
        elif "lamel" in name:
            title = "Lamels"
        elif "top" in name or "tiles" in name:
            title = "Top"
        elif "bottom" in name or "main" in name or "scene" in name:
            title = "Bottom"
        elif "frame" in name:
            title = "Frame"
        else:
            title = next((one for one in ("Top", "Bottom", "Lamels")
                          if one not in wanted and not taken.get(one)), None)
        if title is not None and title not in wanted:
            wanted[title] = str(path)
    return wanted

# What each language is called, in itself.
LANGUAGE_NAMES = {"ru": "Русский", "en": "English"}

# Where the window opens on a machine that has never run it. After that the
# last session is restored over the top of these, so they are the starting
# point rather than the state.
#
# The two by eye, on top of the measured match, on the real content. Named by
# the row's own title because the Frame row shares a screen with Bottom and
# would otherwise be swept up with it.
START_GAIN = {"Top": 1.29, "Bottom": 1.29}
START_SOLID_TOP = True      # the top screen's own back does not show through
START_LINKED = True         # Top and Bottom move together, at the ratio above


def read_rgba(path: Path):
    """A PNG as an array, copied out before the QImage that owns it is gone."""
    image = QImage(str(path)).convertToFormat(QImage.Format.Format_RGBA8888)
    width, height = image.width(), image.height()
    raw = np.frombuffer(bytes(image.constBits()), dtype=np.uint8)
    return raw.reshape(height, image.bytesPerLine() // 4, 4)[:, :width].copy()


SHORT = {
    "Body_hide": "Body",
    "Lamel_Body_hide": "Shell",
    "Cylinder": "Blank",
    "Screen_Bottom": "Bottom",
    "Screen_Top": "Top",
    "screen": "Top",
    "Lamel_screen": "Lamels",
}


ICONS = "icons"
_drawn: dict = {}


def icon(name: str) -> QIcon:
    """One of Houdini's own button icons, by the name this tool calls it.

    Taken out of Houdini's own archive once and kept beside the tool -- see
    icons/WHERE_THESE_CAME_FROM.txt -- so nothing here needs Houdini
    installed, or a renderer for SVG inside the executable.
    """
    if name in theme.DRAWN:
        # The ones that were coloured pictures from four different sets --
        # a broom, a bread roll, a red push button -- redrawn in one line.
        return theme.drawn_icon(name)
    if name not in _drawn:
        folder = (logfile.bundled(ICONS)
                  or (Path(__file__).resolve().parent / ICONS))
        _drawn[name] = QIcon(str(Path(folder) / f"{name}.png"))
    return _drawn[name]


# What a button says when the cursor rests on it: its name after half a
# second, what it is for after two. Two waits rather than one, because a
# glance wants the name and only the name, and the paragraph underneath is
# for whoever waits long enough to be actually asking.
HINTS: dict = {}
HINT_NAME = 500
HINT_STORY = 2000


def faded(name: str, much: float = 0.35) -> QIcon:
    """The same icon, most of the way to invisible.

    A switch that is off should look off. The picture stays the picture --
    it is the same chain either way -- and only says so faintly.
    """
    picture = icon(name).pixmap(QSize(64, 64))
    thin = QPixmap(picture.size())
    thin.fill(Qt.GlobalColor.transparent)
    brush = QPainter(thin)
    brush.setOpacity(much)
    brush.drawPixmap(0, 0, picture)
    brush.end()
    return QIcon(thin)


def iconed(button: QPushButton, picture: str, says: str, story: str = "",
           side: int = 28, name: str = "") -> QPushButton:
    """A button shown as its picture, with its words moved into the hover.

    `name` is what the test driver finds the button by. Qt hands an
    objectName to the platform's accessibility layer as the element's
    automation id, and a button whose words have moved into a hover has
    nothing else left to be found by.
    """
    button.setText("")
    if name:
        button.setObjectName(name)
    button.setIcon(icon(picture))
    button.setIconSize(QSize(side - 10, side - 10))
    button.setFixedSize(side, side)
    button.setStyleSheet("padding:0px;")
    button.setToolTip("")          # ours, on our own timing, not Qt's
    HINTS[button] = (says, story)
    return button


def labeled(button: QPushButton, picture: str, text: str, says: str,
            story: str = "", name: str = "") -> QPushButton:
    """A button that keeps its words: for the few that are the point of a bar.

    Everything else on a bar is a picture with its name in the hover; the
    thing a bar is for says what it does, so it can be found without one.
    """
    if name:
        button.setObjectName(name)
    button.setText(text)
    if picture:
        button.setIcon(icon(picture))
        button.setIconSize(QSize(16, 16))
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    button.setToolTip("")
    HINTS[button] = (says, story)
    return button


class ResetSlider(QSlider):
    """A brightness: a double click puts it back at 1.00."""

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 -- Qt naming
        self.setValue(100)


class ModeTabs(QWidget):
    """How the building is drawn, as tabs rather than a list to open.

    Four ways, always the same four, one always on: a list that has to be
    opened to be read hides what the choice is between. It answers the same
    few questions a QComboBox does -- currentText, setCurrentText,
    currentIndexChanged -- with each tab's key as its text, so everything
    that asked the list which mode it was in asks this the same way.
    """

    currentIndexChanged = Signal(int)

    def __init__(self, items) -> None:
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Expanding)
        self._keys = [key for key, _label, _story in items]
        self._index = 0
        line = QHBoxLayout(self)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = {}
        for index, (key, label, story) in enumerate(items):
            button = QPushButton(label)
            button.setObjectName(f"qa_mode_{MODE_TAG.get(key, key.lower())}")
            button.setCheckable(True)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setProperty("tab", True)
            button.setSizePolicy(QSizePolicy.Policy.Preferred,
                                 QSizePolicy.Policy.Expanding)
            button.setToolTip(story)
            button.clicked.connect(lambda _=False, at=index: self.setCurrentIndex(at))
            self.group.addButton(button)
            line.addWidget(button)
            self.buttons[key] = button
        self.buttons[self._keys[0]].setChecked(True)

    def count(self) -> int:
        return len(self._keys)

    def itemText(self, index: int) -> str:  # noqa: N802 -- as the list's
        return self._keys[index]

    def currentIndex(self) -> int:  # noqa: N802
        return self._index

    def currentText(self) -> str:  # noqa: N802
        return self._keys[self._index]

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802
        index = max(0, min(int(index), len(self._keys) - 1))
        self.buttons[self._keys[index]].setChecked(True)
        if index != self._index:
            self._index = index
            self.currentIndexChanged.emit(index)

    def setCurrentText(self, key: str) -> None:  # noqa: N802
        if key in self._keys:
            self.setCurrentIndex(self._keys.index(key))

    def set_offered(self, key: str, on: bool) -> None:
        self.buttons[key].setVisible(bool(on))

    def is_offered(self, key: str) -> bool:
        return not self.buttons[key].isHidden()


def _small(button: QPushButton, width: int) -> QPushButton:
    """A narrow button that still shows its label.

    The stylesheet gives every button twelve pixels of padding a side, which
    at these widths leaves less room for the text than the text needs.
    """
    button.setFixedWidth(width)
    button.setStyleSheet("padding:5px 2px;")
    return button


# Windows' own codes for the few keys the viewer answers that are not letters.
# A letter's code is its capital, A to Z, which is also Qt's own number for it.
_WIN_KEYS = {0xBF: Qt.Key.Key_Slash, 0xDB: Qt.Key.Key_BracketLeft,
             0xDD: Qt.Key.Key_BracketRight}


def layout_key(event):
    """The key as it stands on the keyboard, whatever layout is switched on.

    Qt's `key()` is what the layout makes of a key: on a Russian one, I is
    Ш and Shift with / is a comma, so the show's letters and the card of
    keys did nothing there. Windows says which key it was as well, and that
    is the same on every layout. Elsewhere the key is taken as Qt gives it.
    """
    key = event.key()
    if sys.platform != "win32":
        return key
    code = event.nativeVirtualKey()
    if 0x41 <= code <= 0x5A:
        return Qt.Key(code)
    return _WIN_KEYS.get(code, key)


def _tag(title: str) -> str:
    """A row's title as the test driver spells it: `Top 2` is `top2`."""
    return title.lower().replace(" ", "")


def _divider() -> QFrame:
    """A thin upright line between two groups on a bar."""
    line = QFrame()
    line.setFixedSize(1, 24)
    line.setStyleSheet(f"background:{theme.SEAM};")
    return line


def _see_through(widget: QWidget) -> QWidget:
    """A box that only holds others: the bar it stands on shows through.

    The sheet paints every widget in the panel's colour, which on a bar of
    another colour is a patch around whatever the box holds.
    """
    widget.setStyleSheet(f"#{widget.objectName()} {{ background:transparent; }}")
    return widget


def _pill(text: str, name: str, story: str,
          checkable: bool = True) -> QPushButton:
    """A switch in a bar of switches: flat until it is on, then the accent."""
    button = QPushButton(text)
    button.setObjectName(name)
    button.setProperty("pill", True)
    button.setCheckable(checkable)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setToolTip(story)
    return button


# How tall every control on a bar is: one height, so a bar reads as one row.
CONTROL = 30


def _even(layout, tall: int = CONTROL) -> None:
    """Every control on a line at one height -- fields, lists, buttons."""
    for index in range(layout.count()):
        widget = layout.itemAt(index).widget()
        if widget is None or isinstance(widget, QLabel):
            continue
        if widget.property("tab") or widget.property("segment"):
            continue
        if (isinstance(widget, (QPushButton, QToolButton, QComboBox, QSpinBox,
                                QLineEdit))
                or widget.property("field")):
            widget.setFixedHeight(tall)


# What is laid over the picture stands on this: dark enough to read over a
# white frame, thin enough that the picture is still there under it.
OVERLAY_BG = "rgba(20,21,24,219)"
# The one light button, Play, has its picture in this.
PLAY_INK = "#111111"


class DependencyDialog(QDialog):
    """What this machine has, and an offer to fetch what it has not.

    Shown once, on the first run, and after that only when something needed
    has gone. Everything Python is inside the executable; ffmpeg is not,
    because it is large and its licence makes shipping a copy inside someone
    else's binary a question better left alone. So it is looked for, and
    offered.
    """

    def __init__(self, found, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Что есть на этой машине"))
        self.setMinimumWidth(700)
        self.job = None

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        intro = QLabel(
            tr("Проверяется один раз, при первом запуске. Ничего не "
               "устанавливается и не прописывается в PATH: скачанное ложится в "
               "папку рядом с программой, и удалить её — значит отменить всё."))
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(16)
        self.grid.setVerticalSpacing(8)
        self.grid.setColumnMinimumWidth(1, 70)
        self.grid.setColumnStretch(2, 1)
        layout.addLayout(self.grid)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.note = QLabel()
        self.note.setObjectName("qa_checks_note")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)

        buttons = QHBoxLayout()
        self.get_button = QPushButton()
        self.get_button.setObjectName("qa_checks_get")
        self.get_button.setIcon(icon("download"))
        self.get_button.clicked.connect(self._start_download)
        buttons.addWidget(self.get_button)
        buttons.addStretch(1)
        self.close_button = QPushButton(tr("Продолжить"))
        self.close_button.setObjectName("qa_checks_close")
        self.close_button.setDefault(True)
        self.close_button.clicked.connect(self.accept)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

        self._show(found)

    # -- the list ------------------------------------------------------------

    # What each check is called on the screen. The log keeps the English, and
    # so do the names the tests find each line by.
    CALLED = {"GPU": "Видеокарта", "Compressed textures": "Сжатые текстуры",
              "ffmpeg": "ffmpeg", "ffmpeg with hap": "ffmpeg с Hap"}

    def _show(self, found) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

        for row, item in enumerate(found):
            name = QLabel(tr(self.CALLED.get(item.name, item.name)))
            name.setFont(QFont("", -1, QFont.Weight.Bold))
            if item.ok:
                mark, colour = tr("есть"), theme.TEXT
            elif item.required:
                mark, colour = tr("НЕТ — нужно"), theme.ERROR
            else:
                mark, colour = tr("нет"), theme.WARN
            status = QLabel(mark)
            status.setObjectName(
                "qa_check_" + item.name.lower().replace(" ", "_"))
            status.setStyleSheet(f"color:{colour};")
            detail = QLabel(item.detail)
            detail.setWordWrap(True)
            detail.setStyleSheet(f"color:{theme.QUIET};")
            for column, widget in enumerate((name, status, detail)):
                self.grid.addWidget(widget, row, column)

        wanted = next((item for item in found
                       if not item.ok and item.fixable), None)
        self.get_button.setVisible(wanted is not None)
        if wanted is not None:
            self.get_button.setText(
                tr("Скачать {0} ({1} МБ)",
                   tr(self.CALLED.get(wanted.name, wanted.name)),
                   depends.download_size_mb()))

        stopped = [tr(self.CALLED.get(i.name, i.name))
                   for i in found if i.required and not i.ok]
        limping = [tr(self.CALLED.get(i.name, i.name))
                   for i in found if not i.required and not i.ok]
        if stopped:
            self._note(tr("На этой машине вьювер работать не сможет: нет {0}.",
                          ', '.join(stopped)), "error")
        elif limping:
            says = [tr("без {0} {1}",
                       tr(self.CALLED.get(item.name, item.name)),
                       item.when_absent)
                    for item in found
                    if not item.required and not item.ok and item.when_absent]
            spoken = "; ".join(says)
            self._note(tr("Смотреть можно — всё нужное для этого есть. ")
                       + (spoken[:1].upper() + spoken[1:] + "." if says
                          else tr("Нет: {0}.", ', '.join(limping))), "warn")
        else:
            self._note(tr("Всё на месте."))

    def _note(self, text: str, level: str = "") -> None:
        colours = {"error": f"color:{theme.ERROR};",
                   "warn": f"color:{theme.WARN};"}
        self.note.setText(text)
        self.note.setStyleSheet(colours.get(level, f"color:{theme.TEXT};"))

    # -- fetching ------------------------------------------------------------

    def _start_download(self) -> None:
        if self.job is not None:
            return
        url = depends.DOWNLOADS[sys.platform][0]
        self._note(tr("качаю с {0}…", url.split('/')[2]))
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.get_button.setEnabled(False)
        self.close_button.setEnabled(False)

        self.job = jobs.DownloadJob(self)
        self.job.progress.connect(self._on_progress)
        self.job.failed.connect(self._on_failed)
        self.job.finished_ok.connect(self._on_finished)
        self.job.start()

    def _on_progress(self, done: int, total: int) -> None:
        if total > 0:
            self.progress.setValue(int(100 * done / total))
        self.progress.setFormat(
            tr("{0:.0f} из {1:.0f} МБ", done / 1e6, total / 1e6) if total
            else tr("{0:.0f} МБ", done / 1e6))

    def _on_failed(self, message: str) -> None:
        self.job = None
        self.progress.setVisible(False)
        self.get_button.setEnabled(True)
        self.close_button.setEnabled(True)
        self._note(tr("Не скачалось: {0}", message), "error")

    def _on_finished(self, path: str) -> None:
        self.job = None
        self.progress.setVisible(False)
        self.get_button.setEnabled(True)
        self.close_button.setEnabled(True)
        self._show(depends.check())
        self._note(f"ready: {path}")

    def reject(self) -> None:  # noqa: D102 -- Esc must not orphan the download
        if self.job is not None:
            self.job.cancel()
        super().reject()


class Timeline(QSlider):
    """The transport's slider, with a mark where each file of a chain starts.

    A programme of seven blocks is one clip as far as the clock is concerned,
    and without these there is no telling from the window which block is on
    the screen. Drawn over the groove rather than with Qt's own tick marks:
    those go outside the widget, want a fixed interval, and cannot carry a
    name.
    """

    def __init__(self, orientation, parent=None) -> None:
        super().__init__(orientation, parent)
        self._marks: list = []          # (seconds, name)
        self._span = 0.0
        self._range = None              # (from, to) as parts of the whole
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # The handle is a line two pixels wide, as the redesign draws the
    # playhead, and a slider that moves only when its handle is caught is a
    # slider that mostly does not move. So the press is where the playhead
    # goes, and the drag carries it from there -- the way the show's ruler
    # has always worked.
    def _value_at(self, x: float) -> int:
        return QStyle.sliderValueFromPosition(
            self.minimum(), self.maximum(), int(round(x)) - 1,
            max(1, self.width() - 2))

    def mousePressEvent(self, event) -> None:  # noqa: N802 -- Qt naming
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self.setSliderDown(True)
        self.setSliderPosition(self._value_at(event.position().x()))
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self.isSliderDown():
            self.setSliderPosition(self._value_at(event.position().x()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self.isSliderDown():
            self.setSliderDown(False)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def set_range(self, part) -> None:
        """The part the render will write, when it is not the whole."""
        self._range = part
        self.update()

    def set_marks(self, marks, span: float = 0.0, title: str = "") -> None:
        """Where the marks go, (seconds, name) each, and what they are: a
        chain's joins, unless `title` says otherwise."""
        self._marks = list(marks or [])
        self._title = title
        if span:
            self._span = float(span)
        self.setToolTip(self._says())
        self.update()

    def set_span(self, span: float) -> None:
        """How long the whole timeline is, so a mark lands where it belongs."""
        self._span = float(span or 0.0)
        self.update()

    def _says(self) -> str:
        if not self._marks:
            return ""
        lines = [getattr(self, "_title", "") or tr("Цепочка:")]
        for at, name in self._marks:
            lines.append(tr("   {0:7.1f} с   {1}", at, name))
        return "\n".join(lines)

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt naming
        super().paintEvent(event)
        if self._range is not None:
            brush = QPainter(self)
            room = self.width() - 2
            left = 1 + round(self._range[0] * room)
            right = 1 + round(self._range[1] * room)
            live = QColor(theme.LIVE)
            live.setAlpha(60)
            middle = self.height() // 2
            brush.fillRect(left, middle - 6, max(2, right - left), 12, live)
            brush.setPen(QPen(QColor(theme.LIVE), 2))
            brush.drawLine(left, middle - 7, left, middle + 7)
            brush.drawLine(right, middle - 7, right, middle + 7)
            brush.end()
        if not self._marks or self._span <= 0:
            return
        brush = QPainter(self)
        pen = QPen(QColor(theme.WARN))
        pen.setWidth(1)
        brush.setPen(pen)
        # Along the groove the handle travels, which is the width less the
        # handle: a mark at the very end must not sit under the handle's own
        # overhang.
        room = self.width() - 2
        for at, _ in self._marks:
            part = max(0.0, min(1.0, at / self._span))
            x = 1 + round(part * room)
            brush.drawLine(x, self.height() // 2 - 6, x, self.height() // 2 + 6)
        brush.end()


class Row(QFrame):
    """One screen's file, as a card in the column of sources.

    One file per card, as before the timeline. Several files one after
    another, and the counts that repeat them, are what the show mode is for;
    here a card is the quick answer to "what does this look like on the
    building". What the card says of its file -- size, codec, rate, length --
    is set in the typewriter face so the cards read as a column; a card with
    nothing in it is a place to drop a file.
    """

    SAID = {"Top": "верхний экран", "Bottom": "нижний экран",
            "Lamels": "ламели", "Frame": "накладка", "Sound": "звук",
            "Kinetic": "моторы"}

    def __init__(self, title: str, screen: str, on_pick, on_drop,
                 overlay: bool = False, on_place=None, on_gain=None,
                 sound: bool = False, motors: bool = False) -> None:
        super().__init__()
        self.title = title
        self.screen = screen
        self.overlay = overlay
        self.sound = sound
        self.motors = motors
        self.on_drop = on_drop
        self.on_pick = on_pick
        self.on_gain = on_gain or (lambda _row: None)
        # What says this card's file again, in the language now chosen; set
        # when the file is described, and None while there is none.
        self.retell = None
        self.setAcceptDrops(True)
        # What the test driver knows this row and its widgets by. Six rows are
        # built from this one class, so every name carries the row's own.
        tag = _tag(title)
        self.setObjectName(f"qa_row_{tag}")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._quiet = (f"#qa_row_{tag} {{ background:{theme.CARD};"
                       f" border:1px solid {theme.CARD_EDGE}; border-radius:6px; }}")
        self._lit = (f"#qa_row_{tag} {{ background:{theme.ACCENT};"
                     f" border:1px solid {theme.LINE}; border-radius:6px; }}")
        self.setStyleSheet(self._quiet)

        whole = QVBoxLayout(self)
        whole.setContentsMargins(12, 7, 12, 8)
        whole.setSpacing(4)

        head = QHBoxLayout()
        head.setSpacing(8)
        mark = QLabel()
        mark.setPixmap(theme.cell(title, 8))
        mark.setFixedWidth(10)
        head.addWidget(mark)
        self.label = QLabel(title)
        self.label.setProperty("fixed_words", True)   # the screen's own name
        self.label.setFont(theme.ui(10, QFont.Weight.DemiBold))
        head.addWidget(self.label)
        said = QLabel(tr(self.SAID.get(title, "")))
        said.setStyleSheet(f"color:{theme.QUIET}; font-size:12px;")
        head.addWidget(said)
        head.addStretch(1)

        self.how = None
        if overlay:
            self.how = QComboBox()
            self.how.setObjectName(f"qa_how_{tag}")
            self.how.addItem(tr("Вписать"), "Fit")
            self.how.addItem(tr("Растянуть"), "Stretch")
            self.how.setFixedWidth(104)
            self.how.setToolTip(
                tr("«Вписать» сохраняет пропорции кадра и ставит его по центру, "
                   "а экран остаётся виден по бокам. «Растянуть» тянет кадр к "
                   "углам экрана, какой бы формы кадр ни был."))
            # Not a reload: the file has not changed, only where it sits, and
            # reloading would throw away the clock and start again from zero.
            self.how.currentIndexChanged.connect(lambda _: on_place())
            head.addWidget(self.how)

        browse = QPushButton(tr("Заменить"))
        browse.setObjectName(f"qa_browse_{tag}")
        browse.setProperty("link", True)
        browse.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        browse.setToolTip(tr("Выбрать файл для этой строки. Перетащить его на "
                             "карточку — то же самое."))
        browse.clicked.connect(lambda: on_pick(self))
        head.addWidget(browse)
        self.browse_button = browse

        self.clear_button = QPushButton("×")
        self.clear_button.setObjectName(f"qa_clear_{tag}")
        self.clear_button.setProperty("link", True)
        self.clear_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.clear_button.setToolTip(tr("Убрать файл из строки. Сам файл не "
                                        "трогается."))
        self.clear_button.setFixedWidth(18)
        self.clear_button.clicked.connect(self.clear)
        head.addWidget(self.clear_button)
        whole.addLayout(head)

        # The path, whole, in a field: what the rest of the viewer reads and a
        # session keeps. Never on show -- a path in a column this narrow is
        # its middle -- the card shows the file's name, and the path is in
        # the name's hover.
        self.field = QLineEdit()
        self.field.setObjectName(f"qa_path_{tag}")
        self.field.setAcceptDrops(False)     # the card handles it
        self.field.textChanged.connect(lambda _: self._shown())
        self.field.setVisible(False)
        self.file = QLabel()
        self.file.setObjectName(f"qa_file_{tag}")
        self.file.setStyleSheet("font-size:13px;")
        self.file.setTextFormat(Qt.TextFormat.PlainText)
        self.file.setSizePolicy(QSizePolicy.Policy.Ignored,
                                QSizePolicy.Policy.Preferred)
        whole.addWidget(self.file)

        self.note = QLabel()
        self.note.setObjectName(f"qa_note_{tag}")
        self.note.setFont(theme.mono(8.5))
        self.note.setStyleSheet(f"color:{theme.META};")
        self.note.setSizePolicy(QSizePolicy.Policy.Ignored,
                                QSizePolicy.Policy.Preferred)
        whole.addWidget(self.note)

        self.drop = QLabel(
            tr("Перетащите WAV или выберите файл") if sound
            else tr("Перетащите JSON моторов или выберите файл") if motors
            else tr("Перетащите ролик или картинку, или выберите файл"))
        self.drop.setObjectName(f"qa_drop_{tag}")
        self.drop.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop.setWordWrap(True)
        self.drop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.drop.setStyleSheet(
            f"QLabel {{ border:1px dashed #3a3d44; border-radius:4px; padding:8px;"
            f" color:{theme.QUIET}; font-size:12px; }}")
        self.drop.mousePressEvent = lambda _event: on_pick(self)
        whole.addWidget(self.drop)

        # By eye, on top of whatever the automatic match works out. A slider
        # rather than a number because this is a judgement, not a measurement,
        # and the useful move is nudging it while looking at the picture. The
        # motors have none: what they do is not a matter of taste.
        self.gain = None
        if not motors:
            line = QHBoxLayout()
            line.setSpacing(10)
            said = QLabel(tr("Громкость") if sound else tr("Яркость"))
            said.setFixedWidth(62)
            said.setStyleSheet(f"color:{theme.QUIET}; font-size:12px;")
            line.addWidget(said)
            self.gain = QSlider(Qt.Orientation.Horizontal)
            self.gain.setObjectName(f"qa_gain_{tag}")
            self.gain.setRange(0, 200)
            self.gain.setValue(100)
            self.gain.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            if sound:
                # Volume, and there is no such thing as louder than the file.
                self.gain.setRange(0, 100)
                self.gain.setToolTip(
                    tr("Громкость: от тишины до файла как он есть"))
            else:
                self.gain.setToolTip(
                    tr("Яркость этого экрана, на глаз. 1.00 оставляет её такой, "
                       "какой её делают геометрия и «Сравнять яркость». "
                       "Двойной щелчок по карточке возвращает обратно."))
            self.gain.valueChanged.connect(self._gain_moved)
            line.addWidget(self.gain, 1)
            self.gain_shown = QLabel("1.00")
            self.gain_shown.setObjectName(f"qa_gainvalue_{tag}")
            self.gain_shown.setFont(theme.mono(9))
            self.gain_shown.setFixedWidth(36)
            self.gain_shown.setAlignment(Qt.AlignmentFlag.AlignRight
                                         | Qt.AlignmentFlag.AlignVCenter)
            line.addWidget(self.gain_shown)
            whole.addLayout(line)
        self._shown()

    @property
    def multiplier(self) -> float:
        """What this row is turned up to. One, for a row with no slider."""
        return self.gain.value() / 100.0 if self.gain is not None else 1.0

    def _gain_moved(self, value: int) -> None:
        self.gain_shown.setText(f"{value / 100.0:.2f}")
        self.on_gain(self)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 -- Qt naming
        if self.gain is not None:
            self.gain.setValue(100)

    def clear(self) -> None:
        """Empty the field and reload, which takes this one off its screen."""
        if not self.field.text():
            return
        self.field.clear()
        self.note.clear()
        self.on_drop()

    def _shown(self) -> None:
        """A file, or a place to drop one."""
        path = self.field.text().strip()
        loaded = bool(path)
        self.file.setText(Path(path).name if loaded else "")
        self.file.setToolTip(path)
        self.file.setVisible(loaded)
        self.note.setVisible(loaded)
        self.drop.setVisible(not loaded)
        self.clear_button.setVisible(loaded)
        self.browse_button.setText(tr("Заменить") if loaded else tr("Выбрать"))

    # -- dropping ------------------------------------------------------------

    MOVIES = (".mov", ".mp4", ".m4v", ".mkv", ".avi")
    PICTURES = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".tga")
    SOUNDS = (".wav",)
    MOTORS = (".json",)

    def _movie_in(self, event) -> str:
        wanted = (Row.SOUNDS if self.sound else Row.MOTORS if self.motors
                  else Row.MOVIES + Row.PICTURES)
        for url in event.mimeData().urls():
            if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in wanted:
                return url.toLocalFile()
        return ""

    def dragEnterEvent(self, event) -> None:  # noqa: N802 -- Qt naming
        if event.mimeData().hasUrls() and self._movie_in(event):
            self.setStyleSheet(self._lit)
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls() and self._movie_in(event):
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self.setStyleSheet(self._quiet)

    def dropEvent(self, event) -> None:  # noqa: N802
        self.setStyleSheet(self._quiet)
        path = self._movie_in(event)
        if path:
            event.acceptProposedAction()
            self.field.setText(path)
            self._shown()
            self.on_drop()


class Viewer(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        # Before a single word is put on the window: see lang.py.
        lang.set_language(logfile.load_settings().get("language", "ru"))
        self.setWindowTitle(f"{APP_NAME}  -  {APP_VERSION}")
        self.resize(1500, 950)

        self.streams: list[player.Stream] = []
        self.screens: list[screen_gpu.Screen] = []
        self.held: list[player.Frame | None] = []
        self.feeding: list[str] = []
        self.frame_at: int | None = None    # the overlay's place in `streams`
        self.frame_on = ""                  # the screen it is laid over
        self.frame_covers = (1.0, 1.0)
        self.clock = player.Clock()
        self.drawn = 0
        self.draw_ms = 0.0

        # The session is written down after the controls have stopped moving.
        # Made here because everything below may ask for it.
        self._restoring = False
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.timeout.connect(self._write_settings)
        self._shown_at = time.perf_counter()
        self._shown_since = 0
        self.shown_fps = 0.0
        self.cover: dict[str, float] = {}
        self.gains: dict[str, tuple] = {}
        self.motors = None                 # the top screen's commands, if any
        self.cell_at = None                # where each of its 1500 cells sits
        self.cell_is = None                # and which (row, id) each one is
        self._moved_to = None
        self.player: sound.Player | None = None
        self.track: sound.Track | None = None
        self.link_ratio: float | None = None
        self._linking = False        # so the two do not push each other about

        # What the window is being used for: the quick look, or a show on a
        # timeline. A different question from `mode`, which is how the
        # building is drawn -- both are asked in the same window.
        self.level = "view"
        self.trix_path = ""
        self.show_open = None          # the show on the timeline, in Шоу
        self.show_view = timeline.ShowView()
        self.composers: dict = {}      # screen -> (Compositor, its tracks)
        self.show_motors = None        # kinetic.Placed, once built
        self.motors_job = None
        self._motors_for = 0           # which opening a motor job is for
        self.mix = None                # the show's sounds, added
        self._mix_file = None          # that mix, written out for a render
        self._show_was = 0.0           # where the playhead was, for the loops
        self._split_sizes: list = []
        self._keys_open = False
        # The editor's: the show's history, and its working file once it has
        # one. `ask_resume` is what asks whether to carry on with a draft --
        # a dialog, which the tests answer for themselves.
        self.history = drafts.History()
        self._history_for = None       # which draft the history is of
        self._took = False             # whether the change begun took a snapshot
        self.draft = None
        self.ask_resume = self._ask_resume
        self._show_source = ""         # trix | draft | rows
        self.layer_of: list = []       # which level each show track is
        self._wavs: dict = {}          # the show's sounds, read once
        self._motor_cache: dict = {}   # the show's motors, built once
        self._draft_timer = QTimer(self)
        self._draft_timer.setSingleShot(True)
        self._draft_timer.timeout.connect(self._save_draft)

        try:
            self.adapter, self.device = screen_gpu.make_device()
        except Exception as error:  # noqa: BLE001 -- the whole point is to say so
            self.adapter = self.device = None
            self.failure = str(error)
        else:
            self.failure = ""

        # The baked scene, if it has been made. Without it the viewer still
        # runs and shows the videos flat, which is what the prototype did
        # before there was any geometry at all.
        self.mesh = None             # the scene as geometry
        self.solid = None            # what draws that
        if self.device is not None:
            folder = logfile.bundled(BAKED) or (logfile.app_dir() / BAKED)
            try:
                self.mesh = scene3d.Scene(self.device, folder)
            except Exception as error:  # noqa: BLE001 -- said in the window
                logfile.write(f"no baked geometry in {folder}: {error}")

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Named, not ordered: the fields can be rearranged without the videos
        # quietly going to the wrong screens.
        self.rows = [Row(title, screen, self._pick, self._load,
                         on_gain=self._gains_changed)
                     for title, screen in (("Top", "Screen_Top"),
                                           ("Bottom", "Screen_Bottom"),
                                           ("Lamels", "Lamel_screen"))]
        # Not a screen of its own: a picture or a movie laid over the bottom
        # one, on top of whatever is playing there and using its own alpha.
        self.rows.append(Row("Frame", "Screen_Bottom", self._pick, self._load,
                             overlay=True, on_place=self._place_frame,
                             on_gain=self._gains_changed))
        # Not a screen either: one WAV under the whole thing, heard while
        # watching and written into the render.
        self.rows.append(Row("Sound", "", self._pick, self._load,
                             sound=True, on_gain=self._volume_changed))
        # The motors of the top screen. Not a picture at all: a JSON of
        # commands that moves the geometry the pictures are shown on.
        self.rows.append(Row("Kinetic", "", self._pick, self._load,
                             motors=True))
        # What is loaded, as a show: one file per screen, all from frame zero.
        # A show because that is what everything plays from now, so the quick
        # look and the timeline are one way of playing things and not two.
        # Not `self.show`, which would put a number where Qt keeps a method.
        self.show_now = None

        # Tying Top and Bottom together: at the foot of the sources, under
        # the two sliders it ties. In the show it is also on the screens'
        # column, as a second button that follows this one.
        self.linked = QPushButton(tr("Связать"))
        self.linked.setObjectName("qa_link")
        self.linked.setCheckable(True)
        self.linked.setProperty("link", True)
        self.linked.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.linked.setToolTip(
            tr("Связывает ползунки Top и Bottom в том отношении, в каком они "
               "стоят на момент включения. Выставьте каждый так, чтобы экраны "
               "читались одинаково, нажмите это — и дальше любой из ползунков "
               "поднимает и опускает оба, не теряя баланса. Если одному упереться "
               "в край, останавливаются оба."))
        self.linked.toggled.connect(self._link_changed)
        self.linked.toggled.connect(lambda _on: self._say_link())

        # The line along the top: the name, Просмотр or Шоу, how the building
        # is drawn, the layers, and the checks and the log.
        layout.addWidget(self._scene_controls())
        # The show's own line: which show, and opening another. Only in Шоу --
        # in the quick look it would be a line of the window given to nothing.
        self.show_bar = self._show_bar()
        layout.addWidget(self.show_bar)
        self.show_bar.setVisible(False)

        body = QWidget()
        body.setObjectName("qa_body")
        across = QHBoxLayout(body)
        across.setContentsMargins(0, 0, 0, 0)
        across.setSpacing(0)
        across.addWidget(self._sources_column())

        # On demand rather than always: a still picture redrawn sixty times a
        # second costs a laptop its battery and tells nobody anything. A frame
        # is asked for when something changes, and while a clip is playing.
        # The picture, with the show's columns beside it, over the show's
        # strips, with a boundary between them that is dragged. Built once and
        # around the canvas, before the canvas is handed to the card: a
        # surface belongs to the window it was made for, and moving the canvas
        # into another one afterwards is not a thing to find out about on
        # somebody else's machine. In Просмотр the columns and the strips are
        # simply not on show.
        self.split = QSplitter(Qt.Orientation.Vertical)
        self.split.setObjectName("qa_split")
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(1)
        upper = QWidget()
        upper.setObjectName("qa_upper")
        beside = QHBoxLayout(upper)
        beside.setContentsMargins(0, 0, 0, 0)
        beside.setSpacing(0)
        self.canvas = RenderCanvas(parent=upper, update_mode="ondemand",
                                   max_fps=60, vsync=True)
        self.canvas.setObjectName("qa_canvas")
        self.canvas.setMinimumHeight(420)
        self._on_card: dict = {}     # which frame each screen's texture holds
        self._dragging = None
        self._sliding = False        # this drag slides rather than swings
        self._waiting = 0            # frames drawn while a seek is answered
        self._rebake_overlays()
        self._full_screen_button()
        self._frame_line()
        self._keys_card()
        self._look_bar()
        # How far into the flat layout somebody is looking. One is the whole
        # of it, and the focus is which point of it sits in the middle.
        #
        # Zooming here moves the strips rather than cropping the picture, so
        # a strip can end up hanging off the edge of the canvas. wgpu takes
        # that: a viewport is a mapping rather than a boundary, and what
        # actually bounds a draw is the clip volume the rasteriser applies to
        # every primitive anyway -- which is the same reason a full-screen
        # triangle reaching to three in clip space is safe.
        #
        # Measured rather than assumed, twice over. A strip drawn twice the
        # width of the target came back matching the middle of the same strip
        # drawn to fit, to one part in 255; a scissor deliberately put out of
        # bounds, by way of a control, was refused outright. And nothing
        # spills past a strip's own rectangle at any zoom: an explicit scissor
        # made no difference to a single pixel, which is why there is not one.
        self.flat_zoom = 1.0
        self.flat_focus = (0.5, 0.5)
        # Threshold maps by the size they were built for, kept for as long as
        # the window is open, and built on a thread of their own.
        self.noise_maps = {}
        self.noise_job = None
        # Through rendercanvas rather than a Qt event filter: what is returned
        # here is a wrapper, and the mouse arrives at a child widget inside it,
        # so a filter on this object never sees a thing.
        self.canvas.add_event_handler(
            self._canvas_event, "wheel", "pointer_down", "pointer_move",
            "pointer_up", "double_click")
        beside.addWidget(self.canvas, 1)
        self.show_side = timeline.SidePane(self.show_view)
        beside.addWidget(self.show_side)
        self.split.addWidget(upper)
        self.show_pane = timeline.TimelinePane(self.show_view)
        self.split.addWidget(self.show_pane)
        self.split.setStretchFactor(0, 1)
        self.split.setStretchFactor(1, 0)
        self.show_side.setVisible(False)
        self.show_pane.setVisible(False)
        self.split.splitterMoved.connect(self._split_moved)
        self.show_view.jumped.connect(
            lambda frame: self._move(frame / showfile.FPS))
        self.show_view.looping_changed.connect(self._say_loop)
        self.show_view.about_to_change.connect(self._before_change)
        self.show_view.unchanged.connect(self._change_dropped)
        self.show_view.edited.connect(self._after_change)
        self.show_view.dropped.connect(self._drop_files)
        self.show_view.editing_changed.connect(self._editing_shown)
        self.show_view.range_wanted.connect(self._range_from_show)
        across.addWidget(self.split, 1)
        layout.addWidget(body, 1)

        # A widget rather than a bare row, so that in Шоу its buttons and its
        # grid can move up to stand beside the show's time, and come back.
        self.transport_bar = self._transport()
        layout.addWidget(self.transport_bar)

        self.export_bar = QWidget()
        self.export_bar.setObjectName("qa_render_bar")
        self.export_bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.export_bar.setStyleSheet(
            f"#qa_render_bar {{ background:{theme.PANEL};"
            f" border-top:1px solid {theme.SEAM}; }}")
        self.export_bar.setFixedHeight(60)
        self.export_bar.setLayout(self._export_controls())
        layout.addWidget(self.export_bar)

        self.rebake_bar = self._rebake_controls()
        layout.addWidget(self.rebake_bar)
        self.rebake_bar.setVisible(False)
        self._screens_column()

        # Everything whose position is worth carrying to the next session,
        # gathered in one place rather than scattered through the handlers
        # that already do something else with each of them. Here, once every
        # bar that owns one of these has been built.
        for row in self.rows:
            if row.gain is not None:
                row.gain.valueChanged.connect(lambda _: self._remember())
            if row.how is not None:
                row.how.currentIndexChanged.connect(lambda _: self._remember())
        for box in (self.matching, self.solid_top, self.linked):
            box.toggled.connect(lambda _: self._remember())
        for combo in (self.alpha, self.backing, self.sync, self.mode):
            combo.currentIndexChanged.connect(lambda _: self._remember())
        self.out_name.textChanged.connect(lambda _: self._remember())

        # The decoder's counts, file by file, over the status line, and
        # folded away to begin with: they are for when something stutters.
        self.stats_open = False
        self._dropped_seen = 0
        self._dropped_grew = 0.0
        self.stats = QLabel()
        self.stats.setObjectName("qa_stats")
        self.stats.setFont(theme.mono(8.5))
        self.stats.setStyleSheet(
            f"QLabel {{ color:{theme.QUIET}; background:{theme.SUNKEN};"
            f" border-top:1px solid {theme.SEAM}; padding:6px 16px; }}")
        self.stats.setTextFormat(Qt.TextFormat.RichText)
        self.stats.setSizePolicy(QSizePolicy.Policy.Ignored,
                                 QSizePolicy.Policy.Preferred)
        self.stats.setVisible(False)
        layout.addWidget(self.stats)
        layout.addWidget(self._status_bar())

        self.painter = None
        self.context = None
        if self.device is not None:
            self.context = self.canvas.get_context("wgpu")
            preferred = self.context.get_preferred_format(self.adapter)
            # Everything reaching the target is already display-encoded: HAP Q
            # decodes to gamma-encoded RGB, the elements were baked as PNG, the
            # calibration is an sRGB file. An -srgb target would encode all of
            # that a second time, which looks exactly like the screens being
            # too bright.
            self.format = preferred.replace("-srgb", "")
            if self.format != preferred:
                logfile.write(f"canvas: {preferred} asked for, {self.format} used "
                              f"so display values are not encoded twice")
            self.context.configure(device=self.device, format=self.format)
            self.painter = screen_gpu.Painter(self.device, self.format)
            if getattr(self.device, "decodes_blocks", False):
                logfile.write("this GPU has no texture-compression-bc; HAP "
                              "blocks are unpacked by a compute pass instead")
            if self.mesh is not None:
                self.solid = renderer3d.Renderer3D(self.mesh, self.format)
                logfile.write(f"baked geometry: {self.mesh.describe()}")
                # Before the measurement, so it sees one top screen and not
                # two standing 350 mm apart inside each other.
                self._pick_top()
                self._measure_screens()

            folder = logfile.bundled(BAKED) or (logfile.app_dir() / BAKED)
            for name in (self.mesh.screens if self.mesh else []):
                picture = folder / f"calibrate_{name}.png"
                if not picture.is_file():
                    continue
                if self.solid is not None:
                    self.solid.load_calibration(name, read_rgba(picture))
            self.canvas.request_draw(self._draw)
        else:
            self._say_failure()

        self._note_output()
        self._framing_changed()

        # Last, because it opens files: the framing and the output folder have
        # to be settled before anything is loaded into them.
        if self.device is not None:
            self._start_from_settings()

        ticker = QTimer(self)
        ticker.timeout.connect(self._show_stats)
        ticker.start(200)
        self._ticker = ticker

        # While something is playing there is a new frame to show sixty times
        # a second; the rest of the time nothing is asked for at all.
        beat = QTimer(self)
        beat.timeout.connect(self._beat)
        beat.start(16)
        self._beat_timer = beat

    def _level_switch(self) -> QFrame:
        """Просмотр or Шоу: one control of two halves, at the head of the top line.

        Two segments of one control rather than two buttons, because it is a
        choice between two, and it keeps its size and its place in both.
        """
        holder = QFrame()
        holder.setObjectName("qa_levels")
        holder.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        holder.setStyleSheet(f"#qa_levels {{ background:{theme.DEEP};"
                             f" border:1px solid {theme.SEAM}; border-radius:6px; }}")
        bar = QHBoxLayout(holder)
        bar.setContentsMargins(2, 2, 2, 2)
        bar.setSpacing(0)
        self.levels = QButtonGroup(self)
        self.levels.setExclusive(True)
        self.level_buttons = {}
        for key, text, story in (
                ("view", tr("Просмотр"),
                 tr("Быстрый просмотр: по файлу на карточку, все с нулевого "
                    "кадра. Положил, посмотрел на здании, отрендерил.")),
                ("show", tr("Шоу"),
                 tr("Шоу на таймлайне: клипы на своих кадрах, слои, фейды, лупы, "
                    "кью; правится в редакторе. Без открытого .trix показывает "
                    "карточки Просмотра как шоу."))):
            button = QPushButton(text)
            button.setObjectName(f"qa_level_{key}")
            button.setCheckable(True)
            button.setProperty("segment", True)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setToolTip(story)
            button.clicked.connect(lambda _=False, k=key: self._set_level(k))
            self.levels.addButton(button)
            self.level_buttons[key] = button
            bar.addWidget(button)
        self.level_buttons["view"].setChecked(True)
        return holder

    def _show_bar(self) -> QWidget:
        """The show's own line, under the top one in Шоу: which show, and the editor.

        Opening a show and starting a new one; the name, which is the show
        file's `project.name` and is typed into only in the editor, over what
        is in the show; the draft, as a pill, while there is one; and at the
        far end the editor's switch, with going back and forward through the
        changes, a cue, deleting and giving the draft up beside it.
        """
        holder = QWidget()
        holder.setObjectName("qa_show_bar")
        holder.setFixedHeight(48)
        holder.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        holder.setStyleSheet(f"#qa_show_bar {{ background:{theme.SHOWBAR};"
                             f" border-bottom:1px solid {theme.SEAM}; }}")
        bar = QHBoxLayout(holder)
        bar.setContentsMargins(16, 0, 16, 0)
        bar.setSpacing(12)

        def button(text, name, hint, act, checkable=False, into=True):
            one = QPushButton(text)
            one.setObjectName(name)
            one.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            one.setToolTip(hint)
            one.setCheckable(checkable)
            one.setSizePolicy(QSizePolicy.Policy.Fixed,
                              QSizePolicy.Policy.Fixed)
            one.clicked.connect(act)
            if into:
                bar.addWidget(one)
            return one

        self.open_show_button = button(
            tr("Открыть шоу…"), "qa_open_show",
            tr("Открыть .trix из редактора шоу. Файл только читается; ничего в "
               "него не пишется. Если у шоу есть черновик — спросит, продолжать "
               "ли его."), lambda: self._open_show())
        button(tr("Новое шоу"), "qa_new_show",
               tr("Пустое шоу на 22 минуты, сразу в редакторе: файлы бросаются "
                  "из проводника прямо на дорожки."), lambda: self._new_show())

        # The name over what is in the show: two lines, the name the larger.
        names = QWidget()
        names.setObjectName("qa_show_names")
        _see_through(names)
        stack = QVBoxLayout(names)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(0)
        self.project_name = QLineEdit()
        self.project_name.setObjectName("qa_project_name")
        self.project_name.setFrame(False)
        self.project_name.setPlaceholderText(tr("имя шоу"))
        self.project_name.setReadOnly(True)
        self.project_name.setFixedWidth(220)
        self.project_name.setStyleSheet(
            f"QLineEdit {{ font-family:{theme.UI_CSS}; font-size:13px;"
            f" font-weight:600; padding:0px 2px; }}")
        self.project_name.setToolTip(tr("Имя шоу — project.name в .trix. Правится "
                                        "в редакторе."))
        self.project_name.editingFinished.connect(self._renamed)
        stack.addWidget(self.project_name)
        self.project = QLabel()
        self.project.setObjectName("qa_project")
        self.project.setFont(theme.mono(8.5))
        self.project.setTextFormat(Qt.TextFormat.PlainText)
        self.project.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        # However long the list, it does not get to widen the window.
        self.project.setSizePolicy(QSizePolicy.Policy.Ignored,
                                   QSizePolicy.Policy.Preferred)
        stack.addWidget(self.project)
        bar.addWidget(names, 1)

        # The draft, while there is one: the work is not in the show file
        # yet, and that is the one thing about it worth a colour of its own.
        self.draft_pill = QLabel()
        self.draft_pill.setObjectName("qa_draft")
        self.draft_pill.setStyleSheet(
            f"QLabel {{ background:{theme.DRAFT_BG}; color:{theme.GOLD};"
            f" border-radius:11px; padding:3px 10px; font-size:12px; }}")
        self.draft_pill.setVisible(False)
        bar.addWidget(self.draft_pill)
        bar.addStretch(1)

        self.editor_only = [
            button("↶", "qa_undo", tr("Отменить (Ctrl+Z)"), lambda: self._undo()),
            button("↷", "qa_redo", tr("Вернуть (Ctrl+Y)"), lambda: self._redo()),
            button(tr("+ кью"), "qa_cue_add",
                   tr("Кью на кадре плейхеда, с тем же адресом, что у кью перед "
                      "ним. Universe, channel и value — справа."),
                   lambda: self.show_view.add_cue()),
            button(tr("Удалить"), "qa_delete", tr("Удалить выбранный клип (Delete)"),
                   lambda: self.show_view.delete_chosen()),
            button(tr("Вернуть файл"), "qa_revert",
                   tr("Бросить черновик и открыть .trix как он есть. Черновик не "
                      "стирается: уходит в drafts\\old."), lambda: self._revert()),
        ]
        for widget in self.editor_only[:2]:
            widget.setFixedWidth(34)
            widget.setStyleSheet("QPushButton { padding:4px 0px; "
                                 "font-size:14px; }")
        for widget in self.editor_only:
            widget.setVisible(False)
        self.editor_button = button(
            tr("✎ Редактор"), "qa_editor",
            tr("Отпереть шоу: клипы тащатся, поля справа пишут в клип, лупы "
               "рисуются, файлы бросаются на дорожки. Каждая правка сама "
               "пишется в черновик рядом с программой (drafts); сам .trix не "
               "трогается никогда."), lambda on: self._set_editing(on), True)
        _even(bar)
        return holder

    # -- the editor ------------------------------------------------------------

    def _set_editing(self, on: bool) -> None:
        self.show_view.set_editing(bool(on) and self.level == "show")

    def _editing_shown(self, on: bool) -> None:
        """What the editor being on or off looks like."""
        self.editor_button.blockSignals(True)
        self.editor_button.setChecked(on)
        self.editor_button.blockSignals(False)
        self.project_name.setReadOnly(not on)
        for widget in self.editor_only:
            widget.setVisible(on)
        self.keys_card.setText(timeline.keys_text("show", on))
        self._say_undo()
        self._lay_overlays()
        logfile.write(f"show: editor {'on' if on else 'off'}")
        self._remember()

    def _say_undo(self) -> None:
        back, ahead = self.history.back, self.history.ahead
        undo, redo = self.editor_only[0], self.editor_only[1]
        undo.setEnabled(bool(back))
        redo.setEnabled(bool(ahead))
        undo.setToolTip(tr("Отменить: {0} (Ctrl+Z)", back[-1][0]) if back
                        else tr("Нечего отменять"))
        redo.setToolTip(tr("Вернуть: {0} (Ctrl+Y)", ahead[-1][0]) if ahead
                        else tr("Нечего возвращать"))
        self.editor_only[4].setEnabled(
            self.draft is not None and bool(self.draft.source))

    def _before_change(self, label: str, key) -> None:
        """A change is coming: the show as it stands goes into the history."""
        if self.show_open is None:
            return
        self._took = self.history.before(self.show_open, label, key)

    def _change_dropped(self) -> None:
        """Begun and not made -- a click on a clip rather than a drag."""
        if self._took:
            self.history.forget_last()
        self._took = False

    def _after_change(self, what) -> None:
        """A change has been made: settled, played, and written down."""
        show = self.show_open
        if show is None:
            return
        self._took = False
        was = show.length
        drafts.settle(show)
        self._ensure_draft()
        self.draft.changes += 1
        self._replay(set(what), was)
        self._say_project(show)
        self._say_undo()
        self._draft_timer.start(800)

    def _replay(self, what: set, length_was: int | None = None) -> None:
        """Play what was touched again, and nothing else."""
        show = self.show_open
        if what & {"Top", "Bottom", "Lamels", "all"}:
            self._play_video()
        if what & {"Sound", "all"}:
            self._play_sound()
        if what & {"Kinetic", "all"}:
            self._play_motors()
        if length_was is not None and show.length != length_was:
            self.clock.duration = show.length / showfile.FPS
            self.show_view.axis.stretch(show.length)
            self._reset_range()
        if what & {"Bottom", "all"} or show.length != length_was:
            self._mark_full()
        self.show_view.changed.emit()
        self.touch()

    def _undo(self) -> None:
        self._through_history(self.history.undo, tr("отменено"))

    def _redo(self) -> None:
        self._through_history(self.history.redo, tr("возвращено"))

    def _through_history(self, step, how: str) -> None:
        if not self.show_view.editing or self.show_open is None:
            return
        was = self.show_open.length
        label = step(self.show_open)
        if label is None:
            self.show_view.say(tr("нечего отменять") if how == tr("отменено")
                               else tr("нечего возвращать"))
            return
        drafts.settle(self.show_open)
        self.show_view.reopen()
        self._ensure_draft()
        self.draft.changes += 1
        self._replay({"all"}, was)
        self._say_project(self.show_open)
        self._say_undo()
        self.show_view.say(f"{how}: {label}")
        self._draft_timer.start(800)

    def _renamed(self) -> None:
        show = self.show_open
        name = self.project_name.text().strip()
        if show is None or not self.show_view.editing or name == show.name:
            return
        if not self.show_view.begin(tr("имя шоу"), key="name"):
            return
        show.name = name
        self.show_view.done({"name"})

    def _ensure_draft(self) -> None:
        """The working file, begun at the first change."""
        if self.draft is not None:
            return
        source = self.trix_path if self._show_source == "trix" else ""
        where = drafts.path_for(logfile.app_dir(), source)
        if where.exists():
            # One that was not taken up when the file was opened: aside, not
            # over it.
            aside = drafts.Draft(where).put_aside()
            logfile.write(f"show: an older draft put aside as {aside}")
        self.draft = drafts.Draft(where, source,
                                  drafts.stamp(source) if source else {})
        self.draft.file_loops = list(self.show_view.file_loops)
        if not source and not self.show_open.name:
            self.show_open.name = tr("Новое шоу")
        self._history_for = str(where)
        logfile.write(f"show: draft begun at {where}")
        self._remember()

    def _save_draft(self) -> None:
        self._draft_timer.stop()
        if self.draft is None or self.show_open is None \
                or self._show_source not in ("draft", "trix", "rows"):
            return
        try:
            self.draft.save(self.show_open)
        except OSError as trouble:  # noqa: BLE001 -- said, and tried again
            logfile.write(f"show: the draft could not be written: {trouble}")
            self.show_view.say(tr("черновик не записался: {0}", trouble))

    def _flush_draft(self) -> None:
        if self._draft_timer.isActive():
            self._save_draft()

    def _ask_resume(self, found) -> str | None:
        """Carry on with the draft, open the file afresh, or neither."""
        said = (tr("У этого шоу есть черновик: правок {0}, последняя записана "
                   "{1}.", found.changes, found.saved or found.started))
        if found.source_changed():
            said += (tr("\n\nФайл шоу изменился после того, как черновик был "
                        "начат: черновик сделан на прежней версии файла."))
        said += (tr("\n\n«Открыть файл заново» не стирает черновик — он уходит "
                    "в drafts\\old."))
        box = QMessageBox(self)
        box.setWindowTitle(tr("Черновик"))
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(said)
        carry = box.addButton(tr("Продолжить черновик"),
                              QMessageBox.ButtonRole.AcceptRole)
        afresh = box.addButton(tr("Открыть файл заново"),
                               QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(tr("Отмена"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(carry)
        box.exec()
        chosen = box.clickedButton()
        return ("draft" if chosen is carry else "file" if chosen is afresh
                else None)

    def _new_show(self) -> None:
        """An empty show on a draft of its own, straight into the editor."""
        if self.job is not None:
            return
        self._flush_draft()
        show = showfile.Show(name=tr("Новое шоу"), length=showfile.LENGTH)
        where = drafts.path_for(logfile.app_dir(), "")
        self.draft = drafts.Draft(where)
        self.draft.save(show)
        self.trix_path = ""
        self.history.clear()
        self._history_for = str(where)
        logfile.write(f"show: a new show, drafted at {where}")
        if self.level == "show":
            self._load_show()
        else:
            self._set_level("show")
        self.show_view.set_editing(True)
        self._remember()

    def _revert(self) -> None:
        """Give the draft up and open the show file as it is."""
        if self.draft is None or not self.draft.source:
            return
        self._draft_timer.stop()
        aside = self.draft.put_aside()
        logfile.write(f"show: draft put aside as {aside}; the file reopened")
        self.trix_path = self.draft.source
        self.draft = None
        self.history.clear()
        self.show_view.set_editing(False)
        self._load_show()
        self.show_view.say(tr("черновик убран в drafts\\old\\{0}", Path(str(aside)).name))
        self._remember()

    def _drop_files(self, paths: list, row: str, level: int, frame: int) -> None:
        """Files from a folder onto a lane: clips, one after another from
        where they were let go."""
        show = self.show_open
        if show is None or not self.show_view.begin(tr("файлы на дорожку")):
            return
        at, made, trouble = int(frame), [], []
        for path in paths:
            try:
                tail = 0
                if row == "Sound":
                    got, kind = showfile.sound_frames(path), "audio"
                    if got is None:
                        raise showfile.ShowError(f"{Path(path).name} is not a WAV")
                elif row == "Kinetic":
                    got, tail = showfile.motor_frames(path)
                    kind = "kinetic"
                    if got is None:
                        raise showfile.ShowError(
                            f"{Path(path).name} is not a motor file")
                else:
                    got, kind = showfile.media_frames(path, strict=True), "video"
            except showfile.ShowError as error:
                trouble.append(str(error))
                continue
            clip = showfile.Clip(kind=kind, row=row, level=level,
                                 path=str(path), tx=at, frames=got or 0,
                                 tail=tail, ident=drafts.next_ident(show))
            show.clips.append(clip)
            made.append(clip)
            # The next one where this one stops showing; a picture has no
            # length, and is given five seconds before the next.
            at = (clip.last - clip.tail if clip.frames
                  else at + int(5 * showfile.FPS))
        if trouble:
            self.show_view.say("; ".join(trouble)[:160])
            logfile.write("show: not placed: " + "; ".join(trouble))
        if not made:
            self.show_view.cancel()
            return
        self.show_view.chosen = made[-1]
        logfile.write(f"show: {len(made)} placed on {row} L{level} from {frame}")
        self.show_view.done({row})

    def _set_level(self, level: str) -> None:
        """Into the quick look or into the show, each with its own content.

        Each keeps what it had. The cards are the quick look's and the show
        is the show's: going into Шоу and back leaves the cards as they were,
        whatever the show had on it, so nothing is lost either way round.
        """
        level = "show" if level == "show" else "view"
        if level == self.level:
            self.level_buttons[level].setChecked(True)
            return
        if self.job is not None:
            # Not while a render has the card: the screens it is writing
            # from would be taken away underneath it.
            self.level_buttons[self.level].setChecked(True)
            return
        if self.clock.playing:
            self._toggle()
        if level != "show":
            self._flush_draft()
            self.show_view.set_editing(False)
        self.level = level
        self.level_buttons[level].setChecked(True)
        showing = level == "show"
        self.sources.setVisible(not showing)
        self.show_side.setVisible(showing)
        self.show_pane.setVisible(showing)
        self.show_bar.setVisible(showing)
        self._move_controls(showing)
        self.keys_card.setText(timeline.keys_text(level))
        # The strips need their three hundred pixels, and the picture can
        # spare them: the boundary gives them back.
        self.canvas.setMinimumHeight(240 if showing else 420)
        for index in range(self.mode.count()):
            key = self.mode.itemText(index)
            if key not in SHOW_MODES:
                # Not offered at all, rather than offered grey.
                self.mode.set_offered(key, not showing)
        if (showing and self.mode.isEnabled()
                and self.mode.currentText() not in SHOW_MODES):
            self.mode.setCurrentText(PREVIEW)
        logfile.write(f"level: {'show' if showing else 'quick look'}")
        if showing:
            self._load_show()
            self._lay_split()
        else:
            self._load()
        self._lay_overlays()
        self._remember()

    def _move_controls(self, showing: bool) -> None:
        """The few controls both levels have, where each level keeps them.

        Moved rather than made twice, so there is one of each to be set and
        remembered. In Шоу the transport's buttons and its grid go up beside
        the show's time, and the match and the link go to the show's Экраны,
        under the sliders they are about; in Просмотр they come back.
        """
        header = self.show_pane.header
        if showing:
            header.insertWidget(0, self.transport_buttons)
            header.addWidget(self.sync_box)
            self.show_switches.insertWidget(0, self.matching)
            self.show_switches.insertWidget(1, self.linked)
        else:
            self._transport_line.insertWidget(0, self.transport_buttons)
            self._transport_line.addWidget(self.sync_box)
            self.look_line.insertWidget(0, self.matching)
            self._banner_line.addWidget(self.linked)
        self.transport_bar.setVisible(not showing)
        for widget in (self.transport_buttons, self.sync_box, self.linked):
            widget.setVisible(True)
        # Said outright rather than left to the layout's own showing, which
        # comes a turn later -- after the bar over the picture was measured.
        self.matching.setVisible(self.mode.currentText() != "ReBake")
        self._say_link()

    def _lay_split(self) -> None:
        """The strips at their height, or where somebody last dragged them."""
        if len(self._split_sizes) == 2 and min(self._split_sizes) > 0:
            self.split.setSizes(self._split_sizes)
            return
        whole = max(self.split.height(), 700)
        wanted = self.show_pane.wanted_height()
        self.split.setSizes([max(240, whole - wanted), wanted])

    def _split_moved(self, *_) -> None:
        if self.show_pane.isVisible():
            self._split_sizes = list(self.split.sizes())
            self._remember()

    def _open_show(self) -> None:
        start = (str(Path(self.trix_path).parent) if self.trix_path
                 else str(SHOW_FOLDER) if SHOW_FOLDER.exists() else "")
        chosen, _ = QFileDialog.getOpenFileName(
            self, tr("Открыть шоу"), start, tr("Шоу (*.trix);;Все файлы (*)"))
        if chosen:
            self.open_show_file(chosen)

    def open_show_file(self, path: str) -> None:
        """Open a show and go to it. Opening one is asking for the show mode.

        If the show has a draft, `ask_resume` is asked whether to carry on
        with it or open the file afresh -- afresh puts the draft aside, it
        does not delete it -- or to leave things as they are.
        """
        self._flush_draft()
        where = drafts.path_for(logfile.app_dir(), str(path))
        resume = None
        if where.exists():
            try:
                found, _ = drafts.Draft.load(where)
            except ValueError as error:
                logfile.write(f"show: {error}")
                found = None
            if found is not None:
                answer = self.ask_resume(found)
                if answer is None:
                    return
                if answer == "draft":
                    resume = found
                else:
                    aside = found.put_aside()
                    logfile.write(f"show: draft put aside as {aside}")
        self.trix_path = str(path)
        self.draft = resume
        if resume is None:
            self.history.clear()
            self._history_for = None
        if self.level == "show":
            self._load_show()
        else:
            self._set_level("show")
        self.show_view.set_editing(resume is not None)
        self._remember()

    def _rows_as_show(self):
        """The rows, as a show: a 0.3 chain laid out where there is one.

        A row's chain is used while the row still starts with the chain's
        first file -- that is what the quick look has been playing out of it.
        A row since given another file has left its chain behind.
        """
        aside = logfile.load_settings().get("chains_0_3") or {}
        rows = {}
        for row in self.rows:
            if row.overlay:
                continue              # a frame is not a thing a show has
            text = row.field.text().strip()
            if not text:
                continue
            chain = aside.get(row.title) or {}
            files = [str(one) for one in (chain.get("files") or [])
                     if str(one).strip()]
            if files and Path(files[0]) == Path(text):
                times = [int(one) for one in (chain.get("repeats") or [])]
                times += [1] * (len(files) - len(times))
                rows[row.title] = list(zip(files, times))
                over = sum(1 for one in times if one > 1)
                logfile.write(
                    f"show: {row.title} is the 0.3 chain of {len(files)}"
                    + (f", {over} of them played over and laid out as copies"
                       if over else ""))
            elif row.motors and len(kinetic.parts_beside(text)) > 1:
                rows[row.title] = [(str(one), 1)
                                   for one in kinetic.parts_beside(text)]
            else:
                rows[row.title] = [(text, 1)]
        return showfile.chained(rows)

    @staticmethod
    def _stop_readers(streams) -> None:
        """Every reader told first, and waited for on a thread of its own:
        each takes about sixty milliseconds to notice, and waited for one at
        a time they were a third of a second of the window standing still."""
        going = list(streams)
        for stream in going:
            asking = getattr(stream, "ask_to_stop", None)
            if asking is not None:
                asking()
        if going:
            threading.Thread(target=lambda: [one.stop() for one in going],
                             daemon=True).start()

    def _let_go_of_screens(self) -> None:
        """Everything that was playing, stopped and handed back."""
        self._stop_readers(self.streams)
        self.streams, self.screens, self.held = [], [], []
        self.layer_of = []
        self._on_card: dict = {}     # which frame each screen's texture holds
        self.feeding = []            # which baked screen each stream feeds
        self.frame_at = None         # which of them is the overlay, if any
        self.frame_on = ""
        self.frame_covers = (1.0, 1.0)
        self.composers = {}
        self._motors_for += 1        # a motor job still running is for nothing
        if self.motors_job is not None:
            self.motors_job.cancel()
            self.motors_job = None
        self.show_motors = None
        self.mix = None
        if self.solid is not None:
            self.solid.set_frame(None)
            # Everything off first, then back on for whatever loads below. A
            # row that has just been emptied has nothing left to say, so if
            # this is not done its last frame stays on the screen for good.
            self.solid.clear_all_videos()

    def _load_show(self) -> None:
        """The show on the timeline: its draft, the .trix, or the rows.

        A draft first, when there is one in hand -- it is the show as edited.
        Otherwise the show file that is open, read afresh, and otherwise the
        rows of the quick look as a show. Then it is played: see
        `_play_video`, `_play_sound` and `_play_motors`.
        """
        started = time.perf_counter()
        self._let_go_of_screens()
        self.motors = None
        if self.player is not None:
            self.player.stop()
        self.player, self.track = None, None
        self.clock.source = None
        if self.device is None:
            return

        show, trouble, file_loops = None, "", None
        if self.draft is not None:
            try:
                self.draft, show = drafts.Draft.load(self.draft.where)
                file_loops = self.draft.file_loops
                self._show_source = "draft"
                if self.draft.source:
                    self.trix_path = self.draft.source
            except ValueError as error:
                trouble = str(error)
                logfile.write(f"show: {error}")
                self.draft = None
        if show is None and self.trix_path:
            try:
                show = showfile.read(self.trix_path)
                self._show_source = "trix"
            except showfile.ShowError as error:
                trouble = str(error)
                logfile.write(f"show: {error}")
        if show is None:
            show = self._rows_as_show()
            self._show_source = "rows"
        mine = str(self.draft.where) if self.draft is not None else None
        if mine is None or mine != self._history_for:
            self.history.clear()
        self._history_for = mine
        self.show_open = show
        self.show_view.open(show, file_loops)
        self._say_project(show, trouble)

        self._play_video()
        self._play_sound()
        self._play_motors(fresh=True)

        self.clock.duration = show.length / showfile.FPS
        self.clock.move_to(0.0)
        self._show_was = 0.0
        self.show_view.set_frame(0.0)
        self._reset_range()
        self._mark_full()
        self._name_from_show(show)
        self._say_undo()
        self._show_stats()
        self.touch()
        logfile.write(f"show: {show.describe()}  {len(self.streams)} tracks on "
                      f"{len(self.composers)} screens, from the "
                      f"{self._show_source}, opened in "
                      f"{time.perf_counter() - started:.2f} s")
        for clip in show.missing():
            logfile.write(f"show: not on this machine: {clip.row} L{clip.level} "
                          f"at {clip.tx}: {clip.path}")

    def _play_video(self) -> None:
        """Every screen's tracks, from the show as it now stands.

        A Track a level, composed by adding into a texture of the screen's own
        size, and that texture is what the scene is given as already light.
        Played again after an edit, a level keeps the surface it had -- and
        the picture on it, until the new track sends one -- so moving a clip
        does not put the screen out for a frame.
        """
        show = self.show_open
        kept = {}
        for index, track in enumerate(self.streams):
            if index < len(self.layer_of):
                kept[(self.feeding[index], self.layer_of[index])] = (
                    self.screens[index], index in self._on_card)
        self._stop_readers(self.streams)
        self.streams, self.screens, self.held = [], [], []
        self.feeding, self.layer_of = [], []
        self._on_card = {}
        for title, name in SHOW_SCREENS:
            across, down = self._pixels(name)
            if min(across, down) < 2:
                continue
            members = []
            for level in show.levels(title):
                try:
                    track = player.Track(show.on(title, level),
                                         screen=(across, down))
                    if not track.clips:
                        continue
                    surface, carded = kept.get((name, level), (None, False))
                    if surface is None or not surface.fits(track.movie):
                        surface = screen_gpu.Screen(self.device, track.movie)
                        carded = False
                except Exception as error:  # noqa: BLE001 -- said in the log
                    logfile.write(f"show: {title} L{level}: {error}")
                    continue
                self.streams.append(track)
                self.screens.append(surface)
                self.held.append(None)
                self.feeding.append(name)
                self.layer_of.append(level)
                at = len(self.streams) - 1
                if carded:
                    self._on_card[at] = -1   # a picture, if not this frame's
                track.on_change = lambda _track, at=at: self._reshape_layer(at)
                members.append(at)
            composer = self.composers.get(name, (None, None))[0]
            if composer is None:
                composer = screen_gpu.Compositor(self.device, across, down)
                if self.solid is not None and name in self.solid.calibration:
                    self.solid.set_video(name, composer.texture,
                                         composer.texture, False, 3, (1.0, 1.0))
                    self.solid.set_video_opacity(1.0)
            self.composers[name] = (composer, members)
        self._gains_changed()

    def _wav(self, path: str):
        """A WAV of the show, read once while the show is open."""
        try:
            stamp = Path(path).stat().st_mtime_ns
        except OSError:
            return None
        key = (str(path), stamp)
        if key not in self._wavs:
            try:
                self._wavs[key] = sound.read_wav(path)
            except sound.SoundError as error:
                logfile.write(f"show: sound: {error}")
                self._wavs[key] = None
        return self._wavs[key]

    def _play_sound(self) -> None:
        """The show's sounds, added into one mix, which keeps the time."""
        show = self.show_open
        playing = self.player is not None and self.player.playing
        if self.player is not None:
            self.player.stop()
        self.player, self.mix = None, None
        self.clock.source = None
        pieces, wanted = [], set()
        for clip in show.clips:
            if clip.kind != "audio" or clip.missing:
                continue
            read = self._wav(clip.path)
            if read is not None:
                pieces.append((read, clip.tx / showfile.FPS, 1.0))
                wanted.add(str(clip.path))
        self._wavs = {key: one for key, one in self._wavs.items()
                      if key[0] in wanted}
        if not pieces:
            return
        try:
            self.mix = sound.Mix(pieces, show.length / showfile.FPS)
            self.player = sound.Player(self.mix)
        except Exception as error:  # noqa: BLE001 -- said in the log
            logfile.write(f"show: no sound: {error}")
            self.mix, self.player = None, None
            return
        self._volume_changed()
        self.clock.source = lambda: (self.player.played
                                     if self.player is not None
                                     and self.player.playing else None)
        self.player.move_to(self.clock.seconds)
        if playing and self.clock.playing:
            self.player.play()
        for note in self.mix.notes:
            logfile.write(f"show: sound: {note}")

    @staticmethod
    def _motor_key(clip) -> tuple:
        """What one file's motors are, to know them again by: the file, how
        far past its end it is sampled, and how it stood on the disk."""
        try:
            stamp = Path(clip.path).stat().st_mtime_ns
        except OSError:
            stamp = 0
        return (str(clip.path), int(clip.tail), stamp)

    def _play_motors(self, fresh: bool = False) -> None:
        """The show's motor files, each at its own frame.

        The motors of a file are built once, on a thread, and kept while the
        show is open -- and for the last show after it closes, so going into
        the quick look and back does not spend four seconds again. A file
        moved along the timeline is the same motors somewhere else.
        """
        show = self.show_open
        self._motors_for += 1
        if self.motors_job is not None:
            self.motors_job.cancel()
            self.motors_job = None
        moving = [one for one in show.clips
                  if one.kind == "kinetic" and not one.missing]
        if self.solid is None or self.mesh is None:
            return
        wanted = {self._motor_key(one): one for one in moving}
        if fresh:
            self._motor_cache = {key: one for key, one in
                                 self._motor_cache.items() if key in wanted}
        self._place_motors()
        missing = [(key, one.path, one.tail) for key, one in wanted.items()
                   if key not in self._motor_cache]
        if missing:
            ticket = self._motors_for
            self.motors_job = jobs.MotorsJob(missing, parent=self)
            self.motors_job.finished_ok.connect(
                lambda got, took, ticket=ticket: self._motors_built(
                    ticket, got, took))
            self.motors_job.start()

    def _place_motors(self) -> None:
        show = self.show_open
        placed = []
        for clip in show.clips:
            if clip.kind == "kinetic" and not clip.missing:
                motors = self._motor_cache.get(self._motor_key(clip))
                if motors is not None:
                    placed.append((clip.tx, motors))
        if placed and self.cell_at is None:
            self.cell_at = self.mesh.cell_middles(scene3d.KINETIC_SCREEN)
            self.cell_is = kinetic.cell_addresses(self.cell_at)
        self.show_motors = kinetic.Placed(placed) if placed else None
        self._moved_to = -1               # nothing is where it should be yet
        if self.show_motors is None and self.solid is not None:
            self.solid.rest_cells()
            self._moved_to = None
        self._pick_top()
        self.touch()

    def _say_project(self, show, trouble: str = "") -> None:
        """The name, what the show is under it, and the draft's pill."""
        self.project_name.blockSignals(True)
        self.project_name.setText(show.name)
        self.project_name.blockSignals(False)
        self.project_name.setCursorPosition(0)
        self.project_name.ensurePolished()
        wide = self.project_name.fontMetrics().horizontalAdvance(
            show.name or tr("имя шоу")) + 18
        self.project_name.setFixedWidth(max(160, min(560, wide)))
        if trouble:
            said = tr("{0}  —  показаны строки Просмотра", trouble)
            colour = theme.ERROR
        else:
            described = show.describe()
            said = (described[len(show.name):].strip()
                    if show.name and described.startswith(show.name)
                    else described.strip())
            if self._show_source == "rows" and self.draft is None:
                said = tr("строки Просмотра как шоу · ") + said
            colour = theme.WARN if show.missing() else theme.QUIET
        self.project.setStyleSheet(f"color:{colour};")
        self.project.setText(said)
        drafted = self.draft is not None and not trouble
        self.draft_pill.setVisible(drafted)
        if drafted:
            self.draft_pill.setText(tr("черновик · правок {0}", self.draft.changes))
            self.draft_pill.setToolTip(tr("черновик: {0}\nсам .trix не "
                                          "трогается", self.draft.where))
        self.project.setToolTip(
            (tr("черновик: {0}\n", self.draft.where) if self.draft else "")
            + (self.trix_path or tr("строки Просмотра")))

    def _name_from_show(self, show) -> None:
        """The render is called after the show, while the name is still ours."""
        if self.out_name.text().strip() != (self._auto_name or ""):
            return
        stem = self._safe_stem(
            show.name or (Path(self.trix_path).stem if self.trix_path else ""))
        if not stem:
            return
        _, suffix = self.format_choice.currentData()
        self._auto_name = f"{stem}_v1{suffix}"
        self.out_name.setText(self._auto_name)

    def _motors_built(self, ticket: int, got, took: float) -> None:
        if ticket != self._motors_for or self.level != "show":
            return                        # built for a show no longer open
        built, notes = got
        self.motors_job = None
        for note in notes:
            logfile.write(f"show: kinetic: {note}")
        self._motor_cache.update(built)
        self._place_motors()
        if self.show_motors is not None:
            logfile.write(f"show: {self.show_motors.describe()}, "
                          f"{len(built)} built in {took:.2f} s")

    @staticmethod
    def _safe_stem(name: str) -> str:
        return "".join(one if one.isalnum() or one in "-_." else "_"
                       for one in name).strip("._")



    def _reshape_layer(self, at: int) -> None:
        """A track of a show has reached a clip of another shape or codec.

        Only the surface: the scene is bound to the screen's composed texture,
        which does not change, and the composer finds the new planes itself.
        """
        if at >= len(self.screens) or at >= len(self.streams):
            return
        movie = self.streams[at].movie
        screen = self.screens[at]
        if movie is None or screen.fits(movie):
            return
        screen.adopt(movie)
        self._on_card.pop(at, None)
        logfile.write(f"show: a track reached {movie.width}x{movie.height} "
                      f"{movie.kind}; its surface was remade")

    def _compose(self, encoder, seconds: float, ready,
                 premultiplied: bool | None = None) -> None:
        """Every screen of a show made out of the layers on show this instant.

        A layer is on show where its track has a clip, faded as far as the
        clip says, and once `ready` says its surface holds a picture.

        In the window that is "the card has been sent a frame of it", not "a
        frame is held": a seek hands the held frames back, and asked the
        second way every scrub along the ruler put the screens out until the
        readers caught up -- the picture blinked. The quick look never did,
        because the scene draws a surface straight, and a surface keeps its
        last picture until it is given the next. Now so does this. A render
        asks the other way, because it has the exact frame or nothing.
        """
        if not self.composers:
            return
        if premultiplied is None:
            premultiplied = self.alpha_mode() == "premultiplied"
        frame = seconds * showfile.FPS
        for composer, members in self.composers.values():
            layers = []
            for index in members:
                if index >= len(self.streams) or not ready(index):
                    continue
                clip = self.streams[index].showing(frame)
                if clip is None:
                    continue
                level = clip.opacity_at(frame)
                if level > 0.0:
                    layers.append((self.screens[index], level))
            composer.compose(layers, premultiplied=premultiplied,
                             encoder=encoder)

    def _render_compose(self):
        """What a render calls to make a show's screens, or None."""
        if not self.composers:
            return None
        premultiplied = self.alpha_mode() == "premultiplied"
        return (lambda seconds, held, p=premultiplied: self._compose(
            None, seconds, lambda index, h=held: h[index] is not None, p))

    def _keys_card(self) -> None:
        """The keys and the mouse, over the picture's top left, when asked for."""
        self.keys_button = QPushButton("?", self.canvas)
        self.keys_button.setObjectName("qa_keys_button")
        self.keys_button.setFixedSize(26, 26)
        self.keys_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.keys_button.setCursor(Qt.CursorShape.PointingHandCursor)
        # No padding: the window's own twelve pixels a side leave a button
        # this small no room for its one character.
        self.keys_button.setStyleSheet(
            f"QPushButton {{ background:{OVERLAY_BG}; border:1px solid {theme.SEAM};"
            f" border-radius:13px; padding:0px; color:{theme.SECOND};"
            f" font-weight:600; }}"
            f" QPushButton:hover {{ background:{theme.RAISED}; color:#ffffff; }}")
        self.keys_button.setToolTip(tr("Клавиши и мышь (?)"))
        self.keys_button.clicked.connect(self._toggle_keys)
        self.keys_card = QLabel(timeline.keys_text("view"), self.canvas)
        self.keys_card.setObjectName("qa_keys")
        self.keys_card.setFont(theme.mono(8.5))
        self.keys_card.setTextFormat(Qt.TextFormat.PlainText)
        self._empty_card()
        self.keys_card.setStyleSheet(
            f"QLabel {{ background:rgba(20,21,24,240); color:{theme.SECOND};"
            f" border:1px solid {theme.SEAM}; border-radius:6px;"
            f" padding:10px 12px; }}")
        self.keys_card.setVisible(False)

    def _say_loop(self, on: bool) -> None:
        view = self.show_view
        here = view.loop_here() or (view.caught if on else view.let_go)
        where = f" {here[0]}..{here[1]}" if here else ""
        logfile.write(f"show: loop{where} {'holds' if on else 'let go'}")

    def _look_bar(self) -> None:
        """How the screens look, in one bar over the top right of the picture.

        Over the picture because that is what each of these changes, and in
        one bar because they are one question -- how is this being shown:
        the match, the top's own back, how the alpha is read, what is behind,
        the render's frame, tiling, the whole monitor, and back to the whole
        frame. Before, they were split between a bar of their own, a panel
        over the picture and the top line.
        """
        bar = QFrame(self.canvas)
        bar.setObjectName("qa_look")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        bar.setStyleSheet(f"#qa_look {{ background:{OVERLAY_BG};"
                          f" border:1px solid {theme.SEAM}; border-radius:6px; }}")
        line = QHBoxLayout(bar)
        line.setContentsMargins(6, 4, 6, 4)
        line.setSpacing(6)
        self.look_line = line
        self.look_seams = []

        def seam() -> QFrame:
            one = QFrame()
            one.setFixedSize(1, 16)
            one.setStyleSheet(f"background:{theme.EDGE};")
            self.look_seams.append(one)
            return one

        for widget in (self.matching, self.solid_top, seam(),
                       self.alpha_label, self.alpha, self.backing_label,
                       self.backing, seam(), self.frame_button,
                       self.tile_button, self.full_button, self.reset_button):
            line.addWidget(widget)
        self.look_bar = bar

    def _say_look(self) -> None:
        """Which of the bar's switches this mode has any use for.

        The frame where there is a render rectangle to mark: Preview and
        Inspection both write the file camera's frame. Tiling only in Flat,
        the one mode that draws strips rather than one picture.
        """
        mode = self.mode.currentText()
        self.frame_button.setVisible(mode in (PREVIEW, "Inspection"))
        self.tile_button.setVisible(mode == "Flat")
        self.look_seams[0].setVisible(mode != "ReBake")

    def _screens_column(self) -> None:
        """The show's Экраны: each screen's brightness and the sound's level.

        In Просмотр these are on the cards. The sliders here move the cards'
        own values -- which are what a session remembers -- so the two never
        disagree, and the link between Top and Bottom holds in both.
        """
        column = self.show_side.screens
        self.levels_sliders = {}
        self.levels_lines = {}
        for title, said in (("Top", "Top"), ("Bottom", "Bottom"),
                            ("Lamels", "Lamels"), ("Sound", tr("Звук"))):
            row = self.row_for(title)
            if row is None or row.gain is None:
                continue
            tag = _tag(title)
            line = QHBoxLayout()
            line.setSpacing(10)
            name = QLabel(said)
            name.setFixedWidth(50)
            slider = ResetSlider(Qt.Orientation.Horizontal)
            slider.setObjectName(f"qa_show_gain_{tag}")
            slider.setRange(row.gain.minimum(), row.gain.maximum())
            slider.setValue(row.gain.value())
            slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            slider.setToolTip(row.gain.toolTip())
            value = QLabel(f"{row.multiplier:.2f}")
            value.setObjectName(f"qa_show_gainvalue_{tag}")
            value.setFont(theme.mono(9))
            value.setFixedWidth(34)
            value.setAlignment(Qt.AlignmentFlag.AlignRight
                               | Qt.AlignmentFlag.AlignVCenter)
            slider.valueChanged.connect(row.gain.setValue)
            row.gain.valueChanged.connect(
                lambda amount, s=slider, v=value: (
                    s.blockSignals(True), s.setValue(amount),
                    s.blockSignals(False), v.setText(f"{amount / 100:.2f}")))
            line.addWidget(name)
            line.addWidget(slider, 1)
            line.addWidget(value)
            column.addLayout(line)
            self.levels_sliders[title] = slider
            self.levels_lines[title] = (name, slider, value)
        # The match and the link stand here in Шоу, under the sliders they are
        # about; `_move_controls` brings them and takes them back.
        self.show_switches = QHBoxLayout()
        self.show_switches.setSpacing(6)
        self.show_switches.addStretch(1)
        column.addSpacing(2)
        column.addLayout(self.show_switches)

    SOURCES_WIDE = 340
    SOURCES_NARROW = 40

    def _sources_column(self) -> QWidget:
        """The files of the quick look, down the left: a card for each.

        A column rather than rows over the picture: six rows across the top
        were a fifth of the picture's height, going to fields that are set
        once and then read. A card says what its file is in a line of its own
        and has its slider under it; one with nothing in it is a place to
        drop a file. Folded, the column is a strip of the six marks, lit for
        the ones that are loaded.
        """
        # Whether the cards are out, kept as a fact rather than asked of the
        # widget: `isVisible` is false for everything in a window that has
        # not been shown yet.
        self.sources_open = True
        column = QWidget()
        column.setObjectName("qa_sources")
        column.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        column.setStyleSheet(f"#qa_sources {{ background:{theme.PANEL};"
                             f" border-right:1px solid {theme.SEAM}; }}")
        column.setFixedWidth(self.SOURCES_WIDE)
        whole = QVBoxLayout(column)
        whole.setContentsMargins(0, 0, 0, 0)
        whole.setSpacing(0)

        head = QHBoxLayout()
        head.setSpacing(8)
        self.sources_head_line = head
        self.sources_head = QPushButton(tr("Источники"))
        self.sources_head.setObjectName("qa_sources_header")
        self.sources_head.setFlat(True)
        self.sources_head.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.sources_head.setCursor(Qt.CursorShape.PointingHandCursor)
        # Through a lambda, not straight at the method: `clicked` hands its
        # handler a bool, and that landed in `open_it`.
        self.sources_head.clicked.connect(lambda: self._fold_sources())
        head.addWidget(self.sources_head, 1)
        self.sources_count = QLabel()
        self.sources_count.setObjectName("qa_sources_count")
        self.sources_count.setStyleSheet(f"color:{theme.QUIET}; font-size:12px;")
        head.addWidget(self.sources_count)
        whole.addLayout(head)

        self.sources_marks = QWidget()
        self.sources_marks.setObjectName("qa_sources_marks")
        marks = QVBoxLayout(self.sources_marks)
        marks.setContentsMargins(0, 6, 0, 0)
        marks.setSpacing(12)
        self.source_marks = []
        for _row in self.rows:
            mark = QLabel()
            mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
            marks.addWidget(mark)
            self.source_marks.append(mark)
        marks.addStretch(1)
        self.sources_marks.setVisible(False)
        whole.addWidget(self.sources_marks)

        self.sources_body = QWidget()
        self.sources_body.setObjectName("qa_sources_body")
        self.source_rows = QVBoxLayout(self.sources_body)
        self.source_rows.setContentsMargins(10, 0, 10, 8)
        self.source_rows.setSpacing(5)
        for row in self.rows:
            self.source_rows.addWidget(row)
        self.source_rows.addStretch(1)
        # Scrolled rather than let set the window's height: six cards are
        # taller than a laptop's picture wants to give up.
        self.sources_scroll = QScrollArea()
        self.sources_scroll.setObjectName("qa_sources_scroll")
        self.sources_scroll.setWidget(self.sources_body)
        self.sources_scroll.setWidgetResizable(True)
        self.sources_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.sources_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        whole.addWidget(self.sources_scroll, 1)

        # The link at the foot, under the two cards whose sliders it ties.
        self.link_banner = QWidget()
        self.link_banner.setObjectName("qa_link_holder")
        around = QVBoxLayout(self.link_banner)
        around.setContentsMargins(10, 0, 10, 12)
        self.link_frame = QFrame()
        self.link_frame.setObjectName("qa_link_banner")
        self.link_frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._banner_line = QHBoxLayout(self.link_frame)
        self._banner_line.setContentsMargins(12, 7, 10, 7)
        self._banner_line.setSpacing(8)
        self.link_said = QLabel()
        self.link_said.setObjectName("qa_link_said")
        self._banner_line.addWidget(self.link_said, 1)
        self._banner_line.addWidget(self.linked)
        around.addWidget(self.link_frame)
        whole.addWidget(self.link_banner)

        self.sources = column
        self._lay_sources()
        self._say_link()
        return column

    def _lay_sources(self) -> None:
        """The column out with its cards, or folded to its marks."""
        on = self.sources_open
        self.sources_scroll.setVisible(on)
        self.link_banner.setVisible(on)
        self.sources_count.setVisible(on)
        self.sources_marks.setVisible(not on)
        self.sources_head_line.setContentsMargins(
            *((16, 14, 16, 10) if on else (0, 12, 0, 4)))
        self.sources_head.setStyleSheet(
            "QPushButton { border:none; background:transparent; padding:0px;"
            f" font-size:14px; font-weight:600; color:{theme.TEXT};"
            f" text-align:{'left' if on else 'center'}; }}"
            f" QPushButton:hover {{ color:{theme.LINE}; }}")
        self.sources.setFixedWidth(self.SOURCES_WIDE if on
                                   else self.SOURCES_NARROW)

    def _status_bar(self) -> QWidget:
        """The line along the foot of the window.

        The card and how fast it is drawing, how many files are being read
        and whether any frames were thrown away, what the render or the
        snapshot last said, and the decoder's counts, folded, at the far end.
        """
        holder = QWidget()
        holder.setObjectName("qa_status_bar")
        holder.setFixedHeight(28)
        holder.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        holder.setStyleSheet(
            f"#qa_status_bar {{ background:{theme.SUNKEN};"
            f" border-top:1px solid {theme.SEAM}; }}"
            f" #qa_status_bar QLabel {{ color:{theme.QUIET}; }}"
            f" #qa_status_bar QPushButton {{ font-family:{theme.MONO_CSS};"
            f" font-size:11px; color:{theme.SECOND}; }}")
        line = QHBoxLayout(holder)
        line.setContentsMargins(16, 0, 16, 0)
        line.setSpacing(18)
        self.status = QLabel()
        self.status.setObjectName("qa_status")
        self.status.setTextFormat(Qt.TextFormat.RichText)
        self.status_pace = QLabel()
        self.status_pace.setObjectName("qa_status_pace")
        self.status_files = QLabel()
        self.status_files.setObjectName("qa_status_files")
        self.eta = QLabel()
        self.eta.setObjectName("qa_eta")
        self.eta.setAlignment(Qt.AlignmentFlag.AlignRight
                              | Qt.AlignmentFlag.AlignVCenter)
        for label in (self.status, self.status_pace, self.status_files,
                      self.eta):
            label.setFont(theme.mono(8.5))
        for label in (self.status_pace, self.eta):
            # However long, they do not get to widen the window.
            label.setSizePolicy(QSizePolicy.Policy.Ignored,
                                QSizePolicy.Policy.Preferred)
        line.addWidget(self.status)
        line.addWidget(self.status_pace, 2)
        line.addWidget(self.status_files)
        line.addWidget(self.eta, 3)
        self.stats_head = QPushButton(tr("Статистика декодера ▴"))
        self.stats_head.setObjectName("qa_stats_header")
        self.stats_head.setProperty("link", True)
        self.stats_head.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.stats_head.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stats_head.setToolTip(tr("Счётчики чтения по каждому файлу: сколько "
                                      "прочитано, выброшено, пропущено. Для "
                                      "случая, когда что-то дёргается. Состояние "
                                      "запоминается."))
        # Through a lambda: `clicked` would hand its bool to `open_it`.
        self.stats_head.clicked.connect(lambda: self._fold_stats())
        line.addWidget(self.stats_head)
        return holder

    def _say_failure(self) -> None:
        """No card: said where the card would have been named."""
        self.status.setText(html.escape(self.failure))
        self.status.setStyleSheet(f"color:{theme.ERROR};")

    def _say_link(self) -> None:
        """What the link says of itself, in the place it stands now."""
        if not hasattr(self, "link_said"):
            return
        on = self.linked.isChecked()
        showing = self.level == "show"
        self.linked.setText("Top ⇄ Bottom" if showing
                            else tr("Разъединить") if on else tr("Связать"))
        self.linked.setProperty("pill", showing)
        self.linked.setProperty("link", not showing)
        style = self.linked.style()
        style.unpolish(self.linked)
        style.polish(self.linked)
        self.link_said.setText(tr("Top и Bottom связаны") if on
                               else tr("Top и Bottom не связаны"))
        self.link_frame.setStyleSheet(
            f"#qa_link_banner {{ background:{theme.LINK_BG if on else theme.CARD};"
            f" border:1px solid {theme.LINK_BG if on else theme.CARD_EDGE};"
            f" border-radius:6px; }}"
            f" #qa_link_banner QLabel {{ color:{theme.LINK_FG if on else theme.QUIET};"
            f" font-size:12px; }}"
            f" #qa_link_banner QPushButton {{ color:{'#ffffff' if on else theme.LINE};"
            f" font-weight:500; font-size:12px; }}")

    def _say_language(self) -> None:
        for code, one in self.language_buttons.items():
            one.setChecked(code == lang.language())

    def _choose_language(self, code: str) -> None:
        """Another language, where the window stands: nothing is built again,
        nothing is opened again, and the picture goes on playing."""
        self._say_language()
        if code == lang.language():
            return
        lang.set_language(code)
        started = time.perf_counter()
        self._retranslate(code)
        logfile.write(f"language: {code}, the window's words turned in "
                      f"{(time.perf_counter() - started) * 1000:.0f} ms")
        self._remember()

    def _retranslate(self, to: str) -> None:
        """Every word on the window into `to`, in its place.

        Every text, placeholder, list line and tooltip that is words the
        window says is looked up in the dictionary and put back in the other
        language; what is not -- a file's name, a path, a number, a sentence
        with something put into it -- is left, and worked out again below.
        A widget can say it keeps its words (`fixed_words`): a card's title is
        the screen's name in both languages, and "Frame" and "Sound" would
        otherwise be taken for the English of Рамка and Звук.
        """
        def turned(text):
            return lang.other(text, to) if text else None

        for widget in [self] + self.findChildren(QWidget):
            if widget.property("fixed_words"):
                continue
            if isinstance(widget, (QAbstractButton, QLabel)):
                said = turned(widget.text())
                if said is not None:
                    widget.setText(said)
            if isinstance(widget, QLineEdit):
                said = turned(widget.placeholderText())
                if said is not None:
                    widget.setPlaceholderText(said)
            if isinstance(widget, QComboBox):
                for index in range(widget.count()):
                    said = turned(widget.itemText(index))
                    if said is not None:
                        widget.setItemText(index, said)
            said = turned(widget.toolTip())
            if said is not None:
                widget.setToolTip(said)
        for button, (says, story) in list(HINTS.items()):
            HINTS[button] = (turned(says) or says, turned(story) or story)
        self._retell()

    def _retell(self) -> None:
        """What the window works out as it goes, worked out again: in the
        language now chosen, without asking any file a second time."""
        for box in (self.sync, self.fps_choice):
            for index in range(box.count()):
                box.setItemText(index, tr("{0} к/с", int(box.itemData(index))))
        self._fill_sizes()
        self._say_language()
        self._say_link()
        self._say_sources()
        # The cards only in the quick look: in a show they are away, their
        # files let go of, and they say their files again on the way back.
        if self.level == "view":
            for row in self.rows:
                if row.retell is not None:
                    row.retell()
        self._say_undo()
        if self.show_open is not None:
            self._say_project(self.show_open)
        else:
            # The show's line, off show, still saying the last show there
            # was: said again the moment one is open.
            for label in (self.project, self.draft_pill):
                label.clear()
                label.setToolTip("")
        self.keys_card.setText(timeline.keys_text(self.level,
                                                  self.show_view.editing))
        self.full_button.setText(tr("Выйти  Esc") if self._full
                                 else tr("Во весь экран"))
        self._show_stats()
        self.show_view.changed.emit()
        self._lay_overlays()

    def _machine_dialog(self) -> None:
        """What this machine has of what is needed, asked for from the top line."""
        found = depends.check()
        logfile.write("machine check asked for: " + depends.summary())
        DependencyDialog(found, self).exec()

    def _empty_card(self) -> None:
        """What an empty quick look offers: to be given something to show."""
        card = QFrame(self.canvas)
        card.setObjectName("qa_empty")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setStyleSheet(
            f"QFrame#qa_empty {{ background:rgba(20,21,24,240);"
            f" border:1px solid {theme.SEAM}; border-radius:8px; }}"
            " QFrame#qa_empty QLabel { background:transparent; }")
        card.setFixedWidth(420)
        whole = QVBoxLayout(card)
        whole.setContentsMargins(20, 16, 20, 18)
        whole.setSpacing(10)
        title = QLabel(tr("Ничего не загружено"))
        title.setFont(theme.heading())
        whole.addWidget(title)
        said = QLabel(tr("Перетащите ролики на карточки слева или выберите их "
                         "здесь — по именам они разойдутся по экранам сами. "
                         "Шоу из редактора площадки открывается как шоу."))
        said.setWordWrap(True)
        said.setStyleSheet(f"color:{theme.SECOND};")
        whole.addWidget(said)
        line = QHBoxLayout()
        pick = QPushButton(tr("Выбрать файлы…"))
        pick.setObjectName("qa_empty_pick")
        pick.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        pick.setStyleSheet(f"QPushButton {{ background:{theme.ACCENT}; "
                           f"border-color:{theme.ACCENT}; color:#ffffff; }}")
        pick.clicked.connect(self._pick_many)
        line.addWidget(pick)
        show = QPushButton(tr("Открыть шоу…"))
        show.setObjectName("qa_empty_show")
        show.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        show.clicked.connect(self._open_show)
        line.addWidget(show)
        line.addStretch(1)
        whole.addLayout(line)
        card.setVisible(False)
        self.empty_card = card

    def _pick_many(self) -> None:
        chosen, _ = QFileDialog.getOpenFileNames(
            self, tr("Выбрать файлы для экранов"), "",
            tr("Ролики, картинки, звук и моторы (*.mov *.mp4 *.m4v *.mkv *.avi "
               "*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp *.tga *.wav *.json);;"
               "Все файлы (*)"))
        if chosen:
            self.put_files(chosen)

    def put_files(self, paths) -> dict:
        """Several files onto the rows they belong on, and load them."""
        taken = {row.title: row.field.text().strip() for row in self.rows}
        wanted = assign_files(paths, taken)
        for title, path in wanted.items():
            self.row_for(title).field.setText(path)
        if wanted:
            logfile.write("files put on rows: " + ", ".join(
                f"{title} {Path(path).name}" for title, path in wanted.items()))
            self._load()
        return wanted

    def _toggle_keys(self) -> None:
        self._keys_open = not self._keys_open
        self._lay_overlays()

    def check_machine(self) -> None:
        """The list on the first run, and after that only if something is gone.

        After the window is up rather than before it, so that a machine which
        cannot run this at all still shows why on the face of the application
        instead of a dialog over nothing.
        """
        found = depends.check()
        logfile.write(depends.summary())
        for item in found:
            logfile.write(f"  {item.name}: {'ok' if item.ok else 'MISSING'}  "
                          f"{item.detail}")

        settings = logfile.load_settings()
        gone = any(item.required and not item.ok for item in found)
        if settings.get("checked_machine") and not gone:
            return

        DependencyDialog(found, self).exec()
        settings = logfile.load_settings()
        settings["checked_machine"] = True
        logfile.save_settings(settings)

    def _beat(self) -> None:
        if self.clock.playing and self.job is None:
            self.canvas.request_draw()

    def touch(self) -> None:
        """Something changed; the picture is worth drawing once more."""
        if self.device is not None and self.job is None:
            self.canvas.request_draw()

    # -- what is shown -------------------------------------------------------

    def _scene_controls(self) -> QWidget:
        """The line along the top: the name, the level, how the building is
        drawn and its layers; the machine's check and the log at the far end.

        The switches about how the screens look are made here as well, and
        laid in the bar over the picture, which is what they change.
        """
        holder = QWidget()
        holder.setObjectName("qa_top_bar")
        holder.setFixedHeight(48)
        holder.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        holder.setStyleSheet(f"#qa_top_bar {{ background:{theme.BAR};"
                             f" border-bottom:1px solid {theme.SEAM}; }}")
        bar = QHBoxLayout(holder)
        bar.setContentsMargins(16, 0, 16, 0)
        bar.setSpacing(16)

        brand = QHBoxLayout()
        brand.setSpacing(8)
        name = QLabel(APP_NAME)
        name.setObjectName("qa_app_name")
        name.setStyleSheet("font-size:14px; font-weight:600;")
        brand.addWidget(name)
        version = QLabel(APP_VERSION)
        version.setFont(theme.mono(9))
        version.setStyleSheet(f"color:{theme.QUIET};")
        brand.addWidget(version)
        bar.addLayout(brand)
        bar.addWidget(self._level_switch())
        bar.addWidget(_divider())

        self.mode = ModeTabs([
            (PREVIEW, tr(MODE_LABEL[PREVIEW]),
             tr("Здание через камеру из файла, кадрированное так, как оно будет "
                "записано, — на нём и судят контент.")),
            ("Flat", tr(MODE_LABEL["Flat"]),
             tr("Экраны развёрнуты в полосы и сложены стопкой: каждый видно "
                "целиком. Рендер здесь пишет каждый экран отдельно.")),
            ("Inspection", tr(MODE_LABEL["Inspection"]),
             tr("Камера отпущена с этого кадра и летает вокруг здания: тянуть — "
                "вращать, колесо — ближе, правая кнопка или Shift — сдвинуть, "
                "двойной щелчок — вернуться.")),
            ("ReBake", tr(MODE_LABEL["ReBake"]),
             tr("Top и Bottom, каждая полоса разрезана посередине: слева файл, "
                "справа то, что из него сделает перепечка."))])
        self.mode.setObjectName("qa_mode")
        _see_through(self.mode)
        if self.mesh is None:
            self.mode.setCurrentIndex(1)
            self.mode.setEnabled(False)
            self.mode.setToolTip(tr("Рядом с приложением нет запечённой сцены"))
        self.mode.currentIndexChanged.connect(self._mode_changed)
        bar.addWidget(self.mode)

        # Everything that is about the building. Перепечка is about a source
        # file, and none of it applies there.
        self.scene_only = []

        # The pieces of the building, in a menu: they are set once a week,
        # and five boxes on the most visible line of the window were the
        # most visible thing in it.
        self.toggles = {}
        self.layers_button = QToolButton()
        self.layers_button.setObjectName("qa_layers")
        self.layers_button.setText(tr("Слои ▾"))
        self.layers_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup)
        self.layers_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.layers_button.setStyleSheet(
            f"QToolButton {{ color:{theme.SECOND}; padding:5px 12px; }}")
        self.layers_button.setToolTip(tr("Какие части здания рисовать"))
        menu = QMenu(self.layers_button)
        # One box for the top screen, not two. Its two geometries are the same
        # screen in two states, and which of them is drawn is decided by
        # whether there is a motor JSON, not by a box of its own.
        listed = [p.name for p in self.mesh.pieces
                  if p.name != scene3d.KINETIC_SCREEN] if self.mesh else []
        for name in listed:
            short = SHORT.get(name, name)
            box = QCheckBox(tr(LAYER_LABEL.get(short, short)))
            box.setObjectName("qa_layer_" + short.lower())
            box.setChecked(True)
            box.setToolTip(name)
            box.setStyleSheet("QCheckBox { padding:4px 10px; }")
            box.toggled.connect(lambda on, n=name: self._show_layer(n, on))
            holder_ = QWidgetAction(menu)
            holder_.setDefaultWidget(box)
            menu.addAction(holder_)
            self.toggles[name] = box
        self.layers_button.setMenu(menu)
        bar.addWidget(self.layers_button)
        self.scene_only.append(self.layers_button)
        bar.addStretch(1)

        # The language, as the redesign has it: RU / EN, the one in use lit.
        tongue = QWidget()
        tongue.setObjectName("qa_language")
        _see_through(tongue)
        line = QHBoxLayout(tongue)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(4)
        self.language_buttons = {}
        for code in lang.LANGUAGES:
            if self.language_buttons:
                slash = QLabel("/")
                slash.setStyleSheet(f"color:{theme.DIM}; font-size:12px;")
                line.addWidget(slash)
            one = QPushButton(code.upper())
            one.setObjectName(f"qa_lang_{code}")
            one.setProperty("link", True)
            one.setCheckable(True)
            one.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            one.setCursor(Qt.CursorShape.PointingHandCursor)
            one.setToolTip(LANGUAGE_NAMES[code])
            one.setProperty("fixed_words", True)    # "RU" is "RU" in English
            one.clicked.connect(lambda _=False, c=code: self._choose_language(c))
            line.addWidget(one)
            self.language_buttons[code] = one
        self._say_language()
        bar.addWidget(tongue)

        check = QPushButton(tr("Проверка машины"))
        check.setObjectName("qa_check_machine")
        check.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        check.setStyleSheet(f"QPushButton {{ color:{theme.SECOND}; }}")
        check.setToolTip(tr("Что есть на этой машине из нужного: видеокарта, "
                            "ffmpeg, звук. Там же — скачать ffmpeg, если его нет."))
        check.clicked.connect(self._machine_dialog)
        bar.addWidget(check)
        # The log is about the same thing the status line is: what the program
        # is doing. It is here, with the check, at the end of the top line.
        log = QPushButton(tr("Лог"))
        log.setObjectName("qa_log")
        log.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        log.setStyleSheet(f"QPushButton {{ color:{theme.SECOND}; }}")
        log.setToolTip(tr("Открыть папку, в которую пишется эта сессия"))
        log.clicked.connect(self._open_log)
        bar.addWidget(log)

        # How the screens look. Made here and laid in the bar over the picture.
        self.matching = _pill(
            tr("Сравнять яркость"), "qa_match",
            tr("Экраны устроены по-разному: верхний — раздельные соты, четверть "
               "его площади тёмная, нижний почти сплошной, поэтому одинаковый "
               "белый на верхнем читается тусклее. Это приводит более яркий к "
               "более тусклому, чтобы они совпадали на всех уровнях, включая "
               "максимум. Выключено — показывает так, как есть в геометрии."))
        self.matching.setChecked(True)
        self.matching.toggled.connect(self._matching_changed)
        self.scene_only.append(self.matching)

        self.solid_top = _pill(
            tr("Без изнанки верха"), "qa_solid_top",
            tr("Убирает дальнюю сторону верхнего экрана, чтобы его собственная "
               "изнанка не просвечивала сквозь передние соты. Работает и на "
               "движущемся, и на неподвижном. Выключено — показывает как есть, "
               "открытым с обеих сторон."))
        self.solid_top.toggled.connect(
            lambda on: (self.solid.cull(on) if self.solid else None, self.touch()))
        self.scene_only.append(self.solid_top)

        self.alpha_label = QLabel(tr("Альфа"))
        self.alpha_label.setStyleSheet(f"color:{theme.QUIET}; font-size:12px;")
        self.scene_only.append(self.alpha_label)
        self.alpha = QComboBox()
        self.alpha.setObjectName("qa_alpha")
        self.alpha.addItems(["Premultiplied", "Straight"])
        self.alpha.setFixedWidth(132)
        self.alpha.setToolTip(
            tr("Premultiplied кладёт цвет целиком: то, что осталось под "
               "прозрачной альфой, видно, а не умножено на неё, и пиксель, чей "
               "цвет ярче собственной альфы, вылетает. На нём и проверяют "
               "контент. Straight умножает цвет на альфу — так контент и "
               "задуман, и так его покажет стена."))
        self.alpha.currentIndexChanged.connect(self._alpha_changed)
        self.scene_only.append(self.alpha)

        self.backing_label = QLabel(tr("Фон"))
        self.backing_label.setStyleSheet(f"color:{theme.QUIET}; font-size:12px;")
        self.backing = QComboBox()
        self.backing.setObjectName("qa_behind")
        self.backing.addItem(tr("Калибровка"), "Calibration")
        self.backing.addItem(tr("Чёрный"), "Black")
        self.backing.setFixedWidth(118)
        self.backing.setToolTip(
            tr("Что показывают экраны там, где контент прозрачен или его нет"))
        self.backing.currentIndexChanged.connect(self._backing_changed)

        self.reset_button = _pill(
            "↺", "qa_reset_view",
            tr("Сбросить вид: назад к целому кадру. Двойной щелчок по картинке "
               "делает то же; колесо приближает, перетаскивание двигает."),
            checkable=False)
        self.reset_button.setStyleSheet("QPushButton { font-size:14px; "
                                        "padding:1px 7px; }")
        self.reset_button.clicked.connect(self.reset_view)
        _even(bar)
        return holder

    def _show_layer(self, name: str, on: bool) -> None:
        if self.solid is not None:
            self.solid.show(name, on)
            if name == scene3d.DEFAULT_TOP:
                self._pick_top()
        self.touch()

    def _pick_top(self) -> None:
        """Which of the two top geometries is drawn.

        The modelled one while there is nothing to move it, and the rigged one
        as soon as there is -- they stand at different radii and would show
        through each other if both were on. Both answer to the same box, and
        the video and the brightness they show it at are the same either way.
        """
        if self.solid is None or self.mesh is None:
            return
        box = self.toggles.get(scene3d.DEFAULT_TOP)
        wanted = box.isChecked() if box is not None else True
        moving = (self.motors is not None
                  or (self.level == "show" and self.show_motors is not None))
        self.solid.show(scene3d.DEFAULT_TOP, wanted and not moving)
        self.solid.show(scene3d.KINETIC_SCREEN, wanted and moving)

    # -- making the screens read alike ----------------------------------------

    MATCH = ("Screen_Top", "Screen_Bottom")

    def _measure_screens(self) -> None:
        """Work out how brightly each screen has to be turned up, or down.

        The screens are not built alike. The top one is a field of separated
        hexagons and leaves a quarter of its own area dark; the bottom one is
        very nearly a solid panel. Fed the same white they read 0.75 against
        1.00, which is why the top has always looked dimmer than it is.

        The correction goes downwards -- the brighter screen is brought to the
        dimmer -- because the other direction cannot work. Turning the top up
        by a third would push its white past what a pixel can hold, clip, and
        leave the average exactly where it started: a screen that covers three
        quarters of its area cannot be made to match one that covers all of
        it, only met in the middle.
        """
        self.cover = self.solid.measure_cover()
        for name, value in sorted(self.cover.items()):
            logfile.write(f"cover: {name} lights {value:.4f} of its own area")

        matched = [n for n in self.MATCH if self.cover.get(n, 0) > 0.01]
        if len(matched) < 2:
            self.gains = {}
            return
        dimmest = min(self.cover[n] for n in matched)
        # Per channel, though every measurement so far has come back grey:
        # this is coverage, and coverage has no colour. Kept as three numbers
        # so a screen that does have a cast would be caught rather than
        # averaged away.
        self.gains = {n: (dimmest / self.cover[n],) * 3 for n in matched}
        for name, gain in sorted(self.gains.items()):
            logfile.write(f"match: {name} x {gain[0]:.4f}")
        self._matching_changed()

    def _matching_changed(self, *_) -> None:
        self._gains_changed()

    # -- carrying a session over to the next one -------------------------------

    def _start_from_settings(self) -> None:
        """Open where the last session left off, or at the defaults.

        Order matters, and it is the same order in both cases. The sliders sit
        on top of the measured match, so the measurement has to have happened;
        Solid top reaches into the renderer, which does not exist while the
        controls are being built; and the link takes its ratio from wherever
        the two sliders are standing when it is ticked, so they have to be
        standing there already.
        """
        saved = logfile.load_settings()
        rows = saved.get("rows") or {}
        files = 0
        aside: dict = {}
        self._restoring = True
        try:
            for row in self.rows:
                kept = rows.get(row.title) or {}
                if row.gain is not None:
                    value = kept.get("gain")
                    if value is None:
                        value = START_GAIN.get(row.title, 1.0) * 100
                    row.gain.setValue(int(round(float(value))))
                if row.how is not None and kept.get("how"):
                    choose_saved(row.how, kept["how"])
                # A chain from 0.3: several files, or one played over. The
                # quick look plays the first of them; the whole of it is put
                # aside untouched for the show mode to open as it was.
                chain = [str(one) for one in (kept.get("files") or [])
                         if str(one).strip()]
                over = [int(one) for one in (kept.get("repeats") or [])]
                if len(chain) > 1 or any(one != 1 for one in over):
                    aside[row.title] = {"files": chain, "repeats": over}
                path = str(kept.get("file") or (chain[0] if chain else ""))
                if path:
                    row.field.setText(path)
                    files += 1
                    if not Path(path).exists():
                        logfile.write(f"{row.title}: {path} is no longer there")

            if saved.get("rebake"):
                choose_saved(self.rebake_what, saved["rebake"])
            if saved.get("rebake_below") is not None:
                self.rebake_threshold.setValue(int(saved["rebake_below"]))
            if aside and not saved.get("chains_0_3"):
                self._keep_chains(aside)
            if "sources_open" in saved:
                self.sources_open = bool(saved["sources_open"])
                self._lay_sources()
            if "stats_open" in saved:
                self.stats_open = bool(saved["stats_open"])
            if "frame_edge" in saved:
                self.frame_button.setChecked(bool(saved["frame_edge"]))
            if "tile_flat" in saved:
                self.tile_button.setChecked(bool(saved["tile_flat"]))
            if saved.get("rebake_format"):
                self.rebake_format.setCurrentText(str(saved["rebake_format"]))
            if saved.get("rebake_colour"):
                choose_saved(self.rebake_colour, saved["rebake_colour"])
            if saved.get("rebake_left"):
                self.rebake_left_alpha.setCurrentText(str(saved["rebake_left"]))
            if saved.get("rebake_right"):
                self.rebake_right_alpha.setCurrentText(str(saved["rebake_right"]))
            if saved.get("out_dir"):
                self.out_dir = Path(str(saved["out_dir"]))
                self._note_output()
            if saved.get("out_name"):
                self.out_name.setText(str(saved["out_name"]))
            # Only when the file has an opinion. Absent means a machine that
            # has never run this, and there the name is still the one the box
            # opened with -- which the sources are welcome to replace.
            if "out_auto" in saved:
                self._auto_name = saved["out_auto"]
            if saved.get("mode") and self.mode.isEnabled():
                was = str(saved["mode"])
                self.mode.setCurrentText(WAS_CALLED.get(was, was))
                self._mode_changed()
            if saved.get("sync"):
                choose_saved(self.sync, saved["sync"])
            self.clock.rate = float(self.sync.currentData() or 60.0)
            self.matching.setChecked(bool(saved.get("match", True)))
            self.solid_top.setChecked(bool(saved.get("solid_top",
                                                     START_SOLID_TOP)))
            self.linked.setChecked(bool(saved.get("linked", START_LINKED)))
            for box, key in ((self.alpha, "alpha"), (self.backing, "behind")):
                if saved.get(key):
                    choose_saved(box, saved[key])
        finally:
            self._restoring = False

        if saved.get("trix"):
            self.trix_path = str(saved["trix"])
            if not Path(self.trix_path).exists():
                logfile.write(f"show: {self.trix_path} is no longer there")
        split = saved.get("split") or []
        if len(split) == 2:
            self._split_sizes = [int(one) for one in split]
        if saved.get("draft") and Path(str(saved["draft"])).exists():
            self.draft = drafts.Draft(Path(str(saved["draft"])))
        if saved.get("level") == "show":
            logfile.write("carried over from the last session: the show mode")
            self._set_level("show")
            if saved.get("editing") and self.draft is not None:
                self.show_view.set_editing(True)
        # Only if there is something to open. `_load` on six empty fields is
        # harmless but it clears and rebuilds every screen for nothing.
        elif files:
            logfile.write(f"carried over from the last session: {files} files")
            self._load()
        # The line the folded panel shows has to agree with whether the rows
        # are up. The link needs nothing: it stands in the Bottom heading and
        # goes away with the panel because the panel is what holds it.
        self._say_sources()
        self._say_link()
        # Written once at the start as well, so the file says what the window
        # is actually showing even in a session where nothing was touched --
        # and so a first run leaves the defaults behind in a readable form.
        self._remember()

    def _settings_now(self) -> dict:
        """The whole of what is worth carrying over, as it stands."""
        rows = {}
        for row in self.rows:
            kept = {"file": row.field.text().strip()}
            if row.gain is not None:
                kept["gain"] = int(row.gain.value())
            if row.how is not None:
                kept["how"] = row.how.currentData()
            rows[row.title] = kept
        return {
            "rows": rows,
            "rebake": self.rebake_what.currentText(),
            "rebake_below": self.rebake_threshold.value(),
            "rebake_colour": self.rebake_colour.currentText(),
            "rebake_format": self.rebake_format.currentText(),
            "frame_edge": self.frame_button.isChecked(),
            "tile_flat": self.tile_button.isChecked(),
            "rebake_left": self.rebake_left_alpha.currentText(),
            "rebake_right": self.rebake_right_alpha.currentText(),
            "out_dir": str(self.out_dir),
            "out_name": self.out_name.text().strip(),
            # Whether that name is still one the sources are allowed to
            # replace, or one somebody chose.
            "out_auto": self._auto_name,
            "mode": self.mode.currentText(),
            "sync": self.sync.currentText(),
            "match": self.matching.isChecked(),
            "solid_top": self.solid_top.isChecked(),
            "linked": self.linked.isChecked(),
            "alpha": self.alpha.currentText(),
            "behind": self.backing.currentData(),
            # Whether the rows are on show. Remembered because on a small
            # screen the picture wants that room and the rows are set once.
            "sources_open": self.sources_open,
            "stats_open": self.stats_open,
            # The show mode, the show that was open in it and how much of the
            # window its strips were given.
            "level": self.level,
            "trix": self.trix_path,
            "split": list(self._split_sizes),
            # The working file, and whether the editor was on over it.
            "draft": str(self.draft.where) if self.draft is not None else "",
            "editing": bool(self.show_view.editing),
            # The window's language: see lang.py.
            "language": lang.language(),
        }

    def _remember(self, now: bool = False) -> None:
        """Write the session down, once the hand has come off the slider.

        Through a timer because a slider being dragged sends two hundred of
        these, and settings.json is not a thing to rewrite two hundred times
        to record where a thumb finally stopped.
        """
        if getattr(self, "_restoring", False):
            return
        if now:
            self._settle.stop()
            self._write_settings()
            return
        self._settle.start(600)

    def _write_settings(self) -> None:
        settings = logfile.load_settings()      # keeps checked_machine
        settings.update(self._settings_now())
        logfile.save_settings(settings)

    def _keep_chains(self, aside: dict) -> None:
        """Put 0.3's chains where the show mode will find them, untouched.

        The quick look plays one file a row and would otherwise write the
        rest of a chain out of the settings the first time it saved them --
        seven blocks of a programme, lined up by hand, gone on the next start.
        Written aside once, under their own key, which nothing here writes
        over; the show mode opens them as the clips they were.
        """
        kept = logfile.load_settings()
        kept["chains_0_3"] = aside
        logfile.save_settings(kept)
        for title, chain in aside.items():
            logfile.write(f"{title}: a chain of {len(chain['files'])} from 0.3 "
                          f"kept aside for the show mode; playing the first")

    def _link_changed(self, on: bool) -> None:
        """Remember the balance the two are at, so it can be kept.

        Taken when the box is ticked rather than fixed in advance: the whole
        point is that somebody sets the two by eye first and only then says
        "hold that".
        """
        if not on:
            self.link_ratio = None
            return
        top = max(1, self.row_for("Top").gain.value())
        bottom = max(1, self.row_for("Bottom").gain.value())
        self.link_ratio = bottom / top
        logfile.write(f"linked: bottom is {self.link_ratio:.3f} of top")

    def _follow_link(self, moved) -> None:
        """Move the other one with it, and stop both if either runs out.

        Pulling the one being dragged back is deliberate. The alternative is
        letting it go on while its partner sits against the end, which quietly
        throws away the balance the link exists to keep.
        """
        if self.link_ratio is None or self._linking:
            return
        pair = [self.row_for("Top"), self.row_for("Bottom")]
        if moved not in pair:
            return
        driver, other = (pair[0], pair[1]) if moved is pair[0] else (pair[1], pair[0])
        ratio = self.link_ratio if driver is pair[0] else 1.0 / self.link_ratio

        wanted = round(driver.gain.value() * ratio)
        lowest, highest = other.gain.minimum(), other.gain.maximum()
        held = min(highest, max(lowest, wanted))

        self._linking = True
        try:
            other.gain.setValue(held)
            if held != wanted and ratio:
                driver.gain.setValue(int(round(held / ratio)))
        finally:
            self._linking = False

    def _gains_changed(self, moved=None) -> None:
        """The measured match and the sliders, multiplied together.

        Two separate things with one answer: the match says what the geometry
        costs each screen, the slider says what somebody wants on top of that.
        Kept apart so turning the match off does not throw away a setting made
        by eye, and so the sliders read 1.00 when nothing has been asked for.
        """
        if moved is not None:
            self._follow_link(moved)
        if self.solid is None:
            return
        matching = self.matching.isChecked() if hasattr(self, "matching") else True
        by_screen = {}
        for row in self.rows:
            if row.overlay or row.sound or row.motors:
                continue
            base = (self.gains.get(row.screen, (1.0, 1.0, 1.0)) if matching
                    else (1.0, 1.0, 1.0))
            by_screen[row.screen] = tuple(v * row.multiplier for v in base)

        frame_row = next((r for r in self.rows if r.overlay), None)
        self.solid.set_gain(
            by_screen, frame_row.multiplier if frame_row else 1.0)

        # Flat draws each screen for itself, so the same numbers have to reach
        # the painter's own textures; the match does not apply there, because
        # side by side there is no geometry to make one dimmer than the next.
        for index, feeds in enumerate(self.feeding):
            if index >= len(self.screens):
                continue
            row = next((r for r in self.rows
                        if (r.overlay and index == self.frame_at)
                        or (not r.overlay and r.screen == feeds
                            and feeds)), None)
            if row is not None:
                self.screens[index].set_gain((row.multiplier,) * 3)
        for title, name in SHOW_SCREENS:
            if name in self.composers:
                self.composers[name][0].as_screen().set_gain(
                    (self.row_for(title).multiplier,) * 3)
        self.touch()

    def alpha_mode(self) -> str:
        return "premultiplied" if self.alpha.currentIndex() == 0 else "straight"

    def _alpha_changed(self, index: int) -> None:
        if self.solid is not None:
            self.solid.set_alpha_mode(index == 0)
        logfile.write(f"alpha read as {self.alpha_mode()}")
        self.touch()

    def _backing_changed(self, index: int) -> None:
        if self.solid is not None:
            self.solid.set_backing(index == 0)
        self.touch()

    # -- the strip of controls ---------------------------------------------

    def _transport_button(self, picture: str, says: str, story: str,
                          name: str, act, tall: int = 32) -> QPushButton:
        """One of the transport's buttons: dark ones, and Play the light one."""
        play = picture == "play"
        button = QPushButton()
        button.setObjectName(name)
        button.setProperty("play" if play else "transport", True)
        button.setIcon(theme.drawn_icon(picture, PLAY_INK if play else theme.TEXT))
        button.setIconSize(QSize(16, 16) if play else QSize(13, 13))
        button.setFixedSize(44 if play else 34, tall)
        # None of them takes the keyboard: a button that had it would answer
        # the space bar itself, and the space bar is Play.
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setToolTip("")          # ours, on our own timing, not Qt's
        HINTS[button] = (says, story)
        button.clicked.connect(act)
        return button

    TRANSPORT = (
        ("first", "В начало", "В начало.  Ctrl со стрелкой влево делает то же."),
        ("back", "На кадр назад",
         "На кадр назад по сетке просмотра.  Стрелка влево делает то же."),
        ("play", "Играть",
         "Играть или остановить.  Пробел делает то же — отовсюду, кроме "
         "поля, в котором печатают."),
        ("on", "На кадр вперёд",
         "На кадр вперёд по сетке просмотра.  Стрелка вправо делает то же."),
        ("last", "В конец", "В конец.  Ctrl со стрелкой вправо делает то же."))

    def _transport_acts(self) -> dict:
        return {"first": lambda: self._move(0.0),
                "back": lambda: self._step(-1),
                "play": self._toggle,
                "on": lambda: self._step(1),
                "last": lambda: self._move(self.clock.duration)}

    def _transport(self) -> QWidget:
        """Under the picture in Просмотр: the buttons, where the piece is, the
        slider along it, and the grid it is watched on.

        The buttons and the grid are widgets of their own so that in Шоу they
        can go up and stand beside the show's time, and come back.
        """
        holder = QWidget()
        holder.setObjectName("qa_transport")
        holder.setFixedHeight(64)
        holder.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        holder.setStyleSheet(f"#qa_transport {{ background:{theme.BAR};"
                             f" border-top:1px solid {theme.SEAM}; }}")
        bar = QHBoxLayout(holder)
        bar.setContentsMargins(16, 0, 16, 0)
        bar.setSpacing(14)
        self._transport_line = bar

        self.transport_buttons = QWidget()
        self.transport_buttons.setObjectName("qa_transport_buttons")
        _see_through(self.transport_buttons)
        buttons = QHBoxLayout(self.transport_buttons)
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(4)
        acts = self._transport_acts()
        for picture, says, story in self.TRANSPORT:
            says, story = tr(says), tr(story)
            button = self._transport_button(picture, says, story,
                                            f"qa_{picture}", acts[picture])
            buttons.addWidget(button)
            if picture == "play":
                self.play_button = button
        bar.addWidget(self.transport_buttons)

        # One reading of where the piece is: the timecode, and the frame out
        # of how many there are. Both on the grid it is watched on.
        self.time_label = QLabel("00:00:00:00")
        self.time_label.setObjectName("qa_time_label")
        self.time_label.setFont(theme.mono(15, bold=True))
        bar.addWidget(self.time_label)
        self.frame_label = QLabel(tr("кадр 0 из 0"))
        self.frame_label.setObjectName("qa_frame_label")
        self.frame_label.setFont(theme.mono(9))
        self.frame_label.setMinimumWidth(150)
        self.frame_label.setStyleSheet(f"color:{theme.QUIET};")
        self.frame_label.setToolTip(tr("Где стоит плейхед: кадр на сетке просмотра "
                                       "и сколько их всего"))
        bar.addWidget(self.frame_label)

        self.slider = Timeline(Qt.Orientation.Horizontal)
        self.slider.setObjectName("qa_timeline")
        self.slider.setRange(0, 1000)
        self.slider.setFixedHeight(32)
        self.slider.sliderMoved.connect(self._scrub)
        bar.addWidget(self.slider, 1)

        self.sync_box = QWidget()
        self.sync_box.setObjectName("qa_sync_box")
        _see_through(self.sync_box)
        watching = QHBoxLayout(self.sync_box)
        watching.setContentsMargins(0, 0, 0, 0)
        watching.setSpacing(6)
        watch = QLabel(tr("Смотреть по"))
        watch.setStyleSheet(f"color:{theme.QUIET}; font-size:12px;")
        watching.addWidget(watch)
        self.sync = QComboBox()
        self.sync.setObjectName("qa_sync")
        self.sync.setFixedWidth(84)
        for rate in (60, 30):
            self.sync.addItem(tr("{0} к/с", rate), float(rate))
        self.sync.setToolTip(
            tr("Сетка, по которой смотрят всю вещь. На неё разом ложится всё — "
               "экраны, счётчик кадров, моторы, — так что вещь на тридцати "
               "кадрах смотрится по кадру, а не выбирается дважды на каждый свой "
               "кадр. С какой частотой писать, выбирается в строке рендера."))
        self.sync.currentIndexChanged.connect(self._sync_changed)
        watching.addWidget(self.sync)
        _even(watching)
        bar.addWidget(self.sync_box)
        return holder

    WRITE_SIZE_HINT = (
        "Камера сужается до центрального окна такой формы: всё, что она видит "
        "сверху донизу, остаётся, отдаются только пустые бока. Из разрешения "
        "не теряется ничего.")

    def _export_controls(self) -> QHBoxLayout:
        """The render's line: its size, its frames, its rate and format, where
        it goes and what it is called, a snapshot, and Рендер in red at the
        end -- the one red thing in the window."""
        bar = QHBoxLayout()
        bar.setContentsMargins(16, 0, 16, 0)
        bar.setSpacing(10)

        def said(text: str) -> QLabel:
            label = QLabel(text)
            label.setStyleSheet(f"color:{theme.QUIET}; font-size:12px;")
            return label

        title = QLabel(tr("Рендер"))
        title.setStyleSheet("font-size:13px; font-weight:600;")
        bar.addWidget(title)
        bar.addSpacing(4)
        self.size_choice = QComboBox()
        self.size_choice.setObjectName("qa_size")
        self.size_choice.setFixedWidth(132)
        self.size_choice.setToolTip(tr(self.WRITE_SIZE_HINT))
        self._fill_sizes()
        self.size_choice.currentIndexChanged.connect(self._framing_changed)
        bar.addWidget(self.size_choice)

        # Which part of the piece goes out, in frames of the grid it is
        # watched on, so a range is read off the screen rather than worked
        # out. Shift+I and Shift+O set it from the playhead; «всё» puts it
        # back to the whole piece.
        bar.addWidget(said(tr("Кадры")))
        self.first_frame = QSpinBox()
        self.first_frame.setObjectName("qa_frame_first")
        self.last_frame = QSpinBox()
        self.last_frame.setObjectName("qa_frame_last")
        # Each tooltip one whole sentence, so switching the language finds it
        # in the dictionary as it stands.
        for box, tip in (
                (self.first_frame,
                 tr("Первый записываемый кадр. Считается так же, как счётчик "
                    "у плейхеда, по сетке просмотра. Shift+I и Shift+O ставят "
                    "начало и конец туда, где плейхед.")),
                (self.last_frame,
                 tr("Последний записываемый кадр, он сам включительно. "
                    "Считается так же, как счётчик у плейхеда, по сетке "
                    "просмотра. Shift+I и Shift+O ставят начало и конец туда, "
                    "где плейхед."))):
            box.setFixedWidth(76)
            box.setRange(0, 0)
            box.setToolTip(tip)
            box.setKeyboardTracking(False)
            box.valueChanged.connect(self._range_changed)
            box.valueChanged.connect(lambda _: self._say_range())
        bar.addWidget(self.first_frame)
        dash = QLabel("–")
        dash.setFixedWidth(8)
        bar.addWidget(dash)
        bar.addWidget(self.last_frame)
        self.range_all = QPushButton(tr("всё"))
        self.range_all.setObjectName("qa_range_all")
        self.range_all.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.range_all.setStyleSheet("QPushButton { padding:5px 8px; }")
        self.range_all.setToolTip(tr("Всю вещь целиком"))
        self.range_all.clicked.connect(self._reset_range)
        bar.addWidget(self.range_all)

        self.fps_choice = QComboBox()
        self.fps_choice.setObjectName("qa_fps")
        self.fps_choice.setFixedWidth(78)
        self.fps_choice.setToolTip(tr("С какой частотой писать файл"))
        for rate in (30, 60):
            self.fps_choice.addItem(tr("{0} к/с", rate), rate)
        bar.addWidget(self.fps_choice)

        self.format_choice = QComboBox()
        self.format_choice.setObjectName("qa_format")
        self.format_choice.setFixedWidth(136)
        self._fill_formats()
        self.format_choice.currentIndexChanged.connect(self._format_changed)
        bar.addWidget(self.format_choice)

        # Where it goes, as one field: the folder, quiet, and after it the
        # name, which is the part that gets typed.
        where = QFrame()
        where.setObjectName("qa_out_path")
        where.setProperty("field", True)
        where.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        where.setStyleSheet(f"#qa_out_path {{ background:{theme.SUNKEN};"
                            f" border:1px solid {theme.EDGE}; border-radius:4px; }}")
        inside = QHBoxLayout(where)
        inside.setContentsMargins(9, 0, 4, 0)
        inside.setSpacing(0)
        # Both halves are typed into: the folder, quiet until it is being
        # edited, and the name. It looks like one path and is written like
        # one -- a whole path pasted into the name goes to both.
        self.out_folder = QLineEdit()
        self.out_folder.setObjectName("qa_out_folder")
        self.out_folder.setFrame(False)
        self.out_folder.setStyleSheet(
            f"QLineEdit {{ background:transparent; border:none; padding:4px 0px;"
            f" color:{theme.QUIET}; }}"
            f" QLineEdit:focus {{ color:{theme.TEXT}; }}")
        self.out_folder.setToolTip(
            tr("Папка, в которую писать: впишите путь или выберите «Куда…». "
               "Папки, которой ещё нет, при записи будет создана."))
        # The folder gives way first: the name is what gets typed most.
        self.out_folder.setSizePolicy(QSizePolicy.Policy.Ignored,
                                      QSizePolicy.Policy.Fixed)
        self.out_folder.setMinimumWidth(60)
        self.out_folder.editingFinished.connect(self._folder_typed)
        inside.addWidget(self.out_folder, 2)
        self.out_name = QLineEdit("preview_v1.mp4")
        self.out_name.setObjectName("qa_out_name")
        self.out_name.setFrame(False)
        self.out_name.setStyleSheet("QLineEdit { background:transparent; "
                                    "border:none; padding:4px 0px; }")
        self.out_name.editingFinished.connect(self._name_typed)
        # The name this worked out for itself. While the box still holds it,
        # the sources may rename the render; the moment it holds something
        # else, somebody has decided and nothing here touches it again.
        self._auto_name = self.out_name.text()
        self.out_name.setToolTip(
            tr("Как будет называться файл. Расширение следует за форматом слева "
               "и подставляется, если его не написать. Загрузите Что-то_top и "
               "Что-то_bottom — и имя составится само."))
        self.out_name.setMinimumWidth(110)
        inside.addWidget(self.out_name, 3)
        bar.addWidget(where, 1)

        browse = labeled(QPushButton(), "", tr("Куда…"),
                         tr("Папка, в которую писать, и как назвать файл"),
                         name="qa_out_browse")
        browse.clicked.connect(self._pick_output)
        bar.addWidget(browse)

        self.bump_button = labeled(
            QPushButton(), "", "+1", tr("Следующая версия"),
            tr("Ничего никогда не перезаписывается; это находит следующее "
               "свободное имя: _v1 становится _v2."), name="qa_bump")
        self.bump_button.clicked.connect(self._bump_version)
        bar.addWidget(self.bump_button)

        snap = labeled(
            QPushButton(), "", tr("Снимок"), tr("Снимок кадра"),
            tr("Записать этот один кадр в PNG, рядом с тем, куда идёт видео. "
               "В Превью это та же картинка, что записал бы рендер, в выбранном "
               "размере; в Развертке — каждый экран отдельно, в его родном "
               "размере."), name="qa_snapshot")
        snap.clicked.connect(self._snapshot)
        bar.addWidget(snap)

        # These only while something is being written, or has just been.
        self.cancel_button = labeled(QPushButton(), "", tr("Стоп"),
                                     tr("Остановить рендер"),
                                     tr("Записанное к этому моменту выбрасывается."),
                                     name="qa_cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self._cancel_export)
        bar.addWidget(self.cancel_button)

        self.progress = QProgressBar()
        self.progress.setObjectName("qa_progress")
        self.progress.setFixedWidth(150)
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        bar.addWidget(self.progress)

        self.open_out = labeled(QPushButton(), "", tr("Открыть папку"),
                                tr("Открыть папку с записанным"), "",
                                name="qa_open_out")
        self.open_out.clicked.connect(self._open_out)
        self.open_out.setVisible(False)
        bar.addWidget(self.open_out)

        self.render_button = labeled(
            QPushButton(), "", tr("Рендер"), tr("Рендер"),
            tr("Записать весь диапазон, все экраны разом, в файл, названный "
               "слева. Вид сперва возвращается к целому кадру, так что "
               "записывается именно то, что в кадре."), name="qa_render")
        self.render_button.clicked.connect(self._start_export)
        bar.addWidget(self.render_button)

        # What gives way to Стоп and the bar while a file is being written:
        # the line keeps its width, and so does the window.
        self._idle_only = (browse, self.bump_button, snap, self.render_button)
        _even(bar)
        self.progress.setFixedHeight(8)
        self.out_dir = logfile.app_dir() / "OUT"
        self.job = None
        return bar

    # -- looking around inside the frame ---------------------------------------

    def inspecting(self) -> bool:
        return self.mode.currentText() == "Inspection"

    def _mode_changed(self, *_) -> None:
        """Preview and Flat keep the file's camera; Inspection lets it go."""
        rebaking = self.mode.currentText() == "ReBake"
        self._export_for_mode()
        self._show_overlays(rebaking)
        self._lay_overlays()
        for widget in getattr(self, "scene_only", ()):
            widget.setVisible(not rebaking)
        # Again, now that the bar over the picture has lost or regained the
        # switches this mode has no use for, so it is laid at its new width.
        self._lay_overlays()
        if hasattr(self, "rebake_bar"):
            self.rebake_bar.setVisible(rebaking)
            # The render row is about the building, and this mode is about a
            # source file. Leaving it up would offer a button that writes
            # something else entirely from what is on screen.
            self.export_bar.setVisible(not rebaking)
            # Off the moment the mode is left: the other two modes are for
            # judging the file as it is, and a screen still carrying a re-bake
            # would be quietly showing something that is not in it.
            if rebaking:
                # Straight away, so the right half is the re-bake from the
                # first frame drawn rather than after somebody touches
                # something. Where a threshold map has to be built first, the
                # note says so and this runs again the moment it lands.
                self._rebake_changed()
                self._offer_ffmpeg()
                self.touch()
            else:
                for index in range(min(len(self.feeding), len(self.screens))):
                    self.screens[index].set_rebake(rebake.OFF)
        if self.solid is not None:
            self.solid.fly(self.inspecting())
            if self.inspecting():
                # The shape it is being drawn into, if the canvas has been
                # given one yet -- restoring a session happens before the
                # window is laid out, and the canvas answers 1x1 until it is.
                # Every draw settles this again, so being early is the only
                # case that needs guarding.
                wide, tall = self.canvas.get_physical_size()
                if wide > 1 and tall > 1:
                    self.solid.free.aspect = wide / tall
                logfile.write(f"inspection: {self.solid.free.describe()}")
        self._dragging = None
        self.touch()

    def _canvas_event(self, event) -> None:
        """Two different things under the same hand, by mode.

        In Preview the camera does not move at all: the window into what it
        sees is made smaller and shifted, which is cropping a photograph
        rather than walking closer, and the perspective the screens are judged
        in stays the one the file was set up with. In Inspection there is no
        frame to keep, and the same gestures fly the camera instead.
        """
        if self.solid is None:
            return
        if self.inspecting():
            self._fly_event(event)
            return
        if self.mode.currentText() in ("Flat", "ReBake"):
            self._flat_event(event)
            return
        if self.mode.currentText() != PREVIEW:
            return
        kind = event["event_type"]
        scene = self.mesh

        if kind == "wheel":
            steps = -event["dy"] / 120.0
            if not steps:
                return
            where = self._in_frame(event["x"], event["y"])
            # Keep whatever is under the pointer where it is, or the picture
            # slides away from the thing being looked at.
            held = (scene.centre[0] + where[0] * scene.zoom,
                    scene.centre[1] + where[1] * scene.zoom)
            zoom = min(1.0, max(0.02, scene.zoom * (0.85 ** steps)))
            self.solid.look_at_window(
                (held[0] - where[0] * zoom, held[1] - where[1] * zoom), zoom)

        elif kind == "double_click":
            self.reset_view()

        elif kind == "pointer_down":
            # Taking the keyboard off whatever had it -- a path field, most
            # likely. Clicking the picture and finding that the space bar
            # still belongs to a text box somewhere is the sort of thing
            # nobody should have to work out.
            self.canvas.setFocus()
            self._dragging = self._in_frame(event["x"], event["y"])

        elif kind == "pointer_move" and self._dragging is not None:
            here = self._in_frame(event["x"], event["y"])
            self.solid.look_at_window(
                (scene.centre[0] - (here[0] - self._dragging[0]) * scene.zoom,
                 scene.centre[1] - (here[1] - self._dragging[1]) * scene.zoom),
                None)
            self._dragging = here

        elif kind == "pointer_up":
            self._dragging = None
        self._lay_frame_edge()
        self.touch()

    FLAT_CLOSEST = 40.0          # far enough in to count pixels on the lamellas

    def _flat_event(self, event) -> None:
        """Wheel to come closer, drag to move about, double click to fit.

        The same three gestures as the other two modes, doing the same three
        things, so nothing has to be relearned on the way between them. What
        moves here is the layout, not a camera and not a crop: the strips are
        drawn larger and somewhere else, which is what looking closely at a
        picture on a table actually is.
        """
        kind = event["event_type"]
        here = self._on_canvas(event.get("x", 0), event.get("y", 0))

        if kind == "wheel":
            steps = -event["dy"] / 120.0
            if not steps:
                return
            magnify = self.flat_zoom
            wanted = min(self.FLAT_CLOSEST, max(1.0, magnify * (1.18 ** steps)))
            # Hold whatever is under the pointer still. Zooming about the
            # middle instead means the thing being looked at slides away from
            # under the hand exactly when it is being looked at closely.
            focus = self._flat_under(here)
            self.flat_focus = (focus[0] - (here[0] - 0.5) / wanted,
                               focus[1] - (here[1] - 0.5) / wanted)
            self.flat_zoom = wanted
        elif kind == "double_click":
            self.flat_zoom, self.flat_focus = 1.0, (0.5, 0.5)
        elif kind == "pointer_down":
            self._dragging = here
            return
        elif kind == "pointer_move" and self._dragging is not None:
            magnify = self.flat_zoom
            self.flat_focus = (
                self.flat_focus[0] - (here[0] - self._dragging[0]) / magnify,
                self.flat_focus[1] - (here[1] - self._dragging[1]) / magnify)
            self._dragging = here
        elif kind == "pointer_up":
            self._dragging = None
            return
        else:
            return
        self._hold_flat()
        self.touch()

    def _flat_under(self, where):
        """Which point of the fitted layout is under a point of the canvas."""
        magnify = self.flat_zoom
        return (self.flat_focus[0] + (where[0] - 0.5) / magnify,
                self.flat_focus[1] + (where[1] - 0.5) / magnify)

    def _hold_flat(self) -> None:
        """Keep the layout covering the canvas rather than wandering off it.

        Zoomed all the way out there is only one place it can be, and the
        clamp says so by itself: the room to move is zero.
        """
        room = 0.5 / self.flat_zoom
        self.flat_focus = (
            min(1.0 - room, max(room, self.flat_focus[0])),
            min(1.0 - room, max(room, self.flat_focus[1])))

    # How far a drag right across the canvas swings the camera. Half a turn,
    # which is far enough to get behind the building in one movement and near
    # enough that a small correction stays small.
    SWING = math.pi

    def _fly_event(self, event) -> None:
        """Drag to swing, wheel to come closer, right or Shift to slide.

        The gestures are the ones every 3D window has, and deliberately so:
        this is for walking round the thing, and nobody should have to learn
        how.
        """
        free = self.solid.free
        if free is None:
            return
        kind = event["event_type"]
        here = self._on_canvas(event.get("x", 0), event.get("y", 0))

        if kind == "wheel":
            steps = -event["dy"] / 120.0
            if steps:
                free.dolly(0.85 ** steps)
        elif kind == "double_click":
            free.reset()
        elif kind == "pointer_down":
            self._dragging = here
            # Which gesture this drag is stays decided for the whole of it,
            # so letting go of Shift halfway through does not turn a slide
            # into a swing under the hand.
            self._sliding = (2 in event.get("buttons", ())
                             or 3 in event.get("buttons", ())
                             or "Shift" in (event.get("modifiers") or ()))
        elif kind == "pointer_move" and self._dragging is not None:
            across = here[0] - self._dragging[0]
            down = here[1] - self._dragging[1]
            if self._sliding:
                free.pan(across, down)
            else:
                free.turn(across * self.SWING, down * self.SWING * 0.5)
            self._dragging = here
        elif kind == "pointer_up":
            self._dragging = None
        else:
            return
        self.solid.refresh()
        self.touch()

    def _on_canvas(self, x: float, y: float):
        """A point on the canvas, as a fraction of its width and height.

        Fractions rather than pixels so that a gesture means the same thing
        whatever size the window has been dragged to.
        """
        wide, tall = self.canvas.get_logical_size()
        return (x / max(wide, 1), y / max(tall, 1))

    def reset_view(self) -> None:
        if self.solid is None:
            return
        if self.inspecting():
            if self.solid.free is not None:
                self.solid.free.reset()
                self.solid.refresh()
        elif self.mode.currentText() in ("Flat", "ReBake"):
            self.flat_zoom, self.flat_focus = 1.0, (0.5, 0.5)
        else:
            self.solid.look_at_window((0.0, 0.0), 1.0)
        self._lay_frame_edge()
        self.touch()

    def _in_frame(self, x: float, y: float):
        """A point on the canvas as -1..1 across the drawn picture.

        The event carries logical pixels and the viewport is in physical ones,
        which on a scaled display are not the same number.
        """
        shape = (self.mesh.cropped or self.mesh.frame) if self.mesh else (1, 1)
        ratio = self.canvas.get_pixel_ratio()
        left, top, wide, tall = self._fitted(*shape)
        return (2.0 * (x * ratio - left) / max(wide, 1) - 1.0,
                1.0 - 2.0 * (y * ratio - top) / max(tall, 1))

    def _screen_to_array(self, name: str, across: int, down: int,
                         bare: bool = False):
        """One screen alone, composited at its own working resolution.

        Through the same call the flat layout draws a strip with, so what is
        written is what is on screen and not a second opinion about it -- only
        into a target the size of the real thing rather than a rectangle of
        the window.
        """
        target = self.device.create_texture(
            size=(across, down, 1), format=self.format,
            usage=wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.COPY_SRC)
        row = across * 4
        stride = -(-row // 256) * 256          # rows are copied out 256-aligned
        readback = self.device.create_buffer(
            size=stride * down,
            usage=wgpu.BufferUsage.COPY_DST | wgpu.BufferUsage.MAP_READ)

        encoder = self.device.create_command_encoder()
        if bare:
            # Nothing underneath, and nothing to add an alpha to: what the
            # blend leaves is the content's own.
            self.painter.clear(encoder, target.create_view(), opaque=False)
        self._draw_strip(encoder, target.create_view(), name,
                         (0, 0, across, down), bare=bare)
        encoder.copy_texture_to_buffer(
            {"texture": target},
            {"buffer": readback, "bytes_per_row": stride, "rows_per_image": down},
            (across, down, 1))
        self.device.queue.submit([encoder.finish()])

        readback.map_sync("read")
        try:
            raw = np.frombuffer(bytes(readback.read_mapped()), dtype=np.uint8)
        finally:
            readback.unmap()
        picture = (raw[:stride * down].reshape(down, stride)[:, :row]
                   .reshape(down, across, 4).copy())
        if self.format.startswith("bgra"):
            picture = picture[..., [2, 1, 0, 3]]
        return picture

    def _snapshot(self) -> None:
        """This frame, as a picture, without waiting for a render.

        What is written depends on what is being looked at, because the two
        views answer different questions. Preview goes through the same path
        a render does, at the size that would be written, so what lands on
        disk is a frame of the film. Flat is not one picture at all -- it is
        the screens laid side by side to be read one at a time -- so it writes
        each of them on its own, at the resolution the wall really has. That
        is the file you can take to whoever made the content.
        """
        if self.device is None:
            return
        chosen = self.mode.currentText()
        folder = self.out_dir / SNAPSHOTS
        at, _ = self._frame_now()
        written = []
        try:
            folder.mkdir(parents=True, exist_ok=True)
            if chosen in (PREVIEW, "Inspection") and self.solid is not None:
                width, height = self.size_choice.currentData()
                # Through the frame, not through the window. On screen the
                # camera is opened out to fill the canvas -- that is what took
                # the black bars off the sides -- and a picture taken through
                # that opened-out camera and then written into the frame's
                # shape is the whole building made narrow. The render sets this
                # back before its first frame; so does this.
                #
                # Only the opening out. Whatever the wheel has cropped into
                # stays cropped: a crop keeps the frame's shape, so it comes
                # out true, and somebody who zoomed in to look at a detail and
                # pressed Snapshot meant that detail.
                spilled = self.mesh.spill      # the scene keeps it, not the drawer
                # Inspection too: opened out, the free camera fills the window
                # and a picture taken through it then written into the frame's
                # shape would be the building made narrow, exactly as on the
                # file camera. Closing to the frame captures the same
                # rectangle the render will, from the angle being inspected.
                self.solid.show_around(1.0, 1.0)
                try:
                    picture = self.solid.to_array(width, height)
                finally:
                    # Put the window back the way it was looking, rather than
                    # leaving it framed and waiting for the next draw to
                    # notice.
                    self.solid.show_around(*spilled)
                written.append(self._write_png(picture, folder, "", at))
            else:
                for name in self._flat_showing():
                    across, down = self._pixels(name)
                    if min(across, down) < 2:
                        continue
                    picture = self._screen_to_array(name, across, down)
                    written.append(
                        self._write_png(picture, folder, SHORT.get(name, name), at))
        except Exception as error:  # noqa: BLE001 -- said in the window
            self.eta.setText(tr("Снимок не записан: {0}", error))
            logfile.write(f"snapshot failed: {error}")
            return

        if not written:
            self.eta.setText(tr("Снимать нечего: ничего не загружено"))
            return
        self.eta.setText(tr("Снимок: {0}/{1}", SNAPSHOTS, written[0].name)
                         + (tr(" и ещё {0}", len(written) - 1) if len(written) > 1
                            else ""))
        for path in written:
            logfile.write(f"snapshot: {path}")

    def _write_png(self, picture, folder: Path, part: str, at: int) -> Path:
        height, width = picture.shape[:2]
        image = QImage(np.ascontiguousarray(picture).data, width, height,
                       width * 4, QImage.Format.Format_RGBA8888).copy()
        path = self._snapshot_path(folder, part, at)
        if not image.save(str(path)):
            raise OSError(f"could not write {path}")
        return path

    def _snapshot_path(self, folder: Path, part: str, at: int) -> Path:
        """Named for the screen and the frame, and never on top of one.

        The same rule the renders follow: a file that is already there is
        something somebody wanted, and a snapshot is too cheap to be worth
        losing one over.
        """
        stem = Path(self.out_name.text().strip() or "preview").stem
        if part:
            stem = f"{stem}_{part}"
        path = folder / f"{stem}_f{at:05d}.png"
        count = 2
        while path.exists():
            path = folder / f"{stem}_f{at:05d}_{count}.png"
            count += 1
        return path

    # What Flat offers instead of shapes: every screen is written at its own
    # size, so the only choice is how much of it.
    FLAT_SCALES = (("Родное", 1.0), ("Половина", 0.5), ("Четверть", 0.25))

    def flat_mode(self) -> bool:
        return self.mode.currentText() == "Flat"

    def _fill_sizes(self) -> None:
        """The Write list, which means one thing in Flat and another elsewhere.

        Kept as one list rather than two because it is the same question --
        how large to write -- and somebody looking for it looks here.
        """
        # Put back by what it is rather than by what it says: the words
        # change with the language, and the size does not.
        was = self.size_choice.currentData()
        self.size_choice.blockSignals(True)
        self.size_choice.clear()
        if self.flat_mode():
            for label, scale in self.FLAT_SCALES:
                self.size_choice.addItem(tr(label), scale)
        else:
            frame = self.mesh.frame if self.mesh else (2048, 2048)
            self.size_choice.addItem("1080x1920", (1080, 1920))
            for label, divide in ((tr("Полный"), 1), (tr("Половина"), 2),
                                  (tr("Четверть"), 4)):
                wide, tall = frame[0] // divide, frame[1] // divide
                self.size_choice.addItem(f"{label} {wide}x{tall}", (wide, tall))
        for index in range(self.size_choice.count()):
            if was is not None and self.size_choice.itemData(index) == was:
                self.size_choice.setCurrentIndex(index)
                break
        self.size_choice.blockSignals(False)

    def _fill_formats(self) -> None:
        """The formats, with the two that carry an alpha added in Flat."""
        was = self.format_choice.currentText()
        self.format_choice.blockSignals(True)
        self.format_choice.clear()
        offered = list(export.FORMATS)
        if self.flat_mode():
            offered += export.ALPHA_FORMATS
        for label, kind, suffix in offered:
            self.format_choice.addItem(label, (kind, suffix))
        if was:
            self.format_choice.setCurrentText(was)
        self.format_choice.blockSignals(False)

    def _export_for_mode(self) -> None:
        """The render row, saying what this mode can actually write."""
        if not hasattr(self, "size_choice"):
            return
        flat = self.flat_mode()
        self._fill_sizes()
        self._fill_formats()
        # In Flat the names come from the sources, so a box to type one in and
        # a button to bump its version have nothing to act on.
        for widget in (self.out_name, self.bump_button):
            widget.setEnabled(not flat)
        self.size_choice.setToolTip(
            tr("Каждый экран пишется в своём собственном разрешении — столько "
               "пикселей, сколько у стены на самом деле. Половина и четверть "
               "считаются от него же и округляются вниз до кратного четырём, "
               "иначе кодировщик не возьмёт кадр.")
            if flat else tr(self.WRITE_SIZE_HINT))
        self._format_changed()
        if not flat:
            # The list was rebuilt and may have landed on a different shape,
            # and the camera has to be framed for whatever it landed on.
            self._framing_changed()

    def _framing_changed(self, *_) -> None:
        """The preview is framed the way the file will be, or it lies.

        Choosing a shape is choosing the crop -- there is no sense in framing
        one thing on screen and writing another, so it is not offered as a
        separate choice.
        """
        # In Flat the list holds scales rather than shapes, and there is no
        # camera frame to set: every screen is written at its own size.
        if self.solid is None or self.flat_mode():
            return
        width, height = self.size_choice.currentData()
        self.solid.frame_as(width, height, True)
        self._lay_overlays()
        self.touch()
        logfile.write(f"framing: a centred {width}x{height} window")

    # -- re-baking a source file ----------------------------------------------

    REBAKE_ROWS = ("Top", "Bottom")

    def _rebake_controls(self) -> QWidget:
        """The strip that only ReBake uses, hidden the rest of the time."""
        holder = QWidget()
        holder.setObjectName("qa_rebake_bar")
        holder.setFixedHeight(60)
        holder.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        holder.setStyleSheet(f"#qa_rebake_bar {{ background:{theme.PANEL};"
                             f" border-top:1px solid {theme.SEAM}; }}")
        bar = QHBoxLayout(holder)
        bar.setContentsMargins(16, 0, 16, 0)
        bar.setSpacing(10)

        title = QLabel(tr("Перепечка"))
        title.setStyleSheet("font-size:13px; font-weight:600;")
        bar.addWidget(title)
        self.rebake_what = QComboBox()
        self.rebake_what.setObjectName("qa_rebake_what")
        self.rebake_what.setFixedWidth(104)
        # Clean first, because it is the default: it leaves the fade the
        # author made and only takes away what a premultiplied reading would
        # bloom on. Dither is the stronger medicine and is chosen on purpose.
        self.rebake_what.addItem(tr("Чистка"), rebake.CLEAN)
        self.rebake_what.addItem(tr("Дизер"), rebake.DITHER)
        self.rebake_what.setToolTip(
            tr("Дизер превращает альфу в одни только 0 и 255 по неподвижной "
               "карте голубого шума и уводит цвет вместе с ней — после этого два "
               "чтения файла не могут различаться вовсе. Чистка альфу не трогает "
               "и стирает цвет там, где альфа ниже порога: фейд остаётся фейдом, "
               "а худшее из того, что показывает премультиплаед, уходит."))
        self.rebake_what.currentIndexChanged.connect(self._rebake_changed)
        bar.addWidget(self.rebake_what)

        bar.addWidget(QLabel(tr("порог")))
        self.rebake_threshold = QSpinBox()
        self.rebake_threshold.setObjectName("qa_rebake_below")
        self.rebake_threshold.setRange(0, 255)
        self.rebake_threshold.setValue(8)
        self.rebake_threshold.setFixedWidth(64)
        self.rebake_threshold.setKeyboardTracking(False)
        self.rebake_threshold.setToolTip(
            tr("Чистка стирает цвет под любой альфой ниже этого значения, в том "
               "счёте, в каком ведёт его файл, от 0 до 255. Восьмёрка не "
               "отличима от прозрачного: убирает грязь и оставляет фейд."))
        self.rebake_threshold.valueChanged.connect(self._rebake_changed)
        bar.addWidget(self.rebake_threshold)

        bar.addWidget(QLabel(tr("цвет")))
        self.rebake_colour = QComboBox()
        self.rebake_colour.setObjectName("qa_rebake_colour")
        self.rebake_colour.setFixedWidth(104)
        self.rebake_colour.addItem(tr("Умножить"), rebake.MULTIPLY)
        self.rebake_colour.addItem(tr("Оставить"), rebake.KEEP)
        self.rebake_colour.addItem(tr("Прижать"), rebake.CLAMP)
        self.rebake_colour.setToolTip(
            tr("Что происходит с цветом выше порога. «Оставить» — фейд ровно "
               "такой, каким он сделан. «Прижать» прижимает каждый канал к его "
               "собственной альфе: вспышка уходит, но появляется излом — канал "
               "либо не тронут, либо срезан. «Умножить» вместо этого сворачивает "
               "цвет с его альфой; это масштаб, а не потолок, поэтому излома нет "
               "нигде: премультиплаед становится верным чтением, а стрэйт "
               "расплачивается тем, что применяет альфу второй раз."))
        self.rebake_colour.currentIndexChanged.connect(self._rebake_changed)
        bar.addWidget(self.rebake_colour)

        bar.addWidget(QLabel(tr("в")))
        self.rebake_format = QComboBox()
        self.rebake_format.setObjectName("qa_rebake_format")
        self.rebake_format.setFixedWidth(126)
        for kind, name in rebake.FORMATS:
            self.rebake_format.addItem(name, kind)
        self.rebake_format.setToolTip(
            tr("Hap Q Alpha — тот самый формат, в котором лежат исходники, "
               "поэтому перепечённый файл встаёт ровно туда, где был старый. "
               "ffmpeg его не пишет: у его кодировщика Hap нет формата с "
               "отдельным слоем альфы, — поэтому цвет жмёт ffmpeg как Hap Q, это "
               "те же блоки YCoCg, а альфу и обёртку делает вьювер. ProRes 4444 "
               "— второй вариант, для мест, где нужен обычный промежуточный "
               "файл."))
        self.rebake_format.currentIndexChanged.connect(
            lambda _: (self._offer_ffmpeg(), self._remember()))
        bar.addWidget(self.rebake_format)

        # Only up when the chosen format cannot be written here. Hap needs an
        # ffmpeg built with snappy, and half the ones people have are not, so
        # the way out belongs where the trouble is rather than three windows
        # away in the machine check.
        self.rebake_get = iconed(
            QPushButton(), "download", tr("Скачать ffmpeg, который умеет"),
            tr("Здесь нет кодировщика, который нужен этому формату. Это скачает "
               "сборку, которая его умеет, и положит рядом с приложением: ничего "
               "не устанавливается, ничего не прописывается в PATH, а удаление "
               "папки отменяет всё."), name="qa_rebake_get")
        self.rebake_get.clicked.connect(self._get_ffmpeg)
        self.rebake_get.setVisible(False)
        bar.addWidget(self.rebake_get)

        bar.addWidget(_divider())
        self.probe_button = iconed(
            QPushButton(), "probe", tr("Проба"),
            tr("Записать кадр, на котором стоит таймлайн, оба экрана, в PNG в "
               "натуральную величину файла. Зерно шириной в один пиксель, а "
               "полосы наверху — нет, так что это единственный честный на него "
               "взгляд."), name="qa_probe")
        self.probe_button.clicked.connect(self._probe)
        bar.addWidget(self.probe_button)

        self.rebake_button = iconed(
            QPushButton(), "rebake", tr("Перепечь"),
            tr("Записать оба экрана целиком, в их собственном размере и частоте, "
               "в выбранном рядом формате. В Hap Q Alpha готовый файл забирает "
               "имя исходника, а исходник отходит с суффиксом _old: всё, что на "
               "эти файлы ссылалось, продолжает работать и показывает уже "
               "перепечённое, и ничего не удаляется. В ProRes файл ложится рядом "
               "с исходником с суффиксом _prores, а исходник остаётся "
               "нетронутым."), name="qa_rebake")
        self.rebake_button.clicked.connect(self._start_rebake)
        bar.addWidget(self.rebake_button)

        self.rebake_stop = iconed(QPushButton(), "stop", tr("Стоп"),
                                  tr("Остановить перепечку. Половина файла хуже, "
                                     "чем ничего, поэтому записанное удаляется."),
                                  name="qa_rebake_stop")
        self.rebake_stop.setEnabled(False)
        self.rebake_stop.clicked.connect(
            lambda: self.job.cancel() if self.job is not None else None)
        bar.addWidget(self.rebake_stop)

        self.rebake_progress = QProgressBar()
        self.rebake_progress.setObjectName("qa_rebake_progress")
        self.rebake_progress.setFixedWidth(150)
        self.rebake_progress.setTextVisible(False)
        self.rebake_progress.setVisible(False)       # only while re-baking
        bar.addWidget(self.rebake_progress)

        self.rebake_note = QLabel()
        self.rebake_note.setObjectName("qa_rebake_note")
        self.rebake_note.setFont(theme.mono(8.5))
        self.rebake_note.setStyleSheet(f"color:{theme.QUIET};")
        bar.addWidget(self.rebake_note, 1)
        _even(bar)
        return holder

    def _rebake_screens(self):
        """The screens this mode is about, and the rows that feed them."""
        pairs = []
        for row in self.rows:
            if row.title not in self.REBAKE_ROWS:
                continue
            screen = self._screen_of(row.screen)
            if screen is not None:
                pairs.append((row, screen))
        return pairs

    def _need_noise(self, screens) -> bool:
        """Hand out the threshold maps, or set one being built.

        None of this happens on the way into the mode a second time: the maps
        are kept, and the only cost anybody pays is the first three seconds.
        """
        wanted = {(s.width, s.height) for s in screens}
        missing = [size for size in wanted if size not in self.noise_maps]
        if not missing:
            for screen in screens:
                if not getattr(screen, "has_noise", False):
                    screen.load_noise(self.noise_maps[(screen.width,
                                                       screen.height)])
                    screen.has_noise = True
            return True
        if self.noise_job is None:
            self.noise_job = jobs.NoiseJob(missing, parent=self)
            self.noise_job.ready.connect(self._noise_ready)
            self.noise_job.start()
            self.rebake_note.setText(tr("строю карту порогов…"))
        return False

    def _noise_ready(self, made: dict) -> None:
        self.noise_maps.update(made)
        self.noise_job = None
        self.rebake_note.setText("")
        self._rebake_changed()

    # Laid over the picture rather than put in a bar. Which half is which is
    # the one thing somebody has to keep straight in this mode, and a control
    # at the other end of the window is no help with that.
    @staticmethod
    def overlay_combo_style() -> str:
        """The whole of a combo box over the picture, not half of it.

        Saying only what the box looks like and leaving the drop-down to the
        platform leaves Qt drawing a complex control half one way and half the
        other. On Windows that passes for a combo box. On macOS it comes out
        as something else entirely -- a frame with two stacked arrows in it,
        which is what the mac was showing. So every part is said here, arrow
        and popup included.
        """
        folder = (logfile.bundled(ICONS)
                  or (Path(__file__).resolve().parent / ICONS))
        arrow = (Path(folder) / "down.png").as_posix()
        return (
            f"QComboBox {{ background:{OVERLAY_BG}; color:{theme.TEXT}; "
            f"border:1px solid {theme.EDGE}; border-radius:4px; "
            "padding:2px 22px 2px 8px; } "
            f"QComboBox:hover {{ border-color:{theme.FAINT}; }} "
            "QComboBox::drop-down { subcontrol-origin:padding; "
            "subcontrol-position:center right; width:20px; border:none; "
            "background:transparent; } "
            'QComboBox::down-arrow { image:url("' + arrow + '"); '
            "width:9px; height:9px; } "
            f"QComboBox QAbstractItemView {{ background:{theme.CARD}; "
            f"color:{theme.TEXT}; border:1px solid {theme.EDGE}; outline:none; "
            f"selection-background-color:{theme.ACCENT}; "
            "selection-color:#ffffff; }")
    OVERLAY_BAR = (f"QFrame {{ background:{OVERLAY_BG}; "
                   f"border:1px solid {theme.SEAM}; border-radius:6px; }}")
    FRAME_EDGE = ("background:transparent; "
                  "border:1px solid rgba(255,255,255,150);")
    OVERLAY_LABEL = (f"background:rgba(20,21,24,200); color:{theme.SECOND}; "
                     "border:none; border-radius:4px; padding:2px 8px;")

    def _rebake_overlays(self) -> None:
        """The reading of each half, and the name of each half, on the picture."""
        # Kept on the window: a style handed to a widget is not owned by it,
        # and one that goes out of scope takes the widget with it.
        self._plain_style = QStyleFactory.create("Fusion")
        self.rebake_left_alpha = QComboBox(self.canvas)
        self.rebake_left_alpha.setObjectName("qa_rebake_left")
        self.rebake_right_alpha = QComboBox(self.canvas)
        self.rebake_right_alpha.setObjectName("qa_rebake_right")
        for box, side, tip in (
                (self.rebake_left_alpha, "Premultiplied",
                 tr("Как читается левая половина — файл как он есть. "
                    "Половины выбирают независимо, в этом и смысл: после "
                    "дизера один и тот же файл, прочитанный любым способом, — "
                    "одна и та же картинка, и поставить их по-разному и не "
                    "увидеть разницы это и есть проверка. Переключатель Alpha "
                    "наверху в этом режиме не действует.")),
                (self.rebake_right_alpha, "Straight",
                 tr("Как читается правая половина — то, что из него делает "
                    "перепечка. Половины выбирают независимо, в этом и смысл: "
                    "после дизера один и тот же файл, прочитанный любым "
                    "способом, — одна и та же картинка, и поставить их "
                    "по-разному и не увидеть разницы это и есть проверка. "
                    "Переключатель Alpha наверху в этом режиме не действует."))):
            box.addItems(["Premultiplied", "Straight"])
            box.setCurrentText(side)
            box.setFixedWidth(126)
            # Off the platform's own style, both the box and its list.
            #
            # A stylesheet is a request the native macOS style is free to
            # ignore, and it does: the box came out drawn as a menu -- a tick
            # beside the current line and a scroll triangle under it -- with
            # the styled drop-down sitting next to it as a second thing. Qt's
            # own Fusion style honours every word of the sheet on all three
            # platforms, and giving the popup a plain list view stops macOS
            # putting a native menu there instead. Windows looks the same
            # either way; the sheet was already doing the drawing.
            box.setStyle(self._plain_style)
            box.setView(QListView())
            box.view().setStyle(self._plain_style)
            box.setStyleSheet(self.overlay_combo_style())
            box.setToolTip(tip)
            box.currentIndexChanged.connect(
                lambda _: (self.touch(), self._remember()))

        self.rebake_before = QLabel(tr("файл"), self.canvas)
        self.rebake_before.setObjectName("qa_rebake_before")
        self.rebake_after = QLabel(tr("перепечка"), self.canvas)
        self.rebake_after.setObjectName("qa_rebake_after")
        for tag in (self.rebake_before, self.rebake_after):
            tag.setFont(theme.mono(8.5))
            tag.setStyleSheet(self.OVERLAY_LABEL)
            tag.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.overlays = (self.rebake_left_alpha, self.rebake_right_alpha,
                         self.rebake_before, self.rebake_after)
        for widget in self.overlays:
            widget.setVisible(False)

        self._hint_at = None
        self._hint_name = QTimer(self)
        self._hint_name.setSingleShot(True)
        self._hint_name.timeout.connect(lambda: self._say_hint(0))
        self._hint_story = QTimer(self)
        self._hint_story.setSingleShot(True)
        self._hint_story.timeout.connect(lambda: self._say_hint(1))

        self.canvas.installEventFilter(self)
        # And on everything: the transport keys have to be taken before the
        # widget with the focus gets a chance to answer them itself.
        self.canvas.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        QApplication.instance().installEventFilter(self)

    def _full_screen_button(self) -> None:
        """The picture alone on the monitor: a switch in the bar over it, and
        the transport over its foot while it lasts."""
        self._full = False
        self._before_full = None
        self._was_showing: list = []
        self.full_button = _pill(
            tr("Во весь экран"), "qa_full",
            tr("Картинка на весь монитор, на котором стоит окно, всё остальное "
               "убирается. Ещё раз — обратно, или Escape. F11 делает то же с "
               "клавиатуры."), checkable=False)
        self.full_button.clicked.connect(self._toggle_full)

        # Full screen takes the transport away with everything else, so the
        # timeline comes back on the picture itself. Only there: in a window
        # the real one is a few pixels below and two would be a question
        # about which is which.
        self.full_bar = QFrame(self.canvas)
        self.full_bar.setObjectName("qa_full_bar")
        self.full_bar.setStyleSheet(self.OVERLAY_BAR)
        self.full_bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        line = QHBoxLayout(self.full_bar)
        line.setContentsMargins(10, 6, 12, 6)
        line.setSpacing(4)
        acts = self._transport_acts()
        for picture, says, story in self.TRANSPORT:
            says, story = tr(says), tr(story)
            button = self._transport_button(picture, says, story,
                                            f"qa_full_{picture}", acts[picture],
                                            tall=30)
            line.addWidget(button)
            if picture == "play":
                self.full_play = button
        line.addSpacing(8)
        # The same slider as the transport's: a press anywhere puts the
        # playhead there, and it carries marks -- in a show, where the
        # sections begin (see `_mark_full`).
        self.full_slider = Timeline(Qt.Orientation.Horizontal)
        self.full_slider.setObjectName("qa_full_slider")
        self.full_slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.full_slider.setFixedHeight(28)
        self.full_slider.setRange(0, 1000)
        self.full_slider.sliderMoved.connect(self._scrub)
        line.addWidget(self.full_slider, 1)
        self.full_time = QLabel("0 / 0")
        self.full_time.setObjectName("qa_full_time")
        self.full_time.setFont(theme.mono(9))
        self.full_time.setStyleSheet(f"color:{theme.SECOND};")
        self.full_time.setMinimumWidth(210)
        self.full_time.setAlignment(Qt.AlignmentFlag.AlignRight
                                    | Qt.AlignmentFlag.AlignVCenter)
        line.addWidget(self.full_time)
        self.full_bar.setVisible(False)

        for keys, wanted in ((Qt.Key.Key_F11, None), (Qt.Key.Key_Escape, True)):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.activated.connect(
                lambda only=wanted: (self._toggle_full()
                                     if only is None or self._full else None))

    def _frame_line(self) -> None:
        """The rectangle that will be written, drawn on the picture.

        A widget over the canvas rather than something in the scene: it is one
        pixel wide whatever the window is doing, and a line drawn in the
        picture would be at the mercy of the same fitting it is there to
        describe.
        """
        self.frame_edge = QFrame(self.canvas)
        self.frame_edge.setObjectName("qa_frame_edge")
        self.frame_edge.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.frame_edge.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.frame_edge.setStyleSheet(self.FRAME_EDGE)
        self.frame_edge.setVisible(False)

        self.frame_button = _pill(
            tr("Рамка"), "qa_frame_edge_button",
            tr("Линия, показывающая, что попадёт в запись. Картинка занимает "
               "всё окно и продолжается за рамкой; эта линия говорит, где "
               "рамка. В Превью и в Инспекторе, где есть что кадрировать."))
        self.frame_button.setChecked(True)
        self.frame_button.toggled.connect(
            lambda _: (self._lay_overlays(), self._remember()))

        # Horizontal tiling, offered only in Flat: each strip is drawn again
        # to its left and right until the window is full, so a screen reads as
        # the endless band it really is on the wall rather than one turn of it
        # standing alone.
        self.tile_button = _pill(
            tr("Плитка"), "qa_tile_button",
            tr("Горизонтальный тайл: каждый экран повторяется лентой без конца, "
               "влево и вправо, как он и идёт по кругу здания. Только в Развертке."))
        self.tile_button.setChecked(False)
        self.tile_button.toggled.connect(
            lambda _: (self._lay_overlays(), self.touch(), self._remember()))

        # What the line is, and what the hand can do here, at the foot.
        self.frame_hint = QLabel(self.canvas)
        self.frame_hint.setObjectName("qa_frame_hint")
        self.frame_hint.setFont(theme.mono(8.5))
        self.frame_hint.setStyleSheet(
            f"QLabel {{ color:{theme.QUIET}; background:rgba(20,21,24,150);"
            f" border-radius:4px; padding:2px 6px; }}")
        self.frame_hint.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.frame_hint.setVisible(False)

    def _beside_canvas(self):
        """Every widget the window lays out, except the picture itself.

        The top of each branch only: hiding a row hides what is in it, and
        walking further would turn the coming back into a guess about which
        of a bar's own widgets were meant to be showing.
        """
        found: list = []

        def take(widget) -> None:
            if widget is self.canvas:
                return
            # What holds the picture is gone into, not hidden: hiding the
            # boundary between the picture and the show's strips would take
            # the picture away with them.
            if widget.isAncestorOf(self.canvas):
                if isinstance(widget, QSplitter):
                    for index in range(widget.count()):
                        take(widget.widget(index))
                elif widget.layout() is not None:
                    walk(widget.layout())
                return
            found.append(widget)

        def walk(layout) -> None:
            for index in range(layout.count()):
                item = layout.itemAt(index)
                if item.widget() is not None:
                    take(item.widget())
                elif item.layout() is not None:
                    walk(item.layout())

        walk(self.centralWidget().layout())
        return found

    def _toggle_full(self) -> None:
        """Full screen and back, on whichever monitor the window is on."""
        going = not self._full
        board = self.centralWidget().layout()
        if going:
            # What was on show, remembered rather than worked out again: the
            # bars belong to modes, and coming back must not raise one this
            # mode keeps down.
            self._was_showing = [(widget, widget.isVisible())
                                 for widget in self._beside_canvas()]
            self._before_full = self.saveGeometry()
            self._margins = board.contentsMargins()
            for widget, _ in self._was_showing:
                widget.setVisible(False)
            board.setContentsMargins(0, 0, 0, 0)
            self.showFullScreen()
        else:
            self.showNormal()
            if self._before_full is not None:
                self.restoreGeometry(self._before_full)
            board.setContentsMargins(self._margins)
            for widget, was in self._was_showing:
                widget.setVisible(was)
        self._full = going
        self.full_button.setText(tr("Выйти  Esc") if going else tr("Во весь экран"))
        self._lay_overlays()
        self.touch()

    # What the transport keeps for itself, wherever the keyboard happens to
    # be pointing.
    TRANSPORT_KEYS = (Qt.Key.Key_Space, Qt.Key.Key_Left, Qt.Key.Key_Right)
    # And in Шоу, these as well. Letters by the key rather than the character,
    # so they work on a Russian layout the same: see `layout_key`.
    # And in both: ? for the card of keys, Shift+I and Shift+O for the range.
    ALWAYS_KEYS = (Qt.Key.Key_Question, Qt.Key.Key_Slash, Qt.Key.Key_I,
                   Qt.Key.Key_O)
    SHOW_KEYS = (Qt.Key.Key_I, Qt.Key.Key_O, Qt.Key.Key_L, Qt.Key.Key_F,
                 Qt.Key.Key_Home, Qt.Key.Key_End, Qt.Key.Key_Question,
                 Qt.Key.Key_Slash, Qt.Key.Key_K, Qt.Key.Key_Z, Qt.Key.Key_Y,
                 Qt.Key.Key_Delete, Qt.Key.Key_BracketLeft,
                 Qt.Key.Key_BracketRight)

    def eventFilter(self, watched, event):  # noqa: N802 -- Qt naming
        if watched is self.canvas and event.type() == QEvent.Type.Resize:
            self._lay_overlays()
        if watched in HINTS:
            if event.type() == QEvent.Type.Enter:
                self._hint(watched)
            elif event.type() in (QEvent.Type.Leave,
                                  QEvent.Type.MouseButtonPress):
                self._hint(None)
        if (event.type() == QEvent.Type.KeyPress
                and (layout_key(event) in self.TRANSPORT_KEYS
                     or layout_key(event) in self.ALWAYS_KEYS
                     or event.text() == "?"
                     or (self.level == "show"
                         and layout_key(event) in self.SHOW_KEYS))
                and self._transport_key(event)):
            return True
        return super().eventFilter(watched, event)

    def _hint(self, button) -> None:
        """Start the two waits behind a button's hover, or drop them."""
        self._hint_at = button
        for timer, wait in ((self._hint_name, HINT_NAME),
                            (self._hint_story, HINT_STORY)):
            timer.stop()
            if button is not None:
                timer.start(wait)
        if button is None:
            QToolTip.hideText()

    def _say_hint(self, which: int) -> None:
        button = self._hint_at
        if button is None or not button.isVisible():
            return
        words = HINTS[button][which]
        if not words:
            return
        QToolTip.showText(
            button.mapToGlobal(QPoint(0, button.height() + 2)), words, button)

    def _typing(self) -> bool:
        """Is a line being typed into? Then the keys belong to it."""
        spot = QApplication.focusWidget()
        return (isinstance(spot, QLineEdit) and spot.isEnabled()
                and not spot.isReadOnly())

    def _transport_key(self, event) -> bool:
        """Space and the arrows, taken before anything else sees them.

        Read through a filter on the whole application rather than as a key
        event on the window. A key event goes to whatever has the focus first,
        and nearly everything here answers these three: a combo box walks its
        own list with the arrows, a slider walks along itself, a checkbox
        takes the space bar as a click, and a button that was pressed a moment
        ago keeps the focus and does it again. So the window takes them first
        and leaves exactly one exception -- a line being typed into, where a
        space is a space and the arrows move the cursor.

        A spin box counts as one: what has the focus inside it is its own
        editor, so the frame numbers still step with the arrows.
        """
        if not self.isActiveWindow() or self._typing():
            return False
        keys = event.modifiers()
        control = bool(keys & Qt.KeyboardModifier.ControlModifier)
        shift = bool(keys & Qt.KeyboardModifier.ShiftModifier)
        key = layout_key(event)
        if event.text() == "?" or key == Qt.Key.Key_Question \
                or (key == Qt.Key.Key_Slash and shift):
            self._toggle_keys()
            return True
        if shift and not control and key in (Qt.Key.Key_I, Qt.Key.Key_O):
            self._range_here(key == Qt.Key.Key_O)
            return True
        if self.level == "show" and self._show_key(event, control):
            return True
        others = keys & ~(Qt.KeyboardModifier.ControlModifier
                          | Qt.KeyboardModifier.KeypadModifier)
        if others:                        # Shift, Alt: somebody else's
            return False
        key = layout_key(event)
        if key == Qt.Key.Key_Space:
            if control:
                return False
            self._toggle()
        elif key == Qt.Key.Key_Left:
            self._move(0.0) if control else self._step(-1)
        elif key == Qt.Key.Key_Right:
            self._move(self.clock.duration) if control else self._step(1)
        else:
            return False
        return True

    def _show_key(self, event, control: bool) -> bool:
        """The show mode's own keys. True when the key was one of them."""
        keys = event.modifiers()
        shift = bool(keys & Qt.KeyboardModifier.ShiftModifier)
        if keys & Qt.KeyboardModifier.AltModifier:
            return False
        key = layout_key(event)
        if shift and not control and key in (Qt.Key.Key_Left,
                                             Qt.Key.Key_Right):
            self._jump_by(-1.0 if key == Qt.Key.Key_Left else 1.0)
            return True
        view = self.show_view
        if view.editing:
            if control and key == Qt.Key.Key_Z:
                self._redo() if shift else self._undo()
                return True
            if control and key == Qt.Key.Key_Y and not shift:
                self._redo()
                return True
            if shift and not control and key == Qt.Key.Key_L:
                view.loop_the_clip()
                return True
            if not shift and not control:
                if key == Qt.Key.Key_Delete:
                    view.delete_chosen()
                    return True
                if key in (Qt.Key.Key_BracketLeft, Qt.Key.Key_BracketRight):
                    view.put_clip(key == Qt.Key.Key_BracketRight)
                    return True
                if key == Qt.Key.Key_K:
                    view.set_locked(not view.locked)
                    return True
        if shift or control:
            return False
        if key == Qt.Key.Key_I:
            view.to_edge(False)
        elif key == Qt.Key.Key_O:
            view.to_edge(True)
        elif key == Qt.Key.Key_L:
            view.set_looping(not view.looping)
        elif key == Qt.Key.Key_F:
            view.axis.fit()
            view.changed.emit()
        elif key == Qt.Key.Key_Home:
            self._move(0.0)
        elif key == Qt.Key.Key_End:
            self._move(self.clock.duration)
        else:
            return False
        return True

    def _lay_overlays(self) -> None:
        """Everything laid over the picture, each in its place for this mode.

        The bar of how it looks at the top right; the keys at the top left,
        their card under them; in ReBake the two readings, one each side, and
        the names under their halves; the frame's own line and what it is; in
        full screen the transport along the foot; with nothing loaded, the
        offer to load something, in the middle.
        """
        if not hasattr(self, "look_bar"):
            return
        wide = self.canvas.width()
        tall = self.canvas.height()
        edge = 14
        full = bool(getattr(self, "_full", False))
        self._say_look()
        bar = self.look_bar
        bar.adjustSize()
        bar.move(max(edge, wide - bar.width() - edge), edge)
        bar.raise_()
        self._lay_frame_edge()

        button, card = self.keys_button, self.keys_card
        button.setVisible(True)
        button.move(edge, edge)
        button.raise_()
        card.setVisible(self._keys_open)
        if card.isVisible():
            card.adjustSize()
            card.move(edge, edge + button.height() + 6)
            card.raise_()

        left, right = self.rebake_left_alpha, self.rebake_right_alpha
        left.adjustSize()
        right.adjustSize()
        left.move(edge + button.width() + 8, edge)
        # Under the bar, which is in that corner in every mode.
        right.move(max(edge, wide - right.width() - edge),
                   edge + bar.height() + 6)

        foot = 0
        self.full_bar.setVisible(full)
        if full:
            high = self.full_bar.sizeHint().height()
            self.full_bar.setGeometry(edge, tall - high - edge,
                                      max(120, wide - 2 * edge), high)
            self.full_bar.raise_()
            foot = high + 6
        for tag, middle in ((self.rebake_before, wide * 0.25),
                            (self.rebake_after, wide * 0.75)):
            tag.adjustSize()
            tag.move(int(middle - tag.width() / 2),
                     max(edge, tall - tag.height() - edge - foot))

        # Only in the quick look, only while nothing is loaded at all.
        empty = (self.level == "view" and not full
                 and not any(row.field.text().strip() for row in self.rows))
        self.empty_card.setVisible(empty)
        if empty:
            self.empty_card.adjustSize()
            self.empty_card.move(
                max(edge, (wide - self.empty_card.width()) // 2),
                max(edge, (tall - self.empty_card.height()) // 2))
            self.empty_card.raise_()

        hint = self.frame_hint
        said = self._frame_hint_text() if (
            self.level == "view" and not full and not empty
            and self.mode.currentText() == PREVIEW) else ""
        hint.setVisible(bool(said))
        if said:
            hint.setText(said)
            hint.adjustSize()
            hint.move(edge, max(edge, tall - hint.height() - 12))
            hint.raise_()

    def _frame_hint_text(self) -> str:
        """What the frame is, and what the hand does, in one line."""
        if self.mesh is None:
            return ""
        across, down = self.mesh.cropped or self.mesh.frame
        what = (tr("Рамка = кадр рендера {0}×{1}", int(across), int(down))
                if self.frame_button.isChecked() else tr("Рамка выключена"))
        return tr("{0} · колесо — ближе, двойной щелчок — сброс", what)

    def _lay_frame_edge(self) -> None:
        """Where the render's rectangle lands on the canvas, as a line.

        In logical pixels: this is a widget, and on a scaled display those are
        not the pixels the picture is drawn in.
        """
        if not hasattr(self, "frame_edge"):
            return
        # Not while cropped into: zoomed in, the line still marks the frame
        # but the picture inside it is a piece of the frame rather than the
        # frame, and a rectangle that says "this is what gets written" over
        # something else is worse than no rectangle. It comes back on the way
        # out -- at the far end of the wheel, or on a reset.
        # In Inspection there is no wheel crop to fall inside, so the line
        # always marks the render rectangle; in Preview it hides while cropped
        # in, where the picture is a piece of the frame rather than the frame.
        mode = self.mode.currentText()
        showing = (self.frame_button.isChecked()
                   and self.mesh is not None
                   and ((mode == PREVIEW and self.mesh.zoom >= 1.0)
                        or mode == "Inspection"))
        self.frame_edge.setVisible(showing)
        if not showing:
            return
        shape = self.mesh.cropped or self.mesh.frame
        left, top, across, down = self._fitted(
            *shape, into=(self.canvas.width(), self.canvas.height()))
        self.frame_edge.setGeometry(round(left), round(top),
                                    round(across), round(down))
        # Over the picture, and under everything else laid over it: the bar,
        # the keys, the offer to load, the readings of ReBake.
        self.frame_edge.raise_()
        for widget in self._over_the_frame():
            widget.raise_()

    def _over_the_frame(self) -> list:
        """What is laid over the picture, the frame's line excepted."""
        names = ("look_bar", "keys_button", "keys_card", "frame_hint",
                 "empty_card", "full_bar", "rebake_left_alpha",
                 "rebake_right_alpha", "rebake_before", "rebake_after")
        return [getattr(self, name) for name in names if hasattr(self, name)]

    def _show_overlays(self, on: bool) -> None:
        if not hasattr(self, "overlays"):
            return
        for widget in self.overlays:
            widget.setVisible(on)
        if on:
            self._lay_overlays()
            for widget in self.overlays:
                widget.raise_()

    def _rebake_recipe(self):
        """What the panel is asking for, as the shader and the job want it."""
        return (int(self.rebake_what.currentData()),
                int(self.rebake_threshold.value()),
                int(self.rebake_colour.currentData()))

    def _offer_ffmpeg(self) -> None:
        """Put the Download button up, or take it down, by what is missing."""
        if not hasattr(self, "rebake_get"):
            return
        needs = rebake.ENCODERS.get(int(self.rebake_format.currentData()), "")
        missing = bool(needs) and not depends.can_encode(needs)
        self.rebake_get.setVisible(missing and depends.can_download())
        self._lay_overlays()
        if missing:
            self.rebake_note.setText(tr("ни в одном ffmpeg здесь нет "
                                        "кодировщика {0}", needs))

    def _get_ffmpeg(self) -> None:
        """Fetch one that has it, saying so on the re-bake's own progress bar."""
        if self.job is not None:
            return
        self.rebake_get.setEnabled(False)
        self.rebake_button.setEnabled(False)
        self.rebake_progress.setRange(0, 100)
        self.rebake_progress.setValue(0)
        self.rebake_note.setText(tr("качаю ffmpeg…"))
        logfile.write("rebake: fetching an ffmpeg that has the encoder")
        self.job = jobs.DownloadJob(self)
        self.job.progress.connect(self._ffmpeg_progress)
        self.job.failed.connect(self._ffmpeg_failed)
        self.job.finished_ok.connect(self._ffmpeg_here)
        self.job.start()

    def _ffmpeg_progress(self, done: int, total: int) -> None:
        self.rebake_progress.setValue(int(100 * done / total) if total else 0)
        self.rebake_note.setText(
            tr("качаю ffmpeg: {0:.0f} из {1:.0f} МБ", done / 1e6, total / 1e6)
            if total else tr("качаю ffmpeg: {0:.0f} МБ", done / 1e6))

    def _ffmpeg_failed(self, why: str) -> None:
        self.job = None
        self.rebake_get.setEnabled(True)
        self.rebake_button.setEnabled(True)
        self.rebake_progress.setValue(0)
        self.rebake_note.setText(tr("не скачалось: {0}", why[:60]))
        logfile.write(f"rebake: could not fetch ffmpeg: {why}")

    def _ffmpeg_here(self, where: str) -> None:
        self.job = None
        self.rebake_get.setEnabled(True)
        self.rebake_button.setEnabled(True)
        self.rebake_progress.setValue(0)
        # Everything that remembers what ffmpeg can do is now out of date.
        depends.forget_ffmpeg()
        export.refresh_ffmpeg()
        logfile.write(f"rebake: ffmpeg fetched to {where}")
        self._offer_ffmpeg()
        if not self.rebake_get.isVisible():
            self.rebake_note.setText(tr("готово — в этом кодировщик есть"))

    def _rebake_changed(self, *_) -> None:
        """Hand the panel's settings to the screens that are showing."""
        what, threshold, colour = self._rebake_recipe()
        self.rebake_threshold.setEnabled(what == rebake.CLEAN)
        self.rebake_colour.setEnabled(what == rebake.CLEAN)
        screens = [screen for _, screen in self._rebake_screens()]
        ready = True
        if what == rebake.DITHER and screens:
            ready = self._need_noise(screens)
        for screen in screens:
            # Until the map is there, the dither has nothing to dither against,
            # and a half that quietly showed the file as it is would be a lie
            # about what the re-bake does. Both halves show the file instead,
            # and the note says why.
            screen.set_rebake(what if ready else rebake.OFF,
                              threshold / 255.0, colour)
        self.touch()
        self._remember()

    def _rebake_work(self):
        """Which screens can be re-baked, and what each would be called."""
        work, skipped = [], []
        what, threshold, colour = self._rebake_recipe()
        for row in self.rows:
            if row.title not in self.REBAKE_ROWS:
                continue
            text = row.field.text().strip()
            if not text:
                continue
            screen = self._screen_of(row.screen)
            if screen is None or not screen.has_alpha:
                skipped.append(row.title)
                continue
            source = Path(text)
            work.append((source, source.parent / rebake.named(
                source, what, threshold, colour,
                kind=int(self.rebake_format.currentData()))))
        return work, skipped

    def _screen_of(self, feeds: str):
        """The card-side screen a row is feeding, if it is loaded at all."""
        for index in range(min(len(self.feeding), len(self.screens))):
            if self.feeding[index] == feeds:
                return self.screens[index]
        return None

    def _probe(self) -> None:
        """This frame, both screens, at the size the file really is."""
        if not self.screens:
            self.rebake_note.setText(tr("пробовать нечего: ничего не загружено"))
            return
        what, threshold, colour = self._rebake_recipe()
        folder = self.out_dir / rebake.PROBES
        at, _ = self._frame_now()
        written = []
        try:
            folder.mkdir(parents=True, exist_ok=True)
            for row in self.rows:
                if row.title not in self.REBAKE_ROWS:
                    continue
                text = row.field.text().strip()
                screen = self._screen_of(row.screen)
                if not text or screen is None or not screen.has_alpha:
                    continue
                name = rebake.named(Path(text), what, threshold, colour,
                                    probe=True)
                target = folder / f"{Path(name).stem}_{at:06d}.png"
                self._write_rgba(self.painter.frame_of(screen), target)
                written.append(target)
        except Exception as error:  # noqa: BLE001 -- said in the window
            self.rebake_note.setText(tr("проба не удалась: {0}", error))
            logfile.write(f"проба не удалась: {error}")
            return
        if not written:
            self.rebake_note.setText(tr("ни у одного экрана здесь нет альфы"))
            return
        self.rebake_note.setText(
            f"-> {rebake.PROBES}/{written[0].name}"
            + (f" and {len(written) - 1} more" if len(written) > 1 else ""))
        for path in written:
            logfile.write(f"probe: {path}")

    def _write_rgba(self, picture, target: Path) -> None:
        """An RGBA array to a PNG, alpha and all."""
        flat = np.ascontiguousarray(picture)
        height, width = flat.shape[:2]
        image = QImage(flat.data, width, height, width * 4,
                       QImage.Format.Format_RGBA8888)
        if not image.save(str(target)):
            raise OSError(f"could not write {target}")

    def _start_rebake(self) -> None:
        if self.job is not None or not self.streams:
            self.rebake_note.setText(tr("перепекать нечего: ничего не загружено"))
            return
        if not depends.ffmpeg_version():
            self.rebake_note.setText(tr("перепечь нечем: не найден ffmpeg"))
            return
        work, skipped = self._rebake_work()
        if not work:
            self.rebake_note.setText(tr("ни у одного экрана здесь нет альфы"))
            return
        already = [target.name for _, target in work if target.exists()]
        if already:
            self.rebake_note.setText(tr("{0} уже есть — уберите его", already[0]))
            return

        # Asked before the first frame rather than found out when the pipe
        # breaks. Not every ffmpeg has every encoder: the Homebrew build has
        # no hap at all, and what came back from it was "Broken pipe".
        kind = int(self.rebake_format.currentData())
        needs = rebake.ENCODERS.get(kind, "")
        if needs and not depends.can_encode(needs):
            self.rebake_note.setText(
                tr("ни в одном ffmpeg здесь нет кодировщика {0}", needs)
                + ("  -- the button beside the format fetches one"
                   if depends.can_download() else ""))
            logfile.write(
                f"rebake refused: {self.rebake_format.currentText()} needs the "
                f"{needs} encoder and none of "
                + ", ".join(depends.ffmpeg_candidates() or ["nothing found"])
                + " has it")
            return

        what, threshold, colour = self._rebake_recipe()
        logfile.write("-" * 78)
        logfile.write(f"rebake: as {self.rebake_format.currentText()}, "
                      f"{rebake.NAMES[what]}"
                      + (f" below {threshold}, colour "
                         f"{rebake.COLOUR_NAMES[colour]}"
                         if what == rebake.CLEAN else ""))
        for source, target in work:
            logfile.write(f"   {source.name} -> {target}")
        for name in skipped:
            logfile.write(f"   {name} skipped: nothing there carries an alpha")

        self.canvas.set_update_mode("manual")
        self.rebake_button.setEnabled(False)
        self.probe_button.setEnabled(False)
        self.rebake_stop.setEnabled(True)
        self.rebake_progress.setVisible(True)
        self.rebake_progress.setRange(0, 1)
        self.rebake_progress.setValue(0)
        self.rebake_note.setText(tr("перепекаю…"))

        # Kept for the swap at the end: the job reports what it wrote, and
        # this says what each of those was made from.
        self._rebake_pairs = list(work)
        self.job = jobs.RebakeJob(self.painter, work, what, threshold, colour,
                                  kind, parent=self)
        self.job.progress.connect(self._rebake_progress)
        self.job.failed.connect(self._rebake_failed)
        self.job.finished_ok.connect(self._rebake_done)
        self.job.start()

    def _rebake_progress(self, done: int, total: int, rate: float,
                         eta: float) -> None:
        self.rebake_progress.setRange(0, total)
        self.rebake_progress.setValue(done)
        self.rebake_note.setText(
            f"{done}/{total} frames, {rate:.1f} a second, {eta:.0f} s left")

    def _rebake_failed(self, why: str) -> None:
        self._rebake_over()
        self.rebake_note.setText(tr("остановлено") if why == "cancelled" else why[:70])
        logfile.write(f"rebake: {why}")

    @staticmethod
    def _free_name(path: Path, tag: str) -> Path:
        """`name_old.mov`, or `name_old_2.mov` where that is taken already."""
        aside = path.with_name(f"{path.stem}{tag}{path.suffix}")
        count = 2
        while aside.exists():
            aside = path.with_name(f"{path.stem}{tag}_{count}{path.suffix}")
            count += 1
        return aside

    def _swap_in(self, pairs):
        """The re-baked file takes the source's name; the source steps aside.

        Done here rather than in the job because the window is still holding
        the sources open, and Windows will not rename a file that something
        has open. The streams are let go first and put back afterwards, so
        the rows keep pointing at the same names and those names now hold the
        re-baked pictures.
        """
        for stream in self.streams:
            stream.stop()
        self.streams = []
        moved, stuck = [], []
        for source, target in pairs:
            if not target.exists():
                continue
            aside = self._free_name(source, "_old")
            try:
                source.rename(aside)
            except OSError as trouble:
                stuck.append(f"{source.name}: {trouble.strerror or trouble}")
                continue
            try:
                target.rename(source)
            except OSError as trouble:
                aside.rename(source)          # put it back rather than leave a hole
                stuck.append(f"{target.name}: {trouble.strerror or trouble}")
                continue
            moved.append((source, aside))
            logfile.write(f"   {source.name} -> {aside.name}, "
                          f"{target.name} -> {source.name}")
        self._load()
        return moved, stuck

    def _rebake_done(self, result: dict) -> None:
        self._rebake_over()
        names = [Path(one).name for one in result["files"]]
        logfile.write(f"rebake: wrote {result['frames']} frames to "
                      + ", ".join(result["files"]))
        # Only Hap Q Alpha steps into the source's place. ProRes is written
        # for somewhere else -- it is not the format the wall plays -- so it
        # stays under its own name and the sources are not touched.
        if int(self.rebake_format.currentData()) != rebake.HAPM:
            self.rebake_note.setText(tr("записано: ") + ", ".join(names))
            return
        moved, stuck = self._swap_in(getattr(self, "_rebake_pairs", []))
        if stuck:
            self.rebake_note.setText(tr("записано, но не встало на место — ")
                                     + stuck[0][:60])
            logfile.write("rebake: could not swap: " + "; ".join(stuck))
            return
        if moved:
            self.rebake_note.setText(
                tr("на месте: {0}; прежние оставлены как ", len(moved))
                + ", ".join(aside.name for _, aside in moved))
        else:
            self.rebake_note.setText(tr("записано: ") + ", ".join(names))

    def _rebake_over(self) -> None:
        self.job = None
        self.rebake_button.setEnabled(True)
        self.probe_button.setEnabled(True)
        self.rebake_stop.setEnabled(False)
        self.rebake_progress.setVisible(False)
        self.canvas.set_update_mode("ondemand")
        self.touch()

    def _output_name(self) -> str:
        """What the file will be called, extension and all.

        The extension is not a thing to be asked for twice: it is already
        settled by the format chosen beside the name, so a name typed without
        one gets it from there rather than being refused at the last moment.
        """
        _, suffix = self.format_choice.currentData()
        name = self.out_name.text().strip() or "preview_v1"
        if Path(name).suffix.lower() not in SUFFIXES:
            name += suffix
        return name

    def _format_changed(self, index: int = -1) -> None:
        # By index when the list said which, by what is chosen when the list
        # has just been rebuilt and the old index means nothing.
        chosen = (self.format_choice.itemData(index) if index >= 0
                  else self.format_choice.currentData())
        if chosen is None:
            return
        _, suffix = chosen
        was = self.out_name.text().strip()
        name = Path(was or "preview_v1")
        if name.suffix.lower() in SUFFIXES:
            name = name.with_suffix(suffix)
        else:
            name = Path(str(name) + suffix)
        if was and was == self._auto_name:
            self._auto_name = str(name)
        self.out_name.setText(str(name))

    def _pick_output(self) -> None:
        """Choose the file, not the folder it goes in.

        A render is one file with a name. Being asked for a folder here and
        then made to type the name into a different box is two answers to one
        question, and the two can disagree.
        """
        label, _, suffix = next(
            (f for f in export.FORMATS
             if f[1:] == tuple(self.format_choice.currentData())),
            export.FORMATS[0])
        chosen, _ = QFileDialog.getSaveFileName(
            self, "Where to write", str(self.out_dir / self._output_name()),
            f"{label} (*{suffix});;All files (*)",
            # The dialog does not promise to overwrite, because RENDER will
            # not: it stops and says to press +1 instead. One refusal, in one
            # place, rather than a warning here and a different answer later.
            options=QFileDialog.Option.DontConfirmOverwrite)
        if not chosen:
            return
        path = Path(chosen)
        if path.suffix.lower() not in SUFFIXES:
            path = path.with_name(path.name + suffix)
        self.out_dir = path.parent
        self.out_name.setText(path.name)
        self._auto_name = None          # chosen by hand; stop guessing at it
        self._note_output()
        self._remember()

    def _name_from_sources(self) -> None:
        """Name the render after the content, when the content says its name.

        Top and Bottom nearly always arrive as one piece cut in two --
        `Something_top.mov` beside `Something_bottom.mov` -- and then
        `Something` is what the render is of, and typing it out again is
        somebody copying a name off their own screen.

        Only when the two agree, and only while the name box still holds a
        name this worked out or the one it opened with. A name somebody typed
        is never taken away from them.
        """
        if self.out_name.text().strip() != (self._auto_name or ""):
            return
        found = {}
        for row in self.rows:
            if row.overlay or row.sound or row.motors:
                continue
            text = row.field.text().strip()
            if text:
                found[row.title] = Path(text).stem
        top, bottom = found.get("Top", ""), found.get("Bottom", "")
        if not (top.lower().endswith("_top")
                and bottom.lower().endswith("_bottom")):
            return
        stem = top[:-len("_top")]
        if not stem or stem.lower() != bottom[:-len("_bottom")].lower():
            return
        _, suffix = self.format_choice.currentData()
        self._auto_name = f"{stem}_v1{suffix}"
        self.out_name.setText(self._auto_name)
        logfile.write(f"output named after the sources: {self._auto_name}")

    def _bump_version(self) -> None:
        import re
        name = self.out_name.text().strip()
        match = re.search(r"_v(\d+)(\.[A-Za-z0-9]+)$", name)
        if match:
            name = f"{name[:match.start()]}_v{int(match.group(1)) + 1}{match.group(2)}"
        else:
            stem, dot, suffix = name.rpartition(".")
            name = f"{stem}_v2{dot}{suffix}" if dot else f"{name}_v2"
        self.out_name.setText(name)

    def _range_here(self, end: bool) -> None:
        """The render's first or last frame, where the playhead stands."""
        at, _ = self._frame_now()
        box = self.last_frame if end else self.first_frame
        box.setValue(at)
        self._range_changed()
        self._say_range()

    def _range_from_show(self, first: int, last: int) -> None:
        """A clip of the show, as the render's range: show frames in, frames
        of the grid it is watched on out."""
        grid = self.clock.rate or 60.0
        begins = int(round(first * grid / showfile.FPS))
        ends = max(begins, int(round(last * grid / showfile.FPS)) - 1)
        self.first_frame.setValue(begins)
        self.last_frame.setValue(ends)
        self._say_range()

    def _say_range(self) -> None:
        """Mark the render's range where time is shown, when it is not all."""
        if not hasattr(self, "slider"):
            return
        _, last = self._frame_now()
        begins, ends = self.first_frame.value(), self.last_frame.value()
        whole = last <= 0 or (begins, ends) == (0, last)
        count = max(1, last + 1)
        part = None if whole else (begins / count, (ends + 1) / count)
        self.slider.set_range(part)
        self.full_slider.set_range(part)
        grid = self.clock.rate or 60.0
        self.show_view.set_render_range(
            None if whole else (begins * showfile.FPS / grid,
                                (ends + 1) * showfile.FPS / grid))

    def _range_changed(self, *_) -> None:
        """Keep the end at or after the beginning, whichever was moved."""
        if self.last_frame.value() < self.first_frame.value():
            mover = self.sender()
            if mover is self.first_frame:
                self.last_frame.setValue(self.first_frame.value())
            else:
                self.first_frame.setValue(self.last_frame.value())

    def _reset_range(self) -> None:
        """The whole piece.

        Called whenever the content or the grid changes, rather than kept from
        one to the next. A range is about the piece in front of you; carried
        over to a different one it would quietly write a fragment of it, and
        the first anybody would know is the file.
        """
        _, last = self._frame_now()
        for box in (self.first_frame, self.last_frame):
            box.blockSignals(True)
            box.setRange(0, last)
            box.blockSignals(False)
        self.first_frame.setValue(0)
        self.last_frame.setValue(last)

    def _note_output(self) -> None:
        """The folder, in the field before the name: its end, which is the
        part that tells one folder from the next."""
        folder = str(self.out_dir).rstrip("\\/") + ("\\" if sys.platform == "win32"
                                                     else "/")
        self.out_folder.setText(folder)
        # Shown from its end, where one folder differs from the next.
        self.out_folder.setCursorPosition(len(folder))

    def _folder_typed(self) -> None:
        """A folder typed by hand: taken when it is a whole path.

        Anything else -- a bare name, half a path -- is put back as it was,
        and the status line says why: a render written into wherever the
        program happened to be started from is not a render anybody finds.
        """
        typed = self.out_folder.text().strip().strip('"')
        if typed and typed.rstrip("\\/") != str(self.out_dir).rstrip("\\/"):
            where = Path(typed).expanduser()
            if where.is_absolute() and not where.is_file():
                self.out_dir = where
                logfile.write(f"output folder typed: {where}")
                self._remember()
            else:
                self.eta.setText(tr("Папка — это полный путь, например "
                                    "D:\\Renders; осталась прежняя"))
        self._note_output()

    def _name_typed(self) -> None:
        """A whole path typed or pasted into the name: its folder and its name."""
        typed = self.out_name.text().strip().strip('"')
        if not ("\\" in typed or "/" in typed):
            return
        where = Path(typed).expanduser()
        if not where.is_absolute() or not where.name:
            return
        self.out_dir = where.parent
        self.out_name.setText(where.name)
        logfile.write(f"output typed whole: {where}")
        self._note_output()
        self._remember()

    # -- rendering it out ------------------------------------------------------

    FLAT_SUFFIX = "_flat"

    def _flat_work(self):
        """Every strip that would be written, and what each would be called.

        One file per screen, named after the file that feeds it, because a
        strip is that file laid out flat and nothing else. Empty rows are
        left out: what a strip shows without a file is the calibration, and
        nobody wants a video of that.
        """
        scale = float(self.size_choice.currentData() or 1.0)
        work = []
        _, suffix = self.format_choice.currentData()
        in_show = self.level == "show" and self.show_open is not None
        for name in self._flat_showing():
            row = next((r for r in self.rows
                        if r.screen == name and not r.overlay
                        and r.field.text().strip()), None)
            if in_show:
                # A show's strip is the show's screen, named after the show.
                row = None
                if name not in self.composers:
                    continue
            elif row is None:
                continue
            across, down = self._pixels(name)
            # Down to a multiple of four. Every encoder here wants an even
            # width and hap wants four, and 1150 or 110 rows are neither --
            # so this bites at the native size too, not only at a quarter of
            # it. Two rows off the bottom of a screen nobody looks at pixel
            # by pixel beats a render that will not start.
            wide = max(4, int(across * scale) // 4 * 4)
            tall = max(4, int(down * scale) // 4 * 4)
            if in_show:
                source = Path(self.trix_path or "rows")
                named = self._safe_stem(self.show_open.name or source.stem)
                stem = f"{named}_{SHORT.get(name, name)}{self.FLAT_SUFFIX}"
            else:
                source = Path(row.field.text().strip())
                # A sequence of stills is not a file but a heap of them, and
                # three heaps of three sizes in one folder cannot be told
                # apart. Each gets a folder of its own, named the way the
                # videos are.
                stem = f"{source.stem}{self.FLAT_SUFFIX}"
            kind, _ = self.format_choice.currentData()
            target = (self.out_dir / stem if kind.startswith("png")
                      else self.out_dir / f"{stem}{suffix}")
            work.append((name, source, target, wide, tall))
        return work

    def _start_flat_export(self) -> None:
        """The strips, each written on its own, at the wall's own size."""
        work = self._flat_work()
        if not work:
            self.eta.setText(tr("Нечего записывать: ничего не загружено"))
            return
        already = [target.name for _, _, target, _, _ in work
                   if target.exists()]
        if already:
            self.eta.setText(tr("{0} уже есть — уберите его или смените имя", already[0]))
            return

        kind, _ = self.format_choice.currentData()
        rate = float(self.fps_choice.currentData())
        grid = self.clock.rate or 60.0
        begins, ends = self.first_frame.value(), self.last_frame.value()
        first = int(round(begins / grid * rate))
        count = max(1, int(round((ends + 1 - begins) / grid * rate)))

        # An alpha and a backing are the same question answered twice: the
        # calibration behind the content would fill in everything transparent
        # and there would be no alpha left to write. Taken off for the writing
        # and put back after, and said so, because it is a switch the window
        # shows and this quietly disagrees with it.
        self._backing_was = None
        if kind in export.CARRY_ALPHA and self.backing.currentText() != "None":
            self._backing_was = self.backing.currentText()
            self.backing.setCurrentText("None")
            logfile.write(f"render: backing {self._backing_was} taken off, "
                          f"an alpha is being written")

        logfile.write("-" * 78)
        _, last = self._frame_now()
        part = ("the whole piece" if (begins, ends) == (0, last)
                else f"frames {begins} to {ends} of {last}")
        logfile.write(f"render: flat, {part}, on a {grid:g} fps grid")
        logfile.write(f"render: {count} frames at {rate:g} fps, "
                      f"{self.format_choice.currentText()}, "
                      f"{self.size_choice.currentText().lower()} of each screen")
        for name, source, target, wide, tall in work:
            logfile.write(f"   {SHORT.get(name, name)}  {source.name}  "
                          f"{wide}x{tall} -> {target}")

        self.canvas.set_update_mode("manual")
        self.render_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self._writing(True)
        self.progress.setRange(0, count * len(work))
        self.progress.setValue(0)

        bare = kind in export.CARRY_ALPHA
        self.job = jobs.FlatExportJob(
            self.streams, self.screens,
            lambda screen, wide, tall: self._screen_to_array(
                screen, wide, tall, bare=bare),
            [(name, target, wide, tall) for name, _, target, wide, tall in work],
            kind, first, count, rate, int(self.fps_choice.currentData()),
            compose=self._render_compose(), parent=self)
        self.job.progress.connect(self._export_progress)
        self.job.failed.connect(self._export_failed)
        self.job.finished_ok.connect(self._export_done)
        self.job.start()

    def _start_export(self) -> None:
        if self.job is not None or self.solid is None:
            return
        if not depends.ffmpeg_version():
            self.eta.setText(tr("Видео записать нечем: не найден ffmpeg"))
            logfile.write("render refused: no ffmpeg on this machine")
            return
        # Flat is not one picture: it is the screens laid out to be read one
        # at a time, so it writes them one at a time.
        if self.flat_mode():
            self._start_flat_export()
            return
        in_show = self.level == "show"
        if not self.streams and not (in_show and (self.mix is not None
                                                  or self.show_motors)):
            self.eta.setText(tr("Нечего записывать: ничего не загружено"))
            return
        # Written back into the box as well, so that what is about to be
        # made and what is on screen are the same string.
        name = self._output_name()
        self.out_name.setText(name)
        target = self.out_dir / name
        if target.exists():
            self.eta.setText(tr("{0} уже есть — нажмите +1, чтобы записать "
                                "следующей версией", target.name))
            return

        # Back to the whole frame before a single frame is written. On screen
        # the picture runs past the frame and the wheel crops into it; the
        # file is the frame itself, so what is about to be written and what
        # is about to be shown are made the same thing rather than left to
        # differ by however far somebody had zoomed.
        #
        # In Inspection the reset is held back: the whole point of the mode is
        # the angle somebody chose, and resetting the orbit would write the
        # file camera's view instead. Only the opening out is undone, so the
        # frame area is written at the output shape from that same angle.
        if not self.inspecting():
            self.reset_view()
        self.solid.show_around(1.0, 1.0)

        width, height = self.size_choice.currentData()
        kind, _ = self.format_choice.currentData()
        # The written rate is chosen, not inherited: the sources are sixty and
        # thirty is what these go out at. Each stream still picks its own
        # nearest frame for the instant, because the clock is in seconds.
        rate = float(self.fps_choice.currentData())
        # The range is given in frames of the Sync grid and written in frames
        # of this one, so it goes through seconds. A frame lasts one grid step,
        # which is why the last one counts as a whole frame and not as an
        # instant -- ask for 0 to 0 and one frame comes out, not none.
        #
        # The sound counts towards the length: a piece whose audio runs on
        # past the last picture is still that long, and cutting it there would
        # be a decision nobody asked for. That is already in the duration the
        # range was set from.
        grid = self.clock.rate or 60.0
        begins, ends = self.first_frame.value(), self.last_frame.value()
        first = int(round(begins / grid * rate))
        count = max(1, int(round((ends + 1 - begins) / grid * rate)))

        # The sound from where the range begins, not from its own start: a
        # range halfway into the piece had the first seconds of the WAV laid
        # under it. A show's sounds are one mix, written out for ffmpeg to
        # read -- on the render's thread, before its first frame.
        heard, before = (self.track.path if self.track else None), None
        if in_show and self.mix is not None:
            folder = logfile.app_dir() / "temp"
            folder.mkdir(parents=True, exist_ok=True)
            heard = self._mix_file = folder / f"show_mix_{int(time.time())}.wav"
            before = lambda mix=self.mix, where=heard: mix.write(where)
        output = export.Output(kind=kind, path=target, fps=int(rate),
                               width=width, height=height, sound=heard,
                               sound_from=first / rate)
        self._log_render(output, count, rate, begins, ends)

        # The device belongs to the render while it runs; the canvas stops
        # drawing rather than competing for it.
        self.canvas.set_update_mode("manual")
        self.render_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self._writing(True)
        self.progress.setRange(0, count)
        self.progress.setValue(0)

        compose = self._render_compose()
        self.job = jobs.ExportJob(self.streams, self.screens, self.solid,
                                  output, first, count, rate,
                                  move=self._move_screens, compose=compose,
                                  before=before, parent=self)
        self.job.progress.connect(self._export_progress)
        self.job.failed.connect(self._export_failed)
        self.job.finished_ok.connect(self._export_done)
        self.job.start()

    def _log_render(self, output, count: int, rate: float,
                    begins: int, ends: int) -> None:
        logfile.write("-" * 78)
        _, last = self._frame_now()
        part = ("the whole piece" if (begins, ends) == (0, last)
                else f"frames {begins} to {ends} of {last}")
        logfile.write(f"render: {part}, on a {self.clock.rate:g} fps grid")
        logfile.write(f"render: {count} frames at {rate:g} fps, "
                      f"{output.width}x{output.height}, "
                      f"{self.format_choice.currentText()} "
                      f"[{output.chosen_encoder}] -> {output.path}")
        if self.level == "show" and self.show_open is not None:
            logfile.write(f"   show: {self.show_open.describe()}; every loop "
                          f"played once")
        for stream in self.streams:
            movie = stream.movie
            if movie is None:
                continue
            logfile.write(f"   {movie.path.name}: {movie.kind} "
                          f"{movie.frames} frames {stream.duration:.2f} s")
        heard = self.mix if self.level == "show" else self.track
        if output.takes_sound and heard is not None:
            logfile.write(f"   {output.sound.name}: {heard.describe()}")
        elif heard is not None:
            logfile.write("   sound is loaded but this format has nowhere "
                          "to put it")

    def _cancel_export(self) -> None:
        if self.job is not None:
            self.job.cancel()

    def _export_progress(self, done, total, fps, eta) -> None:
        self.progress.setValue(done)
        self.eta.setText(tr("{0} из {1}   {2:.1f} к/с   осталось {3:.0f} с",
                            done, total, fps, eta))

    def _backing_back(self) -> None:
        """Put the backing back, if writing an alpha took it off."""
        if getattr(self, "_backing_was", None):
            self.backing.setCurrentText(self._backing_was)
            self._backing_was = None

    def _open_out(self) -> None:
        """The folder the render went into, in the file manager."""
        folder = str(self.out_dir)
        opener = {"win32": ["explorer"], "darwin": ["open"]}.get(
            sys.platform, ["xdg-open"])
        try:
            subprocess.Popen(opener + [folder])
        except OSError as trouble:  # noqa: BLE001 -- said in the log
            logfile.write(f"could not open {folder}: {trouble}")

    def _writing(self, on: bool) -> None:
        """While a file is being written: the bar that says how far, and Stop."""
        self.progress.setVisible(on)
        self.cancel_button.setVisible(on)
        for widget in self._idle_only:
            widget.setVisible(not on)
        if on:
            self.open_out.setVisible(False)

    def _export_finished(self) -> None:
        self._writing(False)
        self.job = None
        self._backing_back()
        if self._mix_file is not None:
            try:
                Path(self._mix_file).unlink(missing_ok=True)
            except OSError as trouble:  # noqa: BLE001 -- said in the log
                logfile.write(f"could not remove {self._mix_file}: {trouble}")
            self._mix_file = None
        self.render_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.canvas.set_update_mode("continuous")
        self.canvas.request_draw(self._draw)

    def _export_failed(self, message: str) -> None:
        lines = message.strip().splitlines() or [message]
        self.eta.setText(tr("Остановлено") if lines[0] == "cancelled"
                         else tr("Не записано: ") + lines[0][:70])
        logfile.write("RENDER FAILED: " + message)
        self._export_finished()

    def _export_done(self, result: dict) -> None:
        self.progress.setValue(self.progress.maximum())
        self.open_out.setVisible(True)
        self.open_out.setToolTip(str(self.out_dir))
        self.eta.setText(tr("Записано: {0} кадров за {1:.0f} с ({2:.1f} к/с)",
                            result['frames'], result['seconds'], result['fps']))
        logfile.write(f"saved: {result['output']}  ({result['encoder']})")
        if result.get("complaints"):
            logfile.write("ffmpeg said: " + result["complaints"])
        self._export_finished()

    def _open_log(self) -> None:
        """Show the folder this session is being written to.

        A new process rather than QDesktopServices, which on Windows is
        ShellExecute on this very thread. Opening a folder that way starts a
        conversation with the shell carried on broadcast messages, and this
        process is a bad place to hold one: the graphics driver leaves
        top-level windows of its own here -- NVOpenGLPbuffer, a temporary
        D3D window, the device's own -- on threads that run no message loop.
        A broadcast waits on every one of them while this thread waits inside
        the call, and the result was the window and Explorer both stopping
        until this process was killed.

        Handing the path to a new explorer keeps all of that outside.
        """
        where = logfile.path()
        if where is None:
            return
        folder = str(where.parent)
        opener = {"win32": ["explorer"], "darwin": ["open"]}.get(
            sys.platform, ["xdg-open"])
        try:
            # Never waited on: explorer answers when it feels like it, and
            # `explorer` returns 1 even when it worked.
            subprocess.Popen(opener + [folder])
        except OSError as trouble:  # noqa: BLE001 -- said in the log
            logfile.write(f"could not open {folder}: {trouble}")

    # -- choosing the files -------------------------------------------------

    def _pick(self, row: Row) -> None:
        start = str(Path(row.field.text()).parent) if row.field.text() else ""
        if row.motors:
            chosen, _ = QFileDialog.getOpenFileName(
                self, tr("Выбрать JSON моторов"), start,
                tr("Моторы (*.json);;Все файлы (*)"))
        elif row.sound:
            chosen, _ = QFileDialog.getOpenFileName(
                self, tr("Выбрать WAV"), start, tr("Звук (*.wav);;Все файлы (*)"))
        else:
            chosen, _ = QFileDialog.getOpenFileName(
                self, tr("Выбрать ролик или картинку"), start,
                tr("Ролики и картинки (*.mov *.mp4 *.m4v *.mkv *.avi "
                   "*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp *.tga);;"
                   "Ролики (*.mov *.mp4 *.m4v *.mkv *.avi);;"
                   "Картинки (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp *.tga);;"
                   "Все файлы (*)"))
        if chosen:
            row.field.setText(chosen)
            self._load()

    # -- the panel of sources -----------------------------------------------

    def row_for(self, title: str):
        """The row of that name: Top, Bottom, Lamels, Frame, Sound, Kinetic."""
        return next((row for row in self.rows if row.title == title), None)

    def kinetic_rows(self) -> list:
        """The row that takes a motor file, as a list for what asks for one."""
        return [row for row in self.rows if row.motors]

    def _fold_sources(self, open_it=None) -> None:
        """Show the cards or fold the column to its marks."""
        if open_it is None:
            open_it = not self.sources_open
        self.sources_open = bool(open_it)
        self._lay_sources()
        self._say_sources()
        self._remember()

    def sources_summary(self) -> str:
        """What is loaded, card by card, in one line."""
        said = []
        for row in self.rows:
            text = row.field.text().strip()
            if not text:
                continue
            more = ""
            if row.motors and self.motors is not None \
                    and len(self.motors.parts) > 1:
                more = f" +{len(self.motors.parts) - 1}"
            said.append(f"{row.title}: {Path(text).name}{more}")
        return "   ".join(said) or tr("ничего не загружено")

    def _say_sources(self) -> None:
        """How many cards have a file, and the marks of the folded column."""
        loaded = [row for row in self.rows if row.field.text().strip()]
        self.sources_count.setText(tr("{0} из {1} загружено",
                                      len(loaded), len(self.rows)))
        self.sources_head.setText(tr("Источники") if self.sources_open else "›")
        whole = self.sources_summary()
        HINTS[self.sources_head] = (
            tr("Источники — свернуть") if self.sources_open
            else tr("Источники — развернуть"),
            whole + tr("\n\nКарточки с файлами: что на каком экране, звук, "
               "моторы. Свёрнутые — картинке достаётся вся ширина окна."))
        for row, mark in zip(self.rows, self.source_marks):
            text = row.field.text().strip()
            mark.setPixmap(theme.cell(row.title if text else "", 8))
            mark.setToolTip(f"{row.title}: {Path(text).name}" if text
                            else tr("{0}: пусто", row.title))

    def _load(self) -> None:
        if self.level == "show":
            self._load_show()
            return
        self._let_go_of_screens()
        self.show_open = None
        if self.device is None:
            return

        self._load_sound()
        self._load_motors()
        self._moved_to = None
        # Everything on the rows as one show, and each screen played out of
        # it by a Track -- the same way a show from the timeline will be.
        wanted = {row.title: row.field.text().strip() for row in self.rows
                  if not row.sound and not row.motors}
        self.show_now = showfile.single(wanted)
        for row in self.rows:
            if row.sound or row.motors:
                continue
            text = row.field.text().strip()
            row._shown()
            row.note.setText("")
            row.retell = None
            row.note.setStyleSheet(f"color:{theme.META};")
            if not text:
                continue
            try:
                clips = self.show_now.on(row.title)
                if not clips or clips[0].missing:
                    # Asked again, strictly this time, for the reason.
                    showfile.media_frames(text, strict=True)
                    raise showfile.ShowError(tr("{0} не открывается", Path(text).name))
                # A frame keeps its own size: where it sits on the screen is
                # decided below, not by resampling it into the screen's shape.
                stream = player.Track(
                    clips, screen=None if row.overlay
                    else self._pixels(row.screen))
                screen = screen_gpu.Screen(self.device, stream.movie)
            except Exception as error:  # noqa: BLE001 -- shown beside the field
                row.note.setText(str(error)[:60])
                row.retell = None
                row.note.setStyleSheet(f"color:{theme.ERROR};")
                logfile.write(f"{text}: {error}")
                continue
            stream.start()
            self.streams.append(stream)
            self.screens.append(screen)
            self.held.append(None)
            if row.overlay:
                self.feeding.append("")          # it feeds no screen of its own
                self.frame_at = len(self.streams) - 1
                self.frame_on = row.screen
                covers = self._covers(row, stream.movie)
                self.frame_covers = covers
                if self.solid is not None:
                    self.solid.set_frame(
                        row.screen, screen.planes[0].texture,
                        screen.planes[1].texture, screen.ycocg,
                        screen.alpha_from, screen.uv_scale, covers)
            else:
                self.feeding.append(row.screen)
                if (self.solid is not None
                        and row.screen in self.solid.calibration):
                    self.solid.set_video(
                        row.screen, screen.planes[0].texture,
                        screen.planes[1].texture,
                        screen.ycocg, screen.alpha_from, screen.uv_scale)
                    self.solid.set_video_opacity(1.0)
            # A clip of another shape re-shapes the surface under it rather
            # than becoming a different screen. One clip a row never does; the
            # show mode's tracks will.
            at = len(self.streams) - 1
            stream.on_change = (
                lambda _track, at=at, row=row: self._reshape(at, row))
            self._say_stream(row, stream)
            row.retell = (lambda row=row, stream=stream:
                          self._say_stream(row, stream))
            movie = stream.movie
            logfile.write(f"{Path(text).name}: {movie.width}x{movie.height} "
                          f"{movie.kind} {movie.frames} frames "
                          f"{stream.duration:.2f} s")

        self._gains_changed()
        # And, if this mode is on, whatever the panel is asking of them. The
        # screens here have just been built and a fresh one carries no
        # re-bake, so without this the right half shows the file as it is
        # until somebody happens to touch a control. It bites in both of the
        # ordinary ways in: dropping files in while already in the mode, and
        # opening a window that was left in it, where the mode is settled
        # before there is anything to settle it on.
        if self.mode.currentText() == "ReBake":
            self._rebake_changed()
        # The sound counts towards the length as much as the picture does. A
        # still under a six second WAV is a six second piece, and leaving the
        # sound out of this gave it a timeline of zero that nothing could be
        # scrubbed along.
        self.clock.duration = max(
            [s.duration for s in self.streams]
            + ([self.track.duration] if self.track else [])
            + ([self.motors.duration] if self.motors else []), default=0.0)
        # The marks on the slider are placed against this, so it is told here
        # rather than wherever the chain happened to be loaded.
        self._mark_span()
        self.clock.move_to(0.0)
        self.touch()
        moving = [s for s in self.streams if s.duration]
        if len({round(s.duration, 2) for s in moving}) > 1:
            logfile.write("the streams are of different lengths; the timeline "
                          "runs to the longest and the others end early")
        # Now that the rows are known, the render can take its name from them
        # and its range from how long they are.
        self._name_from_sources()
        self._reset_range()
        self._lay_overlays()
        # The files above all: what somebody dragged in is the expensive part
        # to do again, so it is written down as soon as it is loaded and not
        # left to depend on the window being closed politely.
        self._remember()

    def _say_stream(self, row, stream) -> None:
        """What the row's file is, beside it.

        Its own rate, not the track's: a track counts in frames of the show's
        sixty-a-second grid, and a thirty a second movie is still thirty.
        """
        movie = stream.movie
        if movie is None:
            return                   # let go of: the card keeps what it said
        rate = float(getattr(movie, "rate", 0.0) or 0.0)
        if rate:
            row.note.setText(tr("{0}x{1}  {2}  {3:g} к/с  {4:.2f} с",
                                movie.width, movie.height, movie.kind, rate,
                                stream.duration))
        elif getattr(movie, "was_fitted", False):
            came = movie.came_as
            row.note.setText(tr("{0}x{1} вписана в {2}x{3}  {4}",
                                came[0], came[1], movie.width, movie.height, movie.kind))
        else:
            row.note.setText(f"{movie.width}x{movie.height}  {movie.kind}")

    def _reshape(self, at: int, row) -> None:
        """A chain has reached a block of another size or another codec.

        The screen takes the new shape and the card is told again. Called from
        inside the chain as it turns over, which is while frames are being
        gathered and before anything has been recorded into an encoder -- and
        which is a thread of the render's own while a file is being written.
        So the card is dealt with either way and the window only where there
        is a window to deal with: a widget read from another thread is the
        kind of fault that shows up once a fortnight on somebody else's
        machine. Nothing is lost by skipping it. The brightness and the
        re-bake are kept on the surface itself and survive the reshaping;
        what the widgets would have done is set them to what they already are.
        """
        if at >= len(self.screens) or at >= len(self.streams):
            return
        stream, screen = self.streams[at], self.screens[at]
        movie = stream.movie
        if screen.fits(movie):
            return
        screen.adopt(movie)
        self._on_card.pop(at, None)
        logfile.write(f"{row.title}: the chain reached {movie.width}x"
                      f"{movie.height} {movie.kind}; the surface was remade")
        if self.solid is None:
            return
        if row.overlay:
            self.frame_covers = self._covers(row, movie)
            self.solid.set_frame(row.screen, screen.planes[0].texture,
                                 screen.planes[1].texture, screen.ycocg,
                                 screen.alpha_from, screen.uv_scale,
                                 self.frame_covers)
        elif row.screen in self.solid.calibration:
            self.solid.set_video(row.screen, screen.planes[0].texture,
                                 screen.planes[1].texture, screen.ycocg,
                                 screen.alpha_from, screen.uv_scale)
        if QThread.currentThread() is not self.thread():
            return
        self._gains_changed()
        if self.mode.currentText() == "ReBake":
            self._rebake_changed()

    # -- time ----------------------------------------------------------------

    def _sync_changed(self, _index: int = 0) -> None:
        """The grid the piece is watched on, without moving off the moment.

        Where the timeline is stays what it was; only which frame that lands
        on changes. The streams are told again because their own frame for
        this instant may now be a different one.
        """
        self.clock.rate = float(self.sync.currentData() or 60.0)
        logfile.write(f"watching at {self.clock.rate:g} fps")
        # The frame numbers mean something else now, so the range does too.
        self._reset_range()
        if self.clock.playing:
            # Nothing to put right: the next tick lands on the new grid by
            # itself. Going through `_move` here would seek the sound, and a
            # sound seeked while it is playing is a click.
            self.touch()
            return
        self._move(self.clock.raw)

    def _toggle(self) -> None:
        self.clock.playing = not self.clock.playing
        self._playing_says(self.clock.playing)
        if self.clock.playing:
            # Start on a frame rather than between two of them, so the sound
            # and the pictures set off from the same place.
            self.clock.move_to(self.clock.seconds)
        if self.player is not None:
            if self.clock.playing:
                self.player.move_to(self.clock.seconds)
                self.player.play()
            else:
                self.player.pause()
        self.touch()

    def _playing_says(self, playing: bool) -> None:
        """Both Play buttons at once -- the bar's below and the picture's."""
        for button in (self.play_button, self.full_play):
            button.setIcon(theme.drawn_icon("pause" if playing else "play",
                                            PLAY_INK))
            HINTS[button] = ((tr("Стоп") if playing else tr("Играть")),
                             HINTS[button][1])

    def _step(self, direction: int) -> None:
        self.clock.playing = False
        self._playing_says(False)
        if self.player is not None:
            self.player.pause()
        self._move(self.clock.seconds + direction / self.clock.rate)

    def _scrub(self, value: int) -> None:
        if self.clock.duration:
            self._move(self.clock.duration * value / 1000)

    def _move(self, seconds: float) -> None:
        """Go somewhere, and say so at once rather than at the next tick."""
        self._waiting = 0
        self.clock.move_to(seconds)
        if self.player is not None:
            self.player.move_to(self.clock.seconds)
        for index, stream in enumerate(self.streams):
            stream.seek(stream.index_at(self.clock.seconds))
            stream.give_back(self.held[index])
            self.held[index] = None
        if self.level == "show":
            # Somewhere new is not arriving anywhere: a loop is armed by the
            # playhead crossing its start while playing, not by a jump.
            self._show_was = self.clock.raw * showfile.FPS
            self.show_view.set_frame(self.clock.seconds * showfile.FPS)
        self._show_stats()
        self.touch()

    def _jump_by(self, seconds: float) -> None:
        """A second back or on, stopped -- the way a frame step is."""
        self.clock.playing = False
        self._playing_says(False)
        if self.player is not None:
            self.player.pause()
        self._move(self.clock.seconds + seconds)

    # -- drawing -------------------------------------------------------------

    def _draw(self) -> None:
        # Not while a render or a re-bake has the drawer. It draws on a thread
        # of its own through the same camera and the same targets, and a
        # frame for the window in the middle of that -- asked for by Qt when
        # something laid over the picture repaints -- opens the camera out to
        # the window's shape under the render, which then wrote the building
        # narrow, one run in two. A download of ffmpeg draws nothing and does
        # not count.
        if self.job is not None and not isinstance(self.job, jobs.DownloadJob):
            return
        started = time.perf_counter()
        seconds = self.clock.tick()
        if self.level == "show" and self.show_open is not None:
            now = self.clock.raw * showfile.FPS
            if self.clock.playing:
                jump = self.show_view.step(self._show_was, now)
                if jump is not None:
                    self._move(jump / showfile.FPS)
                    seconds = self.clock.seconds
                    now = self.clock.raw * showfile.FPS
            self._show_was = now
            self.show_view.set_frame(seconds * showfile.FPS)
        self._move_screens(seconds)
        if self.player is not None and self.player.playing and not self.clock.playing:
            self.player.pause()            # the timeline reached its end
            self._playing_says(False)

        # A stream shorter than the timeline goes dark once it has run out,
        # rather than holding its last frame: a frozen picture reads as a
        # still shot of the content, and this one has simply ended.
        # A still has no length, so it is never past its end -- it stays up for
        # as long as it is loaded, which is the whole point of dropping one on.
        live = [not stream.duration or seconds <= stream.duration
                for stream in self.streams]

        starved = False
        showing = self._showing_now()
        for index, stream in enumerate(self.streams):
            if not live[index]:
                continue
            wanted = stream.index_at(seconds)
            held = self.held[index]
            # More than a second behind is not behind, it is in the wrong
            # place. Read forward from there and the picture walks through
            # every frame in between at whatever rate the disk gives them up,
            # which looks exactly like the piece playing on by itself -- and
            # a stopped timeline that goes on playing is the worst of the
            # ways this can be wrong. Seeking lands on the frame instead.
            if held is not None and wanted - held.index > max(stream.rate, 1.0):
                stream.seek(wanted)
                stream.give_back(held)
                self.held[index] = held = None
            frame = stream.take(wanted, held)
            if frame is not None:
                if held is not None:
                    stream.give_back(held)
                self.held[index] = frame
            standing = self.held[index]
            # Only what this mode draws is handed to the card. ReBake shows
            # the two big screens and nothing else, and copying a lamella band
            # up for it is a copy nobody reads. What was skipped is noticed on
            # the way back rather than remembered: the card is told which
            # frame it is holding, and a mode that starts showing this screen
            # again finds that number stale and sends the frame then.
            if (standing is not None and index in showing
                    and self._on_card.get(index) != standing.index):
                self.screens[index].upload(
                    [memoryview(b) for b in standing.buffers])
                self._on_card[index] = standing.index
            # A track of a show between two clips is not waiting for
            # anything; asking again would only spin the window.
            between = (getattr(stream, "showing", None) is not None
                       and stream.showing(wanted) is None)
            if (not between and not stream.at_end
                    and (standing is None or standing.index < wanted)):
                starved = True

        # The size comes off the texture being drawn into, not off the canvas.
        # They are the same number all but one frame in a lifetime -- and the
        # exception is a resize, where the canvas already reports the new size
        # while the surface handed out is still the old one. A scissor sized
        # against the wrong one is not a wrong picture, it is a refusal.
        surface = self.context.get_current_texture()
        view = surface.create_view()
        width, height = surface.size[0], surface.size[1]
        encoder = self.device.create_command_encoder()
        # A show's screens first, each out of its layers, in the same
        # encoder: they are what the scene below is about to sample.
        self._compose(encoder, seconds, lambda index: index in self._on_card)
        self.painter.clear(encoder, view)
        chosen = self.mode.currentText()
        if chosen == "ReBake":
            self._place_rebake(encoder, view, width, height)
        elif chosen == "Inspection" and self.solid is not None:
            # The whole canvas, and the free camera opened out to fill it the
            # same way Preview opens the file camera: what will be written is
            # the rectangle in the middle, marked by the frame line, and the
            # scene carries on past it instead of sitting in black bars.
            shape = self.mesh.cropped or self.mesh.frame
            box = self._fitted(*shape, into=(width, height))
            self.solid.show_around(width / max(box[2], 1.0),
                                   height / max(box[3], 1.0))
            self.solid.draw(encoder, view, width, height)
        elif chosen == PREVIEW and self.solid is not None:
            # The whole canvas, and the camera opened out to match it: black
            # bars down both sides told nobody anything and took half the
            # window to do it. What will be written is the rectangle in the
            # middle, and that is drawn as a line instead -- see the frame
            # button next to the full screen one.
            shape = self.mesh.cropped or self.mesh.frame
            box = self._fitted(*shape, into=(width, height))
            self.solid.show_around(width / max(box[2], 1.0),
                                   height / max(box[3], 1.0))
            self.solid.draw(encoder, view, width, height)
        else:
            # Always, not only when something is loaded: with no video the
            # strips show their calibration, which is the useful thing to look
            # at before there is any content.
            self._place(encoder, view, live, width, height)
        self.device.queue.submit([encoder.finish()])

        # A seek is answered by the reader a moment later, and until then there
        # is nothing new to show. Ask for another frame rather than leaving the
        # picture where it was: while it is stopped nothing else will ask, and
        # stepping a frame at a time did nothing for twenty presses and then
        # jumped twenty frames at once -- every press seeked again, and no draw
        # was ever asked for once the frame it wanted had actually arrived.
        #
        # Counted, so a stream that will never answer cannot spin the window.
        if starved and not self.clock.playing and self._waiting < 60:
            self._waiting += 1
            self.touch()
        elif not starved:
            self._waiting = 0

        self.drawn += 1
        self.draw_ms += (1000 * (time.perf_counter() - started) - self.draw_ms) * 0.1
        # Frames counted over half a second and divided by it, rather than an
        # average of one-over-each-gap. The two are not the same number: gaps
        # of 10 and 23 ms are 60 frames a second between them, but averaging
        # their reciprocals says 72. That is where "playing at 70" came from,
        # and it was the meter, not the piece.
        now = time.perf_counter()
        self._shown_since += 1
        if now - self._shown_at >= 0.5:
            self.shown_fps = self._shown_since / (now - self._shown_at)
            self._shown_since = 0
            self._shown_at = now

    def _fitted(self, width: int, height: int, into=None):
        """The largest rectangle of that shape that fits, centred.

        Into the canvas unless told otherwise. The exceptions are the drawing
        path, which measures the texture it was handed rather than asking the
        canvas, and the frame line, which is a Qt widget and so wants logical
        pixels where everything else here is in physical ones.
        """
        into_width, into_height = into or self.canvas.get_physical_size()
        scale = min(into_width / max(width, 1), into_height / max(height, 1))
        drawn_width, drawn_height = width * scale, height * scale
        return ((into_width - drawn_width) / 2, (into_height - drawn_height) / 2,
                drawn_width, drawn_height)

    FLAT_ORDER = ["Screen_Top", "Screen_Bottom", "Lamel_screen"]
    BY_PIXEL = {"Lamel_screen"}
    # How much larger a lamella pixel is drawn than one of the big screens'.
    # At parity the band is 158 pixels wide and a calibration cell is six
    # across, which is there but cannot be read; three times over is small
    # enough to stay out of the way and large enough to be worth showing.
    BY_PIXEL_MAGNIFY = 3.0
    # Which screen the layout is hung on. The bottom one: it is the largest,
    # it is what the camera looks at head on, and the middle of its picture is
    # the front of the building -- the calibration says so in words. Everything
    # else is placed by direction from there.
    FLAT_ANCHOR = "Screen_Bottom"

    def _place(self, encoder, view, live, width: int, height: int) -> None:
        """The screens unrolled and stacked as they sit on the building.

        The two big screens are laid out at one scale in metres, so the wider
        ring really is the wider strip: they go round the same turn, but at
        2.88 m of radius against 4.89, so the top one is 18.1 m of screen
        against 30.7 and is drawn that much narrower. The lamella band is not
        at that scale: its pixels are thirteen times coarser -- 88 mm against
        7 -- so in metres it would be the largest thing on screen while
        carrying the least. It is sized by its pixels instead, and goes last.

        Horizontally they hang from one direction, the front of the building,
        put at the middle of the layout. Both calibrations mark it and they
        agree: "Front" is written at the middle of the bottom screen's
        picture, which is 225.04 degrees round, and the rings drawn on the top
        screen are centred at 225.42 -- four tenths of a degree apart, half a
        pixel on screen.

        Away from that column the strips drift apart, and they have to: at one
        scale in metres the same turn is a different width on each, so they
        can only agree about direction in one place. This puts that place
        where the content is built around and where anybody looking at the
        layout is looking.

        A screen with nothing loaded shows its calibration, which is the useful
        thing to see before there is any content.
        """
        unrolled = self.mesh.unrolled if self.mesh else {}
        showing = self._flat_showing()
        if not showing:
            return

        tiling = self._tiling()
        for name, box in self._strips(showing, width, height, tile=tiling):
            if tiling:
                self._draw_tiled(encoder, view, name, box, width)
            else:
                self._draw_strip(encoder, view, name, box)

    def _tiling(self) -> bool:
        """Whether Flat is drawing each strip as an endless repeating band."""
        return (self.flat_mode() and hasattr(self, "tile_button")
                and self.tile_button.isChecked())

    def _draw_tiled(self, encoder, view, name: str, box, width: int) -> None:
        """One strip repeated left and right until the window is covered.

        A viewport is a mapping, not a boundary, so each copy is just the strip
        drawn again shifted by its own width; the hardware keeps the part that
        lands. The copies do not overlap on screen, so nothing is drawn over
        anything and the backing, video and frame all repeat together.
        """
        x, y, wide, high = box
        if wide <= 0:
            self._draw_strip(encoder, view, name, box)
            return
        start = x - math.ceil(x / wide) * wide      # first copy at or left of 0
        at = start
        # Bounded by construction -- start is within one width of zero and the
        # step is a whole width -- but guarded so a degenerate size cannot spin.
        guard = int(width / wide) + 3
        while at < width and guard > 0:
            self._draw_strip(encoder, view, name, (at, y, wide, high))
            at += wide
            guard -= 1

    def _strips(self, showing, width: int, height: int, tile: bool = False):
        """Where each strip lands, in the order they are stacked.

        Shared by Flat and ReBake rather than written twice: the anchoring is
        the part that took the longest to get right, and two copies of it would
        be two things to keep in step.
        """
        unrolled = self.mesh.unrolled if self.mesh else {}
        gap = 12
        by_metre = [n for n in showing if n not in self.BY_PIXEL]

        # Metres a single texture pixel covers on the screens laid out truthfully.
        pitches = [unrolled[n][0] / max(self._pixels(n)[0], 1) for n in by_metre]
        pitch = sum(pitches) / len(pitches) if pitches else 1.0

        sizes = {}
        for name in showing:
            arc, tall, _, _, _ = unrolled[name]
            if name in self.BY_PIXEL:
                across, down = self._pixels(name)
                shown = pitch * self.BY_PIXEL_MAGNIFY
                sizes[name] = (across * shown, down * shown)
            else:
                sizes[name] = (arc, tall)

        scale = min((width - 2 * gap) / max(w for w, _ in sizes.values()),
                    (height - gap * (len(showing) + 1))
                    / max(sum(h for _, h in sizes.values()), 1e-6))

        anchor = self.FLAT_ANCHOR if self.FLAT_ANCHOR in unrolled else showing[0]
        reference = unrolled[anchor]
        middle = reference[2] + reference[3] * 0.5      # the front, in azimuth

        stack = sum(h for _, h in sizes.values()) * scale + gap * (len(showing) - 1)
        top = (height - stack) / 2
        placed = []
        for name in showing:
            wide, high = (value * scale for value in sizes[name])
            _, _, start_angle, sweep, _ = unrolled[name]
            share = ((middle - start_angle) / sweep) % 1.0
            box = self._flat_box(
                (width / 2 - share * wide, top, wide, high), width, height,
                tile=tile)
            if box is not None:
                placed.append((name, box))
            top += high + gap
        return placed

    def _place_rebake(self, encoder, view, width: int, height: int) -> None:
        """Top and Bottom, each strip split: the file left, the re-bake right.

        Both halves are one draw of the same picture into the same rectangle,
        clipped to one side or the other. Nothing is squashed to half width, so
        the two agree pixel for pixel across the join and a difference there is
        a real difference and not the scaling.

        The Frame row is not drawn here. It is an overlay the window puts on
        top and is not in the file; laid over both halves it would hide the one
        thing this mode exists to show.

        The size is handed in rather than asked of the canvas: the halves are
        cut with a scissor, a scissor outside the target is refused outright,
        and the only size that is certainly the target's is the one the caller
        used to make it.
        """
        unrolled = self.mesh.unrolled if self.mesh else {}
        showing = [row.screen for row in self.rows
                   if row.title in self.REBAKE_ROWS and row.screen in unrolled]
        if not showing:
            return
        for name, box in self._strips(showing, width, height):
            x, y, wide, high = box
            behind = (self.solid.calibration.get(name)
                      if self.solid and self.backing.currentData() == "Calibration"
                      else None)
            if behind is not None:
                self.painter.draw_picture(encoder, behind, view, viewport=box)
            else:
                self.painter.fill(encoder, view, viewport=box)
            drawing = self._screen_of(name)
            if drawing is None:
                continue
            # Down the middle of the window rather than of the strip: zoomed
            # in, the strip's own middle can be off the edge, and a wipe you
            # cannot see is not a comparison.
            middle = width / 2
            for rebaked, left, right in ((False, x, min(middle, x + wide)),
                                         (True, max(middle, x), x + wide)):
                clip = (max(0.0, left), max(0.0, y),
                        min(width, right) - max(0.0, left),
                        min(height, y + high) - max(0.0, y))
                if clip[2] < 1 or clip[3] < 1:
                    continue
                # Not `box`: that name already holds the strip's rectangle in
                # the loop around this one, and taking it here made the next
                # turn try to unpack a combo box into four numbers.
                chooser = (self.rebake_right_alpha if rebaked
                           else self.rebake_left_alpha)
                reading = ("premultiplied" if chooser.currentIndex() == 0
                           else "straight")
                self.painter.draw(encoder, drawing, view, viewport=box,
                                  alpha=reading, clip=clip, rebaked=rebaked)

    def _flat_box(self, box, width: int, height: int, tile: bool = False):
        """Where a strip lands once the layout has been zoomed into.

        The rectangle comes back hanging off the edges of the canvas, which
        is the whole trick: a viewport is a mapping rather than a boundary, so
        a strip four times the size of the window is simply drawn as one and
        the hardware keeps the part that lands. None when none of it lands,
        which happens the moment anybody looks closely at one strip of three.

        When the strip is being tiled it never runs off the sides -- it repeats
        to fill them -- so only its height is allowed to take it out of view.
        """
        magnify = self.flat_zoom
        x, y, wide, high = box
        if magnify != 1.0 or self.flat_focus != (0.5, 0.5):
            focus_x, focus_y = self.flat_focus
            x = (x - focus_x * width) * magnify + width / 2
            y = (y - focus_y * height) * magnify + height / 2
            wide, high = wide * magnify, high * magnify
        # Outwards to whole pixels, never inwards: the scissor is here to stop
        # a strip spilling past its own rectangle, and a clip rounded the
        # other way would shave a line off the edge of every strip instead.
        if y + high <= 0 or y >= height:
            return None
        if not tile and (x + wide <= 0 or x >= width):
            return None
        return (x, y, wide, high)

    def _place_frame(self) -> None:
        """Fitted or stretched, without touching what is loaded."""
        if self.frame_at is None:
            return
        row = next((r for r in self.rows if r.overlay), None)
        if row is None:
            return
        self.frame_covers = self._covers(row, self.streams[self.frame_at].movie)
        screen = self.screens[self.frame_at]
        if self.solid is not None:
            self.solid.set_frame(
                    self.frame_on, screen.planes[0].texture,
                    screen.planes[1].texture, screen.ycocg,
                    screen.alpha_from, screen.uv_scale, self.frame_covers)
        logfile.write(f"frame {row.how.currentText().lower()}: covers "
                      f"{self.frame_covers[0]:.3f} x {self.frame_covers[1]:.3f}")
        self.touch()

    # -- the sound ------------------------------------------------------------

    def _clear_marks(self) -> None:
        """No chain, no marks: the slider is one clip again."""
        if hasattr(self, "slider"):
            self.slider.set_marks([])
            self._mark_full()

    def _mark_full(self) -> None:
        """The marks on the full screen's slider, the only transport a show
        has once the ruler has gone with the rest of the window.

        In the quick look, the same joins as the slider under the picture. In
        a show, where its sections begin: every clip of the Bottom block, on
        any of its levels -- the main screen's cuts are the show's -- with
        its name in the hover, one mark to a tenth of a second.
        """
        if not hasattr(self, "full_slider"):
            return
        show = self.show_open
        if self.level != "show" or show is None:
            self.full_slider.set_marks(self.slider._marks, self.clock.duration)
            return
        marks: dict = {}
        for clip in show.on("Bottom"):
            if clip.first > 0:
                marks.setdefault(round(clip.first / showfile.FPS, 1), clip.name)
        self.full_slider.set_marks(sorted(marks.items()),
                                   show.length / showfile.FPS,
                                   tr("Секции по Bottom:"))

    def _mark_span(self) -> None:
        """Tell the slider how long the whole thing is, and where the joins are.

        Every chain at once, deduplicated to the tenth of a second: the
        screens and the motors are usually cut in the same places, and three
        lines drawn over each other are one line drawn three times.
        """
        if not hasattr(self, "slider"):
            return
        self.slider.set_span(self.clock.duration)
        marks: dict = {}
        for stream in self.streams:
            for at, name in getattr(stream, "joins", []):
                marks.setdefault(round(at, 1), name)
        if self.motors is not None and self.motors.fps:
            for frame, name in self.motors.boundaries:
                marks.setdefault(round(frame / self.motors.fps, 1), name)
        self.slider.set_marks(sorted(marks.items()))
        self._mark_full()

    def _load_sound(self) -> None:
        """Open the WAV, or let go of the one that was open."""
        row = next((r for r in self.rows if r.sound), None)
        if row is None:
            return
        row._shown()
        if self.player is not None:
            self.player.stop()
        self.player, self.track = None, None
        self.clock.source = None

        text = row.field.text().strip()
        if not text:
            row.note.setText("")
            row.retell = None
            return
        try:
            self.track = sound.read_wav(text)
            self.player = sound.Player(self.track)
        except Exception as error:  # noqa: BLE001 -- shown beside the field
            self.track = None
            row.note.setText(str(error)[:60])
            row.retell = None
            row.note.setStyleSheet(f"color:{theme.ERROR};")
            logfile.write(f"{text}: {error}")
            return
        self.player.set_volume(row.multiplier)
        self.player.move_to(self.clock.seconds)
        # From here the sound keeps the time, and everything else follows it.
        self.clock.source = lambda: (self.player.played
                                     if self.player is not None
                                     and self.player.playing else None)
        row.note.setText(self.track.describe())
        row.note.setStyleSheet(f"color:{theme.META};")
        row.retell = lambda row=row, track=self.track: row.note.setText(
            track.describe())
        logfile.write(f"{Path(text).name}: {self.track.describe()}")
        if self.clock.playing:
            self.player.play()

    def _load_motors(self) -> None:
        """Open the motor file, or put the screens back at rest.

        One file a row. A file that says it is one part of several brings the
        others with it, if they are beside it: the exporter writes `1_of_2`
        into both the name and the header, so finding them is reading a
        folder, not guessing -- and a show cut in two by the exporter is still
        one show to somebody taking a quick look at it.
        """
        row = next((one for one in self.rows if one.motors), None)
        if row is None or self.solid is None:
            return
        row._shown()
        row.note.setText("")
        row.retell = None
        row.note.setStyleSheet(f"color:{theme.META};")
        self.motors = None
        self._moved_to = None
        text = row.field.text().strip()
        if not text:
            self.solid.rest_cells()
            self._pick_top()
            self._clear_marks()
            self._say_sources()
            return

        chain = [text]
        beside = kinetic.parts_beside(text)
        if len(beside) > 1:
            chain = [str(one) for one in beside]
            logfile.write(f"kinetic: {Path(text).name} is one of "
                          f"{len(chain)} parts; the rest came with it")
        try:
            self.motors = kinetic.Motors(chain)
            if self.cell_at is None:
                self.cell_at = self.mesh.cell_middles(scene3d.KINETIC_SCREEN)
                self.cell_is = kinetic.cell_addresses(self.cell_at)
        except Exception as error:  # noqa: BLE001 -- shown beside the field
            self.motors = None
            self.solid.rest_cells()
            self._pick_top()
            row.note.setText(str(error)[:60])
            row.retell = None
            row.note.setStyleSheet(f"color:{theme.ERROR};")
            logfile.write(f"{', '.join(Path(one).name for one in chain)}: {error}")
            self._say_sources()
            return
        # Away goes the still geometry, in comes the one the motors drive.
        self._pick_top()

        self._say_motors(row, self.motors)
        row.retell = (lambda row=row, motors=self.motors:
                      self._say_motors(row, motors))
        for bad in self.motors.complaints():
            row.note.setText(bad[:60])
            row.retell = None
            row.note.setStyleSheet(f"color:{theme.WARN};")
            logfile.write(f"kinetic: {bad}")
        self._mark_span()
        logfile.write(", ".join(Path(one).name for one in chain)
                      + f": {self.motors.describe()}")
        self._say_sources()

    def _say_motors(self, row, motors) -> None:
        """What the motors' card says of its file, or of its parts."""
        said = motors.describe()
        if len(motors.parts) > 1:
            said = (tr("части {0} из {1}  ",
                       ', '.join(str(part.number) for part in motors.parts),
                       motors.parts[0].of) + said)
        row.note.setText(said)

    def _showing_now(self) -> set:
        """Which of the loaded streams the mode being drawn actually shows."""
        if self.mode.currentText() != "ReBake":
            return set(range(len(self.streams)))
        wanted = {row.screen for row in self.rows
                  if row.title in self.REBAKE_ROWS}
        return {index for index, feeds in enumerate(self.feeding)
                if feeds in wanted}

    def _move_screens(self, seconds: float) -> None:
        """Put every cell of the top screen where the motors say, this instant.

        Skipped when nothing has changed: the whole point of drawing on demand
        is undone by rebuilding 1500 matrices for a picture that is standing
        still.
        """
        if self.solid is None or self.cell_at is None:
            return
        # And only where they are ever seen. The cells belong to the building;
        # Flat and ReBake draw the strips instead, so putting fifteen hundred
        # of them in place there is about a millisecond a frame that nothing
        # looks at. Nothing is carried from frame to frame -- where a cell
        # stands is a function of the timeline and no more -- so a mode that
        # draws them again simply builds them for wherever the timeline has
        # got to, and the frame remembered below still says what is in place.
        if self.mode.currentText() not in (PREVIEW, "Inspection"):
            return
        if self.show_motors is not None:
            # A show's files each at their own frame: the last one to have
            # started is in charge. Before the first, the cells are at rest.
            got = self.show_motors.at(seconds * showfile.FPS)
            key = None if got is None else (id(got[0]), got[1])
            if key == self._moved_to:
                return
            self._moved_to = key
            if got is None:
                self.solid.rest_cells()
            else:
                self.solid.set_cells(kinetic.transforms(
                    self.cell_at, self.cell_is, got[0], got[1]))
            return
        if self.motors is None:
            return
        frame = self.motors.index_at(seconds)
        if frame == self._moved_to:
            return
        self._moved_to = frame
        self.solid.set_cells(kinetic.transforms(
            self.cell_at, self.cell_is, self.motors, frame))

    def _volume_changed(self, row=None) -> None:
        if self.player is not None:
            self.player.set_volume(
                next(r.multiplier for r in self.rows if r.sound))

    def _covers(self, row, movie) -> tuple[float, float]:
        """How much of its screen the frame takes up, across and down.

        Stretched it is the whole of it. Fitted it is as large as goes in with
        its own proportions kept, which leaves the screen showing on two sides
        -- the frame's alpha decides what happens to the rest.
        """
        if row.how is None or row.how.currentData() == "Stretch":
            return (1.0, 1.0)
        across, down = self._pixels(row.screen)
        if min(across, down, movie.width, movie.height) < 1:
            return (1.0, 1.0)
        scale = min(across / movie.width, down / movie.height)
        return (min(1.0, movie.width * scale / across),
                min(1.0, movie.height * scale / down))

    def _pixels(self, name: str) -> tuple[int, int]:
        """How many pixels that screen really has.

        From the calibration first, because that is baked at each screen's own
        resolution and is a fact about the wall. What happens to be loaded is
        only a fallback: a snapshot or a stand-in of the wrong size would
        otherwise resize the layout around itself, and the lamella band -- the
        one thing here measured in pixels -- would jump every time a file was
        dropped on it.
        """
        drawer = self.solid
        texture = drawer.calibration.get(name) if drawer else None
        if texture is not None and tuple(texture.size)[:2] != (1, 1):
            return tuple(texture.size)[:2]
        for index, feeds in enumerate(self.feeding):
            if feeds == name and index < len(self.streams):
                movie = self.streams[index].movie
                return movie.width, movie.height
        return (1, 1)

    def _flat_showing(self) -> list[str]:
        """Which screens the flat layout lays out, in the order it does."""
        unrolled = self.mesh.unrolled if self.mesh else {}
        return [name for name in self.FLAT_ORDER if name in unrolled]

    def _draw_strip(self, encoder, view, name: str, box,
                    bare: bool = False) -> None:
        """One screen's strip: the backing, and the video composited over it.

        The same two things the wall does, in the same order, so that a strip
        here and the same screen in the other two modes disagree about nothing.
        Until now this drew the video *instead* of the backing, which meant the
        Behind switch did nothing in Flat and a transparent frame looked like a
        black one.
        """
        drawing = None
        composed = self.composers.get(name)
        if composed is not None:
            # A show's screen is its layers added up, drawn as it is.
            drawing = composed[0].as_screen()
        else:
            for index, feeds in enumerate(self.feeding):
                if feeds == name and index < len(self.screens):
                    drawing = self.screens[index]
                    break

        behind = None
        if not bare and self.backing.currentData() == "Calibration":
            drawer = self.solid
            behind = drawer.calibration.get(name) if drawer else None
        if behind is not None:
            self.painter.draw_picture(encoder, behind, view, viewport=box)
        elif not bare:
            # Filled rather than left: on screen a strip stands on black. Bare
            # is for a file that carries an alpha, where black underneath is
            # exactly what there must not be.
            self.painter.fill(encoder, view, viewport=box)

        if drawing is not None:
            self.painter.draw(encoder, drawing, view, viewport=box,
                              alpha=("premultiplied" if composed is not None
                                     else self.alpha_mode()))

        # And the frame over the top of it, in the part of the strip it covers.
        # A viewport rather than a transform in the shader: the strip is
        # already one, and shrinking it is the whole of what fitting means.
        if self.frame_at is not None and self.frame_on == name:
            x, y, wide, tall = box
            across, down = self.frame_covers
            self.painter.draw(
                encoder, self.screens[self.frame_at], view,
                viewport=(x + wide * (1.0 - across) / 2,
                          y + tall * (1.0 - down) / 2,
                          wide * across, tall * down),
                alpha=self.alpha_mode())

    # -- what it is doing -----------------------------------------------------

    def _frame_now(self) -> tuple[int, int]:
        """Where the timeline is, in frames of the grid it is watched on.

        The Sync rate, not the rate being written and not whatever the longest
        source happens to run at: this number is for finding a moment, and a
        moment is only quotable if everybody counting has the same grid under
        them. It is also what makes a frame here comparable with a frame in
        Blender, which counts thirty a second while the motors count sixty.
        """
        rate = self.clock.rate or 60.0
        # The last frame there is, not one past it: the duration is where the
        # timeline ends, and the frame that begins there has never been shown.
        last = max(0, int(round(self.clock.duration * rate)) - 1)
        return min(last, max(0, int(round(self.clock.seconds * rate)))), last

    def _show_stats(self) -> None:
        if self.device is None:
            return
        seconds = self.clock.seconds
        if self.clock.duration:
            where = int(1000 * seconds / self.clock.duration)
            for slider in (self.slider, self.full_slider):
                slider.blockSignals(True)
                slider.setValue(where)
                slider.blockSignals(False)
        # Counted on the grid the piece is watched on, not the rate being
        # written: this number is for finding a moment in the material. One
        # reading -- the timecode, and the frame out of how many there are.
        at, last = self._frame_now()
        code = showfile.timecode(at, self.clock.rate or 60.0)
        self.time_label.setText(code)
        self.frame_label.setText(tr("кадр {0} из {1}", at, last + 1))
        self.full_time.setText(tr("{0}   кадр {1} из {2}", code, at, last + 1))

        # Only a rate while something is playing: drawing happens on demand,
        # so between changes "frames a second" would just measure how often
        # somebody touched the mouse.
        pace = (tr("рисует {0:4.1f} к/с · {1:.2f} мс на кадр",
                   self.shown_fps, self.draw_ms)
                if self.clock.playing else
                tr("стоит · последний кадр {0:.2f} мс", self.draw_ms))
        # Where the free camera is standing, while there is one. Otherwise
        # there is no way to say what you are looking at, or to get back to it.
        if self.inspecting() and self.solid is not None and self.solid.free:
            pace = tr("{0} · камера {1}", pace, self.solid.free.describe())
        card = (f'<span style="color:{theme.META}">●</span> '
                + html.escape(f"{self.adapter.info.get('device', '?')} · "
                              f"{self.adapter.info.get('backend_type', '?')}"))
        if card != getattr(self, "_card_said", None):
            self._card_said = card
            self.status.setText(card)
        self.status_pace.setText(pace)
        lines, dropped = [], 0
        for index, stream in enumerate(self.streams):
            counts = stream.counts
            if stream.movie is None:
                continue          # a show's track between two clips
            dropped += counts.dropped
            feeds = self.feeding[index] if index < len(self.feeding) else ""
            row = ("Frame" if index == self.frame_at
                   else theme.BAKED.get(feeds, ""))
            text = (tr("{0:26s} {1:5d}x{2:<5d} прочитано {3:6d}  выброшено "
                       "{4:5d}  пропущено {5:5d}  ждали {6:5d}  демукс "
                       "{7:5.2f}  распаковка {8:5.2f} мс",
                       stream.movie.path.name[:26], stream.movie.width,
                       stream.movie.height, counts.read, counts.dropped,
                       counts.skipped, counts.starved, counts.demux_ms,
                       counts.unpack_ms)
                    + (f"   {stream.error}" if stream.error else "")
                    + (tr("   в конце") if stream.at_end else ""))
            lines.append(theme.cell_html(row) + " " + html.escape(text))
        # Frames thrown away because they came too late are what a stutter
        # is. The status line says how many; while the number is growing it
        # says so in the colour that asks for attention.
        now = time.perf_counter()
        if dropped > self._dropped_seen:
            self._dropped_grew = now
        self._dropped_seen = dropped
        growing = now - self._dropped_grew < 3.0
        files = tr("файлы: {0}", len(lines)) if lines else tr("файлов нет")
        if dropped:
            files += tr(" · выброшено кадров {0}", dropped)
        self.status_files.setText(files)
        arrow = "▾" if self.stats_open else "▴"
        self.stats_head.setText(tr("Статистика декодера {0}", arrow))
        if growing != getattr(self, "_stats_warn", None):
            self._stats_warn = growing
            self.status_files.setStyleSheet(
                f"color:{theme.WARN};" if growing else "")
        self.stats.setText('<div style="white-space:pre">'
                           + "<br>".join(lines) + "</div>")
        self.stats.setVisible(self.stats_open and bool(lines))

    def _fold_stats(self, open_it=None) -> None:
        """The counts under the line about the card, shown or put away."""
        self.stats_open = (not self.stats_open) if open_it is None \
            else bool(open_it)
        self._show_stats()
        self._remember()

    def closeEvent(self, event) -> None:  # noqa: N802 -- Qt naming
        self._flush_draft()
        self._remember(now=True)
        if self.motors_job is not None:
            self.motors_job.cancel()
            self.motors_job.wait(10000)
        for stream in self.streams:
            stream.stop()
        if self.player is not None:
            self.player.stop()
        super().closeEvent(event)


# The palette, as a style sheet: see theme.py.
STYLESHEET = theme.sheet()


def main() -> int:
    written = logfile.start(APP_NAME, APP_VERSION)
    app = QApplication(sys.argv)
    # The design's own faces when they travel with the program, then the
    # window's type and its sheet: see theme.py.
    faces = theme.load_fonts(logfile.bundled("fonts")
                             or (Path(__file__).resolve().parent / "fonts"))
    app.setFont(theme.app_font())
    logfile.write(f"type: {theme.ui_family()} and {theme.mono_family()}"
                  + (f" ({', '.join(faces)})" if faces else
                     ", the design's faces not found"))
    app.setStyleSheet(STYLESHEET)
    # Before the window is built, because building it is what takes the time.
    logfile.raise_splash(app)
    window = Viewer()
    if written is not None:
        logfile.write(f"log: {written}")
    window.show()
    logfile.loading_done()
    # After the window is painted, not during construction: the check talks to
    # the GPU and may open a dialog, and both want something to sit in front of.
    QTimer.singleShot(0, window.check_machine)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
