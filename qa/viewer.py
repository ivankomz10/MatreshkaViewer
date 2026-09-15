"""The application under test: one built executable, run in a sandbox.

A sandbox because the viewer keeps everything beside itself -- its settings,
its logs, the folder it writes into -- and a test that ran the real one would
overwrite the settings somebody is working in. So the executable is copied
into `qa/sandbox`, and that copy is the one that gets driven, filled with
whatever settings the test wants and read back afterwards.

Nothing in here reaches into the application. Every question is asked the way
Windows asks it, and every answer is a click, a key, a file on disk or a line
in the log.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import uia
import winput

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
BUILT = PROJECT / "MatreshkaViewer.exe"
SANDBOX = HERE / "sandbox"
SHOTS = HERE / "artifacts"
TITLE = "Matreshka Viewer"

# How long the one-file build may take to unpack itself and put a window up.
# It is about seven seconds on the machine this was written on; the room is
# for a cold cache, which is much slower.
STARTUP = 120.0


class Timeout(AssertionError):
    """A test asked for something that never happened."""


def keep_exe_fresh() -> Path:
    """The sandbox's copy of whatever was last built."""
    SANDBOX.mkdir(parents=True, exist_ok=True)
    copy = SANDBOX / BUILT.name
    if not BUILT.exists():
        raise FileNotFoundError(f"nothing built at {BUILT}")
    if (not copy.exists()
            or copy.stat().st_mtime < BUILT.stat().st_mtime
            or copy.stat().st_size != BUILT.stat().st_size):
        shutil.copy2(BUILT, copy)
    return copy


def stray_viewers() -> list[int]:
    """Sandbox copies still running, which are ours and nobody else's.

    Only the sandbox: the person who owns this machine may well have the real
    viewer open beside these tests, and it is not for a test to close it.
    """
    got = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process -Filter \"Name='MatreshkaViewer.exe'\""
         " | Where-Object { $_.ExecutablePath -like '*\\qa\\sandbox\\*' }"
         " | ForEach-Object { $_.ProcessId }"],
        capture_output=True, text=True)
    return [int(line) for line in got.stdout.split() if line.strip().isdigit()]


def kill_strays() -> int:
    left = stray_viewers()
    for pid in left:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                       capture_output=True)
    return len(left)


class Viewer:
    """One run of the application, from the double click to the closing."""

    def __init__(self, settings: dict | None = None, env: dict | None = None,
                 clean: bool = True, name: str = "run") -> None:
        self.name = name
        self.settings = settings
        self.env = env
        self.clean = clean
        self.desk = uia.Desk()
        self.launcher = None            # until it is started
        self.window = None
        self.pid = 0
        self.hwnd = 0
        self.started_in = 0.0
        self.splash_seen = False
        self._seen: dict = {}

    # -- the folder it lives in ---------------------------------------------

    @property
    def home(self) -> Path:
        return SANDBOX

    @property
    def out(self) -> Path:
        return SANDBOX / "OUT"

    def _prepare(self) -> Path:
        import json
        exe = keep_exe_fresh()
        if self.clean:
            for rubbish in ("Logs", "OUT"):
                shutil.rmtree(SANDBOX / rubbish, ignore_errors=True)
            (SANDBOX / "settings.json").unlink(missing_ok=True)
        self.out.mkdir(parents=True, exist_ok=True)
        if self.settings is not None:
            (SANDBOX / "settings.json").write_text(
                json.dumps(self.settings, indent=2), encoding="utf-8")
        return exe

    # -- opening and closing -------------------------------------------------

    def start(self) -> "Viewer":
        exe = self._prepare()
        kill_strays()
        room = dict(os.environ)
        room.update(self.env or {})
        began = time.time()
        self.launcher = subprocess.Popen([str(exe)], cwd=str(SANDBOX), env=room)
        # Looked for straight away and often, because the loading window is
        # only up for a few seconds and a test that misses it cannot tell the
        # difference between "there was none" and "it went by".
        while time.time() - began < 6 and not self.splash_seen:
            self.splash_seen = self.desk.splash_up(self.launcher.pid)
            time.sleep(0.15)
        self.hwnd, self.pid = self.desk.wait_window(TITLE, within=STARTUP)
        if not self.hwnd:
            raise Timeout(f"no window in {STARTUP:.0f}s; log says:\n{self.log()}")
        self.started_in = time.time() - began
        # Up is not the same as ready: the picture, the machine checks and the
        # files all arrive after the window itself does.
        self.wait_until(lambda one: one.maybe("qa_mode") is not None,
                        "the window came up with nothing in it", within=90)
        return self

    def __enter__(self) -> "Viewer":
        return self.start()

    def __exit__(self, *_) -> None:
        self.stop()

    def stop(self) -> None:
        """Kill it. For the graceful way out, which saves settings, see `quit`."""
        if self.launcher is not None:
            subprocess.run(["taskkill", "/F", "/T", "/PID",
                            str(self.launcher.pid)], capture_output=True)
        kill_strays()

    def quit(self, within: float = 30.0) -> bool:
        """Close it the way a person does, so that it saves what it knows.

        Waited out on the process, not on the window: the window goes in a
        third of a second and the one-file stub is still there behind it,
        clearing away the folder it unpacked itself into.
        """
        self.front()
        winput.key("f4", "alt")
        deadline = time.time() + within
        while time.time() < deadline:
            if self.launcher.poll() is not None:
                return True
            time.sleep(0.2)
        self.stop()
        return False

    # -- what it is showing --------------------------------------------------

    def refresh(self) -> dict:
        self._seen = self.desk.snapshot(self.pid)
        return self._seen

    def at(self, qa: str, fresh: bool = True) -> uia.Node:
        """The widget with that name, or a failure that says what was there."""
        if fresh:
            self.refresh()
        found = self._seen.get(qa)
        if found is None:
            near = sorted(k for k in self._seen if k.startswith("qa_"))
            raise Timeout(f"no {qa} showing. Showing: {', '.join(near)}")
        return found

    def maybe(self, qa: str, fresh: bool = True) -> uia.Node | None:
        if fresh:
            self.refresh()
        return self._seen.get(qa)

    def wait_for(self, qa: str, within: float = 15.0) -> uia.Node:
        deadline = time.time() + within
        while time.time() < deadline:
            found = self.maybe(qa)
            if found is not None:
                return found
            time.sleep(0.25)
        return self.at(qa)              # for the message it raises

    def wait_gone(self, qa: str, within: float = 15.0) -> None:
        deadline = time.time() + within
        while time.time() < deadline:
            if self.maybe(qa) is None:
                return
            time.sleep(0.25)
        raise Timeout(f"{qa} is still showing after {within:.0f}s")

    def wait_until(self, what, why: str, within: float = 60.0,
                   every: float = 0.4):
        """Wait for something to become true of a fresh snapshot."""
        deadline = time.time() + within
        last = None
        while time.time() < deadline:
            self.refresh()
            try:
                last = what(self)
            except Timeout:
                last = None
            if last:
                return last
            time.sleep(every)
        raise Timeout(f"{why} -- not after {within:.0f}s")

    def says(self, qa: str) -> str:
        """The words a label or a field is showing."""
        node = self.at(qa)
        return (node.value or node.name or "").strip()

    # -- doing things to it --------------------------------------------------

    def in_front(self) -> bool:
        """Whether the window with the keyboard belongs to this application.

        The application's, not the main window's: while a modal window of its
        own is up -- the machine checks, a file picker -- the main window
        cannot come forward and must not, and a click aimed at the modal one
        is still a click on this application.
        """
        ahead = winput.foreground_window()
        return any(hwnd == ahead and pid == self.pid
                   for hwnd, pid, _, _, _ in winput.top_windows())

    def front(self, tries: int = 5) -> None:
        """Make sure this application really is the one in front.

        Strictly, and it fails rather than carries on: every key these tests
        press goes to whatever window has the keyboard, and a test that
        pressed Alt+F4 at a window it did not raise would close somebody
        else's work.
        """
        for turn in range(tries):
            if self.in_front():
                return
            # A modal window of its own comes first: raising the one behind it
            # is a thing Windows will not do anyway.
            for hwnd in self.desk.dialogs(self.pid, self.hwnd) + [self.hwnd]:
                winput.foreground(hwnd)
                if self.in_front():
                    return
            # A click on its own title bar, which is how a person raises a
            # window and is also what earns this process the right to.
            left, top, right, _ = winput.rect_of(self.hwnd)
            winput.click(min(left + 40, right - 10), top + 8, settle=0.25)
            time.sleep(0.2 * (turn + 1))
        raise Timeout("could not bring the viewer to the front -- nothing was "
                      f"typed, so no other window was touched. Up right now: "
                      f"{self.other_windows()}")

    def other_windows(self) -> list:
        """The application's windows apart from the main one, by their titles.

        A modal one of these is why the main window will not come forward, so
        it is what the failure above wants to say.
        """
        return [(klass, title)
                for hwnd, pid, klass, title, showing in winput.top_windows()
                if pid == self.pid and showing and hwnd != self.hwnd and title]

    def checks_up(self) -> bool:
        """Whether the machine-checks window is in front of everything."""
        return any("machine" in title.lower() or "проверк" in title.lower()
                   for _, title in self.other_windows())

    def click(self, qa: str, count: int = 1, settle: float = 0.35) -> uia.Node:
        node = self.at(qa)
        if not node.showing:
            raise Timeout(f"{qa} is not on the screen")
        self.front()
        winput.click(*node.middle, count=count, settle=settle)
        return node

    def click_at(self, x: int, y: int, count: int = 1) -> None:
        self.front()
        winput.click(x, y, count=count)

    def type_into(self, qa: str, text: str, enter: bool = True) -> None:
        """Click into a field, clear it, and type -- with the keyboard."""
        self.click(qa, settle=0.15)
        winput.key("a", "ctrl")
        winput.write(text)
        if enter:
            winput.key("enter")
        time.sleep(0.25)

    def choose(self, qa: str, text: str, within: float = 8.0) -> None:
        """Pick a line out of a drop-down, by opening it and clicking the line.

        Not by telling the box what to hold: on one machine these boxes came
        up as a native menu with the styled list beside it, and a test that
        never opened one would not have seen it.
        """
        self.click(qa, settle=0.4)
        deadline = time.time() + within
        while time.time() < deadline:
            line = self.maybe(f"item:{text}")
            if line is not None and line.showing:
                self.front()
                winput.click(*line.middle, settle=0.4)
                return
            time.sleep(0.2)
        lines = sorted(k[5:] for k in self._seen if k.startswith("item:"))
        winput.key("escape")
        raise Timeout(f"{qa} has no line {text!r}. It offers: {lines}")

    def offered(self, qa: str, within: float = 8.0) -> list[str]:
        """Every line a drop-down offers, read by opening it and looking."""
        self.click(qa, settle=0.4)
        deadline = time.time() + within
        lines: list[str] = []
        while time.time() < deadline:
            lines = [k[5:] for k in self.refresh() if k.startswith("item:")]
            if lines:
                break
            time.sleep(0.2)
        winput.key("escape")
        time.sleep(0.2)
        return lines

    def key(self, name: str, *held: str) -> None:
        self.front()
        winput.key(name, *held)

    def open_file(self, row: str, path: Path | str, within: float = 20.0) -> None:
        """Load a file into a row through the button and the file dialog."""
        self.click(f"qa_browse_{row.lower()}", settle=0.6)
        dialog = 0
        deadline = time.time() + within
        while time.time() < deadline and not dialog:
            up = self.desk.dialogs(self.pid, self.hwnd)
            dialog = up[0] if up else 0
            time.sleep(0.2)
        if not dialog:
            raise Timeout("no file dialog came up")
        for _ in range(6):
            winput.foreground(dialog)
            if winput.is_foreground(dialog):
                break
        else:
            raise Timeout("the file dialog would not come to the front")
        time.sleep(0.3)
        winput.write(str(path))
        winput.key("enter")
        time.sleep(0.8)

    # -- what it wrote down --------------------------------------------------

    def log_file(self) -> Path | None:
        logs = sorted((SANDBOX / "Logs").glob("*.log"),
                      key=lambda p: p.stat().st_mtime)
        return logs[-1] if logs else None

    def log(self) -> str:
        where = self.log_file()
        if where is None:
            return "(no log yet)"
        return where.read_text(encoding="utf-8", errors="replace")

    def log_has(self, text: str, within: float = 30.0) -> str:
        deadline = time.time() + within
        while time.time() < deadline:
            for line in self.log().splitlines():
                if text in line:
                    return line
            time.sleep(0.4)
        raise Timeout(f"the log never said {text!r}")

    def complaints(self) -> list[str]:
        """Anything in the log that reads like the application went wrong."""
        bad = []
        for line in self.log().splitlines():
            low = line.lower()
            if ("traceback" in low or "err]" in low
                    or "exception" in low or "could not" in low):
                bad.append(line)
        return bad

    # -- is it alive ---------------------------------------------------------

    def alive(self) -> bool:
        return self.launcher is not None and self.launcher.poll() is None

    def answering(self, within: float = 2.0) -> bool:
        return winput.answers(self.hwnd, within) and not winput.hung(self.hwnd)

    # -- pictures ------------------------------------------------------------

    def shot(self, tag: str = "") -> Path:
        SHOTS.mkdir(parents=True, exist_ok=True)
        left, top, right, bottom = winput.rect_of(self.hwnd)
        picture = winput.grab(left, top, right - left, bottom - top)
        where = SHOTS / f"{self.name}{'_' + tag if tag else ''}.png"
        picture.save(where)
        return where

    def picture_of(self, qa: str):
        """What is on the pixels of one widget, as an image."""
        node = self.at(qa)
        self.front()
        time.sleep(0.2)
        return winput.grab(node.left, node.top, node.wide, node.tall)
