"""Three HAP screens on one clock, drawn without ever unpacking a frame.

The prototype: flat rectangles rather than geometry, which is the order agreed
on, because the risky part is the video and not the layout. Every number the
machine is managing is on screen from the first run -- this has to work on
machines nobody here will ever see, and a program that cannot be asked what it
is doing costs more than any feature it might have instead.
"""
from __future__ import annotations

import math
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer
from PySide6.QtGui import (QColor, QFont, QIcon, QImage, QKeySequence,
                           QPainter, QPen, QPixmap, QShortcut)
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                               QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QMainWindow, QProgressBar,
                               QListView, QPushButton, QSlider, QSpinBox,
                               QStyleFactory, QToolTip, QVBoxLayout, QWidget)
from rendercanvas.pyside6 import RenderCanvas

import numpy as np
import wgpu

import depends
import export
import jobs
import logfile
import player
import rebake
import renderer3d
import scene3d
import kinetic
import screen_gpu
import sound

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

APP_NAME = "Matreshka Viewer"
APP_VERSION = "0.2"
MONO = "Consolas, DejaVu Sans Mono, Menlo, monospace"

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


# The width every row leaves for the link button that sits between two of
# them. Wide enough for the button and a little air either side.
LINK_SIDE = 24
LINK_COLUMN = LINK_SIDE + 10

ICONS = "icons"
_drawn: dict = {}


def icon(name: str) -> QIcon:
    """One of Houdini's own button icons, by the name this tool calls it.

    Taken out of Houdini's own archive once and kept beside the tool -- see
    icons/WHERE_THESE_CAME_FROM.txt -- so nothing here needs Houdini
    installed, or a renderer for SVG inside the executable.
    """
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


def _small(button: QPushButton, width: int) -> QPushButton:
    """A narrow button that still shows its label.

    The stylesheet gives every button twelve pixels of padding a side, which
    at these widths leaves less room for the text than the text needs.
    """
    button.setFixedWidth(width)
    button.setStyleSheet("padding:5px 2px;")
    return button


def _divider() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.VLine)
    line.setStyleSheet("color:#3a3a3a;")
    return line


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
        self.setWindowTitle("What this machine has")
        self.setMinimumWidth(700)
        self.job = None

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        intro = QLabel(
            "Checked once, on the first run. Nothing is installed and nothing "
            "goes on PATH: a downloaded copy lands in a folder beside this "
            "application, and deleting that folder undoes it.")
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
        self.close_button = QPushButton("Continue")
        self.close_button.setObjectName("qa_checks_close")
        self.close_button.setDefault(True)
        self.close_button.clicked.connect(self.accept)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

        self._show(found)

    # -- the list ------------------------------------------------------------

    def _show(self, found) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

        for row, item in enumerate(found):
            name = QLabel(item.name)
            name.setFont(QFont("", -1, QFont.Weight.Bold))
            if item.ok:
                mark, colour = "found", "#8fbf8f"
            elif item.required:
                mark, colour = "MISSING", "#e06c6c"
            else:
                mark, colour = "absent", "#d9a441"
            status = QLabel(mark)
            status.setObjectName(
                "qa_check_" + item.name.lower().replace(" ", "_"))
            status.setStyleSheet(f"color:{colour};")
            detail = QLabel(item.detail)
            detail.setWordWrap(True)
            detail.setStyleSheet("color:#9a9a9a;")
            for column, widget in enumerate((name, status, detail)):
                self.grid.addWidget(widget, row, column)

        wanted = next((item for item in found
                       if not item.ok and item.fixable), None)
        self.get_button.setVisible(wanted is not None)
        if wanted is not None:
            self.get_button.setText(
                f"Download {wanted.name} ({depends.download_size_mb()} MB)")

        stopped = [i.name for i in found if i.required and not i.ok]
        limping = [i.name for i in found if not i.required and not i.ok]
        if stopped:
            self._note(f"This machine cannot run the viewer: {', '.join(stopped)}.",
                       "error")
        elif limping:
            says = [f"without {item.name}, {item.when_absent}"
                    for item in found
                    if not item.required and not item.ok and item.when_absent]
            spoken = "; ".join(says)
            self._note("Everything needed to watch is here. "
                       + (spoken[:1].upper() + spoken[1:] + "." if says
                          else f"Missing: {', '.join(limping)}."), "warn")
        else:
            self._note("Everything is here.")

    def _note(self, text: str, level: str = "") -> None:
        colours = {"error": "color:#e06c6c;", "warn": "color:#d9a441;"}
        self.note.setText(text)
        self.note.setStyleSheet(colours.get(level, "color:#8fbf8f;"))

    # -- fetching ------------------------------------------------------------

    def _start_download(self) -> None:
        if self.job is not None:
            return
        url = depends.DOWNLOADS[sys.platform][0]
        self._note(f"downloading from {url.split('/')[2]} ...")
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
            f"{done / 1e6:.0f} / {total / 1e6:.0f} MB" if total
            else f"{done / 1e6:.0f} MB")

    def _on_failed(self, message: str) -> None:
        self.job = None
        self.progress.setVisible(False)
        self.get_button.setEnabled(True)
        self.close_button.setEnabled(True)
        self._note(f"could not fetch it: {message}", "error")

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


class Row(QWidget):
    """One screen's file: a field, a button, and somewhere to drop a movie."""

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
        self.on_gain = on_gain or (lambda _row: None)
        self.setAcceptDrops(True)
        # What the test driver knows this row and its widgets by. Six rows are
        # built from this one class, so every name carries the row's own.
        tag = title.lower()
        self.setObjectName(f"qa_row_{tag}")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        label = QLabel(title)
        label.setFixedWidth(52)
        layout.addWidget(label)

        self.field = QLineEdit()
        self.field.setObjectName(f"qa_path_{tag}")
        self.field.setPlaceholderText(
            "drop a WAV here, or browse" if sound
            else "drop a motor JSON here, or browse" if motors
            else "drop a movie or a picture here, or browse")
        self.field.setAcceptDrops(False)     # the row handles it for the whole strip
        layout.addWidget(self.field, 3)

        browse = iconed(QPushButton(), "file", "Выбрать файл",
                        "Выбрать файл для этой строки. Перетащить его на "
                        "строку — то же самое.", name=f"qa_browse_{tag}")
        browse.clicked.connect(lambda: on_pick(self))
        layout.addWidget(browse)

        self.clear_button = iconed(QPushButton(), "clear", "Убрать",
                                   "Очистить строку. Сам файл не трогается.",
                                   name=f"qa_clear_{tag}")
        self.clear_button.clicked.connect(self.clear)
        layout.addWidget(self.clear_button)

        # A column of its own for the link button, which lives between two of
        # these rows rather than in any one of them. Every row leaves the same
        # gap so that everything past it -- the sliders, the numbers, the
        # notes -- still lines up down the window.
        self.link_gap = QWidget()
        self.link_gap.setObjectName(f"qa_linkgap_{tag}")
        self.link_gap.setFixedWidth(LINK_COLUMN)
        layout.addWidget(self.link_gap)

        self.how = None
        if overlay:
            self.how = QComboBox()
            self.how.setObjectName(f"qa_how_{tag}")
            self.how.addItems(["Fit", "Stretch"])
            self.how.setFixedWidth(78)
            self.how.setToolTip(
                "Fit сохраняет пропорции кадра и ставит его по центру, а "
                "экран остаётся виден по бокам. Stretch тянет кадр к углам "
                "экрана, какой бы формы кадр ни был.")
            # Not a reload: the file has not changed, only where it sits, and
            # reloading would throw away the clock and start again from zero.
            self.how.currentIndexChanged.connect(lambda _: on_place())
            layout.addWidget(self.how)

        # By eye, on top of whatever the automatic match works out. A slider
        # rather than a number because this is a judgement, not a measurement,
        # and the useful move is nudging it while looking at the picture.
        #
        # The motors have none. What they do is not a matter of taste: the
        # file says how far the screens travel, and anything else is a picture
        # of a building that does not exist. The width is kept as a gap so the
        # rows still line up.
        self.gain = None
        if motors:
            spacer = QWidget()
            spacer.setFixedWidth(96 + 6 + 36)
            layout.addWidget(spacer)
        else:
            self.gain = QSlider(Qt.Orientation.Horizontal)
            self.gain.setObjectName(f"qa_gain_{tag}")
            self.gain.setRange(0, 200)
            self.gain.setValue(100)
            self.gain.setFixedWidth(96)
            if sound:
                # Volume, and there is no such thing as louder than the file.
                self.gain.setRange(0, 100)
                self.gain.setToolTip(
                    "Громкость: от тишины до файла как он есть")
            else:
                self.gain.setToolTip(
                    "Яркость этого экрана, на глаз. 1.00 оставляет её такой, "
                    "какой её делают геометрия и переключатель Match. "
                    "Двойной щелчок возвращает обратно.")
            self.gain.valueChanged.connect(self._gain_moved)
            layout.addWidget(self.gain)

            self.gain_shown = QLabel("1.00")
            self.gain_shown.setObjectName(f"qa_gainvalue_{tag}")
            self.gain_shown.setFont(QFont(MONO, 9))
            self.gain_shown.setFixedWidth(36)
            layout.addWidget(self.gain_shown)

        self.note = QLabel()
        self.note.setObjectName(f"qa_note_{tag}")
        self.note.setMinimumWidth(160)
        self.note.setStyleSheet("color:#8fbf8f;")
        layout.addWidget(self.note, 2)

        self._quiet = self.styleSheet()
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
        """Nothing loaded, nothing to clear."""
        self.clear_button.setEnabled(bool(self.field.text()))

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
            self.setStyleSheet("background:#2c3d4a;")
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
        for row in self.rows:
            layout.addWidget(row)

        # The link between the two sliders it links, rather than off in the
        # bar below with the switches that are about the building. Sitting in
        # the gap between the Top and Bottom rows it needs no label to say
        # which two it ties, so it has none.
        self.linked = iconed(
            QPushButton(central), "link", "Связать Top и Bottom",
            "Связывает ползунки Top и Bottom в том отношении, в каком они "
            "стоят на момент включения. Выставьте каждый так, чтобы экраны "
            "читались одинаково, нажмите это — и дальше любой из ползунков "
            "поднимает и опускает оба, не теряя баланса. Если одному упереться "
            "в край, останавливаются оба.",
            side=LINK_SIDE, name="qa_link")
        self.linked.setCheckable(True)
        self.linked.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.linked.setStyleSheet(self.LINK_BUTTON)
        # Two ways of saying which it is, because one was not enough: the
        # chain is faint while the sliders are loose and solid while they are
        # tied, and the button behind it fills in.
        self.linked.toggled.connect(
            lambda on: self.linked.setIcon(icon("link") if on
                                           else faded("link")))
        self.linked.toggled.connect(self._link_changed)
        self.linked.setIcon(faded("link"))
        # Not among the scene-only ones any more. It used to sit in the bar
        # with the switches about the building and went away with them; here
        # it belongs to the two sliders beside it, and those are on show in
        # every mode.

        # max_fps defaults to 30 in rendercanvas, which is not a thing to
        # discover by wondering why sixty frames a second look like thirty.
        layout.addLayout(self._scene_controls())

        # On demand rather than always: a still picture redrawn sixty times a
        # second costs a laptop its battery and tells nobody anything. A frame
        # is asked for when something changes, and while a clip is playing.
        self.canvas = RenderCanvas(parent=central, update_mode="ondemand",
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
        layout.addWidget(self.canvas, 1)

        layout.addLayout(self._transport())

        self.export_bar = QWidget()
        self.export_bar.setLayout(self._export_controls())
        layout.addWidget(self.export_bar)

        self.rebake_bar = self._rebake_controls()
        layout.addWidget(self.rebake_bar)
        self.rebake_bar.setVisible(False)

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

        self.stats = QLabel()
        self.stats.setObjectName("qa_stats")
        self.stats.setFont(QFont(MONO, 9))
        self.stats.setStyleSheet("color:#9a9a9a;")
        self.stats.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.stats)

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
            self.stats.setText(self.failure)

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

    def _scene_controls(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(6)

        self.mode = QComboBox()
        self.mode.setObjectName("qa_mode")
        self.mode.addItems([PREVIEW, "Flat", "Inspection", "ReBake"])
        self.mode.setFixedWidth(120)
        self.mode.setToolTip(
            f"{PREVIEW} рисует здание через камеру из файла, кадрированное "
            "так, "
            "как оно будет записано, — на нём и судят контент. Flat "
            "раскладывает видео полосами рядом. Inspection отпускает камеру с "
            "этого кадра и пускает вокруг здания: тянуть — вращать, колесо — "
            "ближе, правая кнопка или Shift — сдвинуть, двойной щелчок — "
            "вернуться. Больше в картинке не меняется ничего, так что смотрят "
            "на тот же контент. ReBake показывает Top и Bottom, разрезав "
            "каждую полосу посередине: слева файл, справа то, что из него "
            "сделает перепечка.")
        if self.mesh is None:
            self.mode.setCurrentIndex(1)
            self.mode.setEnabled(False)
            self.mode.setToolTip("Рядом с приложением нет запечённой сцены")
        self.mode.currentIndexChanged.connect(self._mode_changed)
        bar.addWidget(self.mode)
        bar.addWidget(_divider())

        # Everything on this bar that is about the building. ReBake is about a
        # source file, and none of it applies there: no geometry to switch on
        # or off, no screens to match against each other, and the reading of
        # each half is chosen on the picture itself.
        self.scene_only = []

        self.toggles = {}
        # One box for the top screen, not two. Its two geometries are the same
        # screen in two states, and which of them is drawn is decided by
        # whether there is a motor JSON, not by a box of its own.
        listed = [p.name for p in self.mesh.pieces
                  if p.name != scene3d.KINETIC_SCREEN] if self.mesh else []
        for name in listed:
            box = QCheckBox(SHORT.get(name, name))
            box.setObjectName("qa_layer_" + SHORT.get(name, name).lower())
            box.setChecked(True)
            box.setToolTip(name)
            box.toggled.connect(lambda on, n=name: self._show_layer(n, on))
            bar.addWidget(box)
            self.scene_only.append(box)
            self.toggles[name] = box

        bar.addStretch(1)
        bar.addWidget(_divider())

        self.matching = QCheckBox("Match")
        self.matching.setObjectName("qa_match")
        self.matching.setChecked(True)
        self.matching.setToolTip(
            "Экраны устроены по-разному: верхний — раздельные соты, четверть "
            "его площади тёмная, нижний почти сплошной, поэтому одинаковый "
            "белый на верхнем читается тусклее. Это приводит более яркий к "
            "более тусклому, чтобы они совпадали на всех уровнях, включая "
            "максимум. Выключено — показывает так, как есть в геометрии.")
        self.matching.toggled.connect(self._matching_changed)
        bar.addWidget(self.matching)
        self.scene_only.append(self.matching)

        self.solid_top = QCheckBox("Solid top")
        self.solid_top.setObjectName("qa_solid_top")
        self.solid_top.setToolTip(
            "Убирает дальнюю сторону верхнего экрана, чтобы его собственная "
            "изнанка не просвечивала сквозь передние соты. Работает и на "
            "движущемся, и на неподвижном. Выключено — показывает как есть, "
            "открытым с обеих сторон.")
        self.solid_top.toggled.connect(
            lambda on: (self.solid.cull(on) if self.solid else None, self.touch()))
        bar.addWidget(self.solid_top)
        self.scene_only.append(self.solid_top)

        bar.addWidget(_divider())

        alpha_label = QLabel("Alpha")
        bar.addWidget(alpha_label)
        self.scene_only.append(alpha_label)
        self.alpha = QComboBox()
        self.alpha.setObjectName("qa_alpha")
        self.alpha.addItems(["Premultiplied", "Straight"])
        self.alpha.setFixedWidth(122)
        self.alpha.setToolTip(
            "Premultiplied кладёт цвет целиком: то, что осталось под "
            "прозрачной альфой, видно, а не умножено на неё, и пиксель, чей "
            "цвет ярче собственной альфы, вылетает. На нём и проверяют "
            "контент. Straight умножает цвет на альфу — так контент и "
            "задуман, и так его покажет стена.")
        self.alpha.currentIndexChanged.connect(self._alpha_changed)
        bar.addWidget(self.alpha)
        self.scene_only.append(self.alpha)

        bar.addWidget(QLabel("Behind"))
        self.backing = QComboBox()
        self.backing.setObjectName("qa_behind")
        self.backing.addItems(["Calibration", "Black"])
        self.backing.setFixedWidth(104)
        self.backing.setToolTip(
            "Что показывают экраны там, где контент прозрачен или его нет")
        self.backing.currentIndexChanged.connect(self._backing_changed)
        bar.addWidget(self.backing)

        reset = iconed(QPushButton(), "home", "Сбросить вид",
                       "Назад к целому кадру. Двойной щелчок по картинке "
                       "делает то же; колесо приближает, перетаскивание "
                       "двигает.", name="qa_reset_view")
        reset.clicked.connect(self.reset_view)
        bar.addWidget(reset)
        return bar

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
        moving = self.motors is not None
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
                    row.how.setCurrentText(str(kept["how"]))
                path = str(kept.get("file") or "")
                if path:
                    row.field.setText(path)
                    files += 1
                    if not Path(path).exists():
                        logfile.write(f"{row.title}: {path} is no longer there")

            if saved.get("rebake"):
                self.rebake_what.setCurrentText(str(saved["rebake"]))
            if saved.get("rebake_below") is not None:
                self.rebake_threshold.setValue(int(saved["rebake_below"]))
            if "frame_edge" in saved:
                self.frame_button.setChecked(bool(saved["frame_edge"]))
            if saved.get("rebake_format"):
                self.rebake_format.setCurrentText(str(saved["rebake_format"]))
            if saved.get("rebake_colour"):
                self.rebake_colour.setCurrentText(str(saved["rebake_colour"]))
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
                self.sync.setCurrentText(str(saved["sync"]))
            self.clock.rate = float(self.sync.currentData() or 60.0)
            self.matching.setChecked(bool(saved.get("match", True)))
            self.solid_top.setChecked(bool(saved.get("solid_top",
                                                     START_SOLID_TOP)))
            self.linked.setChecked(bool(saved.get("linked", START_LINKED)))
            for box, key in ((self.alpha, "alpha"), (self.backing, "behind")):
                if saved.get(key):
                    box.setCurrentText(str(saved[key]))
        finally:
            self._restoring = False

        # Only if there is something to open. `_load` on six empty fields is
        # harmless but it clears and rebuilds every screen for nothing.
        if files:
            logfile.write(f"carried over from the last session: {files} files")
            self._load()
        # Once the rows have been given their sizes, which happens after this
        # returns rather than during it.
        QTimer.singleShot(0, self._lay_link)
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
                kept["how"] = row.how.currentText()
            rows[row.title] = kept
        return {
            "rows": rows,
            "rebake": self.rebake_what.currentText(),
            "rebake_below": self.rebake_threshold.value(),
            "rebake_colour": self.rebake_colour.currentText(),
            "rebake_format": self.rebake_format.currentText(),
            "frame_edge": self.frame_button.isChecked(),
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
            "behind": self.backing.currentText(),
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

    def _link_changed(self, on: bool) -> None:
        """Remember the balance the two are at, so it can be kept.

        Taken when the box is ticked rather than fixed in advance: the whole
        point is that somebody sets the two by eye first and only then says
        "hold that".
        """
        if not on:
            self.link_ratio = None
            return
        top = max(1, self.rows[0].gain.value())
        bottom = max(1, self.rows[1].gain.value())
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
        pair = self.rows[:2]
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
            base = self.gains.get(row.screen, (1.0, 1.0, 1.0)) if matching                 else (1.0, 1.0, 1.0)
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
                        or (not r.overlay and r.screen == feeds and feeds)), None)
            if row is not None:
                self.screens[index].set_gain((row.multiplier,) * 3)
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

    def _transport(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(4)

        for picture, says, story, act in (
                ("first", "В начало",
                 "В начало таймлайна.  Ctrl со стрелкой влево делает то же.",
                 lambda: self._move(0.0)),
                ("back", "На кадр назад",
                 "На кадр назад по сетке Sync.  Стрелка влево делает то же.",
                 lambda: self._step(-1)),
                ("on", "На кадр вперёд",
                 "На кадр вперёд по сетке Sync.  Стрелка вправо делает то же.",
                 lambda: self._step(1)),
                ("last", "В конец",
                 "В конец таймлайна.  Ctrl со стрелкой вправо делает то же.",
                 lambda: self._move(self.clock.duration))):
            button = iconed(QPushButton(), picture, says, story,
                            name=f"qa_{picture}")
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(act)
            bar.addWidget(button)
            if picture == "back":
                self.play_button = iconed(
                    QPushButton(), "play", "Играть",
                    "Играть или остановить.  Пробел делает то же — отовсюду, "
                    "кроме поля, в котором печатают.", name="qa_play")
                self.play_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                self.play_button.clicked.connect(self._toggle)
                bar.addWidget(self.play_button)

        self.sync = QComboBox()
        self.sync.setObjectName("qa_sync")
        self.sync.setFixedWidth(74)
        for rate in (60, 30):
            self.sync.addItem(f"{rate} fps", float(rate))
        self.sync.setToolTip(
            "Сетка, по которой смотрят всю вещь. На неё разом ложится всё — "
            "экраны, счётчик кадров, моторы, — так что вещь на тридцати "
            "кадрах смотрится по кадру, а не выбирается дважды на каждый свой "
            "кадр. Что писать на выходе, выбирается отдельно, справа.")
        self.sync.currentIndexChanged.connect(self._sync_changed)
        bar.addWidget(self.sync)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setObjectName("qa_timeline")
        self.slider.setRange(0, 1000)
        self.slider.sliderMoved.connect(self._scrub)
        bar.addWidget(self.slider, 1)

        self.frame_label = QLabel("frame 0")
        self.frame_label.setObjectName("qa_frame_label")
        self.frame_label.setFont(QFont(MONO, 9))
        self.frame_label.setFixedWidth(132)
        self.frame_label.setToolTip("Где стоит таймлайн, в кадрах того "
                                    "темпа, в котором идут исходники")
        bar.addWidget(self.frame_label)

        self.time_label = QLabel("0.00 / 0.00 s")
        self.time_label.setObjectName("qa_time_label")
        self.time_label.setFont(QFont(MONO, 9))
        self.time_label.setFixedWidth(118)
        bar.addWidget(self.time_label)

        log = iconed(QPushButton(), "log", "Лог",
                     "Открыть папку, в которую пишется эта сессия",
                     name="qa_log")
        log.clicked.connect(self._open_log)
        bar.addWidget(log)
        return bar

    WRITE_SIZE_HINT = (
        "Камера сужается до центрального окна такой формы: всё, что она видит "
        "сверху донизу, остаётся, отдаются только пустые бока. Из разрешения "
        "не теряется ничего.")

    def _export_controls(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(6)

        bar.addWidget(QLabel("Write"))
        self.size_choice = QComboBox()
        self.size_choice.setObjectName("qa_size")
        self.size_choice.setFixedWidth(140)
        self.size_choice.setToolTip(self.WRITE_SIZE_HINT)
        self._fill_sizes()
        self.size_choice.currentIndexChanged.connect(self._framing_changed)
        bar.addWidget(self.size_choice)

        # Which part of the piece goes out. Counted the way the number beside
        # the timeline counts, on the Sync grid, so a range is read off the
        # screen rather than worked out -- what gets written is at whatever
        # rate is chosen here, and the two need not be the same.
        bar.addWidget(QLabel("Frames"))
        self.first_frame = QSpinBox()
        self.first_frame.setObjectName("qa_frame_first")
        self.last_frame = QSpinBox()
        self.last_frame.setObjectName("qa_frame_last")
        for box, tip in ((self.first_frame, "Первый записываемый кадр"),
                         (self.last_frame, "Последний записываемый кадр, он "
                                           "сам включительно")):
            box.setFixedWidth(78)
            box.setRange(0, 0)
            box.setToolTip(tip + ". Считается так же, как число у таймлайна, "
                                 "по сетке Sync. Любая загрузка возвращает "
                                 "это к целой вещи.")
            box.setKeyboardTracking(False)
            box.valueChanged.connect(self._range_changed)
        bar.addWidget(self.first_frame)
        dash = QLabel("-")
        dash.setFixedWidth(8)
        bar.addWidget(dash)
        bar.addWidget(self.last_frame)

        self.fps_choice = QComboBox()
        self.fps_choice.setObjectName("qa_fps")
        self.fps_choice.setFixedWidth(74)
        for rate in (30, 60):
            self.fps_choice.addItem(f"{rate} fps", rate)
        bar.addWidget(self.fps_choice)

        self.format_choice = QComboBox()
        self.format_choice.setObjectName("qa_format")
        self.format_choice.setFixedWidth(148)
        self._fill_formats()
        self.format_choice.currentIndexChanged.connect(self._format_changed)
        bar.addWidget(self.format_choice)

        self.out_name = QLineEdit("preview_v1.mp4")
        self.out_name.setObjectName("qa_out_name")
        # The name this worked out for itself. While the box still holds it,
        # the sources may rename the render; the moment it holds something
        # else, somebody has decided and nothing here touches it again.
        self._auto_name = self.out_name.text()
        self.out_name.setToolTip(
            "Как будет называться файл. Расширение следует за форматом слева "
            "и подставляется, если его не написать. Загрузите Что-то_top и "
            "Что-то_bottom — и имя составится само.")
        self.out_name.setMinimumWidth(150)
        bar.addWidget(self.out_name, 1)

        browse = iconed(QPushButton(), "directory", "Куда писать",
                        "Папка, в которую писать, и как назвать файл",
                        name="qa_out_browse")
        browse.clicked.connect(self._pick_output)
        bar.addWidget(browse)

        bump = self.bump_button = iconed(
            QPushButton(), "version", "Следующая версия",
            "Ничего никогда не перезаписывается; это находит следующее "
            "свободное имя", name="qa_bump")
        bump.clicked.connect(self._bump_version)
        bar.addWidget(bump)

        snap = iconed(
            QPushButton(), "snapshot", "Снимок",
            "Записать этот один кадр в PNG, рядом с тем, куда идёт видео. В "
            f"{PREVIEW} это та же картинка, что записал бы рендер, в выбранном "
            "размере; в Flat — раскладка так, как её показывает окно.",
            name="qa_snapshot")
        snap.clicked.connect(self._snapshot)
        bar.addWidget(snap)

        self.render_button = iconed(
            QPushButton(), "render", "Рендер",
            "Записать весь диапазон, все экраны разом, в файл, названный "
            "слева. Вид сперва возвращается к целому кадру, так что "
            "записывается именно то, что в кадре.", name="qa_render")
        self.render_button.clicked.connect(self._start_export)
        bar.addWidget(self.render_button)

        self.cancel_button = iconed(QPushButton(), "stop", "Отмена",
                                    "Остановить рендер. Записанное к этому "
                                    "моменту выбрасывается.",
                                    name="qa_cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_export)
        bar.addWidget(self.cancel_button)

        self.progress = QProgressBar()
        self.progress.setObjectName("qa_progress")
        self.progress.setFixedWidth(150)
        bar.addWidget(self.progress)

        self.eta = QLabel()
        self.eta.setObjectName("qa_eta")
        self.eta.setFont(QFont(MONO, 9))
        self.eta.setMinimumWidth(200)
        bar.addWidget(self.eta, 1)

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
        picture = raw[:stride * down].reshape(down, stride)[:, :row]                                      .reshape(down, across, 4).copy()
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
            self.eta.setText(f"snapshot failed: {error}")
            logfile.write(f"snapshot failed: {error}")
            return

        if not written:
            self.eta.setText("nothing to snapshot")
            return
        self.eta.setText(f"-> {SNAPSHOTS}/{written[0].name}"
                         + (f" and {len(written) - 1} more" if len(written) > 1
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
        was = self.size_choice.currentText()
        self.size_choice.blockSignals(True)
        self.size_choice.clear()
        if self.flat_mode():
            for label, scale in self.FLAT_SCALES:
                self.size_choice.addItem(label, scale)
        else:
            frame = self.mesh.frame if self.mesh else (2048, 2048)
            self.size_choice.addItem("1080x1920", (1080, 1920))
            for label, divide in (("Full", 1), ("Half", 2), ("Quarter", 4)):
                wide, tall = frame[0] // divide, frame[1] // divide
                self.size_choice.addItem(f"{label} {wide}x{tall}", (wide, tall))
        if was:
            self.size_choice.setCurrentText(was)   # nothing if it is not there
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
            "Каждый экран пишется в своём собственном разрешении — столько "
            "пикселей, сколько у стены на самом деле. Половина и четверть "
            "считаются от него же и округляются вниз до кратного четырём, "
            "иначе кодировщик не возьмёт кадр."
            if flat else self.WRITE_SIZE_HINT)
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
        bar = QHBoxLayout(holder)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(6)

        bar.addWidget(QLabel("ReBake"))
        self.rebake_what = QComboBox()
        self.rebake_what.setObjectName("qa_rebake_what")
        self.rebake_what.setFixedWidth(104)
        # Clean first, because it is the default: it leaves the fade the
        # author made and only takes away what a premultiplied reading would
        # bloom on. Dither is the stronger medicine and is chosen on purpose.
        self.rebake_what.addItem("Clean", rebake.CLEAN)
        self.rebake_what.addItem("Dither", rebake.DITHER)
        self.rebake_what.setToolTip(
            "Dither превращает альфу в одни только 0 и 255 по неподвижной "
            "карте голубого шума и уводит цвет вместе с ней — после этого два "
            "чтения файла не могут различаться вовсе. Clean альфу не трогает "
            "и стирает цвет там, где альфа ниже порога: фейд остаётся фейдом, "
            "а худшее из того, что показывает премультиплаед, уходит.")
        self.rebake_what.currentIndexChanged.connect(self._rebake_changed)
        bar.addWidget(self.rebake_what)

        bar.addWidget(QLabel("below"))
        self.rebake_threshold = QSpinBox()
        self.rebake_threshold.setObjectName("qa_rebake_below")
        self.rebake_threshold.setRange(0, 255)
        self.rebake_threshold.setValue(8)
        self.rebake_threshold.setFixedWidth(64)
        self.rebake_threshold.setKeyboardTracking(False)
        self.rebake_threshold.setToolTip(
            "Clean стирает цвет под любой альфой ниже этого значения, в том "
            "счёте, в каком ведёт его файл, от 0 до 255. Восьмёрка не "
            "отличима от прозрачного: убирает грязь и оставляет фейд.")
        self.rebake_threshold.valueChanged.connect(self._rebake_changed)
        bar.addWidget(self.rebake_threshold)

        bar.addWidget(QLabel("colour"))
        self.rebake_colour = QComboBox()
        self.rebake_colour.setObjectName("qa_rebake_colour")
        self.rebake_colour.setFixedWidth(104)
        self.rebake_colour.addItem("Multiply", rebake.MULTIPLY)
        self.rebake_colour.addItem("Keep", rebake.KEEP)
        self.rebake_colour.addItem("Clamp", rebake.CLAMP)
        self.rebake_colour.setToolTip(
            "Что происходит с цветом выше порога. Keep оставляет фейд ровно "
            "таким, каким он сделан. Clamp прижимает каждый канал к его "
            "собственной альфе: вспышка уходит, но появляется излом — канал "
            "либо не тронут, либо срезан. Multiply вместо этого сворачивает "
            "цвет с его альфой; это масштаб, а не потолок, поэтому излома нет "
            "нигде: премультиплаед становится верным чтением, а стрэйт "
            "расплачивается тем, что применяет альфу второй раз.")
        self.rebake_colour.currentIndexChanged.connect(self._rebake_changed)
        bar.addWidget(self.rebake_colour)

        bar.addWidget(QLabel("as"))
        self.rebake_format = QComboBox()
        self.rebake_format.setObjectName("qa_rebake_format")
        self.rebake_format.setFixedWidth(126)
        for kind, name in rebake.FORMATS:
            self.rebake_format.addItem(name, kind)
        self.rebake_format.setToolTip(
            "Hap Q Alpha — тот самый формат, в котором лежат исходники, "
            "поэтому перепечённый файл встаёт ровно туда, где был старый. "
            "ffmpeg его не пишет: у его кодировщика Hap нет формата с "
            "отдельным слоем альфы, — поэтому цвет жмёт ffmpeg как Hap Q, это "
            "те же блоки YCoCg, а альфу и обёртку делает вьювер. ProRes 4444 "
            "— второй вариант, для мест, где нужен обычный промежуточный "
            "файл.")
        self.rebake_format.currentIndexChanged.connect(
            lambda _: (self._offer_ffmpeg(), self._remember()))
        bar.addWidget(self.rebake_format)

        # Only up when the chosen format cannot be written here. Hap needs an
        # ffmpeg built with snappy, and half the ones people have are not, so
        # the way out belongs where the trouble is rather than three windows
        # away in the machine check.
        self.rebake_get = iconed(
            QPushButton(), "download", "Скачать ffmpeg, который умеет",
            "Здесь нет кодировщика, который нужен этому формату. Это скачает "
            "сборку, которая его умеет, и положит рядом с приложением: ничего "
            "не устанавливается, ничего не прописывается в PATH, а удаление "
            "папки отменяет всё.", name="qa_rebake_get")
        self.rebake_get.clicked.connect(self._get_ffmpeg)
        self.rebake_get.setVisible(False)
        bar.addWidget(self.rebake_get)

        bar.addWidget(_divider())
        self.probe_button = iconed(
            QPushButton(), "probe", "Проба",
            "Записать кадр, на котором стоит таймлайн, оба экрана, в PNG в "
            "натуральную величину файла. Зерно шириной в один пиксель, а "
            "полосы наверху — нет, так что это единственный честный на него "
            "взгляд.", name="qa_probe")
        self.probe_button.clicked.connect(self._probe)
        bar.addWidget(self.probe_button)

        self.rebake_button = iconed(
            QPushButton(), "rebake", "Перепечь",
            "Записать оба экрана целиком, в их собственном размере и частоте, "
            "в выбранном рядом формате. В Hap Q Alpha готовый файл забирает "
            "имя исходника, а исходник отходит с суффиксом _old: всё, что на "
            "эти файлы ссылалось, продолжает работать и показывает уже "
            "перепечённое, и ничего не удаляется. В ProRes файл ложится рядом "
            "с исходником с суффиксом _prores, а исходник остаётся "
            "нетронутым.", name="qa_rebake")
        self.rebake_button.clicked.connect(self._start_rebake)
        bar.addWidget(self.rebake_button)

        self.rebake_stop = iconed(QPushButton(), "stop", "Стоп",
                                  "Остановить перепечку. Половина файла хуже, "
                                  "чем ничего, поэтому записанное удаляется.",
                                  name="qa_rebake_stop")
        self.rebake_stop.setEnabled(False)
        self.rebake_stop.clicked.connect(
            lambda: self.job.cancel() if self.job is not None else None)
        bar.addWidget(self.rebake_stop)

        self.rebake_progress = QProgressBar()
        self.rebake_progress.setObjectName("qa_rebake_progress")
        self.rebake_progress.setFixedWidth(150)
        self.rebake_progress.setTextVisible(False)
        bar.addWidget(self.rebake_progress)

        self.rebake_note = QLabel()
        self.rebake_note.setObjectName("qa_rebake_note")
        self.rebake_note.setFont(QFont(MONO, 9))
        self.rebake_note.setStyleSheet("color:#9a9a9a;")
        bar.addWidget(self.rebake_note, 1)
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
            self.rebake_note.setText("building the threshold map...")
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
            "QComboBox { background:rgba(20,20,20,190); color:#dcdcdc; "
            "border:1px solid #4a4a4a; border-radius:3px; "
            "padding:2px 22px 2px 6px; } "
            "QComboBox:hover { border-color:#6f6f6f; } "
            "QComboBox::drop-down { subcontrol-origin:padding; "
            "subcontrol-position:center right; width:20px; border:none; "
            "background:transparent; } "
            'QComboBox::down-arrow { image:url("' + arrow + '"); '
            "width:9px; height:9px; } "
            "QComboBox QAbstractItemView { background:#1c1c1c; color:#dcdcdc; "
            "border:1px solid #4a4a4a; outline:none; "
            "selection-background-color:#3a6ea5; selection-color:#ffffff; }")
    LINK_BUTTON = ("QPushButton { border:1px solid #b4b4b4; border-radius:3px; "
                   "background:#fafafa; padding:0px; } "
                   "QPushButton:hover { background:#eaeaea; } "
                   "QPushButton:checked { background:#cfe4fb; "
                   "border:1px solid #3d86c6; }")
    OVERLAY_BAR = ("QFrame { background:rgba(20,20,20,190); "
                   "border:1px solid #3a3a3a; border-radius:4px; }")
    FRAME_EDGE = ("background:transparent; "
                  "border:1px solid rgba(255,255,255,150);")
    OVERLAY_BUTTON = ("QPushButton { background:rgba(20,20,20,190); "
                      "border:1px solid #3a3a3a; border-radius:3px; } "
                      "QPushButton:hover { background:rgba(64,64,64,220); } "
                      "QPushButton:checked { background:rgba(92,92,92,235); "
                      "border-color:#6f6f6f; }")
    OVERLAY_LABEL = ("background:rgba(20,20,20,170); color:#c8c8c8; "
                     "border:none; padding:2px 8px;")

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
                 "Как читается левая половина — файл как он есть."),
                (self.rebake_right_alpha, "Straight",
                 "Как читается правая половина — то, что из него делает "
                 "перепечка.")):
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
            box.setToolTip(
                tip + " Половины выбирают независимо, в этом и смысл: после "
                "дизера один и тот же файл, прочитанный любым способом, — "
                "одна и та же картинка, и поставить их по-разному и не "
                "увидеть разницы это и есть проверка. Переключатель Alpha "
                "наверху в этом режиме не действует.")
            box.currentIndexChanged.connect(
                lambda _: (self.touch(), self._remember()))

        self.rebake_before = QLabel("before", self.canvas)
        self.rebake_before.setObjectName("qa_rebake_before")
        self.rebake_after = QLabel("after", self.canvas)
        self.rebake_after.setObjectName("qa_rebake_after")
        for tag in (self.rebake_before, self.rebake_after):
            tag.setFont(QFont(MONO, 9))
            tag.setStyleSheet(self.OVERLAY_LABEL)
            tag.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.overlays = (self.rebake_left_alpha, self.rebake_right_alpha,
                         self.rebake_before, self.rebake_after)
        for widget in self.overlays:
            widget.setVisible(False)
        self._link_later = QTimer(self)
        self._link_later.setSingleShot(True)
        self._link_later.timeout.connect(self._lay_link)

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

    def _full_icon(self, out: bool) -> QIcon:
        """Four corners of a frame, facing out to go full and in to come back."""
        # Drawn at four times the size it is shown at and left to Qt to bring
        # down, which is the difference between clean edges and a smudge. The
        # arms are a quarter of the side: longer and the four corners close up
        # into a plain square going out, and meet in the middle coming back.
        side, inset, arm = 64, 9, 15
        picture = QPixmap(side, side)
        picture.fill(Qt.GlobalColor.transparent)
        pen = QPen(QColor("#dcdcdc"))
        pen.setWidth(6)
        pen.setCapStyle(Qt.PenCapStyle.SquareCap)
        brush = QPainter(picture)
        brush.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        brush.setPen(pen)
        near, far = inset, side - inset
        for x, y, across, down in ((near, near, 1, 1), (far, near, -1, 1),
                                   (near, far, 1, -1), (far, far, -1, -1)):
            if not out:
                # The same corner walked inwards and turned around, which
                # reads as the picture pulling back off the monitor.
                x, y = x + across * arm, y + down * arm
                across, down = -across, -down
            brush.drawLine(x, y, x + across * arm, y)
            brush.drawLine(x, y, x, y + down * arm)
        brush.end()
        return QIcon(picture)

    def _full_screen_button(self) -> None:
        """The one overlay every mode has: the picture alone on the monitor."""
        self._full = False
        self._before_full = None
        self._was_showing: list = []
        self.full_button = QPushButton(self.canvas)
        self.full_button.setObjectName("qa_full")
        self.full_button.setIcon(self._full_icon(True))
        self.full_button.setIconSize(QSize(18, 18))
        self.full_button.setFixedSize(28, 28)
        self.full_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.full_button.setStyleSheet(self.OVERLAY_BUTTON)
        self.full_button.setToolTip(
            "Картинка на весь монитор, на котором стоит окно, всё остальное "
            "убирается. Ещё раз — обратно, или Escape. F11 делает то же с "
            "клавиатуры.")
        self.full_button.clicked.connect(self._toggle_full)
        self.full_button.setVisible(True)

        # Full screen takes the transport away with everything else, so the
        # timeline comes back on the picture itself. Only there: in a window
        # the real one is a few pixels below and two would be a question
        # about which is which.
        self.full_bar = QFrame(self.canvas)
        self.full_bar.setObjectName("qa_full_bar")
        self.full_bar.setStyleSheet(self.OVERLAY_BAR)
        self.full_bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        line = QHBoxLayout(self.full_bar)
        line.setContentsMargins(12, 6, 12, 6)
        line.setSpacing(6)
        # The same four moves and the same Play as the bar below has. None of
        # them takes the keyboard: a button that had it would answer the space
        # bar itself, and the space bar is Play.
        for picture, says, story, act in (
                ("first", "В начало",
                 "В начало.  Ctrl со стрелкой влево делает то же.",
                 lambda: self._move(0.0)),
                ("back", "На кадр назад",
                 "На кадр назад.  Стрелка влево делает то же.",
                 lambda: self._step(-1)),
                ("play", "Играть",
                 "Играть или остановить.  Пробел делает то же.", None),
                ("on", "На кадр вперёд",
                 "На кадр вперёд.  Стрелка вправо делает то же.",
                 lambda: self._step(1)),
                ("last", "В конец",
                 "В конец.  Ctrl со стрелкой вправо делает то же.",
                 lambda: self._move(self.clock.duration))):
            button = iconed(QPushButton(), picture, says, story,
                            name=f"qa_full_{picture}")
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(self._toggle if act is None else act)
            line.addWidget(button)
            if act is None:
                self.full_play = button
        self.full_slider = QSlider(Qt.Orientation.Horizontal)
        self.full_slider.setObjectName("qa_full_slider")
        self.full_slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.full_slider.setRange(0, 1000)
        self.full_slider.sliderMoved.connect(self._scrub)
        line.addWidget(self.full_slider, 1)
        self.full_time = QLabel("0 / 0")
        self.full_time.setObjectName("qa_full_time")
        self.full_time.setFont(QFont(MONO, 9))
        self.full_time.setStyleSheet("color:#dcdcdc; background:transparent;")
        self.full_time.setMinimumWidth(190)
        self.full_time.setAlignment(Qt.AlignmentFlag.AlignRight
                                    | Qt.AlignmentFlag.AlignVCenter)
        line.addWidget(self.full_time)
        self.full_bar.setVisible(False)

        for keys, wanted in ((Qt.Key.Key_F11, None), (Qt.Key.Key_Escape, True)):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.activated.connect(
                lambda only=wanted: (self._toggle_full()
                                     if only is None or self._full else None))

    def _frame_icon(self) -> QIcon:
        """A rectangle of the frame's own shape, which is what it marks."""
        side = 64
        picture = QPixmap(side, side)
        picture.fill(Qt.GlobalColor.transparent)
        pen = QPen(QColor("#dcdcdc"))
        pen.setWidth(6)
        brush = QPainter(picture)
        brush.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        brush.setPen(pen)
        brush.drawRect(18, 9, side - 36, side - 18)
        brush.end()
        return QIcon(picture)

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

        self.frame_button = QPushButton(self.canvas)
        self.frame_button.setObjectName("qa_frame_edge_button")
        self.frame_button.setIcon(self._frame_icon())
        self.frame_button.setIconSize(QSize(18, 18))
        self.frame_button.setFixedSize(28, 28)
        self.frame_button.setCheckable(True)
        self.frame_button.setChecked(True)
        self.frame_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.frame_button.setStyleSheet(self.OVERLAY_BUTTON)
        self.frame_button.setToolTip(
            "Линия, показывающая, что попадёт в запись. Картинка занимает всё "
            "окно и продолжается за рамкой; эта линия говорит, где рамка. "
            f"В {PREVIEW} и в Inspection, где есть что кадрировать.")
        self.frame_button.toggled.connect(
            lambda _: (self._lay_overlays(), self._remember()))

    def _beside_canvas(self):
        """Every widget the window lays out, except the picture itself.

        The top of each branch only: hiding a row hides what is in it, and
        walking further would turn the coming back into a guess about which
        of a bar's own widgets were meant to be showing.
        """
        found: list = []

        def walk(layout) -> None:
            for index in range(layout.count()):
                item = layout.itemAt(index)
                if item.widget() is not None:
                    if item.widget() is not self.canvas:
                        found.append(item.widget())
                elif item.layout() is not None:
                    walk(item.layout())

        walk(self.centralWidget().layout())
        # The link button is not in the layout -- it is placed by hand between
        # two rows -- so the walk above cannot find it, and without this it
        # would be the one thing left floating over a full screen picture.
        if hasattr(self, "linked"):
            found.append(self.linked)
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
        self.full_button.setIcon(self._full_icon(not going))
        self._lay_overlays()
        self.touch()

    # What the transport keeps for itself, wherever the keyboard happens to
    # be pointing.
    TRANSPORT_KEYS = (Qt.Key.Key_Space, Qt.Key.Key_Left, Qt.Key.Key_Right)

    def eventFilter(self, watched, event):  # noqa: N802 -- Qt naming
        if watched is self.canvas and event.type() == QEvent.Type.Resize:
            self._lay_overlays()
        if (watched is self.centralWidget()
                and event.type() in (QEvent.Type.Resize, QEvent.Type.Show)):
            # Not now: a filter runs before the widget's own handler, and the
            # rows have not been given their new places yet. Reading them here
            # gives the sizes from before the resize, which is how the button
            # came to stay where it was while everything under it moved.
            self._link_later.start(0)
        if watched in HINTS:
            if event.type() == QEvent.Type.Enter:
                self._hint(watched)
            elif event.type() in (QEvent.Type.Leave,
                                  QEvent.Type.MouseButtonPress):
                self._hint(None)
        if (event.type() == QEvent.Type.KeyPress
                and event.key() in self.TRANSPORT_KEYS
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
        others = keys & ~(Qt.KeyboardModifier.ControlModifier
                          | Qt.KeyboardModifier.KeypadModifier)
        if others:                        # Shift, Alt: somebody else's
            return False
        key = event.key()
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

    def _lay_overlays(self) -> None:
        """Put them in their corners, and the names under their own halves."""
        if not hasattr(self, "overlays"):
            return
        wide = self.canvas.width()
        tall = self.canvas.height()
        edge = 10
        taken = 0
        if hasattr(self, "full_button"):
            self.full_button.move(
                max(edge, wide - self.full_button.width() - edge), edge)
            self.full_button.raise_()
            taken = self.full_button.width() + 6
        if hasattr(self, "frame_button"):
            # Where there is a render rectangle to mark: Preview and
            # Inspection both write the file camera's frame, so both show the
            # line. Flat is not one picture and ReBake is about a source file.
            framed = self.mode.currentText() in (PREVIEW, "Inspection")
            self.frame_button.setVisible(framed)
            if framed:
                self.frame_button.move(
                    max(edge, wide - taken - self.frame_button.width() - edge),
                    edge)
                self.frame_button.raise_()
                taken += self.frame_button.width() + 6
            self._lay_frame_edge()
        self.rebake_left_alpha.adjustSize()
        self.rebake_right_alpha.adjustSize()
        left = self.rebake_left_alpha
        right = self.rebake_right_alpha
        left.move(edge, edge)
        # Clear of the full screen button, which is in that corner in every
        # mode and would otherwise sit under this one.
        right.move(max(edge, wide - right.width() - edge - taken), edge)
        foot = 0
        if hasattr(self, "full_bar"):
            self.full_bar.setVisible(bool(getattr(self, "_full", False)))
            if self.full_bar.isVisible():
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

    def _lay_link(self) -> None:
        """Put the link button in the gap between the two rows it ties.

        Placed against the widgets themselves rather than at a counted
        distance: where the sliders begin depends on the longest label and on
        whatever the machine's own style does with padding, and neither is
        knowable from here.
        """
        if not hasattr(self, "linked"):
            return
        rows = {row.title: row for row in self.rows}
        top, bottom = rows.get("Top"), rows.get("Bottom")
        if top is None or bottom is None or top.gain is None:
            return
        central = self.centralWidget()
        column = top.link_gap.geometry()
        middle = top.mapTo(central, column.center()).x()
        between = (top.mapTo(central, QPoint(0, top.height())).y()
                   + bottom.mapTo(central, QPoint(0, 0)).y()) // 2
        self.linked.move(middle - self.linked.width() // 2,
                         between - self.linked.height() // 2)
        self.linked.raise_()

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
        self.frame_edge.raise_()

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
            self.rebake_note.setText(f"no ffmpeg here has the {needs} encoder")

    def _get_ffmpeg(self) -> None:
        """Fetch one that has it, saying so on the re-bake's own progress bar."""
        if self.job is not None:
            return
        self.rebake_get.setEnabled(False)
        self.rebake_button.setEnabled(False)
        self.rebake_progress.setRange(0, 100)
        self.rebake_progress.setValue(0)
        self.rebake_note.setText("fetching ffmpeg...")
        logfile.write("rebake: fetching an ffmpeg that has the encoder")
        self.job = jobs.DownloadJob(self)
        self.job.progress.connect(self._ffmpeg_progress)
        self.job.failed.connect(self._ffmpeg_failed)
        self.job.finished_ok.connect(self._ffmpeg_here)
        self.job.start()

    def _ffmpeg_progress(self, done: int, total: int) -> None:
        self.rebake_progress.setValue(int(100 * done / total) if total else 0)
        self.rebake_note.setText(
            f"fetching ffmpeg: {done / 1e6:.0f} of {total / 1e6:.0f} MB"
            if total else f"fetching ffmpeg: {done / 1e6:.0f} MB")

    def _ffmpeg_failed(self, why: str) -> None:
        self.job = None
        self.rebake_get.setEnabled(True)
        self.rebake_button.setEnabled(True)
        self.rebake_progress.setValue(0)
        self.rebake_note.setText(f"could not fetch it: {why[:60]}")
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
            self.rebake_note.setText("ready -- that one has the encoder")

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
            self.rebake_note.setText("nothing loaded to probe")
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
            self.rebake_note.setText(f"probe failed: {error}")
            logfile.write(f"probe failed: {error}")
            return
        if not written:
            self.rebake_note.setText("no screen here carries an alpha")
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
            self.rebake_note.setText("nothing loaded to re-bake")
            return
        if not depends.ffmpeg_version():
            self.rebake_note.setText("ffmpeg is missing; it writes the file")
            return
        work, skipped = self._rebake_work()
        if not work:
            self.rebake_note.setText("no screen here carries an alpha")
            return
        already = [target.name for _, target in work if target.exists()]
        if already:
            self.rebake_note.setText(f"{already[0]} exists -- move it aside")
            return

        # Asked before the first frame rather than found out when the pipe
        # breaks. Not every ffmpeg has every encoder: the Homebrew build has
        # no hap at all, and what came back from it was "Broken pipe".
        kind = int(self.rebake_format.currentData())
        needs = rebake.ENCODERS.get(kind, "")
        if needs and not depends.can_encode(needs):
            self.rebake_note.setText(
                f"no ffmpeg here has the {needs} encoder"
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
        self.rebake_progress.setRange(0, 1)
        self.rebake_progress.setValue(0)
        self.rebake_note.setText("re-baking...")

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
        self.rebake_note.setText("cancelled" if why == "cancelled" else why[:70])
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
            self.rebake_note.setText("wrote " + ", ".join(names))
            return
        moved, stuck = self._swap_in(getattr(self, "_rebake_pairs", []))
        if stuck:
            self.rebake_note.setText("written, but not put in place -- "
                                     + stuck[0][:60])
            logfile.write("rebake: could not swap: " + "; ".join(stuck))
            return
        if moved:
            self.rebake_note.setText(
                f"{len(moved)} in place; the old kept as "
                + ", ".join(aside.name for _, aside in moved))
        else:
            self.rebake_note.setText("wrote " + ", ".join(names))

    def _rebake_over(self) -> None:
        self.job = None
        self.rebake_button.setEnabled(True)
        self.probe_button.setEnabled(True)
        self.rebake_stop.setEnabled(False)
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
        self.eta.setText(f"-> {self.out_dir}")

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
        for name in self._flat_showing():
            row = next((r for r in self.rows
                        if r.screen == name and not r.overlay
                        and r.field.text().strip()), None)
            if row is None:
                continue
            across, down = self._pixels(name)
            # Down to a multiple of four. Every encoder here wants an even
            # width and hap wants four, and 1150 or 110 rows are neither --
            # so this bites at the native size too, not only at a quarter of
            # it. Two rows off the bottom of a screen nobody looks at pixel
            # by pixel beats a render that will not start.
            wide = max(4, int(across * scale) // 4 * 4)
            tall = max(4, int(down * scale) // 4 * 4)
            source = Path(row.field.text().strip())
            # A sequence of stills is not a file but a heap of them, and three
            # heaps of three sizes in one folder cannot be told apart. Each
            # gets a folder of its own, named the way the videos are.
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
            self.eta.setText("nothing loaded to write")
            return
        already = [target.name for _, _, target, _, _ in work
                   if target.exists()]
        if already:
            self.eta.setText(f"{already[0]} exists -- move it aside")
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
        self.progress.setRange(0, count * len(work))
        self.progress.setValue(0)

        bare = kind in export.CARRY_ALPHA
        self.job = jobs.FlatExportJob(
            self.streams, self.screens,
            lambda screen, wide, tall: self._screen_to_array(
                screen, wide, tall, bare=bare),
            [(name, target, wide, tall) for name, _, target, wide, tall in work],
            kind, first, count, rate, int(self.fps_choice.currentData()),
            parent=self)
        self.job.progress.connect(self._export_progress)
        self.job.failed.connect(self._export_failed)
        self.job.finished_ok.connect(self._export_done)
        self.job.start()

    def _start_export(self) -> None:
        if self.job is not None or self.solid is None:
            return
        if not depends.ffmpeg_version():
            self.eta.setText("ffmpeg is missing; it is what writes the file")
            logfile.write("render refused: no ffmpeg on this machine")
            return
        # Flat is not one picture: it is the screens laid out to be read one
        # at a time, so it writes them one at a time.
        if self.flat_mode():
            self._start_flat_export()
            return
        if not self.streams:
            self.eta.setText("nothing loaded to write")
            return
        # Written back into the box as well, so that what is about to be
        # made and what is on screen are the same string.
        name = self._output_name()
        self.out_name.setText(name)
        target = self.out_dir / name
        if target.exists():
            self.eta.setText(f"{target.name} exists -- press +1 version")
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

        output = export.Output(kind=kind, path=target, fps=int(rate),
                               width=width, height=height,
                               sound=self.track.path if self.track else None)
        self._log_render(output, count, rate, begins, ends)

        # The device belongs to the render while it runs; the canvas stops
        # drawing rather than competing for it.
        self.canvas.set_update_mode("manual")
        self.render_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress.setRange(0, count)
        self.progress.setValue(0)

        self.job = jobs.ExportJob(self.streams, self.screens, self.solid,
                                  output, first, count, rate,
                                  move=self._move_screens, parent=self)
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
        for stream in self.streams:
            logfile.write(f"   {stream.movie.path.name}: {stream.movie.kind} "
                          f"{stream.movie.frames} frames {stream.duration:.2f} s")
        if output.takes_sound:
            logfile.write(f"   {output.sound.name}: {self.track.describe()}")
        elif self.track is not None:
            logfile.write("   sound is loaded but this format has nowhere "
                          "to put it")

    def _cancel_export(self) -> None:
        if self.job is not None:
            self.job.cancel()

    def _export_progress(self, done, total, fps, eta) -> None:
        self.progress.setValue(done)
        self.eta.setText(f"{done}/{total}   {fps:.1f} fps   ETA {eta:.0f} s")

    def _backing_back(self) -> None:
        """Put the backing back, if writing an alpha took it off."""
        if getattr(self, "_backing_was", None):
            self.backing.setCurrentText(self._backing_was)
            self._backing_was = None

    def _export_finished(self) -> None:
        self.job = None
        self._backing_back()
        self.render_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.canvas.set_update_mode("continuous")
        self.canvas.request_draw(self._draw)

    def _export_failed(self, message: str) -> None:
        lines = message.strip().splitlines() or [message]
        self.eta.setText(lines[0][:70])
        logfile.write("RENDER FAILED: " + message)
        self._export_finished()

    def _export_done(self, result: dict) -> None:
        self.progress.setValue(self.progress.maximum())
        self.eta.setText(f"{result['frames']} frames in {result['seconds']:.0f} s "
                         f"({result['fps']:.1f} fps)")
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
                self, "Choose a motor JSON", start,
                "Motors (*.json);;All files (*)")
        elif row.sound:
            chosen, _ = QFileDialog.getOpenFileName(
                self, "Choose a WAV", start, "Sound (*.wav);;All files (*)")
        else:
            chosen, _ = QFileDialog.getOpenFileName(
                self, "Choose a movie or a picture", start,
                "Movies and pictures (*.mov *.mp4 *.m4v *.mkv *.avi "
                "*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp *.tga);;"
                "Movies (*.mov *.mp4 *.m4v *.mkv *.avi);;"
                "Pictures (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp *.tga);;"
                "All files (*)")
        if chosen:
            row.field.setText(chosen)
            self._load()

    def _load(self) -> None:
        for stream in self.streams:
            stream.stop()
        self.streams, self.screens, self.held = [], [], []
        self._on_card: dict = {}     # which frame each screen's texture holds
        self.feeding = []            # which baked screen each stream feeds
        self.frame_at = None         # which of them is the overlay, if any
        self.frame_on = ""
        self.frame_covers = (1.0, 1.0)
        if self.solid is not None:
            self.solid.set_frame(None)
            # Everything off first, then back on for whatever loads below. A
            # row that has just been emptied has nothing left to say, so if
            # this is not done its last frame stays on the screen for good.
            self.solid.clear_all_videos()
        if self.device is None:
            return

        self._load_sound()
        self._load_motors()
        self._moved_to = None
        for row in self.rows:
            if row.sound or row.motors:
                continue
            text = row.field.text().strip()
            row._shown()
            if not text:
                row.note.setText("")
                continue
            try:
                # A frame keeps its own size: where it sits on the screen is
                # decided below, not by resampling it into the screen's shape.
                stream = player.open_source(
                    text, None if row.overlay else self._pixels(row.screen))
                screen = screen_gpu.Screen(self.device, stream.movie)
            except Exception as error:  # noqa: BLE001 -- shown beside the field
                row.note.setText(str(error)[:60])
                row.note.setStyleSheet("color:#e06c6c;")
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
            if stream.rate:
                row.note.setText(f"{stream.movie.width}x{stream.movie.height}  "
                                 f"{stream.movie.kind}  {stream.rate:g} fps  "
                                 f"{stream.duration:.2f} s")
            elif stream.movie.was_fitted:
                came = stream.movie.came_as
                row.note.setText(f"{came[0]}x{came[1]} fitted into "
                                 f"{stream.movie.width}x{stream.movie.height}  "
                                 f"{stream.movie.kind}")
            else:
                row.note.setText(f"{stream.movie.width}x{stream.movie.height}  "
                                 f"{stream.movie.kind}")
            row.note.setStyleSheet("color:#8fbf8f;")
            logfile.write(f"{Path(text).name}: {stream.movie.width}x"
                          f"{stream.movie.height} {stream.movie.kind} "
                          f"{stream.movie.frames} frames {stream.duration:.2f} s")

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
        # The files above all: what somebody dragged in is the expensive part
        # to do again, so it is written down as soon as it is loaded and not
        # left to depend on the window being closed politely.
        self._remember()

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
            button.setIcon(icon("pause" if playing else "play"))
            HINTS[button] = (("Стоп" if playing else "Играть"),
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
        self._show_stats()
        self.touch()

    # -- drawing -------------------------------------------------------------

    def _draw(self) -> None:
        started = time.perf_counter()
        seconds = self.clock.tick()
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
            if not stream.at_end and (standing is None or standing.index < wanted):
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

        for name, box in self._strips(showing, width, height):
            self._draw_strip(encoder, view, name, box)

    def _strips(self, showing, width: int, height: int):
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
                (width / 2 - share * wide, top, wide, high), width, height)
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
                      if self.solid and self.backing.currentText() == "Calibration"
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

    def _flat_box(self, box, width: int, height: int):
        """Where a strip lands once the layout has been zoomed into.

        The rectangle comes back hanging off the edges of the canvas, which
        is the whole trick: a viewport is a mapping rather than a boundary, so
        a strip four times the size of the window is simply drawn as one and
        the hardware keeps the part that lands. None when none of it lands,
        which happens the moment anybody looks closely at one strip of three.
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
        if x + wide <= 0 or y + high <= 0 or x >= width or y >= height:
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
            return
        try:
            self.track = sound.read_wav(text)
            self.player = sound.Player(self.track)
        except Exception as error:  # noqa: BLE001 -- shown beside the field
            self.track = None
            row.note.setText(str(error)[:60])
            row.note.setStyleSheet("color:#e06c6c;")
            logfile.write(f"{text}: {error}")
            return
        self.player.set_volume(row.multiplier)
        self.player.move_to(self.clock.seconds)
        # From here the sound keeps the time, and everything else follows it.
        self.clock.source = lambda: (self.player.played
                                     if self.player is not None
                                     and self.player.playing else None)
        row.note.setText(self.track.describe())
        row.note.setStyleSheet("color:#8fbf8f;")
        logfile.write(f"{Path(text).name}: {self.track.describe()}")
        if self.clock.playing:
            self.player.play()

    def _load_motors(self) -> None:
        """Open the motor JSON, or put the screens back where they were."""
        row = next((r for r in self.rows if r.motors), None)
        if row is None or self.solid is None:
            return
        row._shown()
        self.motors = None
        self._moved_to = None
        text = row.field.text().strip()
        if not text:
            row.note.setText("")
            self.solid.rest_cells()
            self._pick_top()
            return
        try:
            self.motors = kinetic.Motors(text)
            if self.cell_at is None:
                self.cell_at = self.mesh.cell_middles(scene3d.KINETIC_SCREEN)
                self.cell_is = kinetic.cell_addresses(self.cell_at)
        except Exception as error:  # noqa: BLE001 -- shown beside the field
            self.motors = None
            self.solid.rest_cells()
            self._pick_top()
            row.note.setText(str(error)[:60])
            row.note.setStyleSheet("color:#e06c6c;")
            logfile.write(f"{text}: {error}")
            return
        # Away goes the still geometry, in comes the one the motors drive.
        self._pick_top()
        row.note.setText(self.motors.describe())
        row.note.setStyleSheet("color:#8fbf8f;")
        logfile.write(f"{Path(text).name}: {self.motors.describe()}")

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
        if self.motors is None or self.solid is None or self.cell_at is None:
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
        if row.how is None or row.how.currentText() == "Stretch":
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
        for index, feeds in enumerate(self.feeding):
            if feeds == name and index < len(self.screens):
                drawing = self.screens[index]
                break

        behind = None
        if not bare and self.backing.currentText() == "Calibration":
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
                              alpha=self.alpha_mode())

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
        self.time_label.setText(f"{seconds:6.2f} / {self.clock.duration:.2f} s")

        # Counted at the rate the sources run at, not the rate being written:
        # this number is for finding a moment in the material.
        at, last = self._frame_now()
        self.frame_label.setText(f"frame {at:>5d} / {last}")
        self.full_time.setText(f"frame {at:>5d} / {last}    "
                               f"{seconds:6.2f} / {self.clock.duration:.2f} s")

        # Only a rate while something is playing: drawing happens on demand,
        # so between changes "frames a second" would just measure how often
        # somebody touched the mouse.
        pace = (f"drawing {self.shown_fps:5.1f} fps, {self.draw_ms:.2f} ms a frame"
                if self.clock.playing else
                f"idle, last frame took {self.draw_ms:.2f} ms")
        # Where the free camera is standing, while there is one. Otherwise
        # there is no way to say what you are looking at, or to get back to it.
        if self.inspecting() and self.solid is not None and self.solid.free:
            pace = f"{pace}   camera {self.solid.free.describe()}"
        lines = [f"{self.adapter.info.get('device', '?')} "
                 f"({self.adapter.info.get('backend_type', '?')})   {pace}"]
        for stream in self.streams:
            counts = stream.counts
            lines.append(
                f"  {stream.movie.path.name[:26]:26s} "
                f"{stream.movie.width:5d}x{stream.movie.height:<5d} "
                f"read {counts.read:6d}  dropped {counts.dropped:5d}  "
                f"skipped {counts.skipped:5d}  starved {counts.starved:5d}  "
                f"demux {counts.demux_ms:5.2f}  unpack {counts.unpack_ms:5.2f} ms"
                + (f"   {stream.error}" if stream.error else "")
                + ("   at the end" if stream.at_end else ""))
        self.stats.setText("\n".join(lines))

    def closeEvent(self, event) -> None:  # noqa: N802 -- Qt naming
        self._remember(now=True)
        for stream in self.streams:
            stream.stop()
        if self.player is not None:
            self.player.stop()
        super().closeEvent(event)


STYLESHEET = """
QWidget { background:#232323; color:#dcdcdc; font-size:12px; }
QLineEdit { background:#1b1b1b; border:1px solid #3a3a3a; border-radius:3px;
            padding:3px; }
QPushButton { background:#333; border:1px solid #454545; border-radius:3px;
              padding:5px 12px; }
QPushButton:hover { background:#3c3c3c; }
QPushButton:disabled { color:#666; background:#2a2a2a; }
QSlider::groove:horizontal { height:6px; background:#1b1b1b; border-radius:3px; }
QSlider::handle:horizontal { width:12px; background:#4a7ea8; border-radius:3px;
                             margin:-4px 0; }
"""


def main() -> int:
    written = logfile.start(APP_NAME, APP_VERSION)
    app = QApplication(sys.argv)
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
