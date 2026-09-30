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
  the tools     brush, selection, the vase's profile, the motors, and the
                primitives -- spheres and boxes the honeycomb wraps
  the timeline  a lane of keys a family, a lane a primitive, and the sound
                under them

A mask chosen beside the poses keeps every edit made at the playhead to its
cells; the brush paints it as well as the keys. The primitives lie over the
keys (`kin_prims`): the picture shows what they make, and the simulation and
the export run the piece with them turned into keys.

Under the keys, layers of clips, as Blender's NLA (`kin_layers`): the keys
go into a clip on a layer of their own, clips are laid along and over each
other, blended in and out, repeated, reversed, moved round the building, and
kept in a library beside the program. The keys lie over the layers, and the
primitives over both; the simulation and the export get the lot as keys.

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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import (QAbstractButton, QApplication, QComboBox,
                               QDoubleSpinBox, QFileDialog, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QMainWindow, QMessageBox,
                               QPushButton, QScrollArea, QSplitter,
                               QStackedWidget, QVBoxLayout, QWidget)
from rendercanvas.pyside6 import RenderCanvas

import kin_model as km
import kin_gizmo
import kin_layers
import kin_overlay
import kin_plan
import kin_prims
import kin_sample
import kin_sim
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
from kin_timeline import (FAMILY_COLOUR, FAMILY_NAME, PRIM_COLOUR, KeyTimeline,
                          lane_of)
from kin_unwrap import RING_PITCH, Unwrap, brush_weights
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
# One layer is worked on at a time, Q W E; the picture shows it alone, or
# all three together in Houdini's colours with RGB on.
LAYER_NAMES = ("Подъём", "Вынос", "Наклон")
TOOLS = ("brush", "select", "profile", "motors", "prims", "layers")
TOOL_NAMES = ("Кисть", "Выбор", "Профиль", "Моторы", "Примитивы", "Слои")
TOOL_KEYS = {Qt.Key.Key_B: "brush", Qt.Key.Key_V: "select",
             Qt.Key.Key_P: "profile", Qt.Key.Key_S: "motors",
             Qt.Key.Key_O: "prims", Qt.Key.Key_L: "layers"}
TOOL_LETTERS = "BVPSOL"
# The tools that are no cells' business: what is chosen and the poses step
# aside for their own settings.
OWN_COLUMN = ("prims", "layers")
CLIPS = "kinedit_clips.json"
# A mask painted: its weight from the dark of the cells to its own lilac.
MASK_COLOUR = np.array([0.80, 0.60, 0.95])
POSES = "kinedit_poses.json"
# What the picture shows: the keys, the motors' own motion, or both -- one
# of them then a ghost.
VIEWS = ("keys", "sim", "both")
VIEW_NAMES = ("Ключи", "Симуляция", "Оба")
TIMELINE_NAMES = ("Простой", "Подробный", "Слои")
# Selection's three sizes on 1 2 3, as Blender's modes; the layers on Q W E.
GRAIN_KEYS = {Qt.Key.Key_1: "ring", Qt.Key.Key_2: "group", Qt.Key.Key_3: "cell"}
GRAIN_NAMES = {"ring": "кольца", "group": "группы", "cell": "отдельные соты"}
LAYER_KEYS = {Qt.Key.Key_Q: "lift", Qt.Key.Key_W: "push", Qt.Key.Key_E: "tilt"}
# Behind the building: a little off black, so the dark backs of the panels
# and the canopy read against it.
BACKGROUND = (0.137, 0.141, 0.157)
SIM_WAIT_MS = 250

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
    ("B V P S O L", "кисть, выбор, профиль, моторы, примитивы, слои"),
    ("1 2 3", "выбор: кольца, группы, соты"),
    ("Q W E", "слой: подъём, вынос, наклон"),
    ("G R H", "тянуть вынос, наклон, подъём выбранного; щелчок — принять, Esc — отменить"),
    ("T", "ручки выбранного в 3D; Shift — всем выбранным"),
    ("M", "видео или маска"),
    ("ПКМ по 3D", "облёт; СКМ или Shift — сдвиг; колесо — ближе"),
    ("ПКМ по карте", "сдвиг; колесо — ближе; двойной ПКМ — вся карта"),
    ("?", "эта подсказка"),
]


def to_rgb(colour: str):
    """'#rrggbb' as three 0..1."""
    return tuple(int(colour[i:i + 2], 16) / 255.0 for i in (1, 3, 5))


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
    level = np.abs(tilt) / 0.5            # 45 degrees, the widest there is
    warm = ramp(level, "#e3a04a")
    cold = ramp(level, FAMILY_COLOUR["tilt"])
    return np.where((tilt >= 0)[..., None], cold, warm)


def weight_colours(weights) -> np.ndarray:
    """A mask's weights as the cells' colours, (ROWS, PER_ROW, 3)."""
    weights = np.clip(np.asarray(weights, np.float32).reshape(ROWS, PER_ROW), 0, 1)
    dark = np.array([0.10, 0.105, 0.115])
    return dark * (1 - weights[..., None]) + MASK_COLOUR * weights[..., None]


def work_out_motion(project, pace: dict):
    """Everything the motors' motion needs, worked out off the window's
    thread on a copy of the piece: what it means as keys, the plan of moves
    made of that, the simulation of the plan, the keys past their limits.
    (desired, composed, simulation, warnings, seconds)."""
    started = time.perf_counter()
    desired = kin_prims.compose(kin_layers.flatten(project))
    composed = (kin_plan.plan(desired, pace, project.tolerance) if project.plan
                else desired)
    result = kin_sim.simulate(composed, pace)
    warnings = desired.violations()
    return desired, composed, result, warnings, time.perf_counter() - started


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
        self.show_all = True               # RGB: all three layers together
        self.brush_inside = False          # paint only what is chosen
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
        self.gizmos_on = True           # handles on what is chosen, in 3D
        self.handles: list = []
        self._hot = None                # the handle under the hand
        self._grab = None               # a handle being dragged
        self._modal = None              # G, R, H under way
        self.overlay = None
        self._hover = None
        # Masks and primitives: the mask edits are kept to, what the brush
        # paints, the primitive worked on.
        self.edit_mask = ""
        self.brush_target = "keys"
        self.prim_index = -1
        self._edit_base = None          # the pose an edit under way began at
        self._composed = None
        self._desired = None
        self._shown_cache = None
        self.sampler = None             # the video, a colour a cell, for the strip
        self.strip_picture = None       # and as the cells show it, patch by patch
        self._picture_for = None
        self._video_cells = None
        self._strip_layers = (None, None, None)
        self._prims_seen = None
        self.layer_index = -1           # the layer clips are put on
        self.strip_key = None           # (layer, strip) chosen on the timeline
        # The motors' own motion, worked out a moment after the keys change.
        self.view = "both"
        self.ghost_is = "keys"
        self.cull = True
        self.pace = dict(kin_sim.PACE)
        self.sim = None
        self._sim_for = None
        self._sim_pose = None
        self.sim_timer = QTimer(self)
        self.sim_timer.setSingleShot(True)
        self.sim_timer.timeout.connect(self._resimulate_later)
        # The motion is worked out on a thread of its own, one piece at a
        # time, and looked for every few hundredths of a second: the window
        # goes on while it counts, and a count overtaken by an edit is thrown
        # away and made again.
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="kinetic-motion")
        self._job = None                # (key, future) under way
        self._job_again = False
        self._job_timer = QTimer(self)
        self._job_timer.setInterval(30)
        self._job_timer.timeout.connect(self._job_check)
        self.warnings: list = []
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
        self.body.setSizes([640, 960])
        self.right.setSizes([430, 470])
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
        self.index_of = np.zeros((ROWS, PER_ROW), np.int64)
        self.index_of[self.cell_is[:, 0], self.cell_is[:, 1]] = np.arange(len(self.cell_is))
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
        self.solid.cull(self.cull)
        self.solid.dark_backs(True)
        self.solid.clear = BACKGROUND
        self.overlay = kin_overlay.Overlay(self.device, self.format)
        try:
            piece = next(one for one in self.mesh.pieces
                         if one.name == scene3d.KINETIC_SCREEN)
            places = kin_sample.cell_places(
                self.mesh.raw[f"{scene3d.KINETIC_SCREEN}__uv"], piece.cell,
                len(self.cell_is))
            self.sampler = kin_sample.CellSampler(self.device, places)
        except Exception as error:  # noqa: BLE001 -- the strip keeps the mask
            self.sampler = None
            logfile.write(f"kinetic editor: no video on the strip: {error}")
        self._aim_camera()
        try:
            piece = next(one for one in self.mesh.pieces
                         if one.name == scene3d.KINETIC_SCREEN)
            geometry = kin_sample.strip_geometry(
                self.mesh.points_of(scene3d.KINETIC_SCREEN),
                self.mesh.raw[f"{scene3d.KINETIC_SCREEN}__uv"], piece.cell,
                self.cell_at, self.cell_is, self.unwrap.places, RING_PITCH)
            self.strip_picture = kin_sample.StripPicture(self.device, geometry)
        except Exception as error:  # noqa: BLE001 -- the strip keeps its colours
            self.strip_picture = None
            logfile.write(f"kinetic editor: no picture on the strip: {error}")
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

        # The building down the whole left, tools beside it; on the right the
        # strip of cells and the tool's panel over the timeline.
        body = QSplitter(Qt.Orientation.Horizontal)
        body.setObjectName("qa_kin_body")
        left = QWidget()
        left.setObjectName("qa_kin_left")
        beside = QHBoxLayout(left)
        beside.setContentsMargins(0, 0, 0, 0)
        beside.setSpacing(0)
        beside.addWidget(self._tool_column())
        self.canvas = RenderCanvas(parent=left, update_mode="ondemand",
                                   max_fps=60, vsync=True)
        self.canvas.setObjectName("qa_kin_canvas")
        self.canvas.setMinimumSize(320, 260)
        self.canvas.add_event_handler(
            self._canvas_event, "wheel", "pointer_down", "pointer_move",
            "pointer_up", "double_click", "pointer_leave")
        beside.addWidget(self.canvas, 1)
        body.addWidget(left)
        self.left = left
        # The card of keys, over the picture, on ?.
        self.keys_card = QLabel(left)
        self.keys_card.setObjectName("qa_kin_keys_card")
        self.keys_card.setProperty("fixed_words", True)
        self.keys_card.setFont(theme.mono(8.5))
        self.keys_card.setStyleSheet(
            f"QLabel {{ background:{theme.CARD}; color:{theme.SECOND};"
            f" border:1px solid {theme.EDGE}; border-radius:6px; padding:10px 14px; }}")
        self.keys_card.hide()

        right = QSplitter(Qt.Orientation.Vertical)
        right.setObjectName("qa_kin_right")
        upper = QWidget()
        across = QHBoxLayout(upper)
        across.setContentsMargins(0, 0, 0, 0)
        across.setSpacing(0)
        self.unwrap = Unwrap()
        self.unwrap.stroke_started.connect(self.begin_edit)
        self.unwrap.dabbed.connect(self._dab)
        self.unwrap.stroke_finished.connect(self.end_edit)
        self.unwrap.selected.connect(self._select)
        self.unwrap.hovered.connect(self._hovered)
        self.unwrap.radius_changed.connect(self._radius_from_strip)
        self.unwrap.jacks_started.connect(self.begin_edit)
        self.unwrap.jack_set.connect(self._set_jack)
        self.unwrap.jacks_finished.connect(self.end_edit)
        self.unwrap.placed.connect(self._place_primitive)
        self.unwrap.view_changed.connect(self._picture_on_strip)
        across.addWidget(self.unwrap, 1)
        # The vase stands beside the strip, ring for ring, in its own tool.
        self.profile_strip = kin_tools.ProfileStrip(self.unwrap)
        self.profile_strip.changed.connect(self._profile_drawn)
        self.unwrap.view_changed.connect(self.profile_strip.update)
        self._profiling = False
        across.addWidget(self.profile_strip)

        # The panel: what is chosen, the poses, and the tool's own settings.
        side = QWidget()
        side.setObjectName("qa_kin_side")
        side.setFixedWidth(340)
        side.setStyleSheet(f"QWidget#qa_kin_side {{ background:{theme.CARD};"
                           f" border-left:1px solid {theme.SEAM}; }}")
        stacked = QVBoxLayout(side)
        stacked.setContentsMargins(0, 0, 0, 0)
        stacked.setSpacing(0)
        self.inspector = kin_tools.Inspector(self)
        stacked.addWidget(self.inspector)
        self.poses = kin_tools.Poses(self)
        stacked.addWidget(self.poses)
        self.masks = kin_tools.Masks(self)
        stacked.addWidget(self.masks)
        seam = QFrame()
        seam.setFixedHeight(1)
        seam.setStyleSheet(f"background:{theme.SEAM};")
        stacked.addWidget(seam)
        self.panels = {
            "brush": kin_tools.BrushPanel(self),
            "select": kin_tools.SelectPanel(self),
            "profile": kin_tools.ProfilePanel(self),
            "motors": kin_tools.MotorsPanel(self),
            "prims": kin_tools.PrimsPanel(self),
            "layers": kin_tools.LayersPanel(self),
        }
        self.panel_stack = QStackedWidget()
        self.panel_stack.setObjectName("qa_kin_panels")
        # Each panel scrolls when the column is shorter than it.
        self.panel_pages = {}
        for tool in TOOLS:
            scroll = QScrollArea()
            scroll.setObjectName(f"qa_kin_page_{tool}")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setStyleSheet("QScrollArea { background: transparent; }")
            scroll.viewport().setAutoFillBackground(False)
            self.panels[tool].setAutoFillBackground(False)
            scroll.setWidget(self.panels[tool])
            self.panel_pages[tool] = scroll
            self.panel_stack.addWidget(scroll)
        stacked.addWidget(self.panel_stack, 1)
        across.addWidget(side)
        right.addWidget(upper)

        lower = QWidget()
        column = QVBoxLayout(lower)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        self.timeline = KeyTimeline()
        self.timeline.seek.connect(self.go_to)
        self.timeline.family_chosen.connect(self.set_family)
        self.timeline.moved_keys.connect(self._move_keys)
        self.timeline.chosen_changed.connect(self._say_keys)
        self.timeline.lane_picked.connect(self._lane_picked)
        self.timeline.prim_picked.connect(
            lambda index: self.choose_primitive(index, take_tool=True))
        self.timeline.layer_picked.connect(self.choose_layer)
        self.timeline.layer_muted.connect(self.mute_layer)
        self.timeline.strip_picked.connect(self.choose_strip)
        self.timeline.strip_moved.connect(self._strip_moved)
        self.timeline.strip_stretched.connect(self._strip_stretched)
        # The two ways to look, in the corner over the lanes' names.
        self.timeline_mode = kin_tools.segments(
            [tr(one) for one in TIMELINE_NAMES], "qa_kin_timeline_mode",
            lambda i: self.set_timeline_view(("simple", "detailed", "layers")[i]), 0)
        self.timeline_mode.setParent(self.timeline)
        self.timeline_mode.setGeometry(4, 4, 182, 24)
        self.timeline_mode.setToolTip(tr(
            "Простой — три дорожки, чтобы набрасывать формы; подробный — "
            "кольца, группы и соты, чтобы работать с частями ключей; слои — "
            "клипы под ключами, как NLA в Blender"))
        for button in self.timeline_mode.buttons:
            button.setStyleSheet("padding:2px 4px; font-size:11.5px;")
        column.addWidget(self._transport())
        column.addWidget(self.timeline, 1)
        column.addWidget(self._status_bar())
        right.addWidget(lower)
        right.setStretchFactor(0, 4)
        right.setStretchFactor(1, 5)
        body.addWidget(right)
        body.setStretchFactor(0, 4)
        body.setStretchFactor(1, 6)
        page.addWidget(body, 1)
        self.body, self.right = body, right
        self._choose_tool("brush")
        self.set_family("tilt")
        self.set_detailed(bool(self.settings.get("timeline_detailed", False)))

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
                 tr("Моторный JSON для вьюера и площадки, Ctrl+E")),
                (tr("Во вьюере…"), "qa_kin_viewer", self.show_in_viewer,
                 tr("Сохранить JSON и открыть его во вьюере — вместо того, что "
                    "загружено во вьюере сейчас"))):
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
        # The layer being worked on, Q W E -- the brush's, the key's, the
        # picture's -- and RGB to see all three at once.
        self.layer_switch = kin_tools.segments(
            [tr(one) for one in LAYER_NAMES], "qa_kin_layer",
            lambda i: self.set_family(km.FAMILIES[i]), 2)
        self.layer_switch.setToolTip(tr("Слой, с которым работаем: Q, W, E"))
        row.addWidget(self.layer_switch)
        self.rgb = QPushButton("RGB")
        self.rgb.setObjectName("qa_kin_rgb")
        self.rgb.setProperty("pill", True)
        self.rgb.setProperty("fixed_words", True)
        self.rgb.setCheckable(True)
        self.rgb.setChecked(self.show_all)
        self.rgb.setToolTip(tr("Все три слоя в цветах Houdini: R подъём, G вынос, "
                               "B наклон; иначе — только слой, с которым работаем"))
        self.rgb.clicked.connect(lambda on: self.set_show_all(on))
        row.addWidget(self.rgb)
        row.addWidget(_divider())
        self.view_choice = kin_tools.segments(
            [tr(one) for one in VIEW_NAMES], "qa_kin_show",
            lambda i: self.set_view(VIEWS[i]), VIEWS.index(self.view))
        self.view_choice.setToolTip(tr(
            "Что на сотах: ключи, как их сыграют моторы, или оба — второе "
            "призраком"))
        row.addWidget(self.view_choice)
        self.backs = QPushButton(tr("Изнанка"))
        self.backs.setObjectName("qa_kin_backs")
        self.backs.setProperty("pill", True)
        self.backs.setCheckable(True)
        self.backs.setChecked(not self.cull)
        self.backs.setToolTip(tr(
            "Показывать задние стороны сот, чёрные, — выключает отсечение "
            "задних граней"))
        self.backs.clicked.connect(lambda on: self.set_backs(on))
        row.addWidget(self.backs)
        self.gizmo_button = QPushButton(tr("Ручки"))
        self.gizmo_button.setObjectName("qa_kin_gizmos")
        self.gizmo_button.setProperty("pill", True)
        self.gizmo_button.setCheckable(True)
        self.gizmo_button.setChecked(self.gizmos_on)
        self.gizmo_button.setToolTip(tr(
            "Ручки выбранного в 3D (T): у кольца — подъём, вынос и наклон, у "
            "группы — вынос и наклон, у соты — наклон. Shift — всем выбранным"))
        self.gizmo_button.clicked.connect(lambda on: self.set_gizmos(on))
        row.addWidget(self.gizmo_button)
        row.addStretch(1)
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
        for tool, text, key in zip(TOOLS, TOOL_NAMES, TOOL_LETTERS):
            button = QPushButton(tr(text))
            button.setObjectName(f"qa_kin_tool_{tool}")
            button.setCheckable(True)
            button.setToolTip(key)
            button.setFixedHeight(40)
            button.setStyleSheet("padding:5px 0px; font-size:11.5px;")
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
        self.clock_label.setFixedWidth(self.clock_label.fontMetrics().horizontalAdvance(
            "00:00:00:00  " + tr("кадр {0}", 999999)) + 12)
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
        # Coming and going with the warnings, it must not push the window wider.
        self.warn_button.setMinimumWidth(1)
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
        self.status = kin_tools.Elided()
        self.status.setObjectName("qa_kin_status")
        self.status.setFont(theme.mono(8.5))
        self.status.setStyleSheet(f"color:{theme.QUIET};")
        row.addWidget(self.status, 1)
        self.hover_label = kin_tools.Elided()
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
        self.edit_mask = ""
        self.prim_index = 0 if project.primitives else -1
        self.timeline.set_active_primitive(self.prim_index)
        self.layer_index = len(project.layers) - 1
        self.strip_key = None
        self.timeline.set_layer_state(self.layer_index, None)
        self.masks.refresh()
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

    def _say_warnings(self, warnings=None) -> None:
        warnings = self.desired().violations() if warnings is None else warnings
        self.warnings = list(warnings)
        self.timeline.set_warnings(warnings)
        self.warn_button.setText(tr("Вне предела: {0}", len(warnings)) if warnings else "")
        self.warn_button.setVisible(bool(warnings))

    def desired(self):
        """The piece as it is meant to move, as keys: its layers and its
        primitives in them. What the picture is held against."""
        key = (id(self.project), self.project.version)
        if self._desired is None or self._desired[0] != key:
            self._desired = (key, kin_prims.compose(kin_layers.flatten(self.project)))
        return self._desired[1]

    def composed(self):
        """The piece as the motors will run it: what it means, made a plan
        of moves the machine carries out when the plan is on. What is
        simulated and exported."""
        key = (id(self.project), self.project.version, tuple(sorted(self.pace.items())))
        if self._composed is None or self._composed[0] != key:
            wanted = self.desired()
            if self.project.plan:
                wanted = kin_plan.plan(wanted, self.pace, self.project.tolerance)
            self._composed = (key, wanted)
        return self._composed[1]

    def set_plan(self, on: bool, tolerance: float | None = None) -> None:
        """The plan of moves on or off, and its tolerance (of the travel)."""
        tolerance = self.project.tolerance if tolerance is None else float(tolerance)
        if bool(on) == self.project.plan and abs(tolerance - self.project.tolerance) < 1e-9:
            return
        self._record()
        self.project.plan = bool(on)
        self.project.tolerance = max(0.0, tolerance)
        self.project.changed()
        self._changed(keys=True)

    def shown_now(self):
        """The piece at the playhead with its primitives over its keys."""
        key = (id(self.project), self.project.version, self.frame)
        if self._shown_cache is None or self._shown_cache[0] != key:
            self._shown_cache = (key, kin_prims.pose_at(self.project, self.frame,
                                                        self.pose_now()))
        return self._shown_cache[1]

    def profile_here(self):
        return self.project.profiles.get(self.frame)

    def _changed(self, keys: bool = False) -> None:
        """Something about the piece or the playhead moved: say it all again."""
        count = len(self.project.primitives)
        if self.prim_index >= count or (self.prim_index < 0 and count):
            self.prim_index = count - 1
            self.timeline.set_active_primitive(self.prim_index)
        if self.edit_mask and self.edit_mask not in self.project.masks:
            self.edit_mask = ""
        self._hold_layer_choice()
        solid, ghost = self._shown()
        if self.solid is not None:
            self.solid.set_cells(kinetic.transforms(
                self.cell_at, self.cell_is, PoseMotors(solid), self.frame))
            if ghost is not None:
                self.solid.set_ghost_cells(kinetic.transforms(
                    self.cell_at, self.cell_is, PoseMotors(ghost), self.frame))
            self.solid.show_ghost(ghost is not None)
        self._paint()
        self.timeline.set_frame(self.frame)
        if keys:
            self.dirty = self.dirty or bool(self.undo)
            # The keys past their limits come with the motion, worked out
            # away from the window; until then the last ones stand.
            self.timeline.update()
            self._say_title()
            self.sim_timer.start(SIM_WAIT_MS)
        self.inspector.refresh()
        if keys:
            self.masks.refresh()
            self.timeline._lay_bar()
        self.panels[self.tool].refresh()
        if self.tool == "profile":
            strip = self.profile_strip
            strip.now = self.pose_now()["push"].mean(axis=1)
            points = self.profile_here()
            if points and strip._held is None:
                strip.points = [tuple(one) for one in points]
            strip.update()
        self._say_clock()
        self.touch()

    # -- the motors' own motion ------------------------------------------------------

    def simulation(self):
        """The motion of the keys as they are now, or None while it is still
        to be worked out."""
        if self.sim is not None and self._sim_for == self._sim_key():
            return self.sim
        return None

    def _sim_key(self):
        # The piece itself as well as its version: a new piece starts its
        # counts where the last one's did.
        return (id(self.project), self.project.version,
                tuple(sorted(self.pace.items())))

    def _resimulate(self) -> None:
        """The motion now, waited for: what an explicit step -- putting it
        onto the keys -- needs before it can go on."""
        if self.simulation() is not None:
            return
        key = self._sim_key()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if self._job is not None and self._job[0] == key:
                got = self._job[1].result()
            else:
                got = work_out_motion(self.project, dict(self.pace))
        finally:
            QApplication.restoreOverrideCursor()
        self._install(key, *got)

    def _resimulate_later(self) -> None:
        """The motion worked out on its own thread, the window going on."""
        if self.simulation() is not None:
            return
        if self._job is not None:
            self._job_again = True
            return
        key = self._sim_key()
        future = self._pool.submit(work_out_motion, self.project.copy(), dict(self.pace))
        self._job = (key, future)
        self._job_timer.start()
        self.panels["motors"].refresh()

    def _job_check(self) -> None:
        if self._job is None:
            self._job_timer.stop()
            return
        key, future = self._job
        if not future.done():
            return
        self._job_timer.stop()
        self._job = None
        try:
            got = future.result()
        except Exception as error:  # noqa: BLE001 -- said, and the window goes on
            logfile.write(f"kinetic editor: motion not worked out: {error!r}")
            self.status.setText(tr("Симуляция не посчиталась: {0}", str(error)[:80]))
            return
        if key == self._sim_key() and self.simulation() is None:
            self._install(key, *got)
        if self._job_again or key != self._sim_key():
            self._job_again = False
            self._resimulate_later()

    def _install(self, key, desired, composed, result, warnings, took) -> None:
        """A worked-out motion, taken up: its keys, its plan, its simulation
        and its warnings, all for the piece as it stood."""
        self._desired = (key[:2], desired)
        self._composed = (key, composed)
        self.sim = result
        self._sim_for = key
        self._sim_pose = None
        counts = self.sim.by_family()
        dropped = sum(one["dropped"] for one in counts.values())
        late = sum(one["late"] for one in counts.values())
        logfile.write(f"kinetic editor: simulated in {took * 1000:.0f} ms, "
                      f"{dropped} dropped, {late} late, "
                      f"{len(self.sim.clashes)} frames past the gaps")
        self.timeline.set_simulation(self.sim)
        self._say_warnings(warnings)
        if dropped or late or self.sim.clashes:
            self.status.setText(tr(
                "Моторы: пропущено команд {0}, опоздали ходов {1}, наклон сверх "
                "зазоров на {2} кадрах — «Перенести в ключи» в панели «Моторы»",
                dropped, late, len(self.sim.clashes)))
        self._changed()

    def sim_pose(self):
        """Where the motors are at the playhead, as simulated -- the last
        motion worked out for this piece, while the next is counted."""
        result = self.sim
        if result is None or not self._sim_for or self._sim_for[0] != id(self.project):
            return None
        key = (self._sim_for, self.frame)
        if self._sim_pose is None or self._sim_pose[0] != key:
            self._sim_pose = (key, result.project.pose(self.frame))
        return self._sim_pose[1]

    def _shown(self):
        """(what the cells are drawn at, what the ghost is drawn at or None)."""
        keys = self.shown_now()
        motion = self.sim_pose() if self.view != "keys" else None
        if motion is None:
            return keys, None
        if self.view == "sim":
            return motion, None
        if self.ghost_is == "keys":
            return motion, keys
        return keys, motion

    def set_view(self, view: str) -> None:
        self.view = view
        self.view_choice.buttons[VIEWS.index(view)].setChecked(True)
        if view != "keys" and self.simulation() is None:
            self._resimulate_later()
        self._changed()

    def set_ghost(self, which: str) -> None:
        self.ghost_is = which
        self._changed()

    def set_backs(self, on: bool) -> None:
        """The backs of the cells shown, black; or dropped, which hides the
        far side of the ring behind the near."""
        self.cull = not on
        self.backs.setChecked(bool(on))
        if self.solid is not None:
            self.solid.cull(self.cull)
        self.touch()

    def set_pace(self, pace: dict) -> None:
        self.pace = dict(pace)
        self.sim_timer.start(SIM_WAIT_MS)

    def step_problem(self, direction: int) -> None:
        result = self.simulation()
        if result is None:
            return
        found = result.problems()
        if direction > 0:
            later = [f for f in found if f > self.frame]
            if later:
                self.go_to(later[0])
        else:
            earlier = [f for f in found if f < self.frame]
            if earlier:
                self.go_to(earlier[-1])

    def bake_simulation(self) -> None:
        """The motion onto the timeline: its keys for the keys."""
        result = self.simulation()
        if result is None:
            self._resimulate()
            result = self.simulation()
        self._record()
        for family in km.FAMILIES:
            self.project.tracks[family].restore(
                result.project.tracks[family].state())
        # The motion had the primitives in it: they are in the keys now.
        baked = [one for one in self.project.primitives if one.on]
        for one in baked:
            one.on = False
        if baked:
            self.project.changed()
        # And the layers: they are in the keys now too.
        for layer in self.project.layers:
            if not layer.muted:
                layer.muted = True
                baked.append(layer)
        if baked:
            self.project.changed()
        self.timeline.chosen = set()
        self.status.setText(tr("Симуляция перенесена в ключи") if not baked else
                            tr("Симуляция перенесена в ключи, примитивы и слои в ней — "
                               "выключены"))
        self._changed(keys=True)

    def _paint(self) -> None:
        """The cells' colours, and what is laid over them: red past the
        limit, the brush where it would land, and -- in 3D, where there is
        no outline to draw -- the selection lightened. The colours are the
        ones of what the cells are drawn at; on the strip the cells whose
        motion is not where the keys want it are ringed."""
        pose, _ = self._shown()
        painting_mask = self.tool == "brush" and self.brush_target == "mask"
        video = None if painting_mask or self.show_mask else self.video_cells()
        if painting_mask:
            colours = weight_colours(self.mask_weights())
        elif video is not None:
            colours = video
        else:
            colours = mask_colours(pose, self.layer)
        over = np.zeros((ROWS, PER_ROW, 4), np.float32)
        warn = km.over_limit(pose["tilt"], pose["lift"], pose["push"])
        if self.edit_mask and not painting_mask:
            # What the edits cannot reach, darkened by how far out of it.
            out = 1.0 - self.mask_weights().reshape(ROWS, PER_ROW)
            over[..., 3] = out * 0.62
        one = self.primitive() if self.tool == "prims" else None
        if one is not None and one.kind != "noise":
            touched = kin_prims.touched_cells(self.project, one, self.frame)
            lilac = np.array(to_rgb(PRIM_COLOUR[one.polarity]), np.float32)
            over[touched, :3] = lilac
            over[touched, 3] = 0.45
            values = one.at(self.frame)
            self.unwrap.set_marker(float(values[kin_prims.AZIMUTH]),
                                   float(values[kin_prims.HEIGHT]))
        else:
            self.unwrap.set_marker(None)
        over[warn] = (0.95, 0.25, 0.25, 0.75)
        if self._under is not None:
            weight = self._under
            under = weight > 0
            over[under, :3] = 1.0
            over[under, 3] = np.maximum(over[under, 3], 0.2 + 0.35 * weight[under])
        lag = None
        result = self.simulation()
        if result is not None and self.view != "keys":
            lag = kin_sim.differs(self.desired(), result.project, self.frame)
        self.unwrap.set_colours(colours, over, warn, lag)
        self._strip_layers = (over, warn, lag)
        self._picture_on_strip(video is not None)
        self.unwrap.set_lift(pose["lift"])
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
        # The handles and the primitives, over the picture: worked out where
        # the cells stand now.
        self._rebuild_handles()
        if self.overlay is not None and (self.handles or self._prims_drawn()):
            wide, tall = self.canvas.get_logical_size()
            shapes = kin_overlay.Shapes(wide, tall)
            self._draw_prims(shapes)
            kin_gizmo.draw(shapes, self.handles, self._hot)
            self.overlay.set_triangles(shapes.array())
            self.overlay.draw(encoder, view)
        self.device.queue.submit([encoder.finish()])
        if self.clock.playing:
            self.canvas.request_draw()

    def _prims_drawn(self) -> bool:
        return (self.tool == "prims" and bool(self.project.primitives)
                and self.mesh is not None)

    def prim_outline(self, one, values=None) -> list:
        """A primitive's wire in world metres: a list of polylines -- three
        great circles of a sphere, the twelve edges of a box."""
        values = one.at(self.frame) if values is None else values
        lift = self.shown_now()["lift"]
        centre, e_out, e_round, e_up = kin_prims.frame_of(values, self.base_heights,
                                                          lift)
        if one.kind == "noise":
            return []
        if one.kind == "sphere":
            radius = float(values[kin_prims.WIDTH])
            turn = np.linspace(0, 2 * np.pi, 49)[:, None]
            return [centre + radius * (np.cos(turn) * a + np.sin(turn) * b)
                    for a, b in ((e_out, e_round), (e_out, e_up), (e_round, e_up))]
        half = (values[kin_prims.DEPTH], values[kin_prims.WIDTH], values[kin_prims.TALL])
        corner = {}
        for i in (-1, 1):
            for j in (-1, 1):
                for k in (-1, 1):
                    corner[i, j, k] = (centre + i * half[0] * e_out + j * half[1] * e_round
                                       + k * half[2] * e_up)
        lines = []
        for i, j, k in corner:
            for axis in range(3):
                other = [i, j, k]
                if other[axis] < 0:
                    other[axis] = 1
                    lines.append(np.array([corner[i, j, k], corner[tuple(other)]]))
        return lines

    def _draw_prims(self, shapes) -> None:
        if not self._prims_drawn():
            return
        transform = self.mesh.view_projection().astype(np.float64)
        wide, tall = self.canvas.get_logical_size()
        for index, one in enumerate(self.project.primitives):
            chosen = index == self.prim_index
            colour = list(to_rgb(PRIM_COLOUR[one.polarity])) + [0.95 if chosen else 0.45]
            if not one.on:
                colour = [0.6, 0.6, 0.6, 0.35]
            width = 2.2 if chosen else 1.4
            for line in self.prim_outline(one):
                clip = np.concatenate([line, np.ones((len(line), 1))], axis=1) @ transform.T
                seen = clip[:, 3] > 1e-3
                points = self._project(line, transform, wide, tall)
                for a in range(len(points) - 1):
                    if seen[a] and seen[a + 1]:
                        shapes.line(points[a], points[a + 1], width + 2.0,
                                    (0.0, 0.0, 0.0, 0.4))
                        shapes.line(points[a], points[a + 1], width, colour)

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
            self._video_on_strip()
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
            self._edit_base = (self.frame, self.project.pose(self.frame))

    def end_edit(self) -> None:
        self._editing = False
        self._edit_base = None
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
        self.panel_stack.setCurrentWidget(self.panel_pages[tool])
        # The primitives are no cells' business: what is chosen and the poses
        # step aside for them, the masks stay.
        for part in (self.inspector, self.poses):
            part.setVisible(tool not in OWN_COLUMN)
        if tool == "layers" and not self.timeline.layered:
            self.set_timeline_view("layers")
        self.unwrap.tool = {"brush": "brush", "prims": "place"}.get(tool, "select")
        self.profile_strip.setVisible(tool == "profile")
        self._under = None
        self.panels[tool].refresh()
        self._changed()

    @property
    def layer(self) -> str:
        """What the cells are coloured by: all three, or the layer worked on."""
        return "rgb" if self.show_all else self.family

    def set_family(self, family: str) -> None:
        """The layer worked on: the brush's, the keys', the picture's."""
        self.family = family
        self.timeline.set_family(family)
        self.panels["brush"].show_family(family)
        self.layer_switch.buttons[km.FAMILIES.index(family)].setChecked(True)
        self._changed()

    def set_show_all(self, on: bool) -> None:
        self.show_all = bool(on)
        self.rgb.setChecked(self.show_all)
        self._changed()

    def set_mask(self, on: bool) -> None:
        self.show_mask = bool(on)
        self.view_switch.buttons[1 if on else 0].setChecked(True)
        if self.solid is not None:
            self.solid.show_paint(self.show_mask)
        self._paint()
        self.touch()

    def _picture_on_strip(self, wanted: bool | None = None) -> None:
        """The strip in Video: the picture as the cells show it, drawn again
        when the frame or the strip's view changes."""
        if wanted is None:
            wanted = not self.show_mask and not (self.tool == "brush"
                                                 and self.brush_target == "mask")
        painter = self.strip_picture
        if not wanted or painter is None or self.solid is None:
            if self.unwrap.picture is not None:
                self.unwrap.set_picture(None)
            self._picture_for = None
            return
        calibration = self.solid.calibration.get(TOP)
        screen = self.screen
        if calibration is None and screen is None:
            self.unwrap.set_picture(None)
            return
        centre, middle, size, wide, tall = self.unwrap.view()
        ratio = self.unwrap.devicePixelRatioF()
        key = (id(screen), getattr(self.held, "index", None), centre, size, wide, tall,
               ratio)
        if key == self._picture_for and self.unwrap.picture is not None:
            return
        behind = calibration if calibration is not None else screen.planes[0].texture
        width, height = int(round(wide * ratio)), int(round(tall * ratio))
        if screen is not None:
            raw, stride = painter.render(
                width, height, centre, (middle[0] * ratio, middle[1] * ratio), size * ratio,
                PER_ROW, screen.planes[0].texture, screen.planes[1].texture, behind,
                screen.ycocg, screen.alpha_from, screen.uv_scale, True)
        else:
            raw, stride = painter.render(
                width, height, centre, (middle[0] * ratio, middle[1] * ratio), size * ratio,
                PER_ROW, calibration, calibration, calibration, False, 0, (1.0, 1.0), False)
        from PySide6.QtGui import QImage
        image = QImage(raw, width, height, stride, QImage.Format.Format_RGBA8888).copy()
        image.setDevicePixelRatio(ratio)
        self._picture_for = key
        self.unwrap.set_picture(image)

    def video_cells(self):
        """What each cell shows of the video now, (ROWS, PER_ROW, 3) -- the
        calibration picture when there is no video -- or None."""
        if self.sampler is None or self.solid is None:
            return None
        screen = self.screen
        key = (id(screen), getattr(self.held, "index", None)) if screen else ("calibration",)
        if self._video_cells is not None and self._video_cells[0] == key:
            return self._video_cells[1]
        if screen is not None:
            got = self.sampler.read(screen.planes[0].texture, screen.planes[1].texture,
                                    screen.ycocg, screen.alpha_from, screen.uv_scale)
        else:
            texture = self.solid.calibration.get(TOP)
            if texture is None:
                return None
            got = self.sampler.read(texture, texture, False, 0)
        colours = np.zeros((ROWS, PER_ROW, 3), np.float32)
        colours[self.cell_is[:, 0], self.cell_is[:, 1]] = got
        self._video_cells = (key, colours)
        return colours

    def _video_on_strip(self) -> None:
        """A new frame of the video, onto the strip as well as the cells."""
        if self.show_mask or (self.tool == "brush" and self.brush_target == "mask"):
            return
        colours = self.video_cells()
        if colours is not None:
            self.unwrap.set_colours(colours, *self._strip_layers)
        self._picture_on_strip(True)

    def set_brush_radius(self, radius: float) -> None:
        self.brush_radius = float(radius)
        self.unwrap.radius = self.brush_radius
        self.unwrap.update()

    def _radius_from_strip(self, radius: float) -> None:
        self.brush_radius = float(radius)
        self.panels["brush"].show_radius(self.brush_radius)

    def set_brush_hardness(self, percent: float) -> None:
        self.brush_hardness = float(percent) / 100.0
        self.unwrap.hardness = self.brush_hardness

    def set_grain(self, grain: str, take_tool: bool = False) -> None:
        """What a click takes: a ring, a group of five or a cell. Keys 1 2 3
        also take up the selection tool, and grow what is chosen to the new
        size -- a cell chosen, going to rings, is its whole ring -- as
        Blender's selection modes do."""
        self.unwrap.grain = grain
        panel = self.panels["select"]
        panel.grain.buttons[panel.GRAIN_KEYS.index(grain)].setChecked(True)
        if take_tool and self.tool != "select":
            self._choose_tool("select")
        if self.selection.any():
            self.selection = self.unwrap._grain(self.selection)
            self._changed()
        self.status.setText(tr("Выбор: {0}", tr(GRAIN_NAMES[grain])))

    def _target(self) -> float:
        return {"lift": float(self.brush_lift), "push": self.brush_push,
                "tilt": self.brush_tilt}[self.family]

    def _dab(self, weights) -> None:
        if self.brush_inside and self.selection.any():
            # Only what is chosen takes paint, as Houdini paints on a group.
            weights = np.asarray(weights, np.float32) * self.selection
        if self.brush_target == "mask":
            self._paint_mask(weights)
            return
        track = self.project.tracks[self.family]
        values, mask = km.brush(track, self.frame, weights, self._target(),
                                self.brush_strength, self.brush_mode,
                                base=self.pose_now()[self.family])
        self._write(self.family, values, mask)
        self._changed()

    def _set_jack(self, ring: int, state: int) -> None:
        """A ring's jack put in one of its places, off the strip's column."""
        rings = np.zeros(ROWS, bool)
        rings[ring] = True
        self._write("lift", np.full(ROWS, float(state)), rings)
        self._changed()

    def _profile_drawn(self, points, done: bool) -> None:
        """The vase drawn beside the strip: one undo step a drag."""
        if not self._profiling:
            self.begin_edit()
            self._profiling = True
        self.apply_profile(points, self.panels["profile"].tangent.isChecked())
        if done:
            self.end_edit()
            self._profiling = False

    # -- masks ---------------------------------------------------------------------------

    def mask_names(self) -> list:
        return list(self.project.masks)

    def mask_weights(self, name: str | None = None) -> np.ndarray:
        """A mask's weights, flat; the mask for editing's if not said, and
        every cell whole when there is none."""
        name = self.edit_mask if name is None else name
        weights = self.project.masks.get(name)
        return (np.ones(ROWS * PER_ROW, np.float32) if weights is None
                else np.asarray(weights, np.float32))

    def _fresh_mask_name(self) -> str:
        number = 1
        while tr("Маска {0}", number) in self.project.masks:
            number += 1
        return tr("Маска {0}", number)

    def new_mask(self, name: str | None = None) -> str:
        """A mask of what is chosen -- or an empty one, to paint -- and the
        edits kept to it from now on."""
        self._record()
        name = str(name).strip() if name else self._fresh_mask_name()
        self.project.masks[name] = self.selection.reshape(-1).astype(np.float32)
        self.project.changed()
        self.set_edit_mask(name)
        count = int(self.selection.sum())
        self.status.setText(tr("Маска «{0}»: сот {1} — правки только в ней", name, count)
                            if count else
                            tr("Маска «{0}» пустая — нарисуйте её кистью: «Кисть красит: "
                               "Маску»", name))
        self._changed(keys=True)
        return name

    def set_edit_mask(self, name: str) -> None:
        """The mask every edit is kept to; "" for none."""
        self.edit_mask = name if name in self.project.masks else ""
        self.masks.refresh()
        self.panels["brush"].show_family(self.family)
        self.status.setText(tr("Правки только в маске «{0}»", self.edit_mask)
                            if self.edit_mask else tr("Правки — на всех сотах"))
        self._changed()

    def select_mask(self) -> None:
        if not self.edit_mask:
            self.status.setText(tr("Сначала выберите маску"))
            return
        self._select(self.mask_weights().reshape(ROWS, PER_ROW) >= 0.5, "set")

    def drop_mask(self, name: str | None = None) -> None:
        name = name or self.edit_mask
        if name not in self.project.masks:
            self.status.setText(tr("Сначала выберите маску"))
            return
        self._record()
        del self.project.masks[name]
        for one in self.project.primitives:
            if one.mask == name:
                one.mask = ""
            if one.tilt_mask == name:
                one.tilt_mask = ""
        self.project.changed()
        if self.edit_mask == name:
            self.edit_mask = ""
        self.panels["brush"].show_family(self.family)
        self._changed(keys=True)

    def selection_to_mask(self, add: bool) -> None:
        """What is chosen into the mask for editing, or out of it."""
        if not self.selection.any():
            self.status.setText(tr("Сначала выберите соты"))
            return
        if not self.edit_mask:
            if add:
                self.new_mask()
            return
        self._record()
        weights = self.mask_weights().reshape(ROWS, PER_ROW).copy()
        if add:
            weights = np.maximum(weights, self.selection.astype(np.float32))
        else:
            weights[self.selection] = 0.0
        self.project.masks[self.edit_mask] = weights.reshape(-1)
        self.project.changed()
        self._changed(keys=True)

    def set_brush_target(self, target: str) -> None:
        """What the brush paints: the layer's keys, or the mask for editing."""
        self.brush_target = target
        self.panels["brush"].show_family(self.family)
        self._changed()

    def _paint_mask(self, weights) -> None:
        if not self.edit_mask:
            # A mask to paint into, first; the stroke's undo step has it.
            name = self._fresh_mask_name()
            self.project.masks[name] = np.zeros(ROWS * PER_ROW, np.float32)
            self.edit_mask = name
            self.masks.refresh()
            self.panels["brush"].show_family(self.family)
        self.project.masks[self.edit_mask] = kin_prims.paint_mask(
            self.mask_weights(), weights, self.brush_strength, self.brush_mode)
        self.project.changed()
        self.dirty = True
        self._changed()

    # -- primitives -----------------------------------------------------------------------

    def primitive(self):
        """The primitive worked on, or None."""
        found = self.project.primitives
        return found[self.prim_index] if 0 <= self.prim_index < len(found) else None

    def _prim_changed(self, keys: bool = True) -> None:
        self.project.changed()
        self.dirty = True
        self._changed(keys=keys)

    def add_primitive(self, kind: str) -> None:
        """A sphere or a box, standing where the cells are chosen -- or in
        front of the camera, half way up -- keyed at the playhead."""
        self._record()
        count = sum(1 for one in self.project.primitives if one.kind == kind) + 1
        name = {"sphere": tr("Сфера {0}", count), "box": tr("Куб {0}", count),
                "noise": tr("Шум {0}", count)}[kind]
        if self.selection.any():
            rows, cells = np.nonzero(self.selection)
            turn = np.radians(km.cell_azimuths()[rows, cells])
            azimuth = math.degrees(math.atan2(np.sin(turn).mean(), np.cos(turn).mean()))
            ring = float(rows.mean())
        else:
            azimuth, ring = self._facing(), ROWS / 2.0
        one = kin_prims.Primitive(kind, name, azimuth % 360.0)
        one.seed = len(self.project.primitives) * 7 + count
        values = one.values[0]
        if kind != "noise":
            values[kin_prims.HEIGHT] = ring
        one.frames, one.values = [], []
        one.write(self.frame, values)
        self.project.primitives.append(one)
        self.prim_index = len(self.project.primitives) - 1
        self.timeline.set_active_primitive(self.prim_index)
        if self.tool != "prims":
            self._choose_tool("prims")
        self.status.setText(
            tr("{0}: на всех сотах; как он меняется — его ключами", name) if kind == "noise"
            else tr("{0}: щелчок по карте или по 3D ставит его туда", name))
        self._prim_changed()

    def _facing(self) -> float:
        """The azimuth of the cells facing the camera, degrees."""
        if self.mesh is not None and self.mesh.free is not None:
            eye = self.mesh.free.eye()
            return math.degrees(math.atan2(eye[1], eye[0]))
        return self.unwrap.front

    def drop_primitive(self) -> None:
        if self.primitive() is None:
            return
        self._record()
        del self.project.primitives[self.prim_index]
        self.timeline.chosen = {pair for pair in self.timeline.chosen
                                if pair[0][0] != "prim"}
        self.prim_index = min(self.prim_index, len(self.project.primitives) - 1)
        self.timeline.set_active_primitive(self.prim_index)
        self._prim_changed()

    def choose_primitive(self, index: int, take_tool: bool = False) -> None:
        count = len(self.project.primitives)
        self.prim_index = int(index) if 0 <= index < count else (-1 if not count else
                                                               self.prim_index)
        self.timeline.set_active_primitive(self.prim_index)
        if take_tool and self.tool != "prims":
            self._choose_tool("prims")
        self._changed()

    def set_prim_value(self, param: int, value: float, live: bool = False) -> None:
        """One of the primitive's numbers, keyed at the playhead."""
        one = self.primitive()
        if one is None:
            return
        if not live:
            self._record()
        values = one.at(self.frame)
        values[param] = value
        one.write(self.frame, values)
        self._prim_changed(keys=not live)

    def set_prim_property(self, name: str, value) -> None:
        """What the primitive is, the same all through: its polarity, its
        tilt, its masks, whether it is on."""
        one = self.primitive()
        if one is None or getattr(one, name) == value:
            return
        self._record()
        setattr(one, name, value)
        self._prim_changed()

    def key_primitive(self) -> None:
        one = self.primitive()
        if one is None:
            return
        self._record()
        one.write(self.frame, one.at(self.frame))
        self._prim_changed()

    def unkey_primitive(self) -> None:
        one = self.primitive()
        index = one.index(self.frame) if one is not None else None
        if index is None or len(one.frames) < 2:
            self.status.setText(tr("На этом кадре нет ключа примитива, который можно снять"))
            return
        self._record()
        one.remove(index)
        self._prim_changed()

    def set_prim_step(self, frames: int) -> None:
        frames = max(1, int(frames))
        if frames == self.project.prim_step:
            return
        self._record()
        self.project.prim_step = frames
        self._prim_changed()

    def bake_primitives(self) -> None:
        """What the primitives make, into the keys; they are turned off."""
        if not any(one.on for one in self.project.primitives):
            self.status.setText(tr("Нет включённых примитивов"))
            return
        self._record()
        count = kin_prims.bake(self.project)
        self.status.setText(tr("Примитивы запечены в ключи: {0}; сами выключены", count))
        self._prim_changed()

    def _place_primitive(self, azimuth: float, ring: float) -> None:
        """The primitive worked on, put at a point of the strip or the 3D."""
        one = self.primitive()
        if one is None:
            self.status.setText(tr("Сначала добавьте примитив"))
            return
        if one.kind == "noise":
            self.status.setText(tr("Шум лежит на всех сотах — его место не ставится"))
            return
        values = one.at(self.frame)
        values[kin_prims.AZIMUTH] = float(azimuth) % 360.0
        values[kin_prims.HEIGHT] = float(ring)
        one.write(self.frame, values)
        self._prim_changed(keys=not self._editing)

    def _place_at_cell(self, cell) -> None:
        row, which = cell
        self._place_primitive(float(km.cell_azimuths()[row, which]), float(row))

    # -- layers ---------------------------------------------------------------------------

    def strip(self):
        """The strip chosen on the timeline, or None."""
        if self.strip_key is None:
            return None
        layer, number = self.strip_key
        layers = self.project.layers
        if 0 <= layer < len(layers) and 0 <= number < len(layers[layer].strips):
            return layers[layer].strips[number]
        return None

    def _hold_layer_choice(self) -> None:
        """The layer and the strip chosen, still there after an undo."""
        count = len(self.project.layers)
        if self.layer_index >= count or (self.layer_index < 0 and count):
            self.layer_index = count - 1
        if self.strip_key is not None and self.strip() is None:
            self.strip_key = None
        if (self.timeline.layer_active, self.timeline.strip_chosen) != (
                self.layer_index, self.strip_key):
            self.timeline.set_layer_state(self.layer_index, self.strip_key)

    def _layers_changed(self, keys: bool = True) -> None:
        self.project.changed()
        self.dirty = True
        self.timeline.set_layer_state(self.layer_index, self.strip_key)
        self._changed(keys=keys)

    @staticmethod
    def _fresh_name(taken, called) -> str:
        """The first of `called(1)`, `called(2)`... not taken."""
        number = 1
        while called(number) in taken:
            number += 1
        return called(number)

    def add_layer(self) -> None:
        self._record()
        names = {layer.name for layer in self.project.layers}
        self.project.layers.append(kin_layers.Layer(self._fresh_name(names, lambda n: tr("Слой {0}", n))))
        self.layer_index = len(self.project.layers) - 1
        self._layers_changed()

    def drop_layer(self) -> None:
        if not 0 <= self.layer_index < len(self.project.layers):
            return
        self._record()
        del self.project.layers[self.layer_index]
        self.layer_index = min(self.layer_index, len(self.project.layers) - 1)
        self.strip_key = None
        self._layers_changed()

    def move_layer(self, direction: int) -> None:
        """The chosen layer up or down the stack."""
        here = self.layer_index
        there = here + (1 if direction > 0 else -1)
        layers = self.project.layers
        if not (0 <= here < len(layers) and 0 <= there < len(layers)):
            return
        self._record()
        layers[here], layers[there] = layers[there], layers[here]
        self.layer_index = there
        if self.strip_key is not None and self.strip_key[0] in (here, there):
            self.strip_key = (there if self.strip_key[0] == here else here,
                              self.strip_key[1])
        self._layers_changed()

    def choose_layer(self, index: int) -> None:
        self.layer_index = int(index)
        self.timeline.set_layer_state(self.layer_index, self.strip_key)
        self._changed()

    def mute_layer(self, index: int) -> None:
        if not 0 <= index < len(self.project.layers):
            return
        self._record()
        layer = self.project.layers[index]
        layer.muted = not layer.muted
        self._layers_changed()

    def choose_strip(self, key) -> None:
        self.strip_key = None if key is None else tuple(key)
        if self.strip_key is not None:
            self.layer_index = self.strip_key[0]
        self.timeline.set_layer_state(self.layer_index, self.strip_key)
        if self.tool != "layers":
            self._choose_tool("layers")
        self._changed()

    def push_down(self) -> None:
        """The keys into a clip on a new layer on top -- the chosen keys if
        any are chosen on the timeline, all of them if not."""
        chosen = sorted(self.timeline.chosen)
        parts = self._parts(chosen) if chosen else None
        self._record()
        clip = self._fresh_name(self.project.clips, lambda n: tr("Клип {0}", n))
        layer = self._fresh_name({one.name for one in self.project.layers},
                                 lambda n: tr("Слой {0}", n))
        index = kin_layers.push_down(self.project, clip, layer, parts)
        if index is None:
            self.undo.pop()
            self.status.setText(tr("Нет ключей, которые бы что-то двигали"))
            return
        self.layer_index, self.strip_key = index, (index, 0)
        self.timeline.chosen = set()
        self.set_timeline_view("layers")
        self.status.setText(tr("Ключи ушли в клип «{0}» на слое «{1}»", clip, layer))
        self._layers_changed()

    def bake_layers(self) -> None:
        if not self.project.layers:
            self.status.setText(tr("Слоёв нет"))
            return
        self._record()
        kin_layers.bake_all(self.project)
        self.layer_index, self.strip_key = -1, None
        self.status.setText(tr("Слои сведены в ключи"))
        self._layers_changed()

    INT_FIELDS = ("start", "fade_in", "fade_out", "repeat", "round", "rings")

    def set_strip_value(self, name: str, value: float, live: bool = False) -> None:
        """One of the chosen strip's numbers."""
        strip = self.strip()
        if strip is None:
            return
        if not live:
            self._record()
        value = int(round(value)) if name in self.INT_FIELDS else float(value)
        if name == "repeat":
            value = max(1, value)
        if name == "speed":
            value = max(0.05, value)
        if name == "influence":
            value = min(1.0, max(0.0, value))
        if name in ("start", "fade_in", "fade_out"):
            value = max(0, value)
        setattr(strip, name, value)
        self._layers_changed(keys=not live)

    def set_strip_property(self, name: str, value) -> None:
        strip = self.strip()
        if strip is None or getattr(strip, name) == value:
            return
        self._record()
        setattr(strip, name, value)
        self._layers_changed()

    def strip_to_keys(self) -> None:
        if self.strip() is None:
            return
        self._record()
        count = kin_layers.to_keys(self.project, *self.strip_key)
        self.strip_key = None
        self.status.setText(tr("Клип вынут в ключи: {0} кадров", count))
        self._layers_changed()

    def drop_strip(self) -> None:
        if self.strip() is None:
            return
        self._record()
        layer, number = self.strip_key
        del self.project.layers[layer].strips[number]
        self.strip_key = None
        self._layers_changed()

    def _strip_moved(self, key, to_layer: int, by: int) -> None:
        """A strip dragged along the timeline, and maybe onto another layer."""
        layer, number = key
        layers = self.project.layers
        if not (0 <= layer < len(layers) and 0 <= to_layer < len(layers)):
            return
        self._record()
        strip = layers[layer].strips[number]
        strip.start = max(0, int(strip.start + by))
        if to_layer != layer:
            del layers[layer].strips[number]
            layers[to_layer].strips.append(strip)
            number = len(layers[to_layer].strips) - 1
        self.strip_key = (to_layer, number)
        self.layer_index = to_layer
        self._layers_changed()

    def _strip_stretched(self, key, length: int) -> None:
        """A strip's right end dragged: it plays its clip in that long."""
        layer, number = key
        strip = self.project.layers[layer].strips[number]
        clip = self.project.clips.get(strip.clip)
        if clip is None:
            return
        self._record()
        strip.speed = max(0.05, clip.length * max(1, int(strip.repeat)) / max(1, int(length)))
        self.strip_key = (layer, number)
        self._layers_changed()

    # -- the library of clips, beside the program -------------------------------------------

    def _clip_file(self) -> Path:
        return logfile.app_dir() / CLIPS

    def _read_clips(self) -> dict:
        try:
            data = json.loads(self._clip_file().read_text("utf-8"))
            return data.get("clips", {}) if isinstance(data, dict) else {}
        except Exception:  # noqa: BLE001 -- none yet, or broken by hand
            return {}

    def _write_clips(self, clips: dict) -> None:
        try:
            self._clip_file().write_text(json.dumps({"clips": clips}, ensure_ascii=False),
                                         "utf-8")
        except OSError as error:
            logfile.write(f"kinetic editor: clips not written: {error}")

    def clip_names(self) -> list:
        return sorted(self._read_clips())

    def save_clip(self, name: str | None = None) -> None:
        """The chosen strip's clip into the library, under a name."""
        strip = self.strip()
        if strip is None or strip.clip not in self.project.clips:
            self.status.setText(tr("Выберите полосу на таймлайне («Слои»)"))
            return
        if name is None:
            from PySide6.QtWidgets import QInputDialog
            name, ok = QInputDialog.getText(self, APP_NAME, tr("Имя клипа:"),
                                            text=strip.clip)
            if not ok:
                return
        name = str(name).strip()
        if not name:
            return
        clips = self._read_clips()
        clips[name] = self.project.clips[strip.clip].to_dict()
        self._write_clips(clips)
        self.panels["layers"].refresh()
        self.panels["layers"].library.setCurrentText(name)
        self.status.setText(tr("Клип «{0}» в библиотеке", name))

    def put_clip(self, name: str | None = None) -> None:
        """A clip of the library as a strip on the chosen layer, from the
        playhead -- a layer made for it when there is none."""
        name = name or self.panels["layers"].library.currentText()
        data = self._read_clips().get(name)
        if not data:
            self.status.setText(tr("Сначала положите клип в библиотеку"))
            return
        clip = kin_layers.Clip.from_dict(data, name)
        self._record()
        if not self.project.layers:
            self.project.layers.append(kin_layers.Layer(tr("Слой {0}", 1)))
            self.layer_index = 0
        called = name
        number = 2
        while called in self.project.clips and not self.project.clips[called].same(clip):
            called = f"{name} {number}"
            number += 1
        self.project.clips[called] = clip
        layer = min(max(0, self.layer_index), len(self.project.layers) - 1)
        strip = kin_layers.Strip(called, self.frame)
        self.project.layers[layer].strips.append(strip)
        self.layer_index, self.strip_key = layer, (layer, len(self.project.layers[layer].strips) - 1)
        # A new piece's rest would cover the clip everywhere: it goes.
        if kin_layers.resting(self.project):
            for track in self.project.tracks.values():
                track.restore(([], [], []))
        covered = kin_layers.overridden(self.project, strip)
        self.status.setText(
            tr("Ключи на таймлайне перекрывают клип на {0} моторах — у них играют "
               "ключи", covered) if covered else tr("Клип «{0}» поставлен", called))
        self._layers_changed()

    def drop_clip(self, name: str | None = None) -> None:
        name = name or self.panels["layers"].library.currentText()
        clips = self._read_clips()
        if name in clips:
            del clips[name]
            self._write_clips(clips)
            self.panels["layers"].refresh()

    # -- the pose library --------------------------------------------------------------

    def _pose_file(self) -> Path:
        return logfile.app_dir() / POSES

    def _read_poses(self) -> dict:
        try:
            data = json.loads(self._pose_file().read_text("utf-8"))
            return data.get("poses", {}) if isinstance(data, dict) else {}
        except Exception:  # noqa: BLE001 -- none yet, or broken by hand
            return {}

    def _write_poses(self, poses: dict) -> None:
        try:
            self._pose_file().write_text(json.dumps({"poses": poses}, ensure_ascii=False),
                                         "utf-8")
        except OSError as error:
            logfile.write(f"kinetic editor: poses not written: {error}")

    def pose_names(self) -> list:
        return sorted(self._read_poses())

    def save_pose(self, name: str | None = None) -> None:
        """The piece as it stands at the playhead, kept under a name -- in a
        library beside the program, so every project has it."""
        if name is None:
            from PySide6.QtWidgets import QInputDialog
            name, ok = QInputDialog.getText(self, APP_NAME, tr("Имя позы:"))
            if not ok:
                return
        name = str(name).strip()
        if not name:
            return
        poses = self._read_poses()
        pose = self.pose_now()
        poses[name] = {family: [round(float(v), 5) for v in pose[family].reshape(-1)]
                       for family in km.FAMILIES}
        self._write_poses(poses)
        self.poses.refresh()
        self.poses.choice.setCurrentText(name)
        self.status.setText(tr("Поза «{0}» сохранена", name))

    def put_pose(self, name: str | None = None) -> None:
        """A pose from the library as a key at the playhead: on the chosen
        cells if any are, on all of them if not."""
        name = name or self.poses.choice.currentText()
        pose = self._read_poses().get(name)
        if not pose:
            self.status.setText(tr("Сначала сохраните позу"))
            return
        self._record()
        chosen = self.selection if self.selection.any() else np.ones((ROWS, PER_ROW), bool)
        for family in ("lift", "push", "tilt"):
            values = np.asarray(pose[family], np.float32)
            self._write(family, values, km.cell_mask_for(family, chosen))
        self.status.setText(tr("Поза «{0}» поставлена на кадр {1}", name, self.frame))
        self._changed(keys=True)

    def drop_pose(self, name: str | None = None) -> None:
        name = name or self.poses.choice.currentText()
        poses = self._read_poses()
        if name in poses:
            del poses[name]
            self._write_poses(poses)
            self.poses.refresh()

    # -- what went wrong, one at a time -------------------------------------------------

    def show_problem(self, problem) -> None:
        """A row of the problems list: to its frame, its cells chosen."""
        if not problem:
            return
        cells = np.zeros((ROWS, PER_ROW), bool)
        if problem[0] == "clash":
            frame = int(problem[1])
            self.go_to(frame)
            pose = self.sim_pose() or self.pose_now()
            cells = km.over_limit(pose["tilt"], pose["lift"], pose["push"])
        else:
            family, motor, frame = problem[1], int(problem[2]), int(problem[3])
            self.set_family(family)
            self.go_to(frame)
            row, which = km.motor_address(family, motor)
            if family == "lift":
                cells[row] = True
            elif family == "push":
                cells[row, which * PER_PUSHER:(which + 1) * PER_PUSHER] = True
            else:
                cells[row, which] = True
        self._select(cells, "set")

    def toggle_keys_card(self) -> None:
        card = self.keys_card
        if card.isVisible():
            card.hide()
            return
        listed = [(tr(key), tr(what)) for key, what in KEYS]
        width = max(len(key) for key, _ in listed) + 2
        card.setText("\n".join(f"{key:<{width}}{what}" for key, what in listed))
        card.adjustSize()
        card.move(96, 12)
        card.show()
        card.raise_()

    def key_selected(self, family: str) -> None:
        """◆: the chosen motors of a family keyed where they stand."""
        if not self.selection.any():
            self.status.setText(tr("Сначала выберите соты"))
            return
        self._record()
        mask = km.cell_mask_for(family, self.selection)
        self._write(family, self.pose_now()[family].reshape(-1), mask)
        self._changed(keys=True)

    def _write(self, family: str, values, mask) -> None:
        """Key `values` for the motors in `mask` at the playhead, in bounds
        -- and, with a mask for editing, only its motors, a part-weighted one
        that part of the way from where it stood when the edit began."""
        track = self.project.tracks[family]
        values = np.asarray(values, np.float32).reshape(-1)
        mask = np.asarray(mask, bool).reshape(-1)
        if family == "tilt":
            pose = self.pose_now()
            values = km.clamp_tilt(values, pose["lift"], pose["push"]).reshape(-1)
        weight = self._edit_weights(family)
        if weight is not None:
            wanted = mask.any()
            mask = mask & (weight > 1e-3)
            if wanted and not mask.any():
                self.status.setText(tr("Вне маски «{0}» — ничего не изменилось",
                                       self.edit_mask))
                return
            soft = weight < 1.0 - 1e-3
            if soft.any():
                base = self._base_of(family)
                values = np.where(soft, base + (values - base) * weight, values)
        track.write(self.frame, values, mask)
        self.dirty = True

    def _edit_weights(self, family: str):
        """The mask for editing as a weight a motor, or None for no mask."""
        weights = self.project.masks.get(self.edit_mask) if self.edit_mask else None
        return None if weights is None else kin_prims.motor_weights(family, weights)

    def _base_of(self, family: str) -> np.ndarray:
        """Where a family's motors stood at the playhead before the edit
        under way began -- a drag writes many times, and a part-weighted
        motor goes part of the way from there, not from its last step."""
        if self._edit_base is not None and self._edit_base[0] == self.frame:
            return self._edit_base[1][family].reshape(-1)
        return self.pose_now()[family].reshape(-1)

    def _select(self, cells, how: str) -> None:
        if how == "add":
            self.selection = self.selection | cells
        elif how == "take":
            self.selection = self.selection & ~cells
        else:
            self.selection = np.asarray(cells, bool).copy()
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
            mask = np.ones(track.size, bool)
            weight = self._edit_weights(family)
            if weight is not None:
                mask &= weight > 1e-3
            track.write(self.frame, pose[family].reshape(-1), mask)
        self._changed(keys=True)

    @staticmethod
    def _parts(chosen) -> dict:
        """Chosen keys as (family, frame) -> the motors taken: a key chosen
        on a ring's or a cell's lane is that part of the key, and two lanes
        of one key take both their parts."""
        parts: dict = {}
        for key, frame in chosen:
            if key[0] == "prim":
                continue
            lane = lane_of(key)
            mask = lane.mask()
            got = parts.get((lane.family, int(frame)))
            parts[(lane.family, int(frame))] = mask if got is None else (got | mask)
        return parts

    def delete_keys(self) -> None:
        chosen = sorted(self.timeline.chosen)
        if not chosen:
            self.status.setText(tr("Выберите ключи на таймлайне"))
            return
        self._record()
        for (family, frame), mask in self._parts(chosen).items():
            track = self.project.tracks[family]
            index = track.index(frame)
            if index is not None:
                track.remove(index, None if mask.all() else mask)
        for key, frame in chosen:
            if key[0] == "prim" and key[1] < len(self.project.primitives):
                one = self.project.primitives[key[1]]
                index = one.index(frame)
                # A primitive keeps one key at least: it has to be somewhere.
                if index is not None and len(one.frames) > 1:
                    one.remove(index)
        self.project.changed()
        self.timeline.chosen = set()
        self._changed(keys=True)

    def _move_keys(self, chosen, by: int) -> None:
        self._record()
        parts = self._parts(chosen)
        for family in km.FAMILIES:
            frames = sorted((frame for fam, frame in parts if fam == family),
                            reverse=by > 0)
            track = self.project.tracks[family]
            for frame in frames:
                index = track.index(frame)
                if index is None:
                    continue
                mask = parts[(family, frame)]
                target = max(0, min(self.project.length - 1, frame + by))
                track.move(index, target, None if mask.all() else mask)
        for number, one in enumerate(self.project.primitives):
            frames = sorted((frame for key, frame in chosen
                             if key[0] == "prim" and key[1] == number), reverse=by > 0)
            for frame in frames:
                index = one.index(frame)
                if index is not None:
                    one.move(index, max(0, min(self.project.length - 1, frame + by)))
        self.project.changed()
        top = self.project.length - 1
        self.timeline.chosen = {(key, max(0, min(top, frame + by)))
                                for key, frame in chosen}
        self._changed(keys=True)

    def set_detailed(self, on: bool) -> None:
        """The timeline's tree of lanes, or its three families alone."""
        self.timeline.set_detailed(on)
        self.timeline_mode.buttons[1 if on else 0].setChecked(True)
        if self.settings.get("timeline_detailed") != bool(on):
            self.settings["timeline_detailed"] = bool(on)
            self._write_settings()

    def set_timeline_view(self, view: str) -> None:
        """Простой, подробный, or the layers -- which takes up their tool."""
        if view == "layers":
            self.timeline.set_layered(True)
            self.timeline_mode.buttons[2].setChecked(True)
            if self.tool != "layers":
                self._choose_tool("layers")
            return
        self.set_detailed(view == "detailed")

    def _lane_picked(self, key) -> None:
        """A lane's name clicked: its family to work on, and its cells
        chosen -- a ring, a group, a cell."""
        lane = lane_of(key)
        if lane.is_prim:
            self.choose_primitive(lane.key[1], take_tool=True)
            return
        self.set_family(lane.family)
        if lane.level > 0:
            self._select(lane.cells(), "set")

    def step_key(self, direction: int) -> None:
        one = self.primitive() if self.tool == "prims" else None
        frames = one.frames if one is not None else self.project.tracks[self.family].frames
        if direction > 0:
            later = [f for f in frames if f > self.frame]
            if later:
                self.go_to(later[0])
        else:
            earlier = [f for f in frames if f < self.frame]
            if earlier:
                self.go_to(earlier[-1])

    def next_warning(self) -> None:
        found = [frame for frame, _ in self.warnings]
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
        self._frame_seen = (spot, facing, towards, transform, wide, tall)
        return np.stack([x, y], axis=1), faces, clip[:, 3]

    def _project(self, points, transform, wide, tall) -> np.ndarray:
        clip = np.concatenate([points, np.ones((len(points), 1))], axis=1) @ transform.T
        w = np.where(clip[:, 3] > 1e-6, clip[:, 3], 1e-6)[:, None]
        ndc = clip[:, :2] / w
        return np.stack([(ndc[:, 0] + 1.0) * 0.5 * wide,
                         (1.0 - ndc[:, 1]) * 0.5 * tall], axis=1)

    # -- the handles -----------------------------------------------------------------------

    def _rebuild_handles(self) -> None:
        """The handles of what is chosen, where the cells stand now: in the
        selection tool, with handles on, for rings, groups or cells as 1 2 3
        have it."""
        if (not self.gizmos_on or self.tool != "select" or not self.selection.any()
                or self.solid is None):
            self.handles = []
            return
        places, faces, _ = self._cells_on_screen()
        spot, facing, towards, transform, wide, tall = self._frame_seen
        norms = np.linalg.norm(towards, axis=1) * np.linalg.norm(facing, axis=1)
        frontal = np.einsum("ci,ci->c", facing, towards) / np.maximum(norms, 1e-9)
        out = self._project(spot + self.cell_radial, transform, wide, tall) - places
        self.handles = kin_gizmo.build(self.selection, self.unwrap.grain, places,
                                       faces, frontal, out, self.index_of)

    def set_gizmos(self, on: bool) -> None:
        self.gizmos_on = bool(on)
        self.gizmo_button.setChecked(self.gizmos_on)
        self.touch()

    def _grab_start(self, handle, x: float, y: float, everyone: bool) -> None:
        """A handle taken: its own element moves, or with Shift every one
        chosen, from where they all stand now."""
        chosen = (kin_gizmo.elements(self.selection, self.unwrap.grain) if everyone
                  else [handle.element])
        cells = np.zeros((ROWS, PER_ROW), bool)
        for element in chosen:
            cells |= kin_gizmo.element_cells(element)
        family = handle.family
        self.begin_edit()
        self._grab = (handle, (x, y), km.cell_mask_for(family, cells),
                      self.pose_now()[family].reshape(-1).copy())

    def _grab_move(self, x: float, y: float, fine: bool) -> None:
        handle, start, mask, values = self._grab
        worth = kin_gizmo.amount(handle, start, (x, y), fine)
        self._write(handle.family, values + worth, mask)
        self._changed()

    # -- Blender's G, R and H ---------------------------------------------------------------

    MODAL = {Qt.Key.Key_G: "push", Qt.Key.Key_R: "tilt", Qt.Key.Key_H: "lift"}

    def _start_modal(self, family: str, x: float | None = None) -> None:
        """G, R, H: the chosen motors of one family follow the mouse sideways
        until a click takes it or Esc puts it back. `x` is where the hand is,
        on the screen; the cursor's own place when not said."""
        from PySide6.QtGui import QCursor
        if not self.selection.any():
            self.status.setText(tr("Сначала выберите соты"))
            return
        self.begin_edit()
        self._modal = (family, QCursor.pos().x() if x is None else x,
                       km.cell_mask_for(family, self.selection),
                       self.pose_now()[family].reshape(-1).copy())
        self._say_modal(0.0)

    def _modal_move(self, fine: bool, x: float | None = None) -> None:
        from PySide6.QtGui import QCursor
        family, start, mask, values = self._modal
        here = QCursor.pos().x() if x is None else x
        moved = (here - start) * (0.1 if fine else 1.0)
        worth = {"push": moved * kin_gizmo.PUSH_A_PIXEL,
                 "tilt": moved * 0.25 / 90.0,
                 "lift": float(np.round(moved / kin_gizmo.PIXELS_A_STATE))}[family]
        self._write(family, values + worth, mask)
        self._changed()
        self._say_modal(worth)

    def _say_modal(self, worth: float) -> None:
        family = self._modal[0]
        said = {"push": f"{worth * 1000:+.0f} " + tr("мм"),
                "tilt": f"{worth * 90:+.1f}°",
                "lift": f"{worth:+.0f}"}[family]
        self.status.setText(tr("{0}: {1} — щелчок принять, Esc отменить",
                               tr(FAMILY_NAME[family]), said))

    def _end_modal(self, keep: bool) -> None:
        self._modal = None
        if keep:
            self.end_edit()
            self.status.setText("")
            return
        # Put back exactly what was there: the step begin_edit took.
        self._editing = False
        if self.undo:
            self.project.restore(self.undo.pop())
        self.status.setText(tr("Отменено"))
        self._changed(keys=True)

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
            if button == 1 and self.tool == "prims":
                got = self._cell_under(x, y)
                if got is not None and self.primitive() is not None:
                    self._drag = ("place",)
                    self.begin_edit()
                    self._place_at_cell(got)
                return
            if button == 1:
                handle = kin_gizmo.picked(self.handles, (x, y)) if self.handles else None
                if handle is not None:
                    self._grab_start(handle, x, y, "Shift" in mods)
                    self._drag = ("grab",)
                    return
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
            if self._drag and self._drag[0] == "grab":
                self._grab_move(x, y, "Control" in mods)
                return
            if self._drag and self._drag[0] == "place":
                got = self._cell_under(x, y)
                if got is not None:
                    self._place_at_cell(got)
                return
            if self.handles:
                hot = kin_gizmo.picked(self.handles, (x, y))
                if hot is not self._hot:
                    self._hot = hot
                    self.touch()
            got = self._cell_under(x, y)
            self._hovered(*(got if got else (-1, -1)))
            if self.tool == "brush":
                self._under = self._weights_at(got) if got is not None else None
                if self._drag and self._drag[0] == "brush" and got is not None:
                    self._dab(self._under)
                else:
                    self._paint()
                    self.touch()
            elif self._drag and self._drag[0] == "select" and got is not None:
                how = self._drag[1] if self._drag[1] != "set" else "add"
                self._select(self._grain_cells(got), how)
            return
        if kind == "pointer_up":
            if self._drag and self._drag[0] in ("brush", "grab", "place"):
                self._grab = None
                self.end_edit()
            self._drag = None
            return
        if kind == "pointer_leave":
            self._under = None
            self._hovered(-1, -1)
            self._paint()
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
        pose = self.shown_now()
        lift = float(pose["lift"][row])
        push = float(pose["push"][row, which // PER_PUSHER])
        tilt = float(pose["tilt"][row, which])
        low, high = km.tilt_bounds(pose["lift"], pose["push"])
        # The lowest ring stands on the base: there is no gap under it.
        gap = ("—" if row == km.NO_JACK
               else f"{float(kinetic._state_mm(lift)):.0f} " + tr("мм"))
        self.hover_label.setText(tr(
            "кольцо {0}, сота {1}: зазор под ним {2}, вынос {3:.0f} мм, "
            "наклон {4:+.1f}° (вниз до {5:.0f}°, вверх до {6:.0f}°)",
            row + 1, which + 1, gap, push * 1000, tilt * 90,
            float(high[row, which]) * 90, float(-low[row, which]) * 90))

    # -- keys on the keyboard ------------------------------------------------------------------

    def _typing(self) -> bool:
        spot = QApplication.focusWidget()
        return (isinstance(spot, QLineEdit) and spot.isEnabled()
                and not spot.isReadOnly())

    def eventFilter(self, watched, event):          # noqa: N802
        if self._modal is not None:
            kind = event.type()
            if kind == QEvent.Type.MouseMove:
                self._modal_move(bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier))
                return False
            if kind == QEvent.Type.MouseButtonPress:
                self._end_modal(event.button() == Qt.MouseButton.LeftButton)
                return True
            if kind == QEvent.Type.KeyPress and event.key() in (
                    Qt.Key.Key_Escape, Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._end_modal(event.key() != Qt.Key.Key_Escape)
                return True
        if (event.type() == QEvent.Type.KeyPress and self.isActiveWindow()
                and not self._typing() and self._key(event)):
            return True
        return super().eventFilter(watched, event)

    def _key(self, event) -> bool:
        key = layout_key(event)
        mods = event.modifiers()
        control = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        if event.text() == "?" or key == Qt.Key.Key_Question                 or (key == Qt.Key.Key_Slash and shift):
            self.toggle_keys_card()
        elif key == Qt.Key.Key_Escape and self.keys_card.isVisible():
            self.keys_card.hide()
        elif key == Qt.Key.Key_Space:
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
            if self.timeline.layered and self.strip() is not None:
                self.drop_strip()
            else:
                self.delete_keys()
        elif key == Qt.Key.Key_M:
            self.set_mask(not self.show_mask)
        elif key in self.MODAL and not shift:
            self._start_modal(self.MODAL[key])
        elif key == Qt.Key.Key_T:
            self.set_gizmos(not self.gizmos_on)
        elif key in TOOL_KEYS and not shift:
            self._choose_tool(TOOL_KEYS[key])
        elif key in GRAIN_KEYS:
            self.set_grain(GRAIN_KEYS[key], take_tool=True)
        elif key in LAYER_KEYS:
            self.set_family(LAYER_KEYS[key])
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
        written = km.export_motor_json(self.composed(), path)
        self.settings["export_folder"] = str(written.parent)
        self._write_settings()
        warnings = self.desired().violations()
        words = tr("Записан {0}", written.name)
        if warnings:
            words += " — " + tr("наклон вне предела на {0} ключах", len(warnings))
        result = self.simulation()
        if result is not None and result.dropped:
            words += " — " + tr("моторы пропустят команд: {0}", len(result.dropped))
        self.status.setText(words)
        logfile.write(f"kinetic editor: exported {written}")
        return written

    def show_in_viewer(self, asked: bool = False) -> bool:
        """The piece exported and opened in the viewer, with its video and
        sound -- on the viewer's own rows, in place of what they hold, so
        it is asked first."""
        if not asked:
            replaced = ["Kinetic"] + (["Top"] if self.project.video else []) + (
                ["Sound"] if self.project.sound else [])
            box = QMessageBox(QMessageBox.Icon.Warning, APP_NAME, tr(
                "Вьюер откроется в «Просмотре» с этой кинетикой и заменит свои "
                "строки {0}: то, что в них загружено сейчас, придётся открыть "
                "заново. Открыть во вьюере?", ", ".join(replaced)), parent=self)
            go = box.addButton(tr("Открыть во вьюере"), QMessageBox.ButtonRole.AcceptRole)
            box.addButton(tr("Отмена"), QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is not go:
                return False
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
        return True

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
        self._video_cells = None
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
        # What is said out of pieces, said again.
        self.panels["brush"].show_family(self.family)
        self.panels["motors"]._shown = None
        self.masks.refresh()
        self.timeline.update()
        self.status.setText("")
        self.settings["language"] = code
        self._write_settings()
        self._say_title()
        self._changed(keys=True)

    def closeEvent(self, event) -> None:            # noqa: N802
        if not self._unsaved_ok():
            event.ignore()
            return
        self.sim_timer.stop()
        self._job_timer.stop()
        self._pool.shutdown(wait=False, cancel_futures=True)
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
