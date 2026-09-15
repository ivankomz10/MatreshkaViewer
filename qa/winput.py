"""Real mouse and keyboard, and a way to ask a window whether it is alive.

Real input, not Qt's own: the bugs worth catching here were about who gets a
key press and what a click lands on. A click delivered straight to a widget
cannot notice that something is sitting on top of it, and a key sent to a
widget cannot notice that the field with the cursor in it ate the space bar.
Both of those went wrong in this window at least once.

The price is that the tests take the mouse and the keyboard for as long as
they run. There is no way around it; that is what the thing under test reads.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

# Physical pixels everywhere. Without this the window's own coordinates, which
# come back from automation in real pixels, would not agree with the ones
# SendInput is given on a scaled display.
try:
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))   # per monitor v2
except Exception:                       # noqa: BLE001 -- older Windows
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
    except Exception:                   # noqa: BLE001
        user32.SetProcessDPIAware()

SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
MOUSEEVENTF_MOVE, MOUSEEVENTF_ABSOLUTE, MOUSEEVENTF_VIRTUALDESK = 0x1, 0x8000, 0x4000
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x2, 0x4
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x8, 0x10
MOUSEEVENTF_WHEEL = 0x800
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP = 0x1, 0x2
KEYEVENTF_UNICODE, KEYEVENTF_SCANCODE = 0x4, 0x8

WM_NULL = 0x0000
WM_CLOSE = 0x0010
SMTO_ABORTIFHUNG = 0x0002


class _MOUSE(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.POINTER(wt.ULONG))]


class _KEY(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.POINTER(wt.ULONG))]


class _GUTS(ctypes.Union):
    _fields_ = [("mi", _MOUSE), ("ki", _KEY)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("guts", _GUTS)]


def _send(*events) -> None:
    batch = (_INPUT * len(events))(*events)
    sent = user32.SendInput(len(events), batch, ctypes.sizeof(_INPUT))
    if sent != len(events):
        raise OSError(f"SendInput sent {sent} of {len(events)}: "
                      f"{ctypes.get_last_error()}")


def _mouse(flags, dx=0, dy=0, data=0) -> _INPUT:
    return _INPUT(INPUT_MOUSE, _GUTS(mi=_MOUSE(dx, dy, data, flags, 0, None)))


def _key(scan=0, vk=0, flags=0) -> _INPUT:
    return _INPUT(INPUT_KEYBOARD, _GUTS(ki=_KEY(vk, scan, flags, 0, None)))


def _absolute(x: int, y: int) -> tuple[int, int]:
    """A point on the whole desktop in the 0..65535 the driver wants.

    The whole desktop, not the primary monitor: a second screen to the left of
    the first has negative coordinates, and this window is often on one.
    """
    left = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    top = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    wide = max(1, user32.GetSystemMetrics(SM_CXVIRTUALSCREEN) - 1)
    tall = max(1, user32.GetSystemMetrics(SM_CYVIRTUALSCREEN) - 1)
    return (round((x - left) * 65535 / wide), round((y - top) * 65535 / tall))


def move(x: int, y: int) -> None:
    nx, ny = _absolute(int(x), int(y))
    _send(_mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE
                 | MOUSEEVENTF_VIRTUALDESK, nx, ny))


def click(x: int, y: int, button: str = "left", count: int = 1,
          settle: float = 0.12) -> None:
    """Move there first, as a hand would: hovers and enter events are real."""
    down, up = ((MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP) if button == "left"
                else (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP))
    move(x, y)
    time.sleep(0.05)
    for _ in range(count):
        _send(_mouse(down), _mouse(up))
        time.sleep(0.05)
    time.sleep(settle)


def drag(x1: int, y1: int, x2: int, y2: int, steps: int = 12) -> None:
    move(x1, y1)
    time.sleep(0.05)
    _send(_mouse(MOUSEEVENTF_LEFTDOWN))
    for step in range(1, steps + 1):
        move(x1 + (x2 - x1) * step // steps, y1 + (y2 - y1) * step // steps)
        time.sleep(0.02)
    _send(_mouse(MOUSEEVENTF_LEFTUP))
    time.sleep(0.15)


def wheel(x: int, y: int, notches: int, settle: float = 0.2) -> None:
    move(x, y)
    time.sleep(0.05)
    for _ in range(abs(notches)):
        _send(_mouse(MOUSEEVENTF_WHEEL, data=120 if notches > 0 else -120))
        time.sleep(0.04)
    time.sleep(settle)


# Scan codes rather than virtual keys: this is what a keyboard actually sends,
# and it does not depend on which layout happens to be up.
SCAN = {
    "space": 0x39, "left": 0x4B, "right": 0x4D, "up": 0x48, "down": 0x50,
    "escape": 0x01, "enter": 0x1C, "tab": 0x0F, "backspace": 0x0E,
    "home": 0x47, "end": 0x4F, "delete": 0x53,
    "ctrl": 0x1D, "shift": 0x2A, "alt": 0x38,
    "f4": 0x3E, "f11": 0x57, "a": 0x1E, "s": 0x1F,
}
EXTENDED = {"left", "right", "up", "down", "home", "end", "delete"}


def key(name: str, *held: str, settle: float = 0.12) -> None:
    """One key, optionally with modifiers held down around it."""
    name = name.lower()
    events = []
    for one in held:
        events.append(_key(scan=SCAN[one.lower()], flags=KEYEVENTF_SCANCODE))
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_EXTENDEDKEY if name in EXTENDED else 0)
    events.append(_key(scan=SCAN[name], flags=flags))
    events.append(_key(scan=SCAN[name], flags=flags | KEYEVENTF_KEYUP))
    for one in reversed(held):
        events.append(_key(scan=SCAN[one.lower()],
                           flags=KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP))
    _send(*events)
    time.sleep(settle)


def write(text: str, settle: float = 0.15) -> None:
    """Type text as characters, which is layout-proof and takes paths."""
    events = []
    for letter in text:
        code = ord(letter)
        events.append(_key(scan=code, flags=KEYEVENTF_UNICODE))
        events.append(_key(scan=code, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
    for start in range(0, len(events), 40):       # SendInput dislikes huge batches
        _send(*events[start:start + 40])
        time.sleep(0.01)
    time.sleep(settle)


# -- is anybody home ---------------------------------------------------------

SW_RESTORE = 9


def foreground(hwnd: int) -> None:
    """Ask for a window to come up. Whether it did is a separate question.

    Windows does not let just anybody raise a window, and a test that assumed
    it worked would go on to type into whatever was in front instead. So this
    only asks; `is_foreground` is what the caller must believe.
    """
    if user32.IsIconic(wt.HWND(hwnd)):
        user32.ShowWindow(wt.HWND(hwnd), SW_RESTORE)
    user32.BringWindowToTop(wt.HWND(hwnd))
    user32.SetForegroundWindow(wt.HWND(hwnd))
    time.sleep(0.15)


def foreground_window() -> int:
    return int(user32.GetForegroundWindow())


def is_foreground(hwnd: int) -> bool:
    return user32.GetForegroundWindow() == hwnd


def hung(hwnd: int) -> bool:
    """What the shell itself uses to decide a window has stopped answering."""
    return bool(user32.IsHungAppWindow(hwnd))


def answers(hwnd: int, within: float = 2.0) -> bool:
    """Ping a window's message loop and see whether it comes back in time.

    The freeze this is here for -- the log button that stopped both this
    window and Explorer -- looked exactly like this from outside: the window
    was up, drawn, and answering nothing.
    """
    result = ctypes.c_ulong()
    got = user32.SendMessageTimeoutW(wt.HWND(hwnd), WM_NULL, 0, 0,
                                     SMTO_ABORTIFHUNG, int(within * 1000),
                                     ctypes.byref(result))
    return bool(got)


def shell_answers(within: float = 2.0) -> bool:
    """The same question, asked of Explorer's own window."""
    hwnd = user32.FindWindowW("Shell_TrayWnd", None)
    return answers(hwnd, within) if hwnd else True


def rect_of(hwnd: int) -> tuple[int, int, int, int]:
    box = wt.RECT()
    user32.GetWindowRect(wt.HWND(hwnd), ctypes.byref(box))
    return box.left, box.top, box.right, box.bottom


# -- a picture of what is on the screen --------------------------------------

def grab(left: int, top: int, wide: int, tall: int):
    """Whatever is actually on those pixels, as a Pillow image.

    Off the screen rather than out of the window: this is here to check what
    a person would see, including anything drawn over the window.
    """
    from PIL import Image
    screen = user32.GetDC(0)
    memory = gdi32.CreateCompatibleDC(screen)
    picture = gdi32.CreateCompatibleBitmap(screen, wide, tall)
    gdi32.SelectObject(memory, picture)
    gdi32.BitBlt(memory, 0, 0, wide, tall, screen, left, top, 0x00CC0020)

    class INFO(ctypes.Structure):
        _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG),
                    ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                    ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                    ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
                    ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                    ("biClrImportant", wt.DWORD), ("colours", wt.DWORD * 3)]

    info = INFO()
    info.biSize = 40
    info.biWidth, info.biHeight = wide, -tall      # top down
    info.biPlanes, info.biBitCount = 1, 32
    buffer = ctypes.create_string_buffer(wide * tall * 4)
    gdi32.GetDIBits(memory, picture, 0, tall, buffer, ctypes.byref(info), 0)
    gdi32.DeleteObject(picture)
    gdi32.DeleteDC(memory)
    user32.ReleaseDC(0, screen)
    return Image.frombuffer("RGB", (wide, tall), buffer, "raw", "BGRX", 0, 1)


# -- which windows are up ----------------------------------------------------

_ENUM = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def top_windows() -> list:
    """Every top-level window: handle, process, class, title, showing.

    Straight from the window manager rather than through automation. Asking
    automation costs a call into each owning process, and while this
    application is starting up it does not answer them quickly -- which had a
    window that was up in six seconds looking as though it took thirty.
    """
    found = []

    def look(hwnd, _):
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        title = ctypes.create_unicode_buffer(256)
        klass = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, title, 256)
        user32.GetClassNameW(hwnd, klass, 256)
        found.append((int(hwnd), int(pid.value), klass.value, title.value,
                      bool(user32.IsWindowVisible(hwnd))))
        return True

    user32.EnumWindows(_ENUM(look), 0)
    return found


def close_window(hwnd: int) -> None:
    """Ask a window to close. Used only on windows a test itself opened."""
    user32.PostMessageW(wt.HWND(hwnd), WM_CLOSE, 0, 0)
