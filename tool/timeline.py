"""The show on a timeline: the strips under the picture and the column beside it.

Read only until the editor is switched on. A show opened to be looked at is
played, not changed: nothing is dragged, no field writes into a clip and no
loop is drawn, so what goes to the site cannot be nudged by accident. The
editor unlocks all of it at once -- and the loops have a lock of their own
inside it, because the loops read out of a show file are the easiest thing
there to break.

What is here came out of the prototype on the `proto/timeline` branch, and
looks the way the redesign draws it (rounds 2a and 3a of Matreshka Viewer
Redesign.dc.html): clips filled with their screen's colour, the playhead a
white line with a flag, fades a diagonal across the clip.

  Ruler      the time axis, the only place the playhead is dragged, with
             the LOOP switch at its head and the loops along its foot
  LoopBar    in the editor only: where loops are drawn, with the lock at
             its other end
  Tracks     a row per level, per screen: Cue, Kinetic, Top x3, Bottom x3,
             Lamels x3, Sound x2 -- what triggers first is highest
  LoopPanel  the loops in numbers, under the screens' sliders
  Inspector  the chosen clip, its fields in two columns

and `ShowView`, which is what they all share: the show, where the playhead
is, which clip is chosen, the loops and whether one is holding, whether the
editor is on. The window owns the clock and the show's history; this is told
where the playhead has got to, asks to go elsewhere, and says before every
change that one is coming (`about_to_change`) and after it what it touched
(`edited`), so that the window can take a snapshot first and rebuild only
what was touched afterwards.

The mouse, the same on every strip:
  left     choose a clip, and in the editor drag it. Empty space lets go, and
           never moves the playhead
  right    drag to scroll, without touching the playhead
  middle   the playhead here
  wheel    zoom;  Shift+wheel scroll
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QSizePolicy, QSpinBox, QVBoxLayout,
                               QWidget)

import show as showfile
import theme

MONO = "IBM Plex Mono, Cascadia Mono, Consolas, DejaVu Sans Mono, monospace"

# Top to bottom: what triggers first is highest.
ROWS = ["Cue", "Kinetic", "Top", "Bottom", "Lamels", "Sound"]
# Each screen's colour: the same one it has everywhere in the window.
HUE = theme.SCREEN
# Three content levels per screen, two sounds. The black still on the level
# behind every show is not a clip here: the viewer chooses its own backing.
LEVELS = {"Top": 3, "Bottom": 3, "Lamels": 3, "Sound": 2, "Kinetic": 1,
          "Cue": 1}
HEAD = 150           # the width of the labels down the left of every strip
SIDE = 630           # the columns beside the picture: screens, then the clip
SNAP = 8             # pixels within which a dragged clip meets an edge

# What each row takes from a folder. By the ending, which is what somebody
# dragging a file sees; the file is asked properly once it has landed.
MOVIES = {".mov", ".mp4", ".m4v", ".mkv", ".avi"}
PICTURES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".tga"}
TAKES = {"Top": MOVIES | PICTURES, "Bottom": MOVIES | PICTURES,
         "Lamels": MOVIES | PICTURES, "Sound": {".wav"},
         "Kinetic": {".json"}, "Cue": set()}

# What the keys do here, for the card over the picture.
KEYS = [
    ("Пробел", "играть / пауза"),
    ("← →", "кадр назад / вперёд"),
    ("Shift+← →", "секунда назад / вперёд"),
    ("Ctrl+← →", "в начало / в конец"),
    ("Home / End", "в начало / в конец"),
    ("I / O", "на начало / конец клипа"),
    ("L", "отпустить луп / держать"),
    ("F", "вся длина"),
    ("Shift+I / O", "начало / конец рендера здесь"),
    ("?", "эта подсказка"),
    ("ЛКМ", "выбрать клип"),
    ("ПКМ", "прокрутка"),
    ("СКМ", "плейхед сюда"),
    ("колесо", "зум, с Shift — прокрутка"),
]
# And these on top, in the editor.
EDIT_KEYS = [
    ("Ctrl+Z / Ctrl+Y", "отменить / вернуть"),
    ("Delete", "удалить клип"),
    ("[ / ]", "клип концом / началом к плейхеду"),
    ("Shift+L", "луп на весь клип"),
    ("K", "замок лупов"),
    ("тащить клип", "по времени и по уровням; Alt — без прилипания"),
    ("тащить по лупам", "новый луп; за край — край; Shift — целиком"),
    ("файл на дорожку", "клип там, где отпустили"),
]


# And in the quick look, where there is no timeline but the picture.
VIEW_KEYS = [
    ("Пробел", "играть / пауза"),
    ("← →", "кадр назад / вперёд"),
    ("Ctrl+← →", "в начало / в конец"),
    ("Shift+I / O", "начало / конец рендера здесь"),
    ("F11 / Esc", "во весь экран и обратно"),
    ("?", "эта подсказка"),
    ("колесо", "приблизить кадр"),
    ("тащить", "сдвинуть кадр; в Инспекторе — облёт"),
    ("двойной щелчок", "вернуть вид"),
]


def keys_text(level: str = "show", editing: bool = False) -> str:
    """The card of keys: the quick look's, or the show's, and the editor's."""
    if level != "show":
        width = max(len(key) for key, _ in VIEW_KEYS) + 2
        return "\n".join(f"{key:<{width}}{what}" for key, what in VIEW_KEYS)
    listed = KEYS + (EDIT_KEYS if editing else [])
    width = max(len(key) for key, _ in listed) + 2
    said = "\n".join(f"{key:<{width}}{what}" for key, what in KEYS)
    if editing:
        said += "\n\nредактор\n" + "\n".join(
            f"{key:<{width}}{what}" for key, what in EDIT_KEYS)
    return said


def row_takes(row: str, path: str) -> bool:
    return Path(path).suffix.lower() in TAKES.get(row, set())


class Axis:
    """Where time sits across the strips. One for all of them, so they agree."""

    def __init__(self, length: int) -> None:
        self.length = max(1, int(length))
        self.origin = float(HEAD)      # pixels before frame `left` is drawn
        self.left = 0.0
        self.width = 1200
        self.scale = self.width / self.length

    def fit(self, width: int | None = None) -> None:
        if width is not None:
            self.width = max(1, int(width))
        self.left = 0.0
        self.scale = self.width / self.length

    def stretch(self, length: int) -> None:
        """The show got longer or shorter; keep where the eye is."""
        was = self.fitted
        self.length = max(1, int(length))
        if was:
            self.fit()
        else:
            self.scale = max(self.scale, self.width / self.length)
            self.clamp()

    @property
    def fitted(self) -> bool:
        return abs(self.scale - self.width / self.length) < 1e-9

    def x_of(self, frame: float) -> float:
        return self.origin + (frame - self.left) * self.scale

    def frame_of(self, x: float) -> float:
        return self.left + (x - self.origin) / max(1e-9, self.scale)

    def zoom_at(self, x: float, factor: float) -> None:
        was = self.frame_of(x)
        lowest = self.width / self.length
        self.scale = max(lowest, min(4.0, self.scale * factor))
        self.left = was - (x - self.origin) / self.scale
        self.clamp()

    def slide(self, by_pixels: float) -> None:
        self.left -= by_pixels / self.scale
        self.clamp()

    def clamp(self) -> None:
        span = self.width / self.scale
        self.left = max(0.0, min(max(0.0, self.length - span), self.left))


def _nice_steps(axis: Axis) -> list:
    """Seconds to put a tick on: as close together as stays readable."""
    for step in (1, 2, 5, 10, 15, 30, 60, 120, 300, 600):
        if step * showfile.FPS * axis.scale > 110:
            break
    first = int(axis.left / showfile.FPS / step) * step
    last = int((axis.left + axis.width / axis.scale) / showfile.FPS) + step
    return list(range(first, last + 1, step))


class ShowView(QObject):
    """The show being looked at, and where in it. What the strips share.

    The loops are read out of the show file and there may be several: a show
    cut into blocks waits at every join. LOOP is off to begin with. The
    playhead crossing a loop's start from the left lights it and from then
    the loop holds; only a hand puts it out, and the loop it was let out of
    lets the playhead go on. Starting inside one does not light it -- that is
    the show being scrubbed into the middle of a wait, not arriving at it.

    `loops` is the show's own list, not a copy of it: a loop drawn here is a
    loop of the show.
    """

    jumped = Signal(float)          # asked to put the playhead at a frame
    changed = Signal()              # something the strips draw is different
    moved = Signal()                # only the playhead: sixty times a second
    looping_changed = Signal(bool)  # the switch went on or off, either way
    editing_changed = Signal(bool)
    locked_changed = Signal(bool)
    about_to_change = Signal(str, object)   # what, and what it is one with
    unchanged = Signal()            # the change that was begun did not happen
    edited = Signal(object)         # a set of rows, "loops", "name"
    dropped = Signal(list, str, int, int)   # files, row, level, frame
    said = Signal(str)              # a word for the line over the strips
    range_wanted = Signal(int, int)  # a clip's frames, for the render

    def __init__(self) -> None:
        super().__init__()
        self.show = showfile.Show(length=1)
        self.axis = Axis(1)
        self.frame = 0.0
        self.chosen = None
        self.loops: list = []
        self.file_loops: list = []     # the loops the show came with
        self.loop_at = 0               # which loop the numbers are about
        self.looping = False
        self.let_go = None             # the loop the playhead was let out of
        self.caught = None             # the loop that last caught it
        self.editing = False
        self.locked = True
        self.render_range = None       # (from, to) in show frames, or None

    def set_render_range(self, span) -> None:
        """What the render will write, when that is not the whole show."""
        if span != self.render_range:
            self.render_range = span
            self.changed.emit()

    def open(self, show, file_loops=None) -> None:
        self.show = show
        show.loops[:] = [(int(low), int(high)) for low, high in show.loops]
        self.loops = show.loops
        self.file_loops = [tuple(one) for one in
                           (file_loops if file_loops is not None
                            else show.loops)]
        self.loop_at = 0
        was, self.looping = self.looping, False
        self.let_go = None
        self.chosen = None
        width = self.axis.width
        self.axis = Axis(show.length)
        self.axis.fit(width)
        self.frame = 0.0
        if was:
            self.looping_changed.emit(False)
        self.changed.emit()

    def reopen(self) -> None:
        """The same show, put back from its history: the clips are new
        objects, so the chosen one is found again by who it was."""
        chosen = self.chosen.ident if self.chosen is not None else None
        self.loops = self.show.loops
        self.chosen = next((one for one in self.show.clips
                            if one.ident == chosen), None)
        self.loop_at = max(0, min(self.loop_at, len(self.loops) - 1))
        self.axis.stretch(self.show.length)
        self.changed.emit()

    # -- the playhead --------------------------------------------------------

    def set_frame(self, frame: float) -> None:
        if frame == self.frame:
            return
        self.frame = float(frame)
        self.moved.emit()

    def go_to(self, frame: float) -> None:
        self.jumped.emit(float(max(0, min(self.show.length, frame))))

    # -- the loops -----------------------------------------------------------

    def loop_over(self, frame: float):
        """The loop covering a frame. Named apart from `loop_at`, the index
        into the list: one name for both was a number being called."""
        for low, high in self.loops:
            if low <= frame < high:
                return (low, high)
        return None

    def loop_here(self):
        return self.loop_over(self.frame)

    def loop_region(self):
        """The loop the numbers on the right are about."""
        if not self.loops:
            return None
        self.loop_at = max(0, min(self.loop_at, len(self.loops) - 1))
        return self.loops[self.loop_at]

    def choose_loop(self, index: int) -> None:
        if self.loops:
            self.loop_at = max(0, min(int(index), len(self.loops) - 1))
            self.changed.emit()

    def set_looping(self, on: bool, by_hand: bool = True) -> None:
        on = bool(on)
        if by_hand:
            # Let go of this loop in particular: the playhead has to be able
            # to leave it without being caught again on the very next tick.
            self.let_go = None if on else self.loop_here()
        if on == self.looping:
            return
        self.looping = on
        self.looping_changed.emit(on)
        self.changed.emit()

    def step(self, was: float, now: float):
        """Where the playhead has to be, having gone from `was` to `now`.

        None when it can stay where it got to. The loop is looked up where the
        playhead WAS, not where it is going: looking it up at the new place
        lets a single tick step over the far edge, and from outside there is
        nothing left to catch it.
        """
        over = self.loop_over(was)
        if self.let_go is not None and over != self.let_go:
            self.let_go = None           # clear of it; it may catch us again
        holding = over if (self.looping and over is not None) else None
        if holding is None:
            for low, high in self.loops:
                if was < low <= now and (low, high) != self.let_go:
                    holding = self.caught = (low, high)
                    self.set_looping(True, by_hand=False)
                    break
        if holding is None:
            return None
        low, high = holding
        if now >= high or now < low:
            return low + (now - high) % max(1, high - low)
        return None

    # -- the clip ------------------------------------------------------------

    def pick(self, clip) -> None:
        if clip is not self.chosen:
            self.chosen = clip
            self.changed.emit()

    def to_edge(self, end: bool) -> None:
        clip = self.chosen
        if clip is None:
            return
        self.go_to(clip.last - 1 if end else clip.first)

    # -- the editor ----------------------------------------------------------

    def set_editing(self, on: bool) -> None:
        on = bool(on)
        if on != self.editing:
            self.editing = on
            self.editing_changed.emit(on)
            self.changed.emit()

    def set_locked(self, on: bool) -> None:
        on = bool(on)
        if on != self.locked:
            self.locked = on
            self.locked_changed.emit(on)
            self.changed.emit()

    def begin(self, label: str, key=None) -> bool:
        """Say a change is coming. False, and nothing changes, when the
        editor is off."""
        if not self.editing:
            return False
        self.about_to_change.emit(label, key)
        return True

    def done(self, what) -> None:
        self.edited.emit(set(what))
        self.changed.emit()

    def cancel(self) -> None:
        self.unchanged.emit()

    def say(self, words: str) -> None:
        self.said.emit(words)

    def edges(self, leaving=None) -> list:
        """Where a moving clip meets something: the start, the playhead, and
        both ends of every other clip."""
        found = [0, int(self.frame)]
        for other in self.show.clips:
            if other is leaving:
                continue
            found += [other.first] if other.kind == "cue" \
                else [other.first, other.last - other.tail]
        return found

    def snap(self, clip, wanted: int) -> int:
        """Where the clip's start goes, having been asked for `wanted`: onto
        an edge if its start or its end comes within a few pixels of one."""
        close = SNAP / max(1e-9, self.axis.scale)
        head = clip.first - clip.tx
        tail = (clip.last - clip.tail) - clip.tx if clip.kind != "cue" else 0
        best, gap = int(wanted), close
        for edge in self.edges(leaving=clip):
            for offset in {head, tail}:
                apart = abs(wanted + offset - edge)
                if apart < gap:
                    best, gap = int(edge - offset), apart
        return max(0, best)

    def set_field(self, clip, key: str, value: int) -> None:
        """A number typed into the inspector, into the clip."""
        if clip is None or int(getattr(clip, key, 0) or 0) == int(value):
            return
        if not self.begin(f"поле {key}", key=(clip.ident, key)):
            return
        was_row = clip.row
        setattr(clip, key, int(value))
        self.done({was_row})

    def put_clip(self, right: bool) -> None:
        """The chosen clip's start to the playhead ([...]), or its end."""
        clip = self.chosen
        if clip is None or not self.begin("клип к плейхеду"):
            return
        at = int(self.frame)
        if right or clip.kind == "cue":
            clip.tx = max(0, at - (clip.first - clip.tx))
        else:
            clip.tx = max(0, at - (clip.last - clip.tail - clip.tx))
        self.done({clip.row})

    def delete_chosen(self) -> None:
        clip = self.chosen
        if clip is None or not self.begin("удалить клип"):
            return
        self.show.clips.remove(clip)
        self.chosen = None
        self.done({clip.row})

    def add_cue(self) -> None:
        """A cue at the playhead, saying what the one before it said: shows
        send the same few addresses over and over."""
        if not self.begin("кью"):
            return
        earlier = [one for one in self.show.clips
                   if one.kind == "cue" and one.tx <= self.frame]
        like = max(earlier, key=lambda one: one.tx) if earlier else None
        ident = max([one.ident for one in self.show.clips] or [0]) + 1
        cue = showfile.Clip(kind="cue", row="Cue", level=0, path="",
                            tx=int(self.frame), ident=ident,
                            universe=like.universe if like else 0,
                            channel=like.channel if like else 1,
                            value=like.value if like else 255)
        self.show.clips.append(cue)
        self.chosen = cue
        self.done({"Cue"})

    # -- editing the loops ---------------------------------------------------

    def _sorted(self, keep) -> None:
        self.loops.sort()
        self.loop_at = self.loops.index(keep) if keep in self.loops else 0

    def put_loop(self, low: int, high: int) -> None:
        """The chosen loop's range, with no bracket of its own: for a drag,
        which has begun already and ends on release."""
        if not self.loops:
            return
        low = max(0, min(int(low), self.show.length - 1))
        high = max(low + 1, min(int(high), self.show.length))
        self.loops[self.loop_at] = (low, high)
        self._sorted((low, high))
        self.changed.emit()

    def set_loop_range(self, low: int, high: int) -> None:
        """Exact frames, typed."""
        picked = self.loop_region()
        if picked is None or (int(low), int(high)) == picked:
            return
        if not self.begin("луп числами", key=("loop", self.loop_at)):
            return
        self.put_loop(low, high)
        self.done({"loops"})

    def add_loop(self, low: int | None = None, high: int | None = None) -> None:
        if not self.begin("новый луп"):
            return
        low = int(self.frame) if low is None else int(low)
        high = min(self.show.length, low + int(showfile.FPS) * 5) \
            if high is None else int(high)
        wanted = (low, max(low + 1, high))
        self.loops.append(wanted)
        self._sorted(wanted)
        self.done({"loops"})

    def drop_loop(self) -> None:
        if not self.loops or not self.begin("убрать луп"):
            return
        self.loops.pop(self.loop_at)
        self.loop_at = max(0, min(self.loop_at, len(self.loops) - 1))
        self.done({"loops"})

    def loop_the_clip(self) -> None:
        """A loop over the whole of the chosen clip, and holding."""
        clip = self.chosen
        if clip is None or clip.kind == "cue" or not self.begin("луп по клипу"):
            return
        wanted = (clip.first, max(clip.first + 1, clip.last - clip.tail))
        if self.loops:
            self.loops[self.loop_at] = wanted
        else:
            self.loops.append(wanted)
        self._sorted(wanted)
        self.done({"loops"})
        self.let_go = None
        self.set_looping(True, by_hand=False)
        self.go_to(wanted[0])

    def loop_from_file(self) -> None:
        if list(self.loops) == list(self.file_loops) \
                or not self.begin("лупы из файла"):
            return
        self.loops[:] = [tuple(one) for one in self.file_loops]
        self.loop_at = 0
        self.done({"loops"})


# -- the strips --------------------------------------------------------------

def _clock(frame: float) -> str:
    """mm:ss:ff, for the playhead's flag -- the design's short timecode."""
    return showfile.timecode(frame)[3:]


def _span(first: int, last: int) -> str:
    """How long a clip runs, as m:ss.cc."""
    seconds = max(0, last - first) / showfile.FPS
    return f"{int(seconds // 60)}:{seconds % 60:05.2f}"


def _frames_fit(axis) -> bool:
    """Zoomed in far enough that a frame is a cell of its own."""
    return axis.scale >= 6.0


class _Strip(QWidget):
    """What every strip does with the mouse that is not its own business."""

    def __init__(self, view: ShowView) -> None:
        super().__init__()
        self.view = view
        self.panning = None
        self._drawn_at = None
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        view.changed.connect(self.update)
        view.moved.connect(self._follow)

    def _follow(self) -> None:
        """Redrawn when the playhead has moved a pixel, not every frame: on
        the whole show a pixel is about sixty frames, a second of playing."""
        x = int(self.axis.x_of(self.view.frame))
        if x != self._drawn_at:
            self._drawn_at = x
            self.update()

    @property
    def axis(self) -> Axis:
        return self.view.axis

    def wheelEvent(self, event) -> None:       # noqa: N802 -- Qt naming
        steps = event.angleDelta().y() / 120.0
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.axis.slide(steps * 80)
        else:
            self.axis.zoom_at(event.position().x(), 1.25 ** steps)
        self.view.changed.emit()

    def _common_press(self, event) -> bool:
        """Middle and right. True when the press was one of them."""
        x = event.position().x()
        if event.button() == Qt.MouseButton.MiddleButton:
            self.view.go_to(int(self.axis.frame_of(x)))
            return True
        if event.button() == Qt.MouseButton.RightButton:
            self.panning = x
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return True
        return False

    def _common_move(self, event) -> bool:
        if self.panning is None:
            return False
        x = event.position().x()
        self.axis.slide(x - self.panning)
        self.panning = x
        self.view.changed.emit()
        return True

    def _common_release(self) -> None:
        if self.panning is not None:
            self.panning = None
            self.unsetCursor()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._common_release()

    def draw_playhead(self, brush: QPainter, top: int = 0) -> None:
        """A white line with a dark edge, seen over any clip. Zoomed in to
        frames it is a cell a frame wide, lit, with the line on its left."""
        x = self.axis.x_of(int(self.view.frame))
        if _frames_fit(self.axis):
            brush.fillRect(QRectF(x, top, self.axis.scale, self.height() - top),
                           QColor(255, 255, 255, 40))
        brush.fillRect(QRectF(x - 2, top, 4, self.height() - top),
                       QColor(0, 0, 0, 215))
        brush.fillRect(QRectF(x - 1, top, 2, self.height() - top),
                       QColor("#ffffff"))


class Ruler(_Strip):
    """The time axis, the only place the playhead is dragged -- and at its
    head the LOOP switch, with the range of the loop the playhead is in."""

    HEIGHT = 32

    def __init__(self, view: ShowView) -> None:
        super().__init__(view)
        self.setObjectName("qa_show_ruler")
        self.setFixedHeight(self.HEIGHT)
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self.holding = False

        self.switch = QPushButton("LOOP", self)
        self.switch.setObjectName("qa_show_loop")
        self.switch.setCheckable(True)
        self.switch.setGeometry(12, 6, 46, 20)
        self.switch.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.switch.setCursor(Qt.CursorShape.ArrowCursor)
        self.switch.setToolTip(
            "Загорается сам, когда плейхед въезжает в луп слева: с этого "
            "момента луп держит. Нажми, чтобы отпустить — плейхед поедет "
            "дальше, до следующего лупа (L).")
        self.switch.setStyleSheet(
            f"QPushButton {{ font-family:{MONO}; font-size:10.5px; padding:0px;"
            f" border:1px solid {theme.GOLD_EDGE}; border-radius:3px;"
            f" color:{theme.GOLD}; background:transparent; }}"
            f"QPushButton:checked {{ background:{theme.GOLD}; color:#1a1405;"
            f" border-color:{theme.GOLD}; }}")
        self.switch.clicked.connect(lambda on: view.set_looping(on))
        view.looping_changed.connect(self._shown)

    def _shown(self, on: bool) -> None:
        self.switch.blockSignals(True)
        self.switch.setChecked(bool(on))
        self.switch.blockSignals(False)

    def _follow(self) -> None:
        self.update()           # the flag says the time, to the frame

    def paintEvent(self, event) -> None:      # noqa: N802
        brush = QPainter(self)
        brush.setRenderHint(QPainter.RenderHint.Antialiasing)
        brush.fillRect(self.rect(), QColor(theme.PANEL))
        brush.setFont(QFont(MONO, 8))
        for seconds in _nice_steps(self.axis):
            x = self.axis.x_of(seconds * showfile.FPS)
            if not HEAD - 10 <= x <= self.width() + 40:
                continue
            brush.setPen(QPen(QColor("#4a4d54")))
            brush.drawLine(int(x), self.height() - 10, int(x), self.height())
            brush.setPen(QPen(QColor(theme.DIM)))
            brush.drawText(int(x) + 5, 15,
                           showfile.timecode(seconds * showfile.FPS))
        # Where the show waits, along the foot of the ruler, in gold.
        here = self.view.loop_here()
        for low, high in self.view.loops:
            left, right = self.axis.x_of(low), self.axis.x_of(high)
            running = self.view.looping and here == (low, high)
            gold = QColor(theme.GOLD)
            gold.setAlpha(230 if running else 120)
            brush.fillRect(QRectF(left, self.height() - 4, max(2, right - left), 4),
                           gold)
        # And the render's range, when it is not all of it.
        span = self.view.render_range
        if span is not None:
            left, right = (self.axis.x_of(one) for one in span)
            brush.fillRect(QRectF(left, self.height() - 8, max(2, right - left), 3),
                           QColor(theme.LINE))
            brush.setPen(QPen(QColor(theme.LINE), 2))
            brush.drawLine(int(left), self.height() - 12, int(left), self.height())
            brush.drawLine(int(right), self.height() - 12, int(right), self.height())
        brush.fillRect(QRect(0, 0, HEAD, self.height()), QColor(theme.PANEL))
        brush.setPen(QPen(QColor(theme.SEAM)))
        brush.drawLine(HEAD, 0, HEAD, self.height())
        brush.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        loop = here or self.view.loop_region()
        if loop is not None:
            brush.setFont(QFont(MONO, 8))
            brush.setPen(QPen(QColor(theme.QUIET)))
            brush.drawText(66, 21, f"{loop[0]}–{loop[1]}")
        self._flag(brush)
        brush.end()

    def _flag(self, brush: QPainter) -> None:
        """The playhead's head -- a triangle, which reads better than the
        redesign's flag and was kept for that -- with the time beside it, and
        at frame zoom the frame as well."""
        frame = int(self.view.frame)
        x = self.axis.x_of(frame)
        if x < HEAD - 50 or x > self.width() + 50:
            return
        white = QColor("#ffffff")
        brush.setFont(QFont(MONO, 8, QFont.Weight.Medium))
        if _frames_fit(self.axis):
            brush.fillRect(QRectF(x, 0, self.axis.scale, self.height()), white)
            said = f"{showfile.timecode(frame)} · кадр {frame}"
            start = x + self.axis.scale + 6
        else:
            said = _clock(frame)
            start = x + 10
        wide = QFontMetrics(brush.font()).horizontalAdvance(said) + 14
        box = QRectF(start, 6, wide, 19)
        if box.right() > self.width() - 4:
            box.moveRight(x - 10)       # against the far end: on the other side
        brush.setPen(Qt.PenStyle.NoPen)
        brush.setBrush(white)
        brush.drawPolygon(QPolygonF([QPointF(x - 6, 2), QPointF(x + 6, 2),
                                     QPointF(x, 12)]))
        brush.drawRoundedRect(box, 4, 4)
        brush.setPen(QPen(QColor("#111111")))
        brush.drawText(box, Qt.AlignmentFlag.AlignCenter, said)

    def mousePressEvent(self, event) -> None:   # noqa: N802
        if self._common_press(event):
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.holding = True
            self.view.go_to(int(self.axis.frame_of(event.position().x())))

    def mouseMoveEvent(self, event) -> None:    # noqa: N802
        if self._common_move(event):
            return
        if self.holding:
            self.view.go_to(int(self.axis.frame_of(event.position().x())))

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self.holding = False
        self._common_release()


class LoopBar(_Strip):
    """The loops, drawn and moved: in the editor, and only there.

    Read only, the loops are shown along the ruler's foot and across the
    lanes; this strip is where they are made. A drag across empty strip is a
    new loop, a drag at either end of the chosen one moves that end, and
    Shift held inside one moves the whole of it. The lock at the far end is
    down to begin with -- the loops out of a show file are the easiest thing
    on it to break -- and the numbers in the column work either way.
    """

    GRIP = 5
    HEIGHT = 18

    def __init__(self, view: ShowView) -> None:
        super().__init__(view)
        self.setObjectName("qa_show_loopbar")
        self.setFixedHeight(self.HEIGHT)
        self.setMouseTracking(True)
        self.holding = None            # low | high | move, while dragging
        self.grabbed = 0
        self.moved_any = False

        self.lock = QPushButton("замок", self)
        self.lock.setObjectName("qa_show_lock")
        self.lock.setCheckable(True)
        self.lock.setChecked(True)
        self.lock.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.lock.setToolTip(
            "Запретить рисовать лупы мышью (K). Числами справа их всё равно "
            "можно поправить — на 22 минутах один пиксель это 56 кадров.")
        self.lock.setStyleSheet(
            f"QPushButton {{ font-size:11px; padding:0px 6px; border:none;"
            f" color:{theme.QUIET}; background:transparent; }}"
            f"QPushButton:checked {{ color:{theme.GOLD}; background:transparent; }}")
        self.lock.clicked.connect(lambda on: view.set_locked(on))
        view.locked_changed.connect(self._locked)
        self.setVisible(False)
        view.editing_changed.connect(self.setVisible)

    def _locked(self, on: bool) -> None:
        self.lock.blockSignals(True)
        self.lock.setChecked(bool(on))
        self.lock.blockSignals(False)
        self.lock.setText("замок" if on else "открыто")

    def resizeEvent(self, event) -> None:      # noqa: N802
        self.lock.setGeometry(self.width() - 64, 0, 60, self.height())
        super().resizeEvent(event)

    @property
    def drawing(self) -> bool:
        return self.view.editing and not self.view.locked

    def paintEvent(self, event) -> None:      # noqa: N802
        brush = QPainter(self)
        brush.fillRect(self.rect(), QColor(theme.GOLD_BG))
        brush.setFont(QFont(MONO, 8))
        brush.setPen(QPen(QColor(theme.QUIET)))
        brush.drawText(12, 13, "лупы")
        brush.setPen(QPen(QColor(theme.SEAM)))
        brush.drawLine(HEAD, 0, HEAD, self.height())
        right_end = self.width() - 66
        brush.setClipRect(QRect(HEAD, 0, right_end - HEAD, self.height()))
        here = self.view.loop_here()
        for index, (low, high) in enumerate(self.view.loops):
            left, right = int(self.axis.x_of(low)), int(self.axis.x_of(high))
            running = self.view.looping and here == (low, high)
            picked = index == self.view.loop_at
            brush.fillRect(
                QRect(left, 4, max(3, right - left), self.height() - 8),
                QColor(theme.GOLD) if running
                else QColor("#b89a5a") if picked else QColor(theme.GOLD_EDGE))
            for x in (left, right):
                brush.fillRect(QRect(x - 1, 0, 3, self.height()),
                               QColor("#f3dfad") if picked
                               else QColor(theme.GOLD_EDGE))
            if self.view.locked:
                brush.setPen(QPen(QColor(0, 0, 0, 80)))
                for x in range(left, right, 5):
                    brush.drawLine(x, 4, x - self.height(), self.height() - 4)
        brush.end()

    def _loop_at_x(self, x: float):
        at = self.axis.frame_of(x)
        near = 4 / max(1e-9, self.axis.scale)
        for index, (low, high) in enumerate(self.view.loops):
            if low - near <= at <= high + near:
                return index
        return None

    def _grip(self, x: float):
        picked = self.view.loop_region()
        if picked is None:
            return None
        low, high = (int(self.axis.x_of(one)) for one in picked)
        if abs(x - low) <= self.GRIP:
            return "low"
        if abs(x - high) <= self.GRIP:
            return "high"
        return None

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._common_press(event):
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        x = event.position().x()
        at = int(self.axis.frame_of(x))
        index = self._loop_at_x(x)
        if index is not None:
            self.view.choose_loop(index)
        if not self.drawing:
            if self.view.editing and index is None:
                self.view.say("лупы заперты — «замок» справа на полосе или K")
            return
        grip = self._grip(x)
        sliding = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if grip is None and index is not None and not sliding:
            return                          # a click on a loop chooses it
        if not self.view.begin("луп мышью"):
            return
        self.moved_any = False
        if grip is not None:
            self.holding = grip
        elif sliding and index is not None:
            self.holding = "move"
            self.grabbed = at - self.view.loops[index][0]
        else:
            # Empty strip: a loop of its own, drawn from here.
            self.view.loops.append((at, at + 1))
            self.view._sorted((at, at + 1))
            self.holding = "high"
            self.moved_any = True
        self.view.changed.emit()

    def mouseMoveEvent(self, event) -> None:   # noqa: N802
        if self._common_move(event):
            return
        x = event.position().x()
        if self.holding is None:
            if not self.drawing:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            else:
                self.setCursor(Qt.CursorShape.SizeHorCursor
                               if self._grip(x) else Qt.CursorShape.CrossCursor)
            return
        at = int(self.axis.frame_of(x))
        low, high = self.view.loop_region() or (0, 1)
        if self.holding == "low":
            low = min(at, high - 1)
        elif self.holding == "high":
            high = max(at, low + 1)
        else:
            span = high - low
            low = max(0, at - self.grabbed)
            high = low + span
        self.view.put_loop(low, high)
        self.moved_any = True

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._common_release()
        if self.holding is None:
            return
        self.holding = None
        if self.moved_any:
            self.view.done({"loops"})
        else:
            self.view.cancel()


class Tracks(_Strip):
    """A row per level, per screen. In the editor: dragged, and dropped on.

    A level with clips on it is 26 pixels, a cue lane 20, a level with
    nothing on it 8 -- 16 in the editor, where it is somewhere to drop a
    file. So the dozen lanes of a show take what they use and the picture
    gets the rest.
    """

    LANE = 26            # a level with clips on it
    CUE = 20
    EMPTY = 8
    EMPTY_EDITING = 16

    def __init__(self, view: ShowView) -> None:
        super().__init__(view)
        self.setObjectName("qa_show_tracks")
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.dragging = None
        self.grabbed = 0
        self.began_at = None           # (tx, level) the drag started from
        self.landing = None            # (row, level, frame) under a file
        view.changed.connect(self._fit_height)
        view.editing_changed.connect(lambda _on: self._fit_height())
        self._fit_height()

    def resizeEvent(self, event) -> None:      # noqa: N802
        was = self.axis.fitted
        self.axis.width = max(1, self.width() - HEAD)
        if was:
            self.axis.fit()
        self.axis.clamp()
        super().resizeEvent(event)

    def _used(self) -> set:
        return {(one.row, min(one.level, LEVELS[one.row] - 1))
                for one in self.view.show.clips}

    def lanes(self) -> list:
        """(row, level, top, height) of every lane, top to bottom."""
        used = self._used()
        empty = self.EMPTY_EDITING if self.view.editing else self.EMPTY
        out, y = [], 0
        for row in ROWS:
            for level in range(LEVELS[row]):
                if row == "Cue":
                    tall = self.CUE if (row, level) in used else empty
                else:
                    tall = self.LANE if (row, level) in used else empty
                out.append((row, level, y, tall))
                y += tall + 1
        return out

    def wanted_height(self) -> int:
        lanes = self.lanes()
        row, level, top, tall = lanes[-1]
        return top + tall + 1

    def _fit_height(self) -> None:
        wanted = self.wanted_height()
        if self.height() != wanted:
            self.setFixedHeight(wanted)

    def lane_at(self, y: float):
        """(row, level) of the lane under a height, or None between rows."""
        for row, level, top, tall in self.lanes():
            if top <= y < top + tall + 1:
                return row, level
        return None

    def band_of(self, clip):
        for row, level, top, tall in self.lanes():
            if clip.kind == "cue":
                if row == "Cue":
                    return QRect(int(self.axis.x_of(clip.tx)) - 4, top + 1,
                                 9, max(4, tall - 2))
                continue
            if row == clip.row and level == min(clip.level, LEVELS[row] - 1):
                left = self.axis.x_of(clip.first)
                ends = min(clip.last, self.view.show.length)
                width = max(3.0, (ends - clip.first) * self.axis.scale)
                if left + width < HEAD or left > self.width():
                    return None
                return QRect(int(left), top + 2, int(width), max(4, tall - 4))
        return None

    def clip_under(self, where: QPoint):
        for clip in reversed(self.view.show.clips):
            band = self.band_of(clip)
            if band is not None and band.adjusted(-2, -1, 2, 1).contains(where):
                return clip
        return None

    # -- the mouse -------------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._common_press(event):
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        where = event.position().toPoint()
        clip = self.clip_under(where)
        self.view.pick(clip)
        if clip is not None and self.view.editing:
            if self.view.begin("перенос клипа"):
                self.dragging = clip
                self.grabbed = int(self.axis.frame_of(where.x())) - clip.tx
                self.began_at = (clip.tx, clip.level)

    def mouseMoveEvent(self, event) -> None:   # noqa: N802
        if self._common_move(event):
            return
        where = event.position().toPoint()
        clip = self.dragging
        if clip is None:
            under = self.clip_under(where)
            self.setToolTip(_says(under) if under is not None else "")
            return
        wanted = max(0, int(self.axis.frame_of(where.x())) - self.grabbed)
        loose = bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)
        clip.tx = wanted if loose else self.view.snap(clip, wanted)
        lane = self.lane_at(where.y())
        if lane is not None and lane[0] == clip.row:
            clip.level = lane[1]
        self.view.changed.emit()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._common_release()
        clip, self.dragging = self.dragging, None
        if clip is None:
            return
        if (clip.tx, clip.level) != self.began_at:
            self.view.done({clip.row})
        else:
            self.view.cancel()

    # -- files dropped on --------------------------------------------------------

    @staticmethod
    def _files(event) -> list:
        data = event.mimeData()
        if not data.hasUrls():
            return []
        return [one.toLocalFile() for one in data.urls() if one.isLocalFile()]

    def _landing(self, event):
        lane = self.lane_at(event.position().y())
        files = self._files(event)
        if lane is None or not files:
            return None
        row, level = lane
        if not all(row_takes(row, one) for one in files):
            return None
        frame = max(0, int(self.axis.frame_of(event.position().x())))
        return row, level, frame

    def dragEnterEvent(self, event) -> None:   # noqa: N802
        if self.view.editing and self._files(event):
            event.acceptProposedAction()
        elif self._files(event):
            self.view.say("бросать файлы на дорожки — в редакторе")

    def dragMoveEvent(self, event) -> None:    # noqa: N802
        self.landing = self._landing(event) if self.view.editing else None
        if self.landing is not None:
            event.acceptProposedAction()
        else:
            event.ignore()
        self.update()

    def dragLeaveEvent(self, event) -> None:   # noqa: N802
        self.landing = None
        self.update()

    def dropEvent(self, event) -> None:        # noqa: N802
        landing = self._landing(event) if self.view.editing else None
        self.landing = None
        self.update()
        if landing is None:
            files = self._files(event)
            lane = self.lane_at(event.position().y())
            if files and lane is not None:
                self.view.say(f"{lane[0]} не берёт {Path(files[0]).suffix} "
                              "— ролики и картинки на экраны, .wav на Sound, "
                              ".json на Kinetic")
            return
        event.acceptProposedAction()
        row, level, frame = landing
        self.view.dropped.emit(self._files(event), row, level, frame)

    # -- drawing -------------------------------------------------------------

    @staticmethod
    def _fade(brush: QPainter, band: QRect, wide: float, head: bool) -> None:
        """A fade as the design draws it: the corner above the ramp darkened,
        the ramp itself a white diagonal across the clip's whole height."""
        wide = min(wide, float(band.width()))
        if wide < 2:
            return
        top, bottom = float(band.top()), float(band.bottom() + 1)
        if head:
            left = float(band.left())
            corner = [QPointF(left, top), QPointF(left + wide, top),
                      QPointF(left, bottom)]
            ramp = (QPointF(left, bottom), QPointF(left + wide, top))
        else:
            right = float(band.right() + 1)
            corner = [QPointF(right - wide, top), QPointF(right, top),
                      QPointF(right, bottom)]
            ramp = (QPointF(right - wide, top), QPointF(right, bottom))
        brush.setPen(Qt.PenStyle.NoPen)
        brush.setBrush(QColor(0, 0, 0, 140))
        brush.drawPolygon(QPolygonF(corner))
        brush.setPen(QPen(QColor(255, 255, 255, 230), 1.2))
        brush.drawLine(*ramp)

    def draw_clip(self, brush: QPainter, clip, band: QRect) -> None:
        colours = theme.clip_colours(clip.row)
        chosen = clip is self.view.chosen
        rect = QRectF(band)
        brush.setRenderHint(QPainter.RenderHint.Antialiasing)
        if clip.missing:
            brush.setPen(QPen(QColor(theme.ERROR), 1, Qt.PenStyle.DashLine))
            brush.setBrush(QColor(theme.RAISED))
            brush.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 2, 2)
        else:
            brush.setPen(QPen(QColor(colours["bd"]), 1))
            brush.setBrush(QColor(colours["bg"]))
            brush.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 2, 2)
            brush.fillRect(QRectF(rect.left(), rect.top(), 2, rect.height()),
                           QColor(colours["edge"]))
        brush.save()
        brush.setClipRect(band)
        # The motor is still carrying out its last command after the file has
        # run out, so the clip goes on -- hatched, because nothing is read
        # there: the screens are only still arriving.
        tail_px = int(clip.tail * self.axis.scale) if clip.tail else 0
        if tail_px >= 1:
            brush.setPen(QPen(QColor(255, 255, 255, 45)))
            for x in range(band.right() - tail_px, band.right() + 1, 4):
                brush.drawLine(x, band.top(), x - band.height(), band.bottom())
            brush.setPen(QPen(QColor(colours["meta"]), 1, Qt.PenStyle.DashLine))
            brush.drawLine(band.right() - tail_px, band.top(),
                           band.right() - tail_px, band.bottom())
        faded = band.adjusted(0, 0, -tail_px, 0)
        if clip.fade_end:
            self._fade(brush, faded, abs(clip.fade_end) * self.axis.scale,
                       head=False)
        if clip.fade_start:
            self._fade(brush, band, abs(clip.fade_start) * self.axis.scale,
                       head=True)
        if clip.crop_end:
            brush.setPen(QPen(QColor(theme.TEXT), 2))
            brush.drawLine(faded.right(), faded.top() + 1,
                           faded.right(), faded.top() + 4)
            brush.drawLine(faded.right(), faded.bottom() - 4,
                           faded.right(), faded.bottom() - 1)
        # The name, and after it how long and how it ends, on one line.
        room = band.adjusted(8, 0, -6, 0)
        room.setLeft(max(room.left(), HEAD + 4))
        if room.width() > 16 and band.height() >= 12:
            name = clip.name + ("  — нет файла" if clip.missing else "")
            brush.setFont(QFont(theme.ui_family(), 9, QFont.Weight.Medium))
            metrics = QFontMetrics(brush.font())
            brush.setPen(QPen(QColor(theme.QUIET if clip.missing
                                     else colours["fg"])))
            said = metrics.elidedText(name, Qt.TextElideMode.ElideMiddle,
                                      room.width())
            brush.drawText(room, Qt.AlignmentFlag.AlignVCenter, said)
            used = metrics.horizontalAdvance(said) + 10
            rest = room.adjusted(used, 0, 0, 0)
            if rest.width() > 40 and not clip.missing:
                brush.setFont(QFont(MONO, 8))
                brush.setPen(QPen(QColor(colours["meta"])))
                brush.drawText(rest, Qt.AlignmentFlag.AlignVCenter,
                               QFontMetrics(brush.font()).elidedText(
                                   _meta(clip), Qt.TextElideMode.ElideRight,
                                   rest.width()))
        brush.restore()
        if chosen:
            brush.setPen(QPen(QColor("#ffffff"), 2))
            brush.setBrush(Qt.BrushStyle.NoBrush)
            brush.drawRoundedRect(rect.adjusted(-1.5, -1.5, 1.5, 1.5), 3, 3)

    def draw_overlaps(self, brush: QPainter) -> None:
        """Two clips on one level at once: the engine plays one of them, so
        where they cross is marked for somebody to sort out."""
        for row, level, top, tall in self.lanes():
            if row == "Cue":
                continue
            track = [one for one in self.view.show.on(row)
                     if min(one.level, LEVELS[row] - 1) == level]
            track.sort(key=lambda one: one.first)
            for before, after in zip(track, track[1:]):
                if after.first < before.last:
                    left = int(self.axis.x_of(after.first))
                    right = int(self.axis.x_of(min(before.last, after.last)))
                    brush.fillRect(QRect(left, top, max(2, right - left), 3),
                                   QColor(theme.WARN))

    def draw_cues(self, brush: QPainter, top: int, tall: int) -> None:
        for clip in self.view.show.clips:
            if clip.kind != "cue":
                continue
            x = int(self.axis.x_of(clip.tx))
            chosen = clip is self.view.chosen
            brush.setPen(QPen(QColor("#ffffff" if chosen else theme.SECOND),
                              3 if chosen else 1))
            brush.drawLine(x, top + 1, x, top + tall - 1)
            if tall >= 12 and self.axis.scale > 0.012:
                brush.setFont(QFont(MONO, 8))
                brush.setPen(QPen(QColor("#ffffff" if chosen else theme.DIM)))
                brush.drawText(x + 5, top + tall - 6,
                               f"u{clip.universe}·ch{clip.channel}·v{clip.value}")

    def draw_loops(self, brush: QPainter) -> None:
        here = self.view.loop_here()
        for low, high in self.view.loops:
            left, right = int(self.axis.x_of(low)), int(self.axis.x_of(high))
            running = self.view.looping and here == (low, high)
            gold = QColor(theme.GOLD)
            gold.setAlpha(34 if running else 14)
            brush.fillRect(QRect(left, 0, max(2, right - left), self.height()),
                           gold)
            gold.setAlpha(200 if running else 90)
            brush.setPen(QPen(gold, 1))
            brush.drawLine(left, 0, left, self.height())
            brush.drawLine(right, 0, right, self.height())

    def paintEvent(self, event) -> None:       # noqa: N802
        brush = QPainter(self)
        brush.fillRect(self.rect(), QColor(theme.LANE_A))
        heads = QFont(theme.ui_family(), 9, QFont.Weight.DemiBold)
        levels = QFont(MONO, 8)
        for row, level, top, tall in self.lanes():
            lit = (self.landing is not None
                   and self.landing[:2] == (row, level))
            brush.fillRect(QRect(HEAD, top, self.width() - HEAD, tall),
                           QColor(theme.ACCENT) if lit
                           else QColor(theme.LANE[row]))
            brush.fillRect(QRect(0, top + tall, self.width(), 1),
                           QColor(theme.LANE_EDGE))
            brush.fillRect(QRect(0, top, HEAD, tall), QColor(theme.PANEL))
            brush.fillRect(QRectF(12, top + 2, 3, max(1, tall - 4)),
                           QColor(HUE[row]))
            if tall >= 12:
                first = level == 0
                brush.setFont(heads)
                brush.setPen(QPen(QColor(theme.TEXT if first else theme.DIM)))
                brush.drawText(QRect(22, top, 80, tall),
                               Qt.AlignmentFlag.AlignVCenter, row)
                if LEVELS[row] > 1:
                    label = str(level + 1) if row == "Sound" else f"L{level}"
                    brush.setFont(levels)
                    brush.setPen(QPen(QColor(theme.QUIET)))
                    brush.drawText(QRect(22 + QFontMetrics(heads).horizontalAdvance(row)
                                         + 6, top, 40, tall),
                                   Qt.AlignmentFlag.AlignVCenter, label)
        brush.setPen(QPen(QColor(theme.SEAM)))
        brush.drawLine(HEAD, 0, HEAD, self.height())
        brush.setClipRect(QRect(HEAD + 1, 0, self.width() - HEAD, self.height()))
        self.draw_loops(brush)
        for clip in self.view.show.clips:
            if clip.kind == "cue":
                continue
            band = self.band_of(clip)
            if band is not None:
                self.draw_clip(brush, clip, band)
        self.draw_overlaps(brush)
        for row, _level, top, tall in self.lanes():
            if row == "Cue":
                self.draw_cues(brush, top, tall)
        if self.landing is not None:
            x = int(self.axis.x_of(self.landing[2]))
            brush.setPen(QPen(QColor(theme.META), 2))
            brush.drawLine(x, 0, x, self.height())
        self.draw_playhead(brush)
        brush.end()


def _meta(clip) -> str:
    """The second half of a clip's line: where it runs, how long, its fade."""
    ends = clip.last - clip.tail
    said = f"{_clock(clip.first)} → {_clock(ends)} · {_span(clip.first, ends)}"
    if clip.fade_end:
        said += f" · фейд {abs(clip.fade_end) / showfile.FPS:.1f} с"
    elif clip.fade_start:
        said += f" · фейд вход {abs(clip.fade_start) / showfile.FPS:.1f} с"
    return said


def _says(clip) -> str:
    """One line about a clip, for its tooltip."""
    if clip.kind == "cue":
        return (f"кью  кадр {clip.tx}  universe {clip.universe}  "
                f"channel {clip.channel}  value {clip.value}")
    said = f"{clip.name}\n{clip.row} L{clip.level}   {clip.first}..{clip.last}"
    if clip.missing:
        said += "\nфайла нет на этой машине"
    return said


class TimelinePane(QWidget):
    """Everything under the picture: the transport's line, then the strips.

    The line is the show's clock -- the timecode large, the frame beside it,
    what is on the screens -- and the window's transport buttons come to
    stand at its head in the show mode, with Смотреть по at its end.
    """

    def __init__(self, view: ShowView) -> None:
        super().__init__()
        self.setObjectName("qa_show_pane")
        self.view = view
        whole = QVBoxLayout(self)
        whole.setContentsMargins(0, 0, 0, 0)
        whole.setSpacing(0)

        self.head = QWidget()
        self.head.setObjectName("qa_show_head")
        self.head.setFixedHeight(52)
        self.head.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.head.setStyleSheet(
            f"#qa_show_head {{ background:{theme.PANEL};"
            f" border-top:1px solid {theme.SEAM}; border-bottom:1px solid {theme.SEAM}; }}")
        line = QHBoxLayout(self.head)
        line.setContentsMargins(16, 0, 16, 0)
        line.setSpacing(14)
        self.header = line
        self.clock = QLabel()
        self.clock.setObjectName("qa_show_clock")
        self.clock.setFont(theme.mono(15, bold=True))
        self.clock.setTextFormat(Qt.TextFormat.PlainText)
        line.addWidget(self.clock)
        self.frames = QLabel()
        self.frames.setObjectName("qa_show_frames")
        self.frames.setFont(theme.mono(9))
        self.frames.setStyleSheet(f"color:{theme.QUIET};")
        line.addWidget(self.frames)
        self.state = QLabel()
        self.state.setObjectName("qa_show_state")
        self.state.setFont(theme.ui(9))
        self.state.setStyleSheet(f"color:{theme.QUIET};")
        self.state.setTextFormat(Qt.TextFormat.PlainText)
        # Ignored across: this line lists whatever is on the screens, and a
        # label is otherwise as wide as its text -- the window grew by the
        # width of a clip's name every time one more came on during playing.
        self.state.setSizePolicy(QSizePolicy.Policy.Ignored,
                                 QSizePolicy.Policy.Preferred)
        line.addWidget(self.state, 3)
        # What the editor has to say about the last thing tried: a file a row
        # would not take, the loops being locked.
        self.note = QLabel()
        self.note.setObjectName("qa_show_note")
        self.note.setFont(theme.ui(9))
        self.note.setStyleSheet(f"color:{theme.WARN};")
        self.note.setTextFormat(Qt.TextFormat.PlainText)
        self.note.setAlignment(Qt.AlignmentFlag.AlignRight
                               | Qt.AlignmentFlag.AlignVCenter)
        self.note.setSizePolicy(QSizePolicy.Policy.Ignored,
                                QSizePolicy.Policy.Preferred)
        line.addWidget(self.note, 2)
        whole.addWidget(self.head)

        self.ruler = Ruler(view)
        whole.addWidget(self.ruler)
        self.loopbar = LoopBar(view)
        whole.addWidget(self.loopbar)
        self.tracks = Tracks(view)
        # Scrolled rather than squeezed, so the boundary above can give the
        # picture its height back on a small monitor.
        scroller = QScrollArea()
        scroller.setObjectName("qa_show_scroll")
        scroller.setWidget(self.tracks)
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QScrollArea.Shape.NoFrame)
        scroller.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroller.setMinimumHeight(60)
        scroller.setStyleSheet(f"QScrollArea {{ background:{theme.LANE_A}; }}")
        whole.addWidget(scroller, 1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        self._said = None
        view.changed.connect(self.refresh)
        view.moved.connect(self.refresh)
        view.said.connect(self.note.setText)

    def wanted_height(self) -> int:
        return (self.tracks.wanted_height() + Ruler.HEIGHT + 52
                + (LoopBar.HEIGHT if self.view.editing else 0) + 4)

    def refresh(self) -> None:
        view = self.view
        at = int(view.frame)
        live = view.show.live_at(at)
        here = view.loop_here()
        clock = showfile.timecode(at)
        frames = f"кадр {at} из {view.show.length}"
        said = (("В ЛУПЕ   " if here is not None and view.looping else "")
                + "на экранах: "
                + ("  ·  ".join(f"{one.row} L{one.level} {one.name[:24]}"
                                for one in live) or "ничего"))
        if (clock, frames, said) != self._said:
            self._said = (clock, frames, said)
            self.clock.setText(clock)
            self.frames.setText(frames)
            self.state.setText(said)


# -- the right-hand columns --------------------------------------------------

def _number(lowest: int, highest: int, name: str) -> QSpinBox:
    field = QSpinBox()
    field.setObjectName(name)
    field.setRange(lowest, highest)
    field.setKeyboardTracking(False)
    field.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
    field.setAlignment(Qt.AlignmentFlag.AlignRight)
    field.setMinimumWidth(78)
    return field


def _writable(field: QSpinBox, on: bool) -> None:
    field.setReadOnly(not on)
    field.setButtonSymbols(QSpinBox.ButtonSymbols.UpDownArrows if on
                           else QSpinBox.ButtonSymbols.NoButtons)


def _boxed(name: str) -> QLabel:
    """A value that is shown and not typed, in the same box as one that is."""
    field = QLabel("—")
    field.setObjectName(name)
    field.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    field.setMinimumWidth(78)
    field.setStyleSheet(
        f"QLabel {{ background:{theme.SUNKEN}; border:1px solid {theme.EDGE};"
        f" border-radius:4px; padding:3px 8px; font-family:{MONO}; font-size:12px; }}")
    return field


def _small_button(text: str, name: str, hint: str) -> QPushButton:
    one = QPushButton(text)
    one.setObjectName(name)
    one.setToolTip(hint)
    one.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    one.setStyleSheet("QPushButton { padding:3px 9px; font-size:12px; }")
    return one


class LoopPanel(QWidget):
    """The loops in numbers: on 22 minutes a pixel is 56 frames."""

    def __init__(self, view: ShowView) -> None:
        super().__init__()
        self.setObjectName("qa_show_loops")
        self.view = view
        whole = QVBoxLayout(self)
        whole.setContentsMargins(0, 10, 0, 0)
        whole.setSpacing(8)
        top = QHBoxLayout()
        title = QLabel("Лупы")
        title.setFont(theme.heading())
        top.addWidget(title)
        top.addStretch(1)
        self.says = QLabel()
        self.says.setObjectName("qa_show_loop_says")
        self.says.setFont(theme.mono(9))
        self.says.setStyleSheet(f"color:{theme.GOLD};")
        top.addWidget(self.says)
        whole.addLayout(top)

        frames = QHBoxLayout()
        frames.setSpacing(6)
        frames.addWidget(QLabel("с"))
        self.low = _number(0, 10_000_000, "qa_show_loop_low")
        frames.addWidget(self.low, 1)
        frames.addWidget(QLabel("по"))
        self.high = _number(0, 10_000_000, "qa_show_loop_high")
        frames.addWidget(self.high, 1)
        whole.addLayout(frames)
        self.low.valueChanged.connect(self._typed)
        self.high.valueChanged.connect(self._typed)

        self.buttons = QWidget()
        line = QHBoxLayout(self.buttons)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(6)
        for text, what, hint, name in (
                ("+", view.add_loop, "Ещё один луп с того кадра, где плейхед.",
                 "qa_show_loop_add"),
                ("−", view.drop_loop, "Убрать выбранный луп.",
                 "qa_show_loop_drop"),
                ("по клипу", view.loop_the_clip,
                 "Луп на весь выбранный клип, и держать (Shift+L).",
                 "qa_show_loop_clip"),
                ("из файла", view.loop_from_file,
                 "Вернуть лупы, с которыми шоу открылось.",
                 "qa_show_loop_file")):
            one = _small_button(text, name, hint)
            one.clicked.connect(lambda _=False, act=what: act())
            line.addWidget(one)
        line.addStretch(1)
        whole.addWidget(self.buttons)

        self.frames = QLabel()
        self.frames.setObjectName("qa_show_loop_frames")
        self.frames.setFont(theme.mono(8.5))
        self.frames.setStyleSheet(f"color:{theme.QUIET};")
        self.frames.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        whole.addWidget(self.frames)
        self._saying = False
        view.changed.connect(self.refresh)
        view.moved.connect(self.refresh)
        self.refresh()

    def _typed(self, _value: int = 0) -> None:
        if not self._saying:
            self.view.set_loop_range(self.low.value(), self.high.value())

    def refresh(self) -> None:
        view = self.view
        picked = view.loop_region()
        here = view.loop_here()
        said = "лупов нет"
        if picked is not None:
            said = (f"{view.loop_at + 1} из {len(view.loops)} · "
                    f"{(picked[1] - picked[0]) / showfile.FPS:.1f} с")
        if here is not None:
            said += " · держит" if view.looping else " · отпущен"
        self.says.setText(said)
        self._saying = True
        for field, value in ((self.low, picked[0] if picked else 0),
                             (self.high, picked[1] if picked else 0)):
            _writable(field, view.editing and picked is not None)
            if field.value() != value:
                field.setValue(value)
        self._saying = False
        self.buttons.setVisible(view.editing)
        many = len(view.loops) > 1
        self.frames.setVisible(many)
        self.frames.setText("\n".join(
            f"{'>' if index == view.loop_at else ' '} {index + 1}  "
            f"с {low}  по {high}"
            for index, (low, high) in enumerate(view.loops)))


class Inspector(QWidget):
    """The chosen clip. Shown, and in the editor written to.

    What can be typed is what the show file actually stores: where the clip
    starts, which level it is on, how much is trimmed, how long it fades. The
    rest -- how long the file is, what it comes to, where the motors are still
    moving -- is worked out from those and from the media, so it is shown and
    not offered. A cue is a different animal and gets its own fields.
    """

    # label, key, editable, lowest, highest
    MEDIA = [("Уровень", "level", True, 0, 2),
             ("Кадр начала", "tx", True, 0, 10_000_000),
             ("Подрезка с головы", "crop_start", True, 0, 1_000_000),
             ("Подрезка с хвоста", "crop_end", True, -1_000_000, 0),
             ("Фейд с головы", "fade_start", True, 0, 1_000_000),
             ("Фейд с хвоста", "fade_end", True, -1_000_000, 0),
             ("Длина", "frames", False, 0, 0),
             ("Занимает", "range", False, 0, 0),
             ("Доезд моторов", "tail", False, 0, 0),
             ("Начинается", "at", False, 0, 0)]
    CUE = [("Кадр", "tx", True, 0, 10_000_000),
           ("Время", "range", False, 0, 0),
           ("Universe", "universe", True, 0, 64),
           ("Channel", "channel", True, 1, 512),
           ("Value", "value", True, 0, 255),
           ("Уровень", "level", True, 0, 3)]
    SECONDS = {"tx", "crop_end", "fade_end", "crop_start", "fade_start"}

    def __init__(self, view: ShowView) -> None:
        super().__init__()
        self.setObjectName("qa_show_inspector")
        self.view = view
        self.shown: list = []
        self.body: dict = {}
        self._saying = False
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"#qa_show_inspector {{ background:{theme.SHOWBAR};"
                           f" border-left:1px solid {theme.SEAM}; }}")
        whole = QVBoxLayout(self)
        whole.setContentsMargins(16, 12, 16, 12)
        whole.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.dot = QLabel()
        self.dot.setFixedWidth(10)
        top.addWidget(self.dot)
        heading = QLabel("Клип")
        heading.setFont(theme.heading())
        top.addWidget(heading)
        self.where = QLabel()
        self.where.setObjectName("qa_show_clip_where")
        self.where.setStyleSheet(f"color:{theme.QUIET}; font-size:12px;")
        top.addWidget(self.where)
        top.addStretch(1)
        # The chosen clip as the render's range: the frames it occupies, in
        # one press rather than copied out of the fields below.
        self.to_render = _small_button(
            "Диапазон рендера — этот клип", "qa_show_clip_range",
            "Поставить начало и конец рендера на края выбранного клипа")
        self.to_render.clicked.connect(self._to_render)
        self.to_render.setEnabled(False)
        top.addWidget(self.to_render)
        whole.addLayout(top)

        self.title = QLabel("клип не выбран")
        self.title.setObjectName("qa_show_clip")
        self.title.setFont(theme.mono(9))
        self.title.setWordWrap(True)
        self.title.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        whole.addWidget(self.title)
        self.path = QLabel("")
        self.path.setObjectName("qa_show_path")
        self.path.setFont(theme.mono(9))
        self.path.setWordWrap(True)
        self.path.setStyleSheet(f"color:{theme.QUIET};")
        self.path.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        whole.addWidget(self.path)

        holder = QWidget()
        self.grid = QGridLayout(holder)
        self.grid.setContentsMargins(0, 4, 0, 0)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(6)
        whole.addWidget(holder)
        whole.addStretch(1)
        self._lay_out(self.MEDIA)
        view.changed.connect(self.refresh)
        self.refresh()

    def _lay_out(self, names) -> None:
        for widget in self.shown:
            self.grid.removeWidget(widget)
            widget.setParent(None)
        self.shown, self.body = [], {}
        for index, (label, key, editable, lowest, highest) in enumerate(names):
            row, pair = divmod(index, 2)
            tag = QLabel(label)
            tag.setStyleSheet(f"color:{theme.DIM}; font-size:12px;")
            tag.setWordWrap(True)
            if editable:
                field = _number(lowest, highest, f"qa_show_field_{key}")
                field.valueChanged.connect(
                    lambda value, which=key: self._typed(which, value))
            else:
                field = _boxed(f"qa_show_field_{key}")
            self.grid.addWidget(tag, row, pair * 2)
            self.grid.addWidget(field, row, pair * 2 + 1)
            self.shown += [tag, field]
            self.body[key] = field
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(2, 1)

    def _typed(self, key: str, value: int) -> None:
        if not self._saying:
            self.view.set_field(self.view.chosen, key, value)

    def _to_render(self) -> None:
        clip = self.view.chosen
        if clip is not None:
            ends = clip.tx + 1 if clip.kind == "cue" else clip.last - clip.tail
            self.view.range_wanted.emit(int(clip.first), int(max(clip.first + 1,
                                                                 ends)))

    def refresh(self) -> None:
        clip = self.view.chosen
        wanted = self.CUE if (clip is not None and clip.kind == "cue") \
            else self.MEDIA
        if [one[1] for one in wanted] != list(self.body):
            self._lay_out(wanted)
        self._saying = True
        try:
            self._show(clip)
        finally:
            self._saying = False

    def _show(self, clip) -> None:
        editing = self.view.editing and clip is not None
        self.to_render.setEnabled(clip is not None)
        for field in self.body.values():
            if isinstance(field, QSpinBox):
                _writable(field, editing)
        if clip is None:
            self.dot.clear()
            self.where.setText("")
            self.title.setText("клип не выбран")
            self.path.setText("")
            for field in self.body.values():
                if isinstance(field, QSpinBox):
                    field.setEnabled(False)
                else:
                    field.setText("—")
            return
        self.dot.setPixmap(theme.cell(clip.row, 8))
        self.where.setText("кью" if clip.kind == "cue"
                           else f"{clip.row} · L{clip.level}")
        if clip.kind == "cue":
            self.title.setText(f"кью на кадре {clip.tx}")
            self.path.setText("")
        else:
            self.title.setText(clip.name + ("   (нет файла)"
                                            if clip.missing else ""))
            self.path.setText(str(Path(clip.path).parent) if clip.path else "")
        fps = showfile.FPS
        length = "—"
        if clip.still:
            length = "картинка"
        elif clip.frames:
            length = f"{clip.frames}"
        said = {
            "frames": length,
            "tail": f"+{clip.tail}" if clip.tail else "—",
            "range": (showfile.timecode(clip.tx) if clip.kind == "cue"
                      else f"{_clock(clip.first)}–"
                           f"{_clock(min(clip.last, self.view.show.length))}"),
            "at": showfile.timecode(clip.first),
        }
        top_level = LEVELS.get(clip.row, 1) - 1 if clip.kind != "cue" else 3
        for key, field in self.body.items():
            if isinstance(field, QSpinBox):
                field.setEnabled(True)
                if key == "level":
                    field.setMaximum(max(0, top_level))
                value = int(getattr(clip, key, 0) or 0)
                if field.value() != value:
                    field.setValue(value)
                if key in self.SECONDS:
                    field.setToolTip(f"{abs(value) / fps:.2f} с")
            else:
                field.setText(said.get(key, "—"))


class SidePane(QWidget):
    """The show's columns beside the picture: the screens and the loops, then
    the chosen clip. The window lays the screens' sliders into `screens`."""

    SCREENS = 250
    CLIP = 380

    def __init__(self, view: ShowView) -> None:
        super().__init__()
        self.setObjectName("qa_show_side")
        self.setFixedWidth(self.SCREENS + self.CLIP)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        column = QWidget()
        column.setObjectName("qa_show_screens")
        column.setFixedWidth(self.SCREENS)
        column.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        column.setStyleSheet(f"#qa_show_screens {{ background:{theme.PANEL};"
                             f" border-left:1px solid {theme.SEAM}; }}")
        stack = QVBoxLayout(column)
        stack.setContentsMargins(16, 12, 16, 12)
        stack.setSpacing(10)
        title = QLabel("Экраны")
        title.setFont(theme.heading())
        stack.addWidget(title)
        self.screens = QVBoxLayout()
        self.screens.setSpacing(10)
        stack.addLayout(self.screens)
        stack.addStretch(1)
        rule = QWidget()
        rule.setFixedHeight(1)
        rule.setStyleSheet(f"background:{theme.SEAM};")
        stack.addWidget(rule)
        self.loops = LoopPanel(view)
        stack.addWidget(self.loops)
        row.addWidget(column)

        self.inspector = Inspector(view)
        self.inspector.setFixedWidth(self.CLIP)
        row.addWidget(self.inspector)
