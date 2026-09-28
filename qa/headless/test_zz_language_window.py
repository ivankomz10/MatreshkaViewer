"""The window in English, and switching: the tests that build windows.

Last of the suite on purpose -- the name sorts it there. A second window's
canvas takes the drawing over from the suite's window for good (rendercanvas
draws the newest canvas it has; the application only ever has one window,
and `rebuild` closes the old one the moment the new one is up), so any test
after these would find the suite's window no longer drawing.
"""
from __future__ import annotations

import pytest

from conftest import settings, write_settings


@pytest.fixture
def english(window, clips, tick):
    """A second window, built in English, next to the one the suite uses."""
    import lang
    import main as viewer
    write_settings(settings(clips, language="en"))
    made = []

    def build():
        one = viewer.Viewer()
        from PySide6.QtCore import Qt
        one.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        one.show()
        tick(1.5)
        made.append(one)
        return one

    yield build
    for one in list(viewer._alive) + made:
        try:
            if one is not window:
                # Closed and let go of, as `rebuild` does: a window closed and
                # kept stops the one the rest of the suite uses drawing.
                one.close()
                one.deleteLater()
        except RuntimeError:
            pass                          # deleted already, by a rebuild
    viewer._alive[:] = [window]
    lang.set_language("ru")
    write_settings(settings(clips))
    tick(0.5)


def test_an_english_window_says_it_in_english(english):
    one = english()
    assert one.level_buttons["view"].text() == "Quick look"
    assert one.level_buttons["show"].text() == "Show"
    assert [one.mode.buttons[key].text() for key in one.mode._keys] == [
        "Preview", "Flat", "Inspection", "ReBake"]
    assert one.sources_head.text() == "Sources"
    assert one.sources_count.text() == "3 of 6 loaded"
    assert one.matching.text() == "Match brightness"
    assert one.linked.text() == "Link"
    assert one.language_buttons["en"].isChecked()
    assert not one.language_buttons["ru"].isChecked()
    assert one.frame_label.text().startswith("frame ")
    assert one.stats_head.text().startswith("Decoder stats")
    # The lists that a session remembers by their words.
    assert one.rebake_what.currentText() == "Clean"
    assert one.sync.currentText() == "60 fps"


def test_switching_makes_the_window_again_where_it_was(english, tick):
    import lang
    import main as viewer
    one = english()
    one._move(0.5)
    one.history.back.append(("перенос клипа", None, {}))
    tick(0.3)
    was = one._frame_now()[0]
    one._choose_language("ru")
    tick(2.5)
    assert lang.language() == "ru"
    again = viewer._alive[-1]
    assert again is not one, "the window was not made again"
    assert again.level_buttons["view"].text() == "Просмотр"
    assert again.language_buttons["ru"].isChecked()
    assert again._frame_now()[0] == was, "the playhead did not stay"
    assert again.history.back and again.history.back[-1][0] == "перенос клипа"
    import logfile
    assert logfile.load_settings().get("language") == "ru"
