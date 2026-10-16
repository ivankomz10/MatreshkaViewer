"""The viewer's window with its two other pages: the kinetic editor and the
remap, built in it the first time they are opened.

Last of the suite on purpose, after test_zzz_kinedit.py: a page brings a
canvas of its own. Nothing here clicks -- the tests call what the page
buttons call and read what the window then holds. The remap's first-run list
of what the machine has is answered in the sandbox's remap_tool.json before
the page is built, so no dialog waits for a hand.
"""
from __future__ import annotations

import json

import pytest

from conftest import HOME, TOOL


@pytest.fixture(scope="module")
def paged(window):
    settings = HOME / "remap_tool.json"
    settings.write_text(json.dumps({"checked_dependencies": True}), encoding="utf-8")
    yield window
    window.show_page("viewer")


def test_the_window_opens_on_the_viewer_with_the_pages_unbuilt(paged):
    assert paged._on_viewer_page()
    assert set(paged.page_buttons) == {"viewer", "kinetic"}
    assert paged.remap_window is None
    assert paged.page_buttons["viewer"].isChecked()


def test_the_kinetic_page_is_the_editor_drawing_in_the_same_window(paged, tick):
    import kinedit
    paged.show_page("kinetic")
    tick(1.0)
    editor = paged.page_widgets["kinetic"]
    assert isinstance(editor, kinedit.KineticEditor)
    assert editor.window() is paged, "a page, not a window of its own"
    assert editor.solid is not None, editor.failure
    assert not paged._on_viewer_page()
    assert editor.viewer_hook is not None


def test_a_key_on_one_page_is_not_taken_by_the_other(paged, tick):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    paged.show_page("kinetic")
    tick(0.2)
    space = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier, " ")
    playing = paged.clock.playing
    assert paged.eventFilter(paged.page_widgets["kinetic"], space) is False
    assert paged.clock.playing == playing, "the viewer played from the editor's page"
    paged.show_page("viewer")
    tick(0.2)
    assert paged.page_widgets["kinetic"].eventFilter(paged.canvas, space) is False


def test_in_the_viewer_hands_the_piece_to_this_window(paged, tick):
    paged.show_page("kinetic")
    tick(0.2)
    editor = paged.page_widgets["kinetic"]
    editor.dirty = False
    editor.new_project()
    folder = HOME / "kinedit"
    folder.mkdir(parents=True, exist_ok=True)
    editor.project.path = folder / "pages_check.kin"
    assert editor.show_in_viewer(asked=True)
    tick(0.5)
    assert paged._on_viewer_page()
    assert paged.row_for("Kinetic").field.text().endswith("_1_of_1.json")


def test_the_remap_is_a_window_over_the_viewer_keeping_its_work_beside_it(paged, tick):
    paged.open_remap()
    tick(1.0)
    from remap import constants
    made = paged.remap_window
    assert made.isWindow() and made.parent() is paged, "a window of the viewer's own"
    assert made.isVisible()
    paged.open_remap()
    assert paged.remap_window is made, "called up again, the same window"
    assert constants.PROJECT_DIR == HOME, "the remap's settings would go elsewhere"
    assert constants.tables_present()
    for name in ("full", "half", "quarter"):
        assert constants.table_path(name).parent == TOOL / "remap" / "tables"
    assert constants.find_overlay() is not None
    # Its look stays on its own page.
    from PySide6.QtWidgets import QApplication
    assert "#232323" not in QApplication.instance().styleSheet()


def test_the_remap_draws_a_still_dropped_on_it(paged, tick):
    """A picture dropped on the remap's preview goes through the table, as
    it did in the remap on its own."""
    from PySide6.QtGui import QImage
    paged.open_remap()
    made = paged.remap_window
    still = HOME / "remap_still.png"
    picture = QImage(200, 236, QImage.Format.Format_RGB32)
    picture.fill(0xFF3070C0)
    picture.save(str(still))
    made._handle_drop(still)
    tick(1.5)
    image = made.view._item.pixmap().toImage()
    assert image.width() > 1000, "the warp did not reach the preview"
    blue = [image.pixelColor(x, y).blue() for x in range(0, image.width(), 41)
            for y in range(0, image.height(), 41)]
    assert max(blue) > 100, "nothing of the still reached the preview"


def test_the_viewer_still_draws_after_the_other_pages(paged, tick):
    """Each page brings a canvas of its own; the viewer's must go on
    drawing when it is in front again."""
    paged.show_page("kinetic")
    tick(0.3)
    paged.open_remap()
    tick(0.3)
    paged.remap_window.hide()
    paged.show_page("viewer")
    tick(0.3)
    before = paged.drawn
    for _ in range(5):
        paged.touch()
        tick(0.15)
    inner = paged.canvas._subwidget
    scheduler = inner._BaseRenderCanvas__scheduler
    state = (f"draw asked {scheduler._draw_requested}, waiting for a present "
             f"{scheduler._ready_for_present is not None}, visible {inner.isVisible()}, "
             f"size {inner.get_physical_size()}, job {paged.job}")
    assert paged.drawn > before, "the viewer's picture stopped drawing: " + state
    editor = paged.page_widgets["kinetic"]
    paged.show_page("kinetic")
    tick(0.3)
    editor.go_to(30)
    tick(0.3)
    paged.show_page("viewer")
