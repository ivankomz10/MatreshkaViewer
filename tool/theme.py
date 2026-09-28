"""How the viewer looks: its colours, its type, its few drawn pictures.

From the redesign «Мастерская» (tool/proto_timeline/Matreshka Viewer
Redesign.dc.html, rounds 1a, 2a and 3a): cold graphite, one blue for what is
chosen, a red that belongs to Рендер alone, and each screen a hue of its own
that is the same everywhere the screen is named.

  PANEL     #1c1d20  the window, the columns, the render bar
  BAR       #18191b  the line along the top, the transport
  SHOWBAR   #202125  the show's own line and the clip's column
  SUNKEN    #141517  fields, the status line
  CARD      #232428  a source's card
  SEAM      #2c2e33  borders and dividers;  EDGE #34373d  a control's edge
  TEXT      #e6e7ea;  SECOND #c6cad1;  DIM #9aa0a9;  QUIET #8a8f98
  ACCENT    #2f5f8f  what is chosen: the level, a switch that is on
  LINE      #6aa6de  the chosen tab's underline
  FILL      #5b93c7  a slider's filled part
  META      #8fbf9a  facts about a file: size, codec, rate, length
  RENDER    #c8463c  the Рендер button, and nothing else
  GOLD      #e3c27a  loops, and the draft

Screens are hues on one oklch lightness, so none of them shouts: Top 250,
Bottom 160, Lamels 80, Kinetic 25, Sound 300, Frame 330; Cue is neutral. A
clip is filled with its screen's hue, bordered with a lighter one, with a
lighter still edge on its left.

Type: IBM Plex Sans and IBM Plex Mono when they are in tool/fonts, which the
design is set in; Segoe UI and Cascadia Mono (or Consolas) when not.
"""
from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QIcon, QPainter,
                           QPainterPath, QPen, QPixmap, QPolygonF)

PANEL = "#1c1d20"
BAR = "#18191b"
SHOWBAR = "#202125"
SUNKEN = "#141517"
DEEP = "#101113"
CARD = "#232428"
CARD_EDGE = "#2e3035"
SEAM = "#2c2e33"
EDGE = "#34373d"
RAISED = "#2a2c31"
HOVER = "#33363c"
TEXT = "#e6e7ea"
SECOND = "#c6cad1"
DIM = "#9aa0a9"
QUIET = "#8a8f98"
FAINT = "#5d626b"
ACCENT = "#2f5f8f"
LINE = "#6aa6de"
FILL = "#5b93c7"
META = "#8fbf9a"
RENDER = "#c8463c"
GOLD = "#e3c27a"
GOLD_EDGE = "#6b5a2c"
GOLD_BG = "#1d1b16"
DRAFT_BG = "#3a3220"
LINK_BG = "#1f3347"
LINK_FG = "#bcd6ef"
WARN = "#f0a04a"
ERROR = "#e25c5c"
LANE_A = "#16171a"
LANE_B = "#191a1d"
LANE_EDGE = "#121315"

# The names the rest of the viewer grew up with, pointed at the new values.
NIGHT = SUNKEN
LIVE = LINE
LIVE_DIM = ACCENT
LIVE_EDGE = "#3d74a8"

# Behind the timeline, one shade per screen group, alternating.
LANE = {"Cue": LANE_A, "Kinetic": LANE_B, "Top": LANE_A, "Bottom": LANE_B,
        "Lamels": LANE_A, "Sound": LANE_B}


# -- colour --------------------------------------------------------------------

def oklch(lightness: float, chroma: float, hue: float) -> str:
    """A CSS oklch() colour as #rrggbb: the design's own numbers, as Qt needs
    them. Out of gamut is clipped, which none of the design's values are."""
    a = chroma * math.cos(math.radians(hue))
    b = chroma * math.sin(math.radians(hue))
    l_ = lightness + 0.3963377774 * a + 0.2158037573 * b
    m_ = lightness - 0.1055613458 * a - 0.0638541728 * b
    s_ = lightness - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    linear = (4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
              -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
              -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)

    def encode(value: float) -> int:
        value = min(1.0, max(0.0, value))
        value = (12.92 * value if value <= 0.0031308
                 else 1.055 * value ** (1 / 2.4) - 0.055)
        return round(value * 255)

    return "#" + "".join(f"{encode(one):02x}" for one in linear)


HUE = {"Top": 250, "Bottom": 160, "Lamels": 80, "Kinetic": 25, "Sound": 300,
       "Frame": 330}

# Each screen's own colour: the dot by its name, the bar at its lane's head.
SCREEN = {row: oklch(0.72, 0.12, hue) for row, hue in HUE.items()}
SCREEN["Cue"] = SECOND
# The baked screens, by the name the scene gives them.
BAKED = {"Screen_Top": "Top", "Screen_Bottom": "Bottom",
         "Lamel_screen": "Lamels"}

_clips: dict = {}


def clip_colours(row: str) -> dict:
    """A clip of that screen: fill, border, left edge, name, second line."""
    if row not in _clips:
        hue = HUE.get(row)
        if hue is None:
            _clips[row] = {"bg": RAISED, "bd": EDGE, "edge": SECOND,
                           "fg": SECOND, "meta": QUIET}
        else:
            _clips[row] = {"bg": oklch(0.42, 0.08, hue),
                           "bd": oklch(0.56, 0.10, hue),
                           "edge": oklch(0.78, 0.12, hue),
                           "fg": "#ffffff",
                           "meta": oklch(0.88, 0.04, hue)}
    return _clips[row]


# -- type ----------------------------------------------------------------------

UI_FAMILIES = ("IBM Plex Sans", "Segoe UI")
MONO_FAMILIES = ("IBM Plex Mono", "Cascadia Mono", "Consolas",
                 "DejaVu Sans Mono", "Menlo")
_mono = None
_ui = None
# The same, as a style sheet names them.
UI_CSS = ", ".join(f'"{one}"' for one in UI_FAMILIES)
MONO_CSS = ", ".join(f'"{one}"' for one in MONO_FAMILIES)


def load_fonts(folder: Path | None) -> list:
    """The design's own faces, when they travel with the program."""
    loaded = []
    if folder is not None and Path(folder).is_dir():
        for face in sorted(Path(folder).glob("*.ttf")) + sorted(
                Path(folder).glob("*.otf")):
            if QFontDatabase.addApplicationFont(str(face)) >= 0:
                loaded.append(face.name)
    global _mono, _ui
    _mono = _ui = None
    return loaded


def _first(choices) -> str:
    known = set(QFontDatabase.families())
    return next((one for one in choices if one in known), choices[-1])


def ui_family() -> str:
    global _ui
    if _ui is None:
        _ui = _first(UI_FAMILIES)
    return _ui


def mono_family() -> str:
    global _mono
    if _mono is None:
        _mono = _first(MONO_FAMILIES)
    return _mono


def mono(size: float = 9.0, bold: bool = False) -> QFont:
    font = QFont(mono_family())
    font.setPointSizeF(size)
    font.setStyleHint(QFont.StyleHint.Monospace)
    if bold:
        font.setWeight(QFont.Weight.Medium)
    return font


def ui(size: float = 10.0, weight=QFont.Weight.Normal) -> QFont:
    font = QFont(ui_family())
    font.setPointSizeF(size)
    font.setWeight(weight)
    return font


def app_font() -> QFont:
    """The window's own type, given to the application rather than written
    into the sheet: a face named in the sheet for every widget would win over
    every face a label is given in code, the typewriter ones included."""
    font = QFont(ui_family())
    font.setPixelSize(13)
    return font


def heading() -> QFont:
    """A panel's own name: Источники, Экраны, Клип, Лупы."""
    return ui(10.5, QFont.Weight.DemiBold)


def sheet() -> str:
    """The whole window's style sheet, made out of the values above."""
    families, monos = UI_CSS, MONO_CSS
    return f"""
QWidget {{ background:{PANEL}; color:{TEXT}; }}
QToolTip {{ background:{CARD}; color:{TEXT}; border:1px solid {EDGE};
            padding:5px 8px; }}
QLabel {{ background:transparent; }}
QLineEdit, QSpinBox, QComboBox {{ background:{SUNKEN}; border:1px solid {EDGE};
            border-radius:4px; padding:4px 8px; font-family:{monos}; font-size:12px;
            selection-background-color:{ACCENT}; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color:{LINE}; }}
QLineEdit:read-only {{ background:transparent; border-color:transparent; }}
QComboBox::drop-down {{ border:none; width:18px; }}
QComboBox QAbstractItemView {{ background:{CARD}; border:1px solid {EDGE};
            selection-background-color:{ACCENT}; font-family:{families}; }}
QPushButton, QToolButton {{ background:transparent; border:1px solid {EDGE};
            border-radius:5px; padding:5px 12px; color:{TEXT}; }}
QPushButton:hover, QToolButton:hover {{ background:#26282d; }}
QPushButton:checked {{ background:{ACCENT}; border-color:{ACCENT}; color:#ffffff; }}
QPushButton:disabled, QToolButton:disabled {{ color:{FAINT}; border-color:{RAISED}; }}
QToolButton::menu-indicator {{ image:none; width:0px; }}
QPushButton#qa_render {{ background:{RENDER}; border-color:{RENDER}; color:#ffffff;
            font-weight:600; padding:7px 18px; }}
QPushButton#qa_render:hover {{ background:#d65247; }}
QPushButton#qa_render:disabled {{ background:#5a2a26; border-color:#5a2a26;
            color:#c9a9a5; }}
QPushButton[pill="true"] {{ border:none; border-radius:4px; padding:3px 9px;
            color:{SECOND}; font-size:12px; background:transparent; }}
QPushButton[pill="true"]:hover {{ background:{RAISED}; }}
QPushButton[pill="true"]:checked {{ background:{ACCENT}; color:#ffffff; }}
QPushButton[tab="true"] {{ border:none; border-bottom:2px solid transparent;
            border-radius:0px; padding:0px 14px; color:{DIM}; background:transparent; }}
QPushButton[tab="true"]:hover {{ color:{TEXT}; background:transparent; }}
QPushButton[tab="true"]:checked {{ color:#ffffff; border-bottom-color:{LINE};
            font-weight:500; background:transparent; }}
QPushButton[segment="true"] {{ border:none; border-radius:4px; padding:5px 14px;
            color:#b8bcc4; background:transparent; }}
QPushButton[segment="true"]:checked {{ background:{ACCENT}; color:#ffffff;
            font-weight:500; }}
QPushButton[transport="true"] {{ background:{RAISED}; border:none; border-radius:5px;
            padding:0px; }}
QPushButton[transport="true"]:hover {{ background:{HOVER}; }}
QPushButton[play="true"] {{ background:{TEXT}; border:none; border-radius:5px;
            padding:0px; }}
QPushButton[play="true"]:hover {{ background:#ffffff; }}
QPushButton[link="true"] {{ border:none; background:transparent; color:{DIM};
            padding:0px 2px; font-size:12px; }}
QPushButton[link="true"]:hover {{ color:{TEXT}; background:transparent; }}
QPushButton[link="true"]:checked {{ color:#ffffff; background:transparent;
            border:none; }}
QCheckBox {{ spacing:6px; background:transparent; }}
QSlider {{ background:transparent; }}
QSlider::groove:horizontal {{ height:4px; background:{EDGE}; border-radius:2px; }}
QSlider::sub-page:horizontal {{ background:{FILL}; border-radius:2px; }}
QSlider::handle:horizontal {{ width:14px; height:14px; background:{TEXT};
            border-radius:7px; margin:-5px 0; }}
QSlider#qa_timeline::groove:horizontal, QSlider#qa_full_slider::groove:horizontal {{
            height:6px; background:{RAISED}; border-radius:3px; }}
QSlider#qa_timeline::sub-page:horizontal, QSlider#qa_full_slider::sub-page:horizontal {{
            background:{FILL}; border-radius:3px; }}
QSlider#qa_timeline::handle:horizontal, QSlider#qa_full_slider::handle:horizontal {{
            width:2px; background:#ffffff; border-radius:0px; margin:-9px 0; }}
QProgressBar {{ background:{SUNKEN}; border:1px solid {EDGE}; border-radius:4px;
            color:{TEXT}; text-align:center; height:14px; }}
QProgressBar::chunk {{ background:{FILL}; border-radius:3px; }}
QScrollBar:vertical {{ background:{LANE_A}; width:10px; }}
QScrollBar::handle:vertical {{ background:{EDGE}; border-radius:4px; min-height:24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height:0px; }}
QMenu {{ background:{CARD}; border:1px solid {EDGE}; padding:4px; }}
QMenu::item:selected {{ background:{ACCENT}; }}
QSplitter::handle {{ background:{SEAM}; }}
"""


# -- the screen's mark ---------------------------------------------------------

def paint_cell(brush: QPainter, rect: QRectF, colour: str) -> None:
    """A screen's mark, where a painter is already at work: a small square
    with its corners rounded, as the design draws it."""
    brush.save()
    brush.setRenderHint(QPainter.RenderHint.Antialiasing)
    brush.setPen(Qt.PenStyle.NoPen)
    brush.setBrush(QColor(colour))
    side = min(rect.width(), rect.height())
    square = QRectF(rect.center().x() - side / 2, rect.center().y() - side / 2,
                    side, side)
    brush.drawRoundedRect(square, side * 0.25, side * 0.25)
    brush.restore()


_cells: dict = {}


def cell(row: str, size: int = 8) -> QPixmap:
    """A screen's mark as a picture, for a label or a button."""
    key = (row, size)
    if key not in _cells:
        ratio = 2
        picture = QPixmap(size * ratio, size * ratio)
        picture.setDevicePixelRatio(ratio)
        picture.fill(Qt.GlobalColor.transparent)
        brush = QPainter(picture)
        paint_cell(brush, QRectF(0, 0, size, size), SCREEN.get(row, QUIET))
        brush.end()
        _cells[key] = picture
    return _cells[key]


def cell_html(row: str) -> str:
    """The mark inside rich text."""
    return f'<span style="color:{SCREEN.get(row, QUIET)}">■</span>'


# -- the drawn icons -------------------------------------------------------------

def _pen(colour: str, width: float = 4.2) -> QPen:
    pen = QPen(QColor(colour), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _triangle(brush: QPainter, points) -> None:
    brush.drawPolygon(QPolygonF([QPointF(x, y) for x, y in points]))


def _draw(name: str, brush: QPainter, colour: str) -> None:
    brush.setPen(_pen(colour))
    brush.setBrush(Qt.BrushStyle.NoBrush)
    if name == "clear":
        brush.drawLine(20, 20, 44, 44)
        brush.drawLine(44, 20, 20, 44)
    elif name == "directory":
        path = QPainterPath()
        path.moveTo(8, 18)
        path.lineTo(26, 18)
        path.lineTo(31, 24)
        path.lineTo(56, 24)
        path.lineTo(56, 50)
        path.lineTo(8, 50)
        path.closeSubpath()
        brush.drawPath(path)
    elif name == "file":
        path = QPainterPath()
        path.moveTo(16, 8)
        path.lineTo(38, 8)
        path.lineTo(50, 20)
        path.lineTo(50, 56)
        path.lineTo(16, 56)
        path.closeSubpath()
        brush.drawPath(path)
        brush.drawLine(38, 8, 38, 20)
        brush.drawLine(38, 20, 50, 20)
    elif name == "snapshot":
        brush.drawRoundedRect(QRectF(8, 18, 48, 34), 5, 5)
        brush.drawLine(22, 18, 26, 11)
        brush.drawLine(26, 11, 38, 11)
        brush.drawLine(38, 11, 42, 18)
        brush.drawEllipse(QPointF(32, 35), 9, 9)
    elif name == "render":
        brush.setPen(Qt.PenStyle.NoPen)
        brush.setBrush(QColor(colour))
        brush.drawEllipse(QPointF(32, 32), 11, 11)
    elif name == "probe":
        brush.drawEllipse(QPointF(28, 28), 15, 15)
        brush.drawLine(39, 39, 54, 54)
    elif name == "rebake":
        path = QPainterPath()
        path.arcMoveTo(QRectF(12, 12, 40, 40), 30)
        path.arcTo(QRectF(12, 12, 40, 40), 30, 280)
        brush.drawPath(path)
        brush.drawLine(49, 22, 49, 11)
        brush.drawLine(49, 22, 38, 22)
    elif name == "download":
        brush.drawLine(32, 10, 32, 40)
        brush.drawLine(20, 29, 32, 41)
        brush.drawLine(44, 29, 32, 41)
        brush.drawLine(12, 52, 52, 52)
    elif name == "stop":
        brush.setPen(Qt.PenStyle.NoPen)
        brush.setBrush(QColor(colour))
        brush.drawRoundedRect(QRectF(20, 20, 24, 24), 3, 3)
    elif name == "keys":
        brush.drawRoundedRect(QRectF(8, 16, 48, 32), 5, 5)
        brush.drawLine(20, 38, 44, 38)
    elif name in ("play", "pause", "first", "last", "back", "on"):
        brush.setPen(Qt.PenStyle.NoPen)
        brush.setBrush(QColor(colour))
        if name == "play":
            _triangle(brush, ((22, 16), (22, 48), (48, 32)))
        elif name == "pause":
            brush.drawRect(QRectF(20, 17, 8, 30))
            brush.drawRect(QRectF(36, 17, 8, 30))
        elif name == "first":
            brush.drawRect(QRectF(16, 18, 5, 28))
            _triangle(brush, ((46, 18), (46, 46), (24, 32)))
        elif name == "last":
            brush.drawRect(QRectF(43, 18, 5, 28))
            _triangle(brush, ((18, 18), (18, 46), (40, 32)))
        elif name == "back":
            _triangle(brush, ((36, 18), (36, 46), (16, 32)))
            brush.drawRect(QRectF(40, 18, 5, 28))
        elif name == "on":
            _triangle(brush, ((28, 18), (28, 46), (48, 32)))
            brush.drawRect(QRectF(19, 18, 5, 28))


DRAWN = ("clear", "directory", "file", "snapshot", "render", "probe",
         "rebake", "download", "stop", "keys", "play", "pause", "first",
         "last", "back", "on")
_icons: dict = {}


def drawn_icon(name: str, colour: str = TEXT) -> QIcon:
    """One of the viewer's own icons: one weight, one colour."""
    key = (name, colour)
    if key not in _icons:
        picture = QPixmap(64, 64)
        picture.fill(Qt.GlobalColor.transparent)
        brush = QPainter(picture)
        brush.setRenderHint(QPainter.RenderHint.Antialiasing)
        _draw(name, brush, colour)
        brush.end()
        _icons[key] = QIcon(picture)
    return _icons[key]
