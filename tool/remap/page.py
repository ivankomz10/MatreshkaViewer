"""The remap's window, made to sit inside the viewer's as a page."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QStyleFactory, QWidget

from . import constants, logfile
from . import main as remap_main


def make() -> QWidget:
    """Matreshka Remap's main window, as it is, turned into a widget.

    Standalone it set the Fusion style, its palette and its sheet on the whole
    application. Here they go on its own window and everything in it, so the
    viewer's pages keep their own look.
    """
    for line in constants.ensure_project_files():
        logfile.write(line)
    window = remap_main.MainWindow()
    window.setWindowFlags(Qt.WindowType.Widget)
    fusion = QStyleFactory.create("Fusion")
    if fusion is not None:
        fusion.setParent(window)
        for one in [window, *window.findChildren(QWidget)]:
            one.setStyle(fusion)
    window.setPalette(remap_main.dark_palette())
    window.setStyleSheet(remap_main.STYLESHEET)
    logfile.write(f"page built; settings in {constants.PROJECT_DIR / constants.SETTINGS_FILE}")
    return window
