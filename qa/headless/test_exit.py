"""The program's end, as the log tells it.

On a station a viewer once stopped answering at its very end: the window
gone, the program not. The log said why only as a drawing library's error
repeated every frame. Now it says it once, as what it is.
"""
from __future__ import annotations

import logging

import logfile


def test_the_drawing_loop_outliving_the_window_is_said_once(monkeypatch):
    lines = []
    monkeypatch.setattr(logfile, "write", lambda message, tag="": lines.append(message))

    class App:
        class aboutToQuit:                       # noqa: N801 -- Qt's name
            connected = []

            @classmethod
            def connect(cls, call):
                cls.connected.append(call)

    logger = logging.getLogger("rendercanvas")
    before = list(logger.filters)
    try:
        logfile.quiet_after_quit(App)
        for _ in range(5):
            logger.warning("Error in CallLaterThread callback: Signal source has been deleted")
        logger.warning("something else")
        said = [one for one in lines if one.startswith("exit:")]
        assert said == ["exit: the drawing loop outlived the window; the program is "
                        "finishing"]
    finally:
        logger.filters[:] = before
