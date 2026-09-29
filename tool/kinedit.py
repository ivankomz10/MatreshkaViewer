"""Matreshka Kinetic: the editor for the moving honeycomb on top of the building.

A second program in the viewer's executable (`MatreshkaViewer --kinetic`,
or MatreshkaKinetic.exe beside it, which says exactly that). It makes the
motor JSON the viewer plays and the site runs, the way the artists made it in
Houdini and Cinema 4D -- a shape for the screens, then keys through time --
without either.

  the picture   the building from a camera that goes round it, the cells
                showing the video, or painted in their mask colours:
                red the jacks, green the pushers, blue the tilts, as
                Houdini's PMR -- or one family at a time
  the strip     the same cells unrolled, all fifteen hundred at once
  the tools     brush, selection, the vase's profile, the rings
  the timeline  a lane of keys a family, and the sound under them

Every edit is made at the playhead and keys only the motors it touched (see
`kin_model`). Cinema 4D's limits hold throughout: a jack stands in one of its
four places, and a cell tilts no further than the gaps beside its ring let
it -- what goes past is clamped as it is made, and what an earlier change has
put past it is shown in red.

The next stage is the motors' own movement: speeds, accelerations, the rest
a motor needs between moves, as Houdini's DRIVERS_sim works them out. Until
then a key is where a motor is at that frame, and the ease between two keys
is the exporter's.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import (QAbstractButton, QApplication, QComboBox,
                               QDoubleSpinBox, QFileDialog, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QMainWindow, QMessageBox,
                               QPushButton, QSplitter, QStackedWidget,
                               QVBoxLayout, QWidget)
from rendercanvas.pyside6 import RenderCanvas

import kin_model as km
import kin_tools
import kinetic
import lang
import logfile
import player
import renderer3d
import scene3d
import screen_gpu
import sound
import theme
from kin_timeline import FAMILY_COLOUR, FAMILY_NAME, KeyTimeline
from kin_unwrap import Unwrap, brush_weights
from kinetic import PER_PUSHER, PER_ROW, ROWS
from lang import tr

APP_NAME = "Matreshka Kinetic"
BAKED = "baked"
SETTINGS = "kinedit.json"
TOP = "Screen_Top"
PROJECT_SUFFIX = ".kin"
UNDO_DEPTH = 80

# Houdini's red for the four jack places: the mask is millimetres over 130.
LIFT_LEVEL = np.array([0.0, 33.0 / 130.0, 66.0 / 130.0, 1.0])
LAYERS = ("rgb", "lift", "push", "tilt")
LAYER_NAMES = ("RGB", "Подъём", "Вынос", "Наклон")
TOOLS = ("brush", "select", "profile", "rings")
TOOL_NAMES = ("Кисть", "Выбор", "Профиль", "Кольца")
TOOL_KEYS = {Qt.Key.Key_B: "brush", Qt.Key.Key_V: "select",
             Qt.Key.Key_P: "profile", Qt.Key.Key_R: "rings"}

# The keys, for the card and for the tooltips.
KEYS = [
    ("Пробел", "играть / пауза"),
    ("← →", "кадр назад / вперёд"),
    ("Shift+← →", "секунда назад / вперёд"),
    ("Home / End", "в начало / в конец"),
    (", .", "к ключу назад / вперёд"),
    ("K", "ключ всем моторам слоя"),
    ("Shift+K", "ключ всем моторам всех слоёв"),
    ("Delete", "удалить выбранные ключи"),
    ("Ctrl+C / Ctrl+V", "копировать позу слоя / вставить на плейхед"),
    ("Ctrl+Z / Ctrl+Y", "отменить / вернуть"),
    ("B V P R", "кисть, выбор, профиль, кольца"),
    ("1 2 3", "слой: подъём, вынос, наклон"),
    ("M", "видео или маска"),
    ("ПКМ по 3D", "облёт; СКМ или Shift — сдвиг; колесо — ближе"),
]


def _divider() -> QFrame:
    line = QFrame()
    line.setFixedSize(1, 24)
    line.setStyleSheet(f"background:{theme.SEAM};")
    return line


def _button(text: str, name: str, call, hint: str = "") -> QPushButton:
    """A plain button; the words already in the window's language."""
    button = QPushButton(text)
    button.setObjectName(name)
    button.clicked.connect(call)
    if hint:
        button.setToolTip(hint)
    return button


def layout_key(event):
    """The key as it stands on the keyboard, whatever layout is on."""
    key = event.key()
    if sys.platform != "win32":
        return key
    code = event.nativeVirtualKey()
    if 0x41 <= code <= 0x5A:
        return Qt.Key(code)
    if 0x30 <= code <= 0x39:
        return Qt.Key(code)
    return {0xBC: Qt.Key.Key_Comma, 0xBE: Qt.Key.Key_Period}.get(code, key)


class PoseMotors:
    """A pose, answering the three questions `kinetic.transforms` asks of a
    motor file -- so the editor's cells move by the viewer's own arithmetic,
    the one checked against the rig."""

    def __init__(self, pose: dict) -> None:
        self.pose = pose

    def angle(self, frame=None) -> np.ndarray:
        return self.pose["tilt"] * kinetic.TILT_DEGREES

    def out(self, frame=None) -> np.ndarray:
        return (np.repeat(self.pose["push"], PER_PUSHER, axis=1)
                * kinetic.PUSHER_MM)

    def rise(self, frame=None) -> np.ndarray:
        # The machine's numbering, not the rig's: row N lifts ring N.
        return kinetic.rise_mm(self.pose["lift"], km.READING)


def mask_colours(pose: dict, layer: str) -> np.ndarray:
    """What each cell is painted, (ROWS, PER_ROW, 3), 0..1."""
    lift = km.spread("lift", pose["lift"])
    push = km.spread("push", pose["push"])
    tilt = pose["tilt"]
    red = np.interp(lift, [0, 1, 2, 3], LIFT_LEVEL)
    if layer == "rgb":
        return np.stack([red, push, np.clip(tilt + 0.5, 0, 1)], axis=-1)
    dark = np.array([0.10, 0.105, 0.115])

    def ramp(level, colour):
        colour = np.array([int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)])
        level = np.clip(level, 0, 1)[..., None]
        return dark * (1 - level) + colour * level

    if layer == "lift":
        return ramp(0.15 + 0.85 * red, FAMILY_COLOUR["lift"])
    if layer == "push":
        return ramp(0.12 + 0.88 * push, FAMILY_COLOUR["push"])
    level = np.abs(tilt) / km.TILT_REACH[2]
    warm = ramp(level, "#e3a04a")
    cold = ramp(level, FAMILY_COLOUR["tilt"])
    return np.where((tilt >= 0)[..., None], cold, warm)


class KineticEditor(QMainWindow):
    def __init__(self, open_path: str | None = None,
                 language: str | None = None) -> None:
        super().__init__()
        self.setObjectName("qa_kinedit")
        self.settings = self._read_settings()
        lang.set_language(language or self.settings.get("language")
                          or lang.language())
        self.context = None

        self.project = km.Project()
        self.frame = 0
        self.family = "tilt"
        self.layer = "rgb"
        self.show_mask = True
        self.tool = "brush"
        self.selection = np.zeros((ROWS, PER_ROW), bool)
        self.brush_lift = 1
        self.brush_push = 0.5
        self.brush_tilt = 10.0 / 90.0
        self.brush_mode = "paint"
        self.brush_strength = 0.6
        self.brush_radius = 2.5
        self.brush_hardness = 0.5
        self.undo: list = []
        self.redo: list = []
        self._editing = False
        self.dirty = False
        self.clipboard = None
        self._pose_cache = None
        self._under = None           # brush cells under the pointer in 3D
        self._drag = None
        self._hover = None
        self.clock = player.Clock()
        self.clock.rate = float(km.FPS)
        self.stream = None
        self.screen = None
        self.held = None
        self.track = None
        self.player = None

        self._start_device()
        self._build()
        self._start_drawing()
        QApplication.instance().installEventFilter(self)
        self._set_project(self.project)
        self.resize(1600, 960)
        if open_path:
            QTimer.singleShot(0, lambda: self.open_any(open_path))

    # -- settings, beside the program and its own ---------------------------------

    def _read_settings(self) -> dict:
        try:
            return json.loads((logfile.app_dir() / SETTINGS).read_text("utf-8"))
        except Exception:  # noqa: BLE001 -- first run, or a file broken by hand
            return {}

    def _write_settings(self) -> None:
        try:
            (logfile.app_dir() / SETTINGS).write_text(
                json.dumps(self.settings, indent=2, ensure_ascii=False), "utf-8")
        except OSError as error:
            logfile.write(f"kinetic editor: settings not written: {error}")

    def _folder(self, key: str) -> str:
        return self.settings.get(key) or str(Path.home())

    # -- the card and the scene -------------------------------------------------------

    def _start_device(self) -> None:
        self.failure = ""
        self.mesh = None
        self.solid = None
        try:
            self.adapter, self.device = screen_gpu.make_device()
        except Exception as error:  # noqa: BLE001 -- said in the window
            self.adapter = self.device = None
            self.failure = str(error)
            return
        folder = logfile.bundled(BAKED) or (logfile.app_dir() / BAKED)
        try:
            self.mesh = scene3d.Scene(self.device, folder)
        except Exception as error:  # noqa: BLE001
            self.failure = f"no baked geometry in {folder}: {error}"
            logfile.write(self.failure)
            return
        self.cell_at = self.mesh.cell_middles(scene3d.KINETIC_SCREEN)
        self.cell_is = kinetic.cell_addresses(self.cell_at)
        self.base_heights = np.array(
            [self.cell_at[self.cell_is[:, 0] == row, 2].mean()
             for row in range(ROWS)])
        flat = self.cell_at[:, :2].astype(np.float64)
        self.cell_radial = np.concatenate(
            [flat / np.linalg.norm(flat, axis=1, keepdims=True),
             np.zeros((len(flat), 1))], axis=1)

    def _start_drawing(self) -> None:
        self.context = None
        if self.device is None or self.mesh is None:
            self.status.setText(tr("Нет 3D: {0}", self.failure))
            return
        self.context = self.canvas.get_context("wgpu")
        preferred = self.context.get_preferred_format(self.adapter)
        self.format = preferred.replace("-srgb", "")
        self.context.configure(device=self.device, format=self.format)
        self.solid = renderer3d.Renderer3D(self.mesh, self.format)
        self.solid.show(scene3d.DEFAULT_TOP, False)
        self.solid.show(scene3d.KINETIC_SCREEN, True)
        folder = logfile.bundled(BAKED) or (logfile.app_dir() / BAKED)
        picture = folder / f"calibrate_{TOP}.png"
        if picture.is_file():
            from main import read_rgba
            self.solid.load_calibration(TOP, read_rgba(picture))
            self.solid.set_backing(True)
        self.solid.show_paint(self.show_mask)
        self.solid.cull(True)
        self._aim_camera()
        self.canvas.request_draw(self._draw)

    def _aim_camera(self) -> None:
        """Round the top screen rather than the whole building: from the
        file camera's side, level with the middle of the honeycomb."""
        self.mesh.fly(True)
        free = self.mesh.free
        low, high = self.cell_at.min(axis=0), self.cell_at.max(axis=0)
        centre = (low + high) / 2.0
        tall = float(high[2] - low[2])
        free.centre = centre.astype(np.float64)
        free.distance = tall * 0.8 / math.tan(free.fov_y / 2.0)
        free.pitch = math.radians(4.0)
        free._home = (free.centre.copy(), free.distance, free.yaw, free.pitch)
        self.unwrap.set_front(math.degrees(free.yaw))
        self.solid.refresh()

    # -- the window ---------------------------------------------------------------------

    def _build(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        page = QVBoxLayout(central)
        page.setContentsMargins(0, 0, 0, 0)
        page.setSpacing(0)
        page.addWidget(self._top_bar())

        body = QSplitter(Qt.Orientation.Vertical)
        body.setObjectName("qa_kin_body")
        # Laid side by side rather than split: the tools and the panel keep
        # their widths, and every pixel the window grows by goes to the view.
        upper = QWidget()
        across = QHBoxLayout(upper)
        across.setContentsMargins(0, 0, 0, 0)
        across.setSpacing(0)
        across.addWidget(self._tool_column())

        middle = QSplitter(Qt.Orientation.Vertical)
        self.canvas = RenderCanvas(parent=middle, update_mode="ondemand",
                                   max_fps=60, vsync=True)
        self.canvas.setObjectName("qa_kin_canvas")
        self.canvas.setMinimumHeight(260)
        self.canvas.add_event_handler(
            self._canvas_event, "wheel", "pointer_down", "pointer_move",
            "pointer_up", "double_click", "pointer_leave")
        middle.addWidget(self.canvas)
        self.unwrap = Unwrap()
        self.unwrap.stroke_started.connect(self.begin_edit)
        self.unwrap.dabbed.connect(self._dab)
        self.unwrap.stroke_finished.connect(self.end_edit)
        self.unwrap.selected.connect(self._select)
        self.unwrap.hovered.connect(self._hovered)
        middle.addWidget(self.unwrap)
        middle.setStretchFactor(0, 3)
        middle.setStretchFactor(1, 2)
        across.addWidget(middle, 1)

        self.panels = {
            "brush": kin_tools.BrushPanel(self),
            "select": kin_tools.SelectPanel(self),
            "profile": kin_tools.ProfilePanel(self),
            "rings": kin_tools.RingsPanel(self),
        }
        self.panel_stack = QStackedWidget()
        self.panel_stack.setObjectName("qa_kin_panels")
        self.panel_stack.setFixedWidth(330)
        self.panel_stack.setStyleSheet(
            f"QStackedWidget {{ background:{theme.CARD};"
            f" border-left:1px solid {theme.SEAM}; }}")
        for tool in TOOLS:
            self.panel_stack.addWidget(self.panels[tool])
        across.addWidget(self.panel_stack)
        body.addWidget(upper)

        lower = QWidget()
        column = QVBoxLayout(lower)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        self.timeline = KeyTimeline()
        self.timeline.seek.connect(self.go_to)
        self.timeline.family_chosen.connect(self.set_family)
        self.timeline.moved_keys.connect(self._move_keys)
        self.timeline.chosen_changed.connect(self._say_keys)
        column.addWidget(self._transport())
        column.addWidget(self.timeline, 1)
        body.addWidget(lower)
        body.setStretchFactor(0, 1)
        body.setStretchFactor(1, 0)
        page.addWidget(body, 1)
        page.addWidget(self._status_bar())
        self._choose_tool("brush")
        self.set_family("tilt")

    def _top_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("qa_kin_top")
        bar.setFixedHeight(48)
        bar.setStyleSheet(f"QWidget#qa_kin_top {{ background:{theme.BAR};"
                          f" border-bottom:1px solid {theme.SEAM}; }}")
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 0, 14, 0)
        row.setSpacing(8)
        name = QLabel(APP_NAME)
        name.setProperty("fixed_words", True)
        name.setFont(theme.heading())
        row.addWidget(name)
        self.project_name = QLabel()
        self.project_name.setObjectName("qa_kin_project")
        self.project_name.setProperty("fixed_words", True)
        self.project_name.setStyleSheet(f"color:{theme.SECOND};")
        row.addWidget(self.project_name)
        row.addSpacing(10)
        for text, name_, call, hint in (
                (tr("Новый"), "qa_kin_new", self.new_project,
                 tr("Пустая кинетика")),
                (tr("Открыть…"), "qa_kin_open", self.open_dialog,
                 tr("Проект редактора (.kin) или моторный JSON")),
                (tr("Сохранить"), "qa_kin_save", self.save, "Ctrl+S"),
                (tr("Экспорт JSON…"), "qa_kin_export", self.export_dialog,
                 tr("Моторный JSON для вьюера и площадки, Ctrl+E"))):
            row.addWidget(_button(text, name_, call, hint))
        row.addWidget(_divider())
        row.addWidget(_button(tr("Видео…"), "qa_kin_video", self.video_dialog,
                              tr("HAP или картинка на соты")))
        row.addWidget(_button(tr("Звук…"), "qa_kin_sound", self.sound_dialog,
                              "WAV"))
        row.addWidget(_divider())
        self.view_switch = kin_tools.segments(
            (tr("Видео"), tr("Маска")), "qa_kin_view",
            lambda i: self.set_mask(i == 1), 1)
        row.addWidget(self.view_switch)
        self.layer_switch = kin_tools.segments(
            [tr(one) for one in LAYER_NAMES], "qa_kin_layer",
            lambda i: self.set_layer(LAYERS[i]), 0)
        row.addWidget(self.layer_switch)
        row.addStretch(1)
        row.addWidget(_button(tr("Во вьюере"), "qa_kin_viewer", self.show_in_viewer,
                              tr("Сохранить JSON и открыть его во вьюере")))
        row.addWidget(_button(tr("Вид"), "qa_kin_home", self.home_view,
                              tr("Вернуть камеру")))
        for code, text in (("ru", "RU"), ("en", "EN")):
            button = QPushButton(text)
            button.setObjectName(f"qa_kin_lang_{code}")
            button.setProperty("pill", True)
            button.setProperty("fixed_words", True)
            button.setCheckable(True)
            button.setChecked(lang.language() == code)
            button.clicked.connect(lambda _=False, code=code: self.choose_language(code))
            row.addWidget(button)
            setattr(self, f"lang_{code}", button)
        return bar

    def _tool_column(self) -> QWidget:
        holder = QWidget()
        holder.setObjectName("qa_kin_tools")
        holder.setFixedWidth(84)
        holder.setStyleSheet(f"QWidget#qa_kin_tools {{ background:{theme.BAR};"
                             f" border-right:1px solid {theme.SEAM}; }}")
        column = QVBoxLayout(holder)
        column.setContentsMargins(6, 10, 6, 10)
        column.setSpacing(6)
        self.tool_buttons = {}
        for tool, text, key in zip(TOOLS, TOOL_NAMES, "BVPR"):
            button = QPushButton(tr(text))
            button.setObjectName(f"qa_kin_tool_{tool}")
            button.setCheckable(True)
            button.setToolTip(key)
            button.setFixedHeight(40)
            button.setStyleSheet("padding:5px 2px;")
            button.clicked.connect(lambda _=False, tool=tool: self._choose_tool(tool))
            column.addWidget(button)
            self.tool_buttons[tool] = button
        column.addStretch(1)
        return holder

    def _transport(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("qa_kin_transport")
        bar.setFixedHeight(44)
        bar.setStyleSheet(f"QWidget#qa_kin_transport {{ background:{theme.BAR};"
                          f" border-top:1px solid {theme.SEAM}; }}")
        row = QHBoxLayout(bar)
        row.setContentsMargins(12, 0, 12, 0)
        row.setSpacing(8)
        self.play_button = QPushButton("▶")
        self.play_button.setObjectName("qa_kin_play")
        self.play_button.setProperty("play", True)
        self.play_button.setProperty("fixed_words", True)
        self.play_button.setFixedSize(40, 30)
        self.play_button.setStyleSheet("color:#111111; font-size:14px;")
        self.play_button.clicked.connect(self.toggle_play)
        row.addWidget(self.play_button)
        self.clock_label = QLabel()
        self.clock_label.setObjectName("qa_kin_clock")
        self.clock_label.setFont(theme.mono(10))
        self.clock_label.setProperty("fixed_words", True)
        self.clock_label.setMinimumWidth(170)
        row.addWidget(self.clock_label)
        row.addWidget(_divider())
        for text, name, call, hint in (
                (tr("Ключ"), "qa_kin_key", lambda: self.key_all(False),
                 tr("K: ключ всем моторам слоя на плейхеде")),
                (tr("Ключ всем"), "qa_kin_key_all", lambda: self.key_all(True),
                 tr("Shift+K: ключ всем моторам всех слоёв")),
                (tr("Удалить ключи"), "qa_kin_delete_keys", self.delete_keys,
                 tr("Delete: выбранные ключи на таймлайне")),
                (tr("◀ ключ"), "qa_kin_prev_key", lambda: self.step_key(-1), ","),
                (tr("ключ ▶"), "qa_kin_next_key", lambda: self.step_key(1), ".")):
            row.addWidget(_button(text, name, call, hint))
        row.addWidget(_divider())
        self.warn_button = _button("", "qa_kin_warnings", self.next_warning,
                                   tr("К следующему ключу, где наклон вне предела"))
        self.warn_button.setStyleSheet(f"color:{theme.ERROR}; border-color:#5a2a26;")
        row.addWidget(self.warn_button)
        row.addStretch(1)
        length_label = QLabel(tr("Длина"))
        length_label.setStyleSheet(f"color:{theme.DIM};")
        row.addWidget(length_label)
        self.length_box = QDoubleSpinBox()
        self.length_box.setObjectName("qa_kin_length")
        self.length_box.setRange(1.0, 3600.0)
        self.length_box.setDecimals(2)
        self.length_box.setSuffix(tr(" с"))
        self.length_box.setFixedWidth(110)
        self.length_box.editingFinished.connect(self._length_typed)
        row.addWidget(self.length_box)
        return bar

    def _status_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("qa_kin_status_bar")
        bar.setFixedHeight(28)
        bar.setStyleSheet(f"QWidget#qa_kin_status_bar {{ background:{theme.SUNKEN};"
                          f" border-top:1px solid {theme.SEAM}; }}")
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 0, 14, 0)
        self.status = QLabel()
        self.status.setObjectName("qa_kin_status")
        self.status.setFont(theme.mono(8.5))
        self.status.setStyleSheet(f"color:{theme.QUIET};")
        row.addWidget(self.status, 1)
        self.hover_label = QLabel()
        self.hover_label.setObjectName("qa_kin_hover")
        self.hover_label.setFont(theme.mono(8.5))
        self.hover_label.setStyleSheet(f"color:{theme.SECOND};")
        row.addWidget(self.hover_label)
        return bar

    # -- the piece -----------------------------------------------------------------------

    def _set_project(self, project: km.Project) -> None:
        self.project = project
        self.undo, self.redo = [], []
        self.dirty = False
        self.frame = min(self.frame, project.length - 1)
        self.timeline.set_project(project)
        self.length_box.setValue(project.length / km.FPS)
        self._changed(keys=True)
        self._say_title()

    def _say_title(self) -> None:
        name = self.project.path.name if self.project.path else tr("без имени")
        star = " *" if self.dirty else ""
        self.project_name.setText(f"{name}{star}")
        self.setWindowTitle(f"{APP_NAME} — {name}{star}")

    def pose_now(self):
        key = (self.project.version, self.frame)
        if self._pose_cache is None or self._pose_cache[0] != key:
            self._pose_cache = (key, self.project.pose(self.frame))
        return self._pose_cache[1]

    def profile_here(self):
        return self.project.profiles.get(self.frame)

    def _changed(self, keys: bool = False) -> None:
        """Something about the piece or the playhead moved: say it all again."""
        pose = self.pose_now()
        if self.solid is not None:
            self.solid.set_cells(kinetic.transforms(
                self.cell_at, self.cell_is, PoseMotors(pose), self.frame))
        self._paint(pose)
        self.timeline.set_frame(self.frame)
        if keys:
            self.dirty = self.dirty or bool(self.undo)
            warnings = self.project.violations()
            self.timeline.set_warnings(warnings)
            self.warn_button.setText(tr("Вне предела: {0}", len(warnings))
                                     if warnings else "")
            self.warn_button.setVisible(bool(warnings))
            self.timeline.update()
            self._say_title()
        self.panels[self.tool].refresh()
        self._say_clock()
        self.touch()

    def _paint(self, pose: dict) -> None:
        """The cells' colours, and what is laid over them: red past the
        limit, the brush where it would land, and -- in 3D, where there is
        no outline to draw -- the selection lightened."""
        colours = mask_colours(pose, self.layer)
        over = np.zeros((ROWS, PER_ROW, 4), np.float32)
        warn = km.over_limit(pose["tilt"], pose["lift"])
        over[warn] = (0.95, 0.25, 0.25, 0.75)
        if self._under is not None:
            weight = self._under
            under = weight > 0
            over[under, :3] = 1.0
            over[under, 3] = np.maximum(over[under, 3], 0.2 + 0.35 * weight[under])
        self.unwrap.set_colours(colours, over, warn)
        self.unwrap.set_selection(self.selection)
        if self.solid is not None:
            solid = over.copy()
            chosen = self.selection & (solid[..., 3] < 0.35)
            solid[chosen] = (1.0, 1.0, 1.0, 0.35)
            rows, ids = self.cell_is[:, 0], self.cell_is[:, 1]
            self.solid.set_tints(colours[rows, ids], solid[rows, ids])

    def touch(self) -> None:
        if self.context is not None:
            self.canvas.request_draw()

    # -- drawing -------------------------------------------------------------------------

    def _draw(self) -> None:
        if self.clock.playing:
            seconds = self.clock.tick()
            frame = min(self.project.length - 1, int(round(seconds * km.FPS)))
            if frame != self.frame:
                self.frame = frame
                self._changed()
            if not self.clock.playing:
                self._stopped()
        self._feed_video()
        surface = self.context.get_current_texture()
        view = surface.create_view()
        width, height = surface.size[0], surface.size[1]
        encoder = self.device.create_command_encoder()
        self.solid.draw(encoder, view, width, height)
        self.device.queue.submit([encoder.finish()])
        if self.clock.playing:
            self.canvas.request_draw()

    def _feed_video(self) -> None:
        stream = self.stream
        if stream is None or self.screen is None:
            return
        seconds = self.frame / km.FPS
        wanted = stream.index_at(seconds)
        held = self.held
        if held is not None and wanted - held.index > max(stream.rate, 1.0):
            stream.seek(wanted)
            stream.give_back(held)
            self.held = held = None
        if held is not None and wanted < held.index:
            stream.seek(wanted)
            stream.give_back(held)
            self.held = held = None
        got = stream.take(wanted, held)
        if got is not None:
            if held is not None:
                stream.give_back(held)
            self.held = got
            self.screen.upload([memoryview(b) for b in got.buffers])
        if (self.held is None or self.held.index < wanted) and stream.rate:
            QTimer.singleShot(8, self.touch)

    # -- time --------------------------------------------------------------------------------

    def go_to(self, frame: int) -> None:
        frame = int(max(0, min(self.project.length - 1, frame)))
        self.clock.move_to(frame / km.FPS)
        if self.player is not None:
            self.player.move_to(frame / km.FPS)
        if frame != self.frame:
            self.frame = frame
            self._changed()

    def toggle_play(self) -> None:
        if self.clock.playing:
            self.clock.playing = False
            self._stopped()
            return
        self.clock.duration = (self.project.length - 1) / km.FPS
        if self.frame >= self.project.length - 1:
            self.go_to(0)
        self.clock.move_to(self.frame / km.FPS)
        if self.player is not None:
            self.player.move_to(self.frame / km.FPS)
            self.player.play()
        self.clock.playing = True
        self.play_button.setText("❚❚")
        self.touch()

    def _stopped(self) -> None:
        if self.player is not None:
            self.player.pause()
        self.play_button.setText("▶")

    def _say_clock(self) -> None:
        import show as showfile
        self.clock_label.setText(f"{showfile.timecode(self.frame)}  "
                                 + tr("кадр {0}", self.frame))

    def _length_typed(self) -> None:
        frames = int(round(self.length_box.value() * km.FPS))
        if frames == self.project.length:
            return
        self._record()
        self.project.length = max(2, frames)
        self.timeline.set_project(self.project)
        self.go_to(min(self.frame, self.project.length - 1))
        self._changed(keys=True)

    # -- undo ------------------------------------------------------------------------------

    def _record(self) -> None:
        self.undo.append(self.project.state())
        del self.undo[:-UNDO_DEPTH]
        self.redo.clear()
        self.dirty = True

    def begin_edit(self) -> None:
        """A drag begins: one undo step for all of it."""
        if not self._editing:
            self._record()
            self._editing = True

    def end_edit(self) -> None:
        self._editing = False
        self._changed(keys=True)

    def _step_undo(self, back: bool) -> None:
        source, target = (self.undo, self.redo) if back else (self.redo, self.undo)
        if not source:
            return
        target.append(self.project.state())
        self.project.restore(source.pop())
        self.timeline.chosen = set()
        self.timeline.axis.stretch(self.project.length)
        self.length_box.setValue(self.project.length / km.FPS)
        self.frame = min(self.frame, self.project.length - 1)
        self.dirty = True
        self._changed(keys=True)

    # -- the tools ----------------------------------------------------------------------------

    def _choose_tool(self, tool: str) -> None:
        self.tool = tool
        for name, button in self.tool_buttons.items():
            button.setChecked(name == tool)
        self.panel_stack.setCurrentWidget(self.panels[tool])
        self.unwrap.tool = "brush" if tool == "brush" else "select"
        self.unwrap.grain = "ring" if tool == "rings" else self.unwrap.grain
        self._under = None
        self.panels[tool].refresh()
        self._changed()

    def set_family(self, family: str) -> None:
        self.family = family
        self.timeline.set_family(family)
        self.panels["brush"].show_family(family)
        if self.layer != "rgb":
            self.set_layer(family)

    def set_layer(self, layer: str) -> None:
        self.layer = layer
        self.layer_switch.buttons[LAYERS.index(layer)].setChecked(True)
        if layer != "rgb" and layer != self.family:
            self.set_family(layer)
            return
        self._changed()

    def set_mask(self, on: bool) -> None:
        self.show_mask = bool(on)
        self.view_switch.buttons[1 if on else 0].setChecked(True)
        if self.solid is not None:
            self.solid.show_paint(self.show_mask)
        self.touch()

    def set_brush_radius(self, radius: float) -> None:
        self.brush_radius = float(radius)
        self.unwrap.radius = self.brush_radius
        self.unwrap.update()

    def set_brush_hardness(self, percent: float) -> None:
        self.brush_hardness = float(percent) / 100.0
        self.unwrap.hardness = self.brush_hardness

    def set_grain(self, grain: str) -> None:
        self.unwrap.grain = grain

    def _target(self) -> float:
        return {"lift": float(self.brush_lift), "push": self.brush_push,
                "tilt": self.brush_tilt}[self.family]

    def _dab(self, weights) -> None:
        track = self.project.tracks[self.family]
        values, mask = km.brush(track, self.frame, weights, self._target(),
                                self.brush_strength, self.brush_mode)
        self._write(self.family, values, mask)
        self._changed()

    def _write(self, family: str, values, mask) -> None:
        """Key `values` for the motors in `mask` at the playhead, in bounds."""
        track = self.project.tracks[family]
        if family == "tilt":
            values = km.clamp_tilt(values, self.pose_now()["lift"]).reshape(-1)
        track.write(self.frame, values, mask)
        self.dirty = True

    def _select(self, cells, how: str) -> None:
        if how == "add":
            self.selection = self.selection | cells
        elif how == "take":
            self.selection = self.selection & ~cells
        else:
            self.selection = np.asarray(cells, bool).copy()
        if self.tool == "rings" and cells.any():
            pass
        self._changed()

    def select_all(self) -> None:
        self._select(np.ones((ROWS, PER_ROW), bool), "set")

    def select_none(self) -> None:
        self._select(np.zeros((ROWS, PER_ROW), bool), "set")

    def select_invert(self) -> None:
        self._select(~self.selection, "set")

    def set_selected(self, family: str, value: float, live: bool = False) -> None:
        """One value for every chosen motor of a family, keyed here."""
        cells = self.selection
        if not cells.any():
            self.status.setText(tr("Сначала выберите соты"))
            return
        if not live:
            self._record()
        mask = km.cell_mask_for(family, cells)
        size = self.project.tracks[family].size
        self._write(family, np.full(size, value, np.float32), mask)
        self._changed(keys=not live)

    def set_rings(self, rings, state: int) -> None:
        self._record()
        rings = np.asarray(rings, bool)
        self._write("lift", np.full(ROWS, float(state)), rings)
        self._changed(keys=True)

    def auto_rotate(self, gain: float) -> None:
        pose = self.pose_now()
        cells = self.selection if self.selection.any() else np.ones((ROWS, PER_ROW), bool)
        tilt = km.auto_tilt(pose["lift"], pose["push"], gain, self.base_heights
                            if self.mesh is not None else None)
        self._record()
        self._write("tilt", tilt, cells.reshape(-1))
        self._changed(keys=True)

    def apply_profile(self, points, tangent: bool) -> None:
        """The vase at the playhead: every chosen ring's pushers to the curve,
        and the cells laid along it if asked."""
        curve = km.profile_curve(points)
        push = np.repeat(curve[:, None], km.GROUPS, axis=1)
        groups = (km.cell_mask_for("push", self.selection)
                  if self.selection.any() else np.ones(ROWS * km.GROUPS, bool))
        self._write("push", push.reshape(-1), groups)
        self.project.profiles[self.frame] = [list(p) for p in points]
        if tangent:
            pose = self.project.pose(self.frame)
            tilt = km.auto_tilt(pose["lift"], pose["push"], 1.0,
                                self.base_heights if self.mesh is not None else None)
            rows = groups.reshape(ROWS, km.GROUPS).any(axis=1)
            cells = np.repeat(rows[:, None], PER_ROW, axis=1)
            if self.selection.any():
                cells = cells & np.repeat(
                    groups.reshape(ROWS, km.GROUPS), PER_PUSHER, axis=1)
            self._write("tilt", tilt, cells.reshape(-1))
        self._changed()

    # -- keys ------------------------------------------------------------------------------

    def key_all(self, every: bool) -> None:
        self._record()
        pose = self.pose_now()
        for family in (km.FAMILIES if every else (self.family,)):
            track = self.project.tracks[family]
            track.write(self.frame, pose[family].reshape(-1),
                        np.ones(track.size, bool))
        self._changed(keys=True)

    def delete_keys(self) -> None:
        chosen = sorted(self.timeline.chosen)
        if not chosen:
            self.status.setText(tr("Выберите ключи на таймлайне"))
            return
        self._record()
        for family, frame in chosen:
            track = self.project.tracks[family]
            index = track.index(frame)
            if index is not None:
                track.remove(index)
        self.timeline.chosen = set()
        self._changed(keys=True)

    def _move_keys(self, chosen, by: int) -> None:
        self._record()
        moved = set()
        for family in km.FAMILIES:
            frames = sorted((f for fam, f in chosen if fam == family),
                            reverse=by > 0)
            track = self.project.tracks[family]
            for frame in frames:
                index = track.index(frame)
                if index is None:
                    continue
                target = max(0, min(self.project.length - 1, frame + by))
                track.move(index, target)
                moved.add((family, target))
        self.timeline.chosen = moved
        self._changed(keys=True)

    def step_key(self, direction: int) -> None:
        frames = self.project.tracks[self.family].frames
        if direction > 0:
            later = [f for f in frames if f > self.frame]
            if later:
                self.go_to(later[0])
        else:
            earlier = [f for f in frames if f < self.frame]
            if earlier:
                self.go_to(earlier[-1])

    def next_warning(self) -> None:
        found = [frame for frame, _ in self.project.violations()]
        if not found:
            return
        later = [f for f in found if f > self.frame]
        self.go_to(later[0] if later else found[0])

    def copy_pose(self) -> None:
        self.clipboard = (self.family, self.pose_now()[self.family].copy())
        self.status.setText(tr("Поза слоя «{0}» скопирована", tr(FAMILY_NAME[self.family])))

    def paste_pose(self) -> None:
        if self.clipboard is None:
            return
        family, values = self.clipboard
        self._record()
        track = self.project.tracks[family]
        self._write(family, values.reshape(-1), np.ones(track.size, bool))
        self._changed(keys=True)

    def _say_keys(self) -> None:
        count = len(self.timeline.chosen)
        self.status.setText(tr("Выбрано ключей: {0}", count) if count else "")

    # -- the 3D view ---------------------------------------------------------------------------

    def _cells_on_screen(self):
        """Every cell's centre on the canvas, in logical pixels, and whether
        it faces the camera."""
        matrices = kinetic.transforms(self.cell_at, self.cell_is,
                                      PoseMotors(self.pose_now()), self.frame)
        spot = (np.einsum("cij,cj->ci", matrices[:, :3, :3], self.cell_at)
                + matrices[:, :3, 3])
        facing = np.einsum("cij,cj->ci", matrices[:, :3, :3], self.cell_radial)
        transform = self.mesh.view_projection().astype(np.float64)
        clip = np.concatenate([spot, np.ones((len(spot), 1))], axis=1) @ transform.T
        wide, tall = self.canvas.get_logical_size()
        in_front = clip[:, 3] > 1e-6
        ndc = clip[:, :2] / np.where(in_front, clip[:, 3], 1.0)[:, None]
        x = (ndc[:, 0] + 1.0) * 0.5 * wide
        y = (1.0 - ndc[:, 1]) * 0.5 * tall
        eye = self.mesh.free.eye()
        towards = eye[None, :] - spot
        faces = in_front & (np.einsum("ci,ci->c", facing, towards) > 0)
        return np.stack([x, y], axis=1), faces, clip[:, 3]

    def _cell_under(self, x: float, y: float):
        places, faces, depth = self._cells_on_screen()
        gap = np.hypot(places[:, 0] - x, places[:, 1] - y)
        gap = np.where(faces, gap, np.inf)
        best = int(np.argmin(gap))
        if not np.isfinite(gap[best]) or gap[best] > 40:
            return None
        return tuple(int(v) for v in self.cell_is[best])

    def _canvas_event(self, event) -> None:
        if self.solid is None:
            return
        kind = event["event_type"]
        free = self.mesh.free
        x, y = event.get("x", 0.0), event.get("y", 0.0)
        buttons = event.get("buttons", ()) or ()
        mods = event.get("modifiers", ()) or ()
        if kind == "wheel":
            steps = -event.get("dy", 0) / 120.0
            if "Control" in mods and self.tool == "brush":
                self.set_brush_radius(float(np.clip(
                    self.brush_radius * 1.15 ** steps, 0.5, 15.0)))
                self.panels["brush"].show_radius(self.brush_radius)
            elif steps:
                free.dolly(0.85 ** steps)
                self.solid.refresh()
            self.touch()
            return
        if kind == "double_click" and event.get("button") == 3:
            self.home_view()
            return
        if kind == "pointer_down":
            button = event.get("button")
            if button == 2 or button == 3 or ("Alt" in mods and button == 1):
                sliding = button == 3 or "Shift" in mods
                self._drag = ("slide" if sliding else "turn", x, y)
                return
            if button == 1:
                got = self._cell_under(x, y)
                if self.tool == "brush":
                    self._drag = ("brush",)
                    self.begin_edit()
                    if got is not None:
                        self._dab(self._weights_at(got))
                else:
                    how = ("take" if "Control" in mods
                           else "add" if "Shift" in mods else "set")
                    self._drag = ("select", how)
                    if got is not None:
                        self._select(self._grain_cells(got), how)
                    elif how == "set":
                        self.select_none()
            return
        if kind == "pointer_move":
            got = None
            if self._drag and self._drag[0] in ("turn", "slide"):
                wide, tall = self.canvas.get_logical_size()
                across = (x - self._drag[1]) / max(wide, 1)
                down = (y - self._drag[2]) / max(tall, 1)
                if self._drag[0] == "slide":
                    free.pan(across, down)
                else:
                    free.turn(across * math.pi, down * math.pi * 0.5)
                self._drag = (self._drag[0], x, y)
                self.solid.refresh()
                self.touch()
                return
            got = self._cell_under(x, y)
            self._hovered(*(got if got else (-1, -1)))
            if self.tool == "brush":
                self._under = self._weights_at(got) if got is not None else None
                if self._drag and self._drag[0] == "brush" and got is not None:
                    self._dab(self._under)
                else:
                    self._paint(self.pose_now())
                    self.touch()
            elif self._drag and self._drag[0] == "select" and got is not None:
                how = self._drag[1] if self._drag[1] != "set" else "add"
                self._select(self._grain_cells(got), how)
            return
        if kind == "pointer_up":
            if self._drag and self._drag[0] == "brush":
                self.end_edit()
            self._drag = None
            return
        if kind == "pointer_leave":
            self._under = None
            self._hovered(-1, -1)
            self._paint(self.pose_now())
            self.touch()

    def _weights_at(self, cell) -> np.ndarray:
        row, which = cell
        return brush_weights(self.unwrap.places, self.unwrap.places[row, which],
                             self.brush_radius, self.brush_hardness)

    def _grain_cells(self, cell) -> np.ndarray:
        cells = np.zeros((ROWS, PER_ROW), bool)
        cells[cell] = True
        return self.unwrap._grain(cells)

    def home_view(self) -> None:
        if self.mesh is not None and self.mesh.free is not None:
            self.mesh.free.reset()
            self.solid.refresh()
            self.touch()

    def _hovered(self, row: int, which: int) -> None:
        if row < 0:
            self.hover_label.setText("")
            return
        pose = self.pose_now()
        lift = float(pose["lift"][row])
        push = float(pose["push"][row, which // PER_PUSHER])
        tilt = float(pose["tilt"][row, which])
        reach = float(km.tilt_reach(pose["lift"])[row])
        # The lowest ring stands on the base: there is no gap under it.
        gap = ("—" if row == km.NO_JACK
               else f"{float(kinetic._state_mm(lift)):.0f} " + tr("мм"))
        self.hover_label.setText(tr(
            "кольцо {0}, сота {1}: зазор под ним {2}, вынос {3:.0f} мм, "
            "наклон {4:+.1f}° (предел ±{5:.0f}°)",
            row + 1, which + 1, gap, push * 1000, tilt * 90, reach * 90))

    # -- keys on the keyboard ------------------------------------------------------------------

    def _typing(self) -> bool:
        spot = QApplication.focusWidget()
        return (isinstance(spot, QLineEdit) and spot.isEnabled()
                and not spot.isReadOnly())

    def eventFilter(self, watched, event):          # noqa: N802
        if (event.type() == QEvent.Type.KeyPress and self.isActiveWindow()
                and not self._typing() and self._key(event)):
            return True
        return super().eventFilter(watched, event)

    def _key(self, event) -> bool:
        key = layout_key(event)
        mods = event.modifiers()
        control = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        if key == Qt.Key.Key_Space:
            self.toggle_play()
        elif key == Qt.Key.Key_Left:
            self.go_to(self.frame - (km.FPS if shift else 1))
        elif key == Qt.Key.Key_Right:
            self.go_to(self.frame + (km.FPS if shift else 1))
        elif key == Qt.Key.Key_Home:
            self.go_to(0)
        elif key == Qt.Key.Key_End:
            self.go_to(self.project.length - 1)
        elif key == Qt.Key.Key_Comma:
            self.step_key(-1)
        elif key == Qt.Key.Key_Period:
            self.step_key(1)
        elif control and key == Qt.Key.Key_Z:
            self._step_undo(True)
        elif control and key == Qt.Key.Key_Y:
            self._step_undo(False)
        elif control and key == Qt.Key.Key_S:
            self.save()
        elif control and key == Qt.Key.Key_E:
            self.export_dialog()
        elif control and key == Qt.Key.Key_O:
            self.open_dialog()
        elif control and key == Qt.Key.Key_C:
            self.copy_pose()
        elif control and key == Qt.Key.Key_V:
            self.paste_pose()
        elif control:
            return False
        elif key == Qt.Key.Key_K:
            self.key_all(shift)
        elif key == Qt.Key.Key_Delete:
            self.delete_keys()
        elif key == Qt.Key.Key_M:
            self.set_mask(not self.show_mask)
        elif key in TOOL_KEYS and not shift:
            self._choose_tool(TOOL_KEYS[key])
        elif key in (Qt.Key.Key_1, Qt.Key.Key_2, Qt.Key.Key_3):
            self.set_family(km.FAMILIES[int(key) - int(Qt.Key.Key_1)])
        else:
            return False
        return True

    # -- files -----------------------------------------------------------------------------------

    def _unsaved_ok(self) -> bool:
        if not self.dirty:
            return True
        answer = QMessageBox.question(
            self, APP_NAME, tr("Сохранить изменения в кинетике?"),
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            return self.save()
        return True

    def new_project(self) -> None:
        if not self._unsaved_ok():
            return
        self.frame = 0
        self._set_project(km.Project())

    def open_dialog(self) -> None:
        if not self._unsaved_ok():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Открыть кинетику"), self._folder("folder"),
            tr("Кинетика (*.kin *.json)"))
        if path:
            self.open_any(path, asked=True)

    def open_any(self, path: str, asked: bool = False) -> bool:
        path = Path(path)
        try:
            if path.suffix.lower() == PROJECT_SUFFIX:
                project = km.Project.load(path)
                said = []
            else:
                project, said = km.from_motor_json(path)
        except km.ModelError as error:
            QMessageBox.warning(self, APP_NAME, str(error))
            return False
        self.settings["folder"] = str(path.parent)
        self._write_settings()
        self.frame = 0
        self._set_project(project)
        if project.video:
            self.load_video(project.video)
        if project.sound:
            self.load_sound(project.sound)
        words = tr("Открыто: {0}", path.name)
        if said:
            words += " — " + "; ".join(said)
        self.status.setText(words)
        logfile.write(f"kinetic editor: opened {path.name} "
                      f"({', '.join(said) or 'clean'})")
        return True

    def save(self) -> bool:
        path = self.project.path
        if path is None or path.suffix.lower() != PROJECT_SUFFIX:
            path, _ = QFileDialog.getSaveFileName(
                self, tr("Сохранить кинетику"),
                str(Path(self._folder("folder")) / f"{self.project.name}{PROJECT_SUFFIX}"),
                tr("Проект кинетики (*.kin)"))
            if not path:
                return False
            path = Path(path)
            if path.suffix.lower() != PROJECT_SUFFIX:
                path = path.with_suffix(PROJECT_SUFFIX)
        self.project.name = path.stem
        self.project.save(path)
        self.dirty = False
        self.settings["folder"] = str(path.parent)
        self._write_settings()
        self._say_title()
        self.status.setText(tr("Сохранено: {0}", path.name))
        return True

    def export_dialog(self) -> None:
        folder = Path(self._folder("export_folder"))
        path, _ = QFileDialog.getSaveFileName(
            self, tr("Экспорт моторного JSON"),
            str(folder / f"{self.project.name}_1_of_1.json"),
            tr("Моторный JSON (*.json)"))
        if path:
            self.export_to(path)

    def export_to(self, path) -> Path:
        written = km.export_motor_json(self.project, path)
        self.settings["export_folder"] = str(written.parent)
        self._write_settings()
        warnings = self.project.violations()
        words = tr("Записан {0}", written.name)
        if warnings:
            words += " — " + tr("наклон вне предела на {0} ключах", len(warnings))
        self.status.setText(words)
        logfile.write(f"kinetic editor: exported {written}")
        return written

    def show_in_viewer(self) -> None:
        folder = (self.project.path.parent if self.project.path
                  else logfile.app_dir())
        written = self.export_to(folder / f"{self.project.name}_1_of_1.json")
        if getattr(sys, "frozen", False):
            command = [sys.executable, "--motors", str(written)]
        else:
            command = [sys.executable, str(Path(__file__).with_name("main.py")),
                       "--motors", str(written)]
        if self.project.video:
            command += ["--top", self.project.video]
        if self.project.sound:
            command += ["--sound", self.project.sound]
        subprocess.Popen(command, close_fds=True)

    def video_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Видео на соты"), self._folder("media_folder"),
            tr("Видео и картинки (*.mov *.mp4 *.png *.jpg *.jpeg *.tif *.tiff)"))
        if path:
            self._record()
            self.project.video = path
            self.settings["media_folder"] = str(Path(path).parent)
            self._write_settings()
            self.load_video(path)
            self.set_mask(False)

    def load_video(self, path: str) -> None:
        if self.device is None or self.solid is None:
            return
        if self.stream is not None:
            self.stream.stop()
            self.stream = self.screen = self.held = None
        try:
            texture = self.solid.calibration.get(TOP)
            pixels = (tuple(texture.size)[:2] if texture is not None
                      and tuple(texture.size)[:2] != (1, 1) else None)
            self.stream = player.open_source(path, pixels)
            self.screen = screen_gpu.Screen(self.device, self.stream.movie)
        except Exception as error:  # noqa: BLE001 -- said in the window
            self.stream = self.screen = None
            self.status.setText(tr("Видео не открылось: {0}", str(error)[:80]))
            logfile.write(f"kinetic editor: {path}: {error}")
            return
        self.stream.start()
        screen = self.screen
        self.solid.set_video(TOP, screen.planes[0].texture, screen.planes[1].texture,
                             screen.ycocg, screen.alpha_from, screen.uv_scale)
        self.solid.set_video_opacity(1.0)
        seconds = self.stream.duration
        if seconds and seconds * km.FPS > self.project.length:
            self.project.length = int(round(seconds * km.FPS))
            self.timeline.set_project(self.project)
            self.length_box.setValue(self.project.length / km.FPS)
        self.status.setText(tr("Видео: {0}", Path(path).name))
        self.touch()

    def sound_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Звук"), self._folder("media_folder"), tr("Звук (*.wav)"))
        if path:
            self._record()
            self.project.sound = path
            self.settings["media_folder"] = str(Path(path).parent)
            self._write_settings()
            self.load_sound(path)

    def load_sound(self, path: str) -> None:
        if self.player is not None:
            self.player.stop()
        self.player = self.track = None
        self.clock.source = None
        try:
            self.track = sound.read_wav(path)
            self.player = sound.Player(self.track)
        except Exception as error:  # noqa: BLE001
            self.track = None
            self.player = None
            self.timeline.set_sound(None)
            self.status.setText(tr("Звук не открылся: {0}", str(error)[:80]))
            return
        self.player.set_volume(1.0)
        self.player.move_to(self.frame / km.FPS)
        self.clock.source = lambda: (self.player.played if self.player is not None
                                     and self.player.playing else None)
        self.timeline.set_sound(self.track)
        if self.track.duration * km.FPS > self.project.length:
            self.project.length = int(round(self.track.duration * km.FPS))
            self.timeline.set_project(self.project)
            self.length_box.setValue(self.project.length / km.FPS)
        self.status.setText(tr("Звук: {0}", self.track.describe()))

    # -- language --------------------------------------------------------------------------------

    def choose_language(self, code: str) -> None:
        for other in ("ru", "en"):
            getattr(self, f"lang_{other}").setChecked(other == code)
        if code == lang.language():
            return
        lang.set_language(code)
        for widget in [self] + self.findChildren(QWidget):
            if widget.property("fixed_words"):
                continue
            if isinstance(widget, (QAbstractButton, QLabel)):
                said = lang.other(widget.text(), code) if widget.text() else None
                if said is not None:
                    widget.setText(said)
            if isinstance(widget, QComboBox):
                for index in range(widget.count()):
                    said = lang.other(widget.itemText(index), code)
                    if said is not None:
                        widget.setItemText(index, said)
            tip = widget.toolTip()
            said = lang.other(tip, code) if tip else None
            if said is not None:
                widget.setToolTip(said)
            # A number's unit, which rides after it with a space.
            if isinstance(widget, QDoubleSpinBox) and widget.suffix().strip():
                said = lang.other(widget.suffix().strip(), code)
                if said is not None:
                    widget.setSuffix(f" {said}")
        self.length_box.setSuffix(tr(" с"))
        self.status.setText("")
        self.settings["language"] = code
        self._write_settings()
        self._say_title()
        self._changed(keys=True)

    def closeEvent(self, event) -> None:            # noqa: N802
        if not self._unsaved_ok():
            event.ignore()
            return
        if self.stream is not None:
            self.stream.stop()
        if self.player is not None:
            self.player.stop()
        super().closeEvent(event)


def main(argv=None) -> int:
    """The editor on its own: a file to open, and `--lang ru|en`."""
    from main import APP_VERSION
    argv = list(sys.argv if argv is None else argv)
    logfile.start(APP_NAME, APP_VERSION)
    app = QApplication.instance() or QApplication(argv)
    folder = logfile.bundled("fonts") or (Path(__file__).resolve().parent / "fonts")
    theme.load_fonts(folder)
    app.setFont(theme.app_font())
    app.setStyleSheet(theme.sheet())
    logfile.raise_splash(app)
    opened = next((one for one in argv[1:] if not one.startswith("--")
                   and Path(one).suffix.lower() in (PROJECT_SUFFIX, ".json")), None)
    asked = None
    for index, one in enumerate(argv):
        if one == "--lang" and index + 1 < len(argv):
            asked = argv[index + 1]
    window = KineticEditor(opened, asked)
    window.show()
    logfile.loading_done()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
