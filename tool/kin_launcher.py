"""MatreshkaKinetic.exe: the kinetic editor's own door into the viewer's program.

The editor is not a second copy of a hundred megabytes of Qt, wgpu and the
baked building. It lives inside MatreshkaViewer.exe and starts with
`--kinetic`; this is a few megabytes of Python that sits beside it, has the
editor's name, and asks for exactly that -- with whatever file was dropped on
it passed along.
"""
from __future__ import annotations

import os
import subprocess
import sys

VIEWER = "MatreshkaViewer.exe"


def main() -> int:
    here = os.path.dirname(os.path.abspath(sys.executable))
    target = os.path.join(here, VIEWER)
    if not os.path.isfile(target):
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            None, f"{VIEWER} is not beside MatreshkaKinetic.exe.\n"
                  f"{VIEWER} не найден рядом с MatreshkaKinetic.exe.",
            "Matreshka Kinetic", 0x10)
        return 1
    subprocess.Popen([target, "--kinetic", *sys.argv[1:]], close_fds=True,
                     cwd=here)
    return 0


if __name__ == "__main__":
    sys.exit(main())
