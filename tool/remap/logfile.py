"""The remap page writes into the viewer's log.

Standalone, Matreshka Remap kept a log of its own and caught stdout and
stderr into it. Inside the viewer there is one program and one log: the
viewer's `logfile` already does all of that, so this only hands the lines
on, marked as the remap's.
"""
from __future__ import annotations

import logfile as viewer_log            # the viewer's own


def start():
    """The viewer started the log long before this page was built."""
    return None


def write(message: str) -> None:
    viewer_log.write(f"remap: {message}")


def path():
    return viewer_log.path()
