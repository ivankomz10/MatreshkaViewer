"""The show on a timeline: the strips under the picture and the column beside it.

Read only until the editor is switched on. A show opened to be looked at is
played, not changed: nothing is dragged, no field writes into a clip and no
loop is drawn, so what goes to the site cannot be nudged by accident. The
editor unlocks all of it at once -- and the loops have a lock of their own
inside it, because the loops read out of a show file are the easiest thing
there to break.

What is here came out of the prototype on the `proto/timeline` branch, as it
was when it was signed off:

  LoopBar    the loops, on a strip of their own, with LOOP at its head and,
             in the editor, the lock at its other end
  Ruler      the time axis, and the only place the playhead is dragged
  Tracks     a row per level, per screen: Cue, Kinetic, Top x3, Bottom x3,
             Lamels x3, Sound x2 -- what triggers first is highest
  LoopPanel  the loops in numbers, down the right
  Inspector  the chosen clip, and its path in full

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

from PySide6.QtCore import QObject, QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QSizePolicy, QSpinBox, QVBoxLayout,
                               QWidget)

import show as showfile
import theme

MONO = "Cascadia Mono, Consolas, DejaVu Sans Mono, monospace"

# Top to bottom: what triggers first is highest.
ROWS = ["Cue", "Kinetic", "Top", "Bottom", "Lamels", "Sound"]
# Each screen's colour: the same one it has everywhere in the window.
HUE = theme.SCREEN
# Three content levels per screen, two sounds. The black still on the level
# behind every show is not a clip here: the viewer chooses its own backing.
LEVELS = {"Top": 3, "Bottom": 3, "Lamels": 3, "Sound": 2, "Kinetic": 1,
          "Cue": 1}
HEAD = 74            # the width of the labels down the left of every strip
SIDE = 290           # the right-hand column
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
        self.origin = float(HEAD - 6)  # pixels before frame `left` is drawn
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
        if step * showfile.FPS * axis.scale > 70:
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
        x = int(self.axis.x_of(self.view.frame))
        brush.setPen(QPen(QColor("#4ec9e0"), 1))
        brush.drawLine(x, top, x, self.height())


class Ruler(_Strip):
    """The time axis -- and the only place the playhead is dragged."""

    def __init__(self, view: ShowView) -> None:
        super().__init__(view)
        self.setObjectName("qa_show_ruler")
        self.setFixedHeight(24)
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self.holding = False

    def _follow(self) -> None:
        self.update()           # the playhead's mark follows to the frame

    def paintEvent(self, event) -> None:      # noqa: N802
        brush = QPainter(self)
        brush.fillRect(self.rect(), QColor(theme.NIGHT))
        brush.setFont(QFont(MONO, 8))
        for seconds in _nice_steps(self.axis):
            x = self.axis.x_of(seconds * showfile.FPS)
            if not HEAD - 10 <= x <= self.width() + 40:
                continue
            brush.setPen(QPen(QColor(theme.SEAM)))
            brush.drawLine(int(x), 16, int(x), 24)
            brush.setPen(QPen(QColor(theme.QUIET)))
            brush.drawText(int(x) + 3, 14,
                           showfile.timecode(seconds * showfile.FPS)[3:])
        brush.fillRect(QRect(0, 0, HEAD - 6, self.height()), QColor(theme.NIGHT))
        # The render's range, when it is not all of it: a band and its ends.
        span = self.view.render_range
        if span is not None:
            left, right = (int(self.axis.x_of(one)) for one in span)
            live = QColor(theme.LIVE)
            live.setAlpha(55)
            brush.fillRect(QRect(left, 16, max(2, right - left), 8), live)
            brush.setPen(QPen(QColor(theme.LIVE), 2))
            brush.drawLine(left, 14, left, 24)
            brush.drawLine(right, 14, right, 24)
        x = int(self.axis.x_of(self.view.frame))
        brush.setPen(QPen(QColor("#4ec9e0"), 1))
        brush.drawLine(x, 6, x, self.height())
        brush.setPen(Qt.PenStyle.NoPen)
        brush.setBrush(QColor("#4ec9e0"))
        brush.drawPolygon([QPoint(x - 5, 6), QPoint(x + 5, 6), QPoint(x, 14)])
        brush.end()

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
    """The loops, on a strip of their own, with their switch at its head.

    In the editor, and unlocked, loops are drawn here: a drag across empty
    strip is a new loop, a drag at either end of the chosen one moves that
    end, and Shift held inside one moves the whole of it. The lock at the far
    end is down to begin with -- the loops out of a show file are the easiest
    thing on it to break -- and the numbers down the right work either way.
    """

    GRIP = 5

    def __init__(self, view: ShowView) -> None:
        super().__init__(view)
        self.setObjectName("qa_show_loopbar")
        self.setFixedHeight(20)
        self.setMouseTracking(True)
        self.holding = None            # low | high | move, while dragging
        self.grabbed = 0
        self.moved_any = False

        self.switch = QPushButton("LOOP", self)
        self.switch.setObjectName("qa_show_loop")
        self.switch.setCheckable(True)
        self.switch.setGeometry(2, 1, HEAD - 12, 18)
        self.switch.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.switch.setToolTip(
            "Загорается сам, когда плейхед въезжает в луп слева: с этого "
            "момента луп держит. Нажми, чтобы отпустить — плейхед поедет "
            "дальше, до следующего лупа (L).")
        self.switch.setStyleSheet(
            "QPushButton { font-size:10px; padding:0px; }"
            f"QPushButton:checked {{ background:{theme.LIVE}; color:#061318;"
            f" border-color:{theme.LIVE}; }}")
        # By hand only: the playhead lighting it is told the other way round.
        self.switch.clicked.connect(lambda on: view.set_looping(on))
        view.looping_changed.connect(self._shown)

        self.lock = QPushButton("\U0001f512", self)
        self.lock.setObjectName("qa_show_lock")
        self.lock.setCheckable(True)
        self.lock.setChecked(True)
        self.lock.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.lock.setToolTip(
            "Запретить рисовать лупы мышью (K). Числами справа их всё равно "
            "можно поправить — на 22 минутах один пиксель это 56 кадров.")
        self.lock.setStyleSheet("QPushButton { font-size:11px; padding:0px; }")
        self.lock.clicked.connect(lambda on: view.set_locked(on))
        self.lock.setVisible(False)
        view.locked_changed.connect(self._locked)
        view.editing_changed.connect(self.lock.setVisible)

    def _shown(self, on: bool) -> None:
        self.switch.blockSignals(True)
        self.switch.setChecked(bool(on))
        self.switch.blockSignals(False)

    def _locked(self, on: bool) -> None:
        self.lock.blockSignals(True)
        self.lock.setChecked(bool(on))
        self.lock.blockSignals(False)
        self.lock.setText("\U0001f512" if on else "\U0001f513")

    def resizeEvent(self, event) -> None:      # noqa: N802
        self.lock.setGeometry(self.width() - 32, 1, 30, 18)
        super().resizeEvent(event)

    @property
    def drawing(self) -> bool:
        return self.view.editing and not self.view.locked

    def paintEvent(self, event) -> None:      # noqa: N802
        brush = QPainter(self)
        brush.fillRect(self.rect(), QColor(theme.NIGHT))
        right_end = self.width() - (34 if self.lock.isVisible() else 0)
        brush.setClipRect(QRect(HEAD - 6, 0, right_end - HEAD + 6,
                                self.height()))
        here = self.view.loop_here()
        for index, (low, high) in enumerate(self.view.loops):
            left, right = int(self.axis.x_of(low)), int(self.axis.x_of(high))
            running = self.view.looping and here == (low, high)
            picked = index == self.view.loop_at
            brush.fillRect(
                QRect(left, 3, max(3, right - left), self.height() - 6),
                QColor(theme.LIVE) if running
                else QColor(theme.LIVE_EDGE) if picked
                else QColor(theme.LIVE_DIM))
            for x in (left, right):
                brush.fillRect(QRect(x - 2, 0, 4, self.height()),
                               QColor("#a9ecf6") if picked
                               else QColor(theme.LIVE_EDGE))
            if right - left > 70:
                brush.setFont(QFont(MONO, 7, QFont.Weight.Bold))
                brush.setPen(QPen(QColor("#061318" if running else theme.TEXT)))
                brush.drawText(left + 7, self.height() - 6,
                               f"{index + 1}  "
                               f"{(high - low) / showfile.FPS:.1f}с")
            if self.view.editing and self.view.locked:
                brush.setPen(QPen(QColor(0, 0, 0, 80)))
                for x in range(left, right, 5):
                    brush.drawLine(x, 3, x - self.height(), self.height() - 3)
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
                self.view.say("лупы заперты — замок справа на полосе или K")
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
    """A row per level, per screen. In the editor: dragged, and dropped on."""

    LANE = 19
    GAP = 5

    def __init__(self, view: ShowView) -> None:
        super().__init__(view)
        self.setObjectName("qa_show_tracks")
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setFixedHeight(self.wanted_height())
        self.dragging = None
        self.grabbed = 0
        self.began_at = None           # (tx, level) the drag started from
        self.landing = None            # (row, level, frame) under a file

    def resizeEvent(self, event) -> None:      # noqa: N802
        was = self.axis.fitted
        self.axis.width = max(1, self.width() - HEAD + 6)
        if was:
            self.axis.fit()
        self.axis.clamp()
        super().resizeEvent(event)

    def lanes(self) -> list:
        out, y = [], 2
        for row in ROWS:
            for level in range(LEVELS[row]):
                out.append((row, level, y))
                y += self.LANE
            y += self.GAP
        return out

    def lane_at(self, y: float):
        """(row, level) of the lane under a height, or None between rows."""
        for row, level, top in self.lanes():
            if top <= y < top + self.LANE:
                return row, level
        return None

    @classmethod
    def wanted_height(cls) -> int:
        return sum(LEVELS[row] * cls.LANE + cls.GAP for row in ROWS) + 4

    def band_of(self, clip):
        if clip.kind == "cue":
            for row, _level, y in self.lanes():
                if row == "Cue":
                    return QRect(int(self.axis.x_of(clip.tx)) - 4, y,
                                 9, self.LANE - 2)
            return None
        for row, level, y in self.lanes():
            if row == clip.row and level == min(clip.level, LEVELS[row] - 1):
                left = self.axis.x_of(clip.first)
                ends = min(clip.last, self.view.show.length)
                width = max(3.0, (ends - clip.first) * self.axis.scale)
                if left + width < HEAD or left > self.width():
                    return None
                return QRect(int(left), y, int(width), self.LANE - 2)
        return None

    def clip_under(self, where: QPoint):
        for clip in reversed(self.view.show.clips):
            band = self.band_of(clip)
            if band is not None and band.adjusted(-2, 0, 2, 0).contains(where):
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
    def mark_fade(brush: QPainter, band: QRect, wide: float, frames: int,
                  head: bool = False) -> None:
        """Make a fade legible: a notch where it starts, and the ramp drawn."""
        edge = band.left() + int(wide) if head else band.right() - int(wide)
        pale = QColor(theme.TEXT)
        brush.setPen(QPen(pale, 1))
        if head:
            brush.drawLine(band.left(), band.bottom() - 1, edge, band.top() + 1)
        else:
            brush.drawLine(edge, band.top() + 1, band.right(), band.bottom() - 1)
        brush.setPen(QPen(pale, 2))
        brush.drawLine(edge, band.top() + 1, edge, band.top() + 5)
        brush.drawLine(edge, band.bottom() - 5, edge, band.bottom() - 1)
        if wide > 46 and band.height() > 14:
            brush.setFont(QFont(MONO, 7))
            brush.setPen(QPen(pale))
            brush.drawText(edge + 3, band.center().y() + 3,
                           f"{abs(frames) / showfile.FPS:.1f}с")

    @staticmethod
    def _shade(brush: QPainter, band: QRect, wide: float, head: bool) -> None:
        for step in range(int(wide)):
            x = band.left() + step if head else band.right() - int(wide) + step
            if band.left() <= x <= band.right():
                much = (1 - step / max(1.0, wide)) if head \
                    else step / max(1.0, wide)
                brush.setPen(QPen(QColor(0, 0, 0, int(165 * much))))
                brush.drawLine(x, band.top(), x, band.bottom())

    def draw_clip(self, brush: QPainter, clip, band: QRect) -> None:
        colour = QColor(theme.ERROR).darker(160) if clip.missing \
            else QColor(HUE[clip.row])
        chosen = clip is self.view.chosen
        body = QColor(colour)
        body.setAlpha(215 if chosen else 130)
        brush.fillRect(band, body)
        # The motor is still carrying out its last command after the file has
        # run out, so the clip goes on -- hatched, because nothing is read
        # there: the screens are only still arriving.
        if clip.tail:
            over = int(clip.tail * self.axis.scale)
            if over >= 1:
                brush.setPen(QPen(QColor(255, 255, 255, 30)))
                for x in range(band.right() - over, band.right() + 1, 4):
                    brush.drawLine(x, band.top(), x - band.height(),
                                   band.bottom())
                brush.setPen(QPen(QColor("#e0b0b0"), 1, Qt.PenStyle.DashLine))
                brush.drawLine(band.right() - over, band.top(),
                               band.right() - over, band.bottom())
        tail_px = int(clip.tail * self.axis.scale) if clip.tail else 0
        faded = band.adjusted(0, 0, -tail_px, 0)
        if clip.fade_end:
            wide = abs(clip.fade_end) * self.axis.scale
            if wide > 2:
                self._shade(brush, faded, wide, head=False)
                self.mark_fade(brush, faded, wide, clip.fade_end)
        if clip.fade_start:
            wide = abs(clip.fade_start) * self.axis.scale
            if wide > 2:
                self._shade(brush, band, wide, head=True)
                self.mark_fade(brush, band, wide, clip.fade_start, head=True)
        if clip.crop_end:
            cut = int(abs(clip.crop_end) * self.axis.scale)
            brush.setPen(QPen(QColor(theme.QUIET), 1, Qt.PenStyle.DotLine))
            brush.drawLine(faded.right(), faded.center().y(),
                           faded.right() + cut, faded.center().y())
            brush.setPen(QPen(QColor(theme.TEXT), 2))
            brush.drawLine(faded.right(), faded.top() + 1,
                           faded.right(), faded.top() + 4)
            brush.drawLine(faded.right(), faded.bottom() - 4,
                           faded.right(), faded.bottom() - 1)
        brush.setPen(QPen(QColor("#e8e8e8") if chosen else colour.lighter(130)))
        brush.drawRect(band)
        if band.width() > 34:
            brush.setFont(QFont(MONO, 8))
            brush.setPen(QPen(QColor("#f0f0f0" if chosen else "#c8c8c8")))
            room = band.adjusted(4, 0, -3, 0)
            room.setLeft(max(room.left(), HEAD - 2))
            metrics = QFontMetrics(brush.font())
            brush.drawText(room, Qt.AlignmentFlag.AlignVCenter,
                           metrics.elidedText(clip.name,
                                              Qt.TextElideMode.ElideMiddle,
                                              max(0, room.width())))

    def draw_overlaps(self, brush: QPainter) -> None:
        """Two clips on one level at once: the engine plays one of them, so
        where they cross is marked, in red, for somebody to sort out."""
        for row, level, y in self.lanes():
            if row == "Cue":
                continue
            track = [one for one in self.view.show.on(row)
                     if min(one.level, LEVELS[row] - 1) == level]
            track.sort(key=lambda one: one.first)
            for before, after in zip(track, track[1:]):
                if after.first < before.last:
                    left = int(self.axis.x_of(after.first))
                    right = int(self.axis.x_of(min(before.last, after.last)))
                    brush.fillRect(QRect(left, y, max(2, right - left), 3),
                                   QColor(theme.WARN))

    def draw_cues(self, brush: QPainter, band: QRect) -> None:
        for clip in self.view.show.clips:
            if clip.kind != "cue":
                continue
            x = int(self.axis.x_of(clip.tx))
            chosen = clip is self.view.chosen
            brush.setPen(QPen(QColor("#f5e39a" if chosen else HUE["Cue"]),
                              3 if chosen else 1))
            brush.drawLine(x, band.top(), x, band.bottom())
            if self.axis.scale > 0.015:
                brush.setFont(QFont(MONO, 7))
                brush.setPen(QPen(QColor("#f5e39a" if chosen else theme.QUIET)))
                brush.drawText(x + 4, band.top() + 10,
                               f"u{clip.universe}·ch{clip.channel}·v{clip.value}")

    def draw_loops(self, brush: QPainter) -> None:
        here = self.view.loop_here()
        for low, high in self.view.loops:
            left, right = int(self.axis.x_of(low)), int(self.axis.x_of(high))
            running = self.view.looping and here == (low, high)
            brush.fillRect(QRect(left, 0, max(2, right - left), self.height()),
                           QColor(78, 201, 224, 34 if running else 12))
            brush.setPen(QPen(QColor(theme.LIVE if running else theme.LIVE_EDGE),
                              2 if running else 1))
            brush.drawLine(left, 0, left, self.height())
            brush.drawLine(right, 0, right, self.height())

    def paintEvent(self, event) -> None:       # noqa: N802
        brush = QPainter(self)
        brush.fillRect(self.rect(), QColor(theme.NIGHT))
        for row, level, y in self.lanes():
            lit = (self.landing is not None
                   and self.landing[:2] == (row, level))
            brush.fillRect(QRect(0, y, self.width(), self.LANE - 2),
                           QColor(theme.LIVE_DIM) if lit
                           else QColor("#161b21" if level % 2 else "#13171c"))
            # The screen's mark before its name, on its first lane: the same
            # cell and colour as on its row and its slider.
            if level == 0:
                theme.paint_cell(brush, QRectF(3, y + 2.5, 13, self.LANE - 7),
                                 HUE[row])
            brush.setFont(QFont(MONO, 8))
            brush.setPen(QPen(QColor(theme.TEXT) if level == 0
                              else QColor(theme.FAINT)))
            brush.drawText(18, y + self.LANE - 7,
                           f"{row} L{level}" if LEVELS[row] > 1 else row)
        brush.setPen(QPen(QColor(theme.SEAM)))
        brush.drawLine(HEAD - 6, 0, HEAD - 6, self.height())
        brush.setClipRect(QRect(HEAD - 6, 0,
                                self.width() - HEAD + 6, self.height()))
        self.draw_loops(brush)
        for clip in self.view.show.clips:
            if clip.kind == "cue":
                continue
            band = self.band_of(clip)
            if band is not None:
                self.draw_clip(brush, clip, band)
        self.draw_overlaps(brush)
        for row, _level, y in self.lanes():
            if row == "Cue":
                self.draw_cues(brush, QRect(0, y, self.width(), self.LANE - 2))
        if self.landing is not None:
            x = int(self.axis.x_of(self.landing[2]))
            brush.setPen(QPen(QColor("#8fdf8f"), 2))
            brush.drawLine(x, 0, x, self.height())
        self.draw_playhead(brush)
        brush.end()


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
    """Everything under the picture: a line of what is where, then the strips."""

    def __init__(self, view: ShowView) -> None:
        super().__init__()
        self.setObjectName("qa_show_pane")
        self.view = view
        whole = QVBoxLayout(self)
        whole.setContentsMargins(0, 2, 0, 0)
        whole.setSpacing(2)

        line = QHBoxLayout()
        line.setSpacing(12)
        # The window's transport comes to stand at the head of this line in
        # the show mode, beside the one reading of the time.
        self.header = line
        self.clock = QLabel()
        self.clock.setObjectName("qa_show_clock")
        self.clock.setFont(theme.mono(11, bold=True))
        self.clock.setTextFormat(Qt.TextFormat.PlainText)
        line.addWidget(self.clock)
        self.state = QLabel()
        self.state.setObjectName("qa_show_state")
        self.state.setFont(QFont(MONO, 9))
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
        self.note.setFont(QFont(MONO, 9))
        self.note.setStyleSheet(f"color:{theme.WARN};")
        self.note.setTextFormat(Qt.TextFormat.PlainText)
        self.note.setAlignment(Qt.AlignmentFlag.AlignRight
                               | Qt.AlignmentFlag.AlignVCenter)
        self.note.setSizePolicy(QSizePolicy.Policy.Ignored,
                                QSizePolicy.Policy.Preferred)
        line.addWidget(self.note, 2)
        whole.addLayout(line)

        self.loopbar = LoopBar(view)
        whole.addWidget(self.loopbar)
        self.ruler = Ruler(view)
        whole.addWidget(self.ruler)
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
        whole.addWidget(scroller, 1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        self._said = None
        view.changed.connect(self.refresh)
        view.moved.connect(self.refresh)
        view.said.connect(self.note.setText)

    def wanted_height(self) -> int:
        return Tracks.wanted_height() + 20 + 24 + 22 + 8

    def refresh(self) -> None:
        view = self.view
        at = int(view.frame)
        live = view.show.live_at(at)
        here = view.loop_here()
        clock = f"{showfile.timecode(at)}   кадр {at} из {view.show.length}"
        said = (("В ЛУПЕ   " if here is not None and view.looping else "")
                + "на экранах: "
                + ("  ·  ".join(f"{one.row} L{one.level} {one.name[:24]}"
                                for one in live) or "ничего"))
        if (clock, said) != self._said:
            self._said = (clock, said)
            self.clock.setText(clock)
            self.state.setText(said)


# -- the right-hand column ---------------------------------------------------

def _number(lowest: int, highest: int, name: str) -> QSpinBox:
    field = QSpinBox()
    field.setObjectName(name)
    field.setRange(lowest, highest)
    field.setKeyboardTracking(False)
    field.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
    field.setFont(QFont(MONO, 9))
    return field


def _writable(field: QSpinBox, on: bool) -> None:
    field.setReadOnly(not on)
    field.setButtonSymbols(QSpinBox.ButtonSymbols.UpDownArrows if on
                           else QSpinBox.ButtonSymbols.NoButtons)
    field.setFrame(on)


class LoopPanel(QWidget):
    """The loops in numbers: on 22 minutes a pixel is 56 frames."""

    def __init__(self, view: ShowView) -> None:
        super().__init__()
        self.setObjectName("qa_show_loops")
        self.view = view
        whole = QVBoxLayout(self)
        whole.setContentsMargins(8, 6, 8, 8)
        whole.setSpacing(4)
        title = QLabel("Лупы")
        title.setFont(theme.heading())
        title.setStyleSheet(f"color:{theme.QUIET};")
        whole.addWidget(title)
        self.says = QLabel()
        self.says.setObjectName("qa_show_loop_says")
        self.says.setFont(QFont(MONO, 9))
        self.says.setStyleSheet(f"color:{theme.LIVE};")
        self.says.setWordWrap(True)
        whole.addWidget(self.says)

        frames = QHBoxLayout()
        frames.setSpacing(4)
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
        line.setSpacing(4)
        for text, what, hint, name, wide in (
                ("+", view.add_loop, "Ещё один луп с того кадра, где плейхед.",
                 "qa_show_loop_add", 26),
                ("−", view.drop_loop, "Убрать выбранный луп.",
                 "qa_show_loop_drop", 26),
                ("по клипу", view.loop_the_clip,
                 "Луп на весь выбранный клип, и держать (Shift+L).",
                 "qa_show_loop_clip", 0),
                ("из файла", view.loop_from_file,
                 "Вернуть лупы, с которыми шоу открылось.",
                 "qa_show_loop_file", 0)):
            one = QPushButton(text)
            one.setObjectName(name)
            if wide:
                one.setFixedWidth(wide)
                # Without this the window's own twelve pixels a side leave a
                # button this narrow no room for its one character.
                one.setStyleSheet("QPushButton { padding:2px 0px; }")
            one.setToolTip(hint)
            one.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            one.clicked.connect(lambda _=False, act=what: act())
            line.addWidget(one)
        line.addStretch(1)
        whole.addWidget(self.buttons)

        self.frames = QLabel()
        self.frames.setObjectName("qa_show_loop_frames")
        self.frames.setFont(QFont(MONO, 9))
        self.frames.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        whole.addWidget(self.frames)
        self.setStyleSheet(f"background:{theme.RAISED};")
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
            said = (f"луп {view.loop_at + 1} из {len(view.loops)}   "
                    f"{(picked[1] - picked[0]) / showfile.FPS:.1f}с")
        if here is not None:
            said += ("   ДЕРЖИТ" if view.looping
                     else "   плейхед внутри, луп отпущен")
        self.says.setText(said)
        self._saying = True
        for field, value in ((self.low, picked[0] if picked else 0),
                             (self.high, picked[1] if picked else 0)):
            _writable(field, view.editing and picked is not None)
            if field.value() != value:
                field.setValue(value)
        self._saying = False
        self.buttons.setVisible(view.editing)
        self.frames.setText("\n".join(
            f"{'>' if index == view.loop_at else ' '} {index + 1}  "
            f"с {low}  по {high}"
            for index, (low, high) in enumerate(view.loops)) or "—")


class Inspector(QWidget):
    """The chosen clip. Shown, and in the editor written to.

    What can be typed is what the show file actually stores: where the clip
    starts, which level it is on, how much is trimmed, how long it fades. The
    rest -- how long the file is, what it comes to, where the motors are still
    moving -- is worked out from those and from the media, so it is shown and
    not offered. A cue is a different animal and gets its own fields.
    """

    # label, key, editable, lowest, highest
    MEDIA = [("Дорожка", "row", False, 0, 0),
             ("Уровень", "level", True, 0, 2),
             ("Кадр начала", "tx", True, 0, 10_000_000),
             ("Длина", "frames", False, 0, 0),
             ("Доезд моторов", "tail", False, 0, 0),
             ("Подрезка с хвоста", "crop_end", True, -1_000_000, 0),
             ("Фейд с хвоста", "fade_end", True, -1_000_000, 0),
             ("Подрезка с головы", "crop_start", True, 0, 1_000_000),
             ("Фейд с головы", "fade_start", True, 0, 1_000_000),
             ("Занимает", "range", False, 0, 0),
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
        self.aside: dict = {}          # seconds beside a number
        self._saying = False
        whole = QVBoxLayout(self)
        whole.setContentsMargins(0, 0, 0, 0)
        whole.setSpacing(2)
        heading = QLabel("Клип")
        heading.setFont(theme.heading())
        heading.setStyleSheet(f"color:{theme.QUIET};")
        heading.setContentsMargins(8, 8, 8, 0)
        whole.addWidget(heading)
        self.title = QLabel("клип не выбран")
        self.title.setObjectName("qa_show_clip")
        self.title.setFont(QFont(MONO, 10, QFont.Weight.Bold))
        self.title.setWordWrap(True)
        self.title.setContentsMargins(8, 0, 8, 0)
        whole.addWidget(self.title)
        # The chosen clip as the render's range: the frames it occupies, in
        # one press rather than copied out of the two fields below.
        self.to_render = QPushButton("Диапазон рендера — этот клип")
        self.to_render.setObjectName("qa_show_clip_range")
        self.to_render.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.to_render.setToolTip("Поставить начало и конец рендера на края "
                                  "выбранного клипа")
        self.to_render.clicked.connect(self._to_render)
        self.to_render.setEnabled(False)
        shelf = QHBoxLayout()
        shelf.setContentsMargins(8, 2, 8, 2)
        shelf.addWidget(self.to_render)
        shelf.addStretch(1)
        whole.addLayout(shelf)
        holder = QWidget()
        self.grid = QGridLayout(holder)
        self.grid.setContentsMargins(8, 4, 8, 4)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(3)
        whole.addWidget(holder)
        # The path gets a block of its own, across the whole column, because
        # it has to be readable in full and a grid row will not grow for it.
        tag = QLabel("Файл")
        tag.setStyleSheet(f"color:{theme.QUIET};")
        tag.setContentsMargins(8, 6, 8, 0)
        whole.addWidget(tag)
        self.path = QLabel("—")
        self.path.setObjectName("qa_show_path")
        self.path.setFont(QFont(MONO, 9))
        self.path.setWordWrap(True)
        self.path.setContentsMargins(8, 0, 8, 6)
        self.path.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.path.setStyleSheet(f"color:{theme.TEXT};")
        whole.addWidget(self.path)
        whole.addStretch(1)
        self._lay_out(self.MEDIA)
        view.changed.connect(self.refresh)
        self.refresh()

    def _lay_out(self, names) -> None:
        for widget in self.shown:
            self.grid.removeWidget(widget)
            widget.setParent(None)
        self.shown, self.body, self.aside = [], {}, {}
        for index, (label, key, editable, lowest, highest) in enumerate(names):
            tag = QLabel(label)
            tag.setStyleSheet(f"color:{theme.QUIET};")
            tag.setFixedWidth(118)
            if editable:
                field = _number(lowest, highest, f"qa_show_field_{key}")
                field.valueChanged.connect(
                    lambda value, which=key: self._typed(which, value))
            else:
                field = QLabel("—")
                field.setObjectName(f"qa_show_field_{key}")
                field.setFont(QFont(MONO, 9))
            self.grid.addWidget(tag, index, 0)
            self.grid.addWidget(field, index, 1)
            self.shown += [tag, field]
            self.body[key] = field
            if editable and key in self.SECONDS:
                beside = QLabel()
                beside.setFont(QFont(MONO, 8))
                beside.setStyleSheet(f"color:{theme.FAINT};")
                self.grid.addWidget(beside, index, 2)
                self.shown.append(beside)
                self.aside[key] = beside
        self.grid.setColumnStretch(1, 1)

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
        for key, field in self.body.items():
            if isinstance(field, QSpinBox):
                _writable(field, editing)
        if clip is None:
            self.title.setText("клип не выбран")
            self.path.setText("—")
            for key, field in self.body.items():
                if isinstance(field, QSpinBox):
                    field.setEnabled(False)
                else:
                    field.setText("—")
            for beside in self.aside.values():
                beside.setText("")
            return
        self.title.setText(f"кью на кадре {clip.tx}" if clip.kind == "cue"
                           else clip.name + ("   (нет файла)"
                                             if clip.missing else ""))
        self.path.setText(clip.path or "—")
        fps = showfile.FPS
        length = "—"
        if clip.still:
            length = "картинка"
        elif clip.frames:
            length = f"{clip.frames}  ({clip.frames / fps:.1f} с)"
        said = {
            "row": clip.row,
            "frames": length,
            "tail": (f"+{clip.tail}  ({clip.tail / fps:.1f} с)"
                     if clip.tail else "—"),
            "range": (showfile.timecode(clip.tx) if clip.kind == "cue"
                      else f"{clip.first}..{min(clip.last, self.view.show.length)}"),
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
            else:
                field.setText(said.get(key, "—"))
        for key, beside in self.aside.items():
            value = abs(int(getattr(clip, key, 0) or 0))
            beside.setText(f"{value / fps:.1f} с" if value else "")


class SidePane(QWidget):
    """The right-hand column: the loops, then the chosen clip."""

    def __init__(self, view: ShowView) -> None:
        super().__init__()
        self.setObjectName("qa_show_side")
        self.setFixedWidth(SIDE)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"#qa_show_side {{ background:{theme.PANEL}; }}")
        stack = QVBoxLayout(self)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(0)
        self.loops = LoopPanel(view)
        stack.addWidget(self.loops)
        self.inspector = Inspector(view)
        stack.addWidget(self.inspector, 1)
