"""What Windows itself can see of the window, read in one round trip.

Every widget in the viewer that a test needs to point at carries an
objectName, and Qt hands that to Windows as the element's automation id. So a
test says `app.at("qa_render")` and gets the real button: where it is on the
screen, whether it is enabled, whether it is showing at all -- and, because
the id travels with the widget rather than with its place in a row, moving a
button around the bar does not break a single test.

Reading one property at a time is a call into the other process each time,
which for a hundred widgets is slow enough to notice. So the whole tree comes
back at once, with the properties already filled in, and a snapshot is a
plain dictionary from that moment.
"""
from __future__ import annotations

import time

import comtypes
import comtypes.client as cc

import winput

cc.GetModule("UIAutomationCore.dll")
from comtypes.gen import UIAutomationClient as UIA   # noqa: E402

CLIENT = "{ff48dba4-60ef-4201-aa87-54103eef594e}"

# Everything a test ever asks about a widget, fetched in the one call.
WANTED = (
    UIA.UIA_AutomationIdPropertyId,
    UIA.UIA_NamePropertyId,
    UIA.UIA_ClassNamePropertyId,
    UIA.UIA_ControlTypePropertyId,
    UIA.UIA_BoundingRectanglePropertyId,
    UIA.UIA_IsEnabledPropertyId,
    UIA.UIA_IsOffscreenPropertyId,
    UIA.UIA_NativeWindowHandlePropertyId,
    UIA.UIA_ValueValuePropertyId,
    UIA.UIA_ToggleToggleStatePropertyId,
    UIA.UIA_RangeValueValuePropertyId,
    UIA.UIA_LegacyIAccessibleValuePropertyId,
)

KIND = {
    UIA.UIA_ButtonControlTypeId: "button",
    UIA.UIA_CheckBoxControlTypeId: "check",
    UIA.UIA_ComboBoxControlTypeId: "combo",
    UIA.UIA_EditControlTypeId: "edit",
    UIA.UIA_TextControlTypeId: "text",
    UIA.UIA_SliderControlTypeId: "slider",
    UIA.UIA_SpinnerControlTypeId: "spin",
    UIA.UIA_ProgressBarControlTypeId: "progress",
    UIA.UIA_ListItemControlTypeId: "item",
    UIA.UIA_ListControlTypeId: "list",
    UIA.UIA_WindowControlTypeId: "window",
    UIA.UIA_PaneControlTypeId: "pane",
}


class Node:
    """One widget, as it was at the moment the snapshot was taken."""

    def __init__(self, element) -> None:
        self.element = element
        self.id = _cached(element, UIA.UIA_AutomationIdPropertyId, "")
        self.qa = self.id.rsplit(".", 1)[-1] if self.id else ""
        self.name = _cached(element, UIA.UIA_NamePropertyId, "") or ""
        self.klass = _cached(element, UIA.UIA_ClassNamePropertyId, "") or ""
        self.kind = KIND.get(_cached(element, UIA.UIA_ControlTypePropertyId, 0),
                             "other")
        box = _cached(element, UIA.UIA_BoundingRectanglePropertyId,
                      (0.0, 0.0, 0.0, 0.0))
        self.left, self.top = int(box[0]), int(box[1])
        self.wide, self.tall = int(box[2]), int(box[3])
        self.enabled = bool(_cached(element, UIA.UIA_IsEnabledPropertyId, True))
        self.showing = not _cached(element, UIA.UIA_IsOffscreenPropertyId, False)
        self.hwnd = int(_cached(element,
                                UIA.UIA_NativeWindowHandlePropertyId, 0) or 0)
        # Qt fills one or the other depending on the widget; a combo says what
        # it is showing through the legacy interface and an edit through Value.
        self.value = (_cached(element, UIA.UIA_ValueValuePropertyId, "")
                      or _cached(element,
                                 UIA.UIA_LegacyIAccessibleValuePropertyId, "")
                      or "")
        toggle = _cached(element, UIA.UIA_ToggleToggleStatePropertyId, None)
        self.checked = None if toggle is None else bool(toggle == 1)
        self.number = _cached(element, UIA.UIA_RangeValueValuePropertyId, None)

    # -- where a hand would go ----------------------------------------------

    @property
    def middle(self) -> tuple[int, int]:
        return self.left + self.wide // 2, self.top + self.tall // 2

    @property
    def rect(self) -> tuple[int, int, int, int]:
        return self.left, self.top, self.wide, self.tall

    def overlaps(self, other: "Node") -> bool:
        return not (self.left + self.wide <= other.left
                    or other.left + other.wide <= self.left
                    or self.top + self.tall <= other.top
                    or other.top + other.tall <= self.top)

    def __repr__(self) -> str:
        return (f"<{self.qa or self.name or self.klass} {self.kind} "
                f"{self.wide}x{self.tall} at {self.left},{self.top}"
                f"{'' if self.enabled else ' disabled'}"
                f"{'' if self.showing else ' hidden'}>")


def _cached(element, which, fallback):
    try:
        got = element.GetCachedPropertyValue(which)
    except Exception:                   # noqa: BLE001 -- gone between calls
        return fallback
    return fallback if got is None else got


class Desk:
    """The automation client, and the one place that talks to it.

    Which windows exist is asked of the window manager, which answers at once;
    what is inside one is asked of automation, which does not. Mixing the two
    is deliberate: a walk of the desktop through automation stalls on whatever
    process is busy, and the process that is busiest while this application
    starts is this application.
    """

    def __init__(self) -> None:
        comtypes.CoInitialize()
        self.uia = cc.CreateObject(CLIENT, interface=UIA.IUIAutomation)
        self.everything = self.uia.CreateTrueCondition()
        self.cache = self.uia.CreateCacheRequest()
        for one in WANTED:
            self.cache.AddProperty(one)
        self.cache.TreeScope = UIA.TreeScope_Element | UIA.TreeScope_Descendants

    # -- finding the application's windows ----------------------------------

    def wait_window(self, title_has: str, within: float = 90.0,
                    klass_starts: str = "Qt") -> tuple:
        """Wait for the real window, and answer with its handle and process.

        By class as well as by title, because the loading window the one-file
        build puts up carries neither -- and because a file dialog this
        application opens would otherwise pass for the window itself.
        """
        deadline = time.time() + within
        while time.time() < deadline:
            for hwnd, pid, klass, title, showing in winput.top_windows():
                if (showing and title_has in title
                        and klass.startswith(klass_starts)):
                    return hwnd, pid
            time.sleep(0.1)
        return 0, 0

    @staticmethod
    def splash_up(pid: int) -> bool:
        """Whether that process has its loading window on the screen now.

        By class and process, not by title: it is the bootloader's own window,
        put up before any of the application's code has run, and it is still
        wearing the name Tk gave it.
        """
        return any(showing and klass == "TkTopLevel" and owner == pid
                   for _, owner, klass, _, showing in winput.top_windows())

    @staticmethod
    def dialogs(pid: int, main: int = 0) -> list:
        """That process's windows apart from its main one, nearest first.

        The file picker is a `#32770` from the platform; the machine checks
        are a window of the application's own. Both are windows this process
        owns and neither is the main one, which is all a caller needs.
        """
        return [hwnd for hwnd, owner, _, title, showing in winput.top_windows()
                if owner == pid and showing and hwnd != main and title]

    # -- everything the application is showing, in one call ------------------

    def element(self, hwnd: int):
        try:
            return self.uia.ElementFromHandle(hwnd)
        except Exception:               # noqa: BLE001 -- window just died
            return None

    def snapshot(self, pid: int) -> dict:
        """Every widget of every window that process has up, by its qa name.

        Its windows rather than the whole desktop, so that a combo box's
        drop-down -- a window of its own, off in a corner of the tree -- is
        in the same picture as the combo box that opened it.
        """
        seen: dict = {}
        for hwnd, owner, _, _, showing in winput.top_windows():
            if owner != pid or not showing:
                continue
            window = self.element(hwnd)
            if window is None:
                continue
            try:
                found = window.FindAllBuildCache(
                    UIA.TreeScope_Element | UIA.TreeScope_Descendants,
                    self.everything, self.cache)
            except Exception:           # noqa: BLE001 -- window died mid-walk
                continue
            for index in range(found.Length):
                node = Node(found.GetElement(index))
                if node.qa and node.qa.startswith("qa_"):
                    seen.setdefault(node.qa, node)
                # A drop-down's lines have no names of their own; they are
                # kept under the text they show so a test can pick one.
                elif node.kind == "item" and node.name:
                    seen.setdefault(f"item:{node.name}", node)
                elif node.kind == "window" and node.name:
                    seen.setdefault(f"window:{node.name}", node)
        return seen

    def under(self, x: int, y: int) -> "Node | None":
        """What a click at that point would land on, whoever put it there."""
        try:
            element = self.uia.ElementFromPoint(UIA.tagPOINT(int(x), int(y)))
        except Exception:               # noqa: BLE001
            return None
        if element is None:
            return None
        try:
            found = element.BuildUpdatedCache(self.cache)
        except Exception:               # noqa: BLE001
            found = element
        return Node(found)
