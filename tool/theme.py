"""How the viewer looks: its colours, its type, its few drawn pictures.

A handful of values, each meaning one thing, instead of whatever colour was
to hand where a widget was made. Everything else in the window is derived
from these.

  NIGHT    behind the picture and the timeline
  PANEL    the window's chrome: bars, rows, the column
  RAISED   buttons and fields standing on the panel
  SEAM     every border and divider
  TEXT     what is read
  QUIET    what is looked up: file facts, captions, labels
  LIVE     what is live: the playhead, a loop holding, a switch that is on

States are separate from the accent and are always a word as well as a
colour: WARN for what wants attention, ERROR for what failed.

Each screen has its colour, and it is the same colour wherever the screen is
named -- its row, its slider, its lane on the timeline, its line in the
counts -- so a screen is recognised by colour anywhere in the window. The
mark beside its name is a hexagon, a cell of the honeycomb the top screen is
made of: the viewer's one signature, and used for nothing else.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QIcon, QPainter,
                           QPainterPath, QPen, QPixmap, QPolygonF)

NIGHT = "#0f1318"
PANEL = "#171c23"
RAISED = "#222933"
HOVER = "#2b333e"
SEAM = "#2a313c"
TEXT = "#dde3ea"
QUIET = "#8d97a5"
FAINT = "#5a6270"
LIVE = "#4ec9e0"
LIVE_DIM = "#1f3b44"           # a switch that is on: the live hue, sunk
LIVE_EDGE = "#2f5864"
WARN = "#f08c4a"
ERROR = "#e25c5c"

SCREEN = {"Top": "#5b9bd5", "Bottom": "#4fb38a", "Lamels": "#cda349",
          "Frame": "#b9c2ce", "Sound": "#9c80d6", "Kinetic": "#d0708f",
          "Cue": "#e7c95e"}
# The baked screens, by the name the scene gives them.
BAKED = {"Screen_Top": "Top", "Screen_Bottom": "Bottom",
         "Lamel_screen": "Lamels"}

UI = "Segoe UI"
# Numbers, timecodes and counts: a face whose digits all have one width, so
# a running counter does not shiver. Cascadia Mono where Windows has it,
# Consolas everywhere else.
_MONO_CHOICES = ("Cascadia Mono", "Consolas", "DejaVu Sans Mono", "Menlo")
_mono = None


def mono_family() -> str:
    global _mono
    if _mono is None:
        known = set(QFontDatabase.families())
        _mono = next((one for one in _MONO_CHOICES if one in known), "monospace")
    return _mono


def mono(size: float = 9.0, bold: bool = False) -> QFont:
    font = QFont(mono_family())
    font.setPointSizeF(size)
    font.setStyleHint(QFont.StyleHint.Monospace)
    if bold:
        font.setWeight(QFont.Weight.DemiBold)
    return font


def heading() -> QFont:
    """A panel's own name: small capitals, spaced, quiet."""
    font = QFont(UI)
    font.setPointSizeF(8.0)
    font.setWeight(QFont.Weight.DemiBold)
    font.setCapitalization(QFont.Capitalization.AllUppercase)
    font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 114)
    return font


def sheet() -> str:
    """The whole window's style sheet, made out of the values above."""
    return f"""
QWidget {{ background:{PANEL}; color:{TEXT}; font-family:"{UI}"; font-size:12px; }}
QToolTip {{ background:{RAISED}; color:{TEXT}; border:1px solid {SEAM};
            padding:4px 6px; }}
QLineEdit, QSpinBox, QComboBox {{ background:{NIGHT}; border:1px solid {SEAM};
            border-radius:3px; padding:3px 5px; selection-background-color:{LIVE_DIM}; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color:{LIVE_EDGE}; }}
QLineEdit:read-only {{ background:transparent; border-color:transparent; }}
QComboBox QAbstractItemView {{ background:{RAISED}; border:1px solid {SEAM};
            selection-background-color:{LIVE_DIM}; }}
QPushButton, QToolButton {{ background:{RAISED}; border:1px solid {SEAM};
            border-radius:3px; padding:5px 12px; }}
QPushButton:hover, QToolButton:hover {{ background:{HOVER}; }}
QPushButton:checked {{ background:{LIVE_DIM}; border-color:{LIVE_EDGE}; }}
QPushButton:disabled, QToolButton:disabled {{ color:{FAINT}; background:{PANEL}; }}
QPushButton#qa_render {{ background:{LIVE_DIM}; border-color:{LIVE_EDGE};
            font-weight:600; padding:5px 16px; }}
QPushButton#qa_render:hover {{ background:#28505b; }}
QCheckBox {{ spacing:6px; background:transparent; }}
QSlider {{ background:transparent; }}
QSlider::groove:horizontal {{ height:4px; background:{NIGHT}; border-radius:2px; }}
QSlider::sub-page:horizontal {{ background:{SEAM}; border-radius:2px; }}
QSlider::handle:horizontal {{ width:12px; background:{QUIET}; border-radius:6px;
            margin:-5px 0; }}
QSlider::handle:horizontal:hover {{ background:{TEXT}; }}
QProgressBar {{ background:{NIGHT}; border:1px solid {SEAM}; border-radius:3px;
            color:{TEXT}; text-align:center; height:14px; }}
QProgressBar::chunk {{ background:{LIVE_EDGE}; border-radius:2px; }}
QScrollBar:vertical {{ background:{NIGHT}; width:10px; }}
QScrollBar::handle:vertical {{ background:{SEAM}; border-radius:4px; min-height:24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height:0px; }}
QMenu {{ background:{RAISED}; border:1px solid {SEAM}; padding:4px; }}
QMenu::item:selected {{ background:{LIVE_DIM}; }}
"""


# -- the signature: a honeycomb cell -----------------------------------------

def _hexagon(rect: QRectF) -> QPolygonF:
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    return QPolygonF([QPointF(x + w * 0.25, y), QPointF(x + w * 0.75, y),
                      QPointF(x + w, y + h / 2), QPointF(x + w * 0.75, y + h),
                      QPointF(x + w * 0.25, y + h), QPointF(x, y + h / 2)])


def paint_cell(brush: QPainter, rect: QRectF, colour: str) -> None:
    """A screen's mark, where a painter is already at work."""
    brush.save()
    brush.setRenderHint(QPainter.RenderHint.Antialiasing)
    brush.setPen(Qt.PenStyle.NoPen)
    brush.setBrush(QColor(colour))
    brush.drawPolygon(_hexagon(rect))
    brush.restore()


_cells: dict = {}


def cell(row: str, size: int = 12) -> QPixmap:
    """A screen's mark as a picture, for a label or a button."""
    key = (row, size)
    if key not in _cells:
        ratio = 2
        picture = QPixmap(size * ratio, size * ratio)
        picture.setDevicePixelRatio(ratio)
        picture.fill(Qt.GlobalColor.transparent)
        brush = QPainter(picture)
        paint_cell(brush, QRectF(0.5, size * 0.1, size - 1, size * 0.8),
                   SCREEN.get(row, QUIET))
        brush.end()
        _cells[key] = picture
    return _cells[key]


def cell_html(row: str) -> str:
    """The mark inside rich text: the hexagon character, in the colour."""
    return f'<span style="color:{SCREEN.get(row, QUIET)}">⬢</span>'


# -- the drawn icons -----------------------------------------------------------

def _pen(width: float = 4.2) -> QPen:
    pen = QPen(QColor(TEXT), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _draw(name: str, brush: QPainter) -> None:
    brush.setPen(_pen())
    brush.setBrush(Qt.BrushStyle.NoBrush)
    if name == "clear":
        brush.drawLine(18, 18, 46, 46)
        brush.drawLine(46, 18, 18, 46)
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
        brush.drawRoundedRect(QRectF(8, 14, 36, 36), 4, 4)
        path = QPainterPath()
        path.moveTo(44, 26)
        path.lineTo(56, 18)
        path.lineTo(56, 46)
        path.lineTo(44, 38)
        brush.drawPath(path)
        brush.setBrush(QColor(LIVE))
        brush.setPen(Qt.PenStyle.NoPen)
        brush.drawEllipse(QPointF(26, 32), 6, 6)
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
        brush.drawRoundedRect(QRectF(16, 16, 32, 32), 3, 3)
    elif name == "keys":
        brush.drawRoundedRect(QRectF(8, 16, 48, 32), 5, 5)
        for x in (18, 28, 38, 48):
            brush.drawPoint(QPointF(x - 2, 27))
        brush.drawLine(20, 38, 44, 38)


DRAWN = ("clear", "directory", "file", "snapshot", "render", "probe",
         "rebake", "download", "stop", "keys")
_icons: dict = {}


def drawn_icon(name: str) -> QIcon:
    """One of the viewer's own line icons: one weight, one colour."""
    if name not in _icons:
        picture = QPixmap(64, 64)
        picture.fill(Qt.GlobalColor.transparent)
        brush = QPainter(picture)
        brush.setRenderHint(QPainter.RenderHint.Antialiasing)
        _draw(name, brush)
        brush.end()
        _icons[name] = QIcon(picture)
    return _icons[name]
