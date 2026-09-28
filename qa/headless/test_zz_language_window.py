"""A window that opens in English: the one test here that builds a window.

Last of the suite on purpose -- the name sorts it there. A second window's
canvas takes the drawing over from the suite's window for good (rendercanvas
draws the newest canvas it has; the application only ever has the one), so
any test after this would find the suite's window no longer drawing.
Switching the language of a window that is up is tested in test_lang.py,
on the suite's own window, because it builds nothing.
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
    for one in made:
        one.close()
        one.deleteLater()
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
