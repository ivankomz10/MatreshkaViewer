"""The advanced mode, step by step (docs/advanced_mode.md), in the window.

Step 1: the switch, the column of screens and the drawer. Simple is the
viewer as it was: nothing of the advanced mode shows in it.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QWidget


@pytest.fixture
def advanced(window, tick):
    window.set_advanced(True)
    tick(0.1)
    yield window
    window.drawer.pin.setChecked(False)
    window.set_advanced(False)
    tick(0.1)


def press_at(window, where: QPoint) -> None:
    """A press of the mouse at a point of the screen, as the click-away sees it."""
    target = window.canvas
    local = QPointF(target.mapFromGlobal(where))
    event = QMouseEvent(QEvent.Type.MouseButtonPress, local, QPointF(where),
                        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(target, event)


def test_simple_is_the_viewer_as_it_was(window, tick):
    window.set_advanced(False)
    tick(0.1)
    assert window.ui_buttons["simple"].isChecked()
    assert not window.rail.isVisible() and not window.drawer.isVisible()
    assert window._settings_now()["advanced"] is False


def test_advanced_shows_the_screens_and_is_remembered(advanced):
    window = advanced
    assert window.ui_buttons["advanced"].isChecked() and window.rail.isVisible()
    assert [name for name in window.rail.buttons] == ["Top", "Bottom", "Lamels", "Sound", "Kinetic"]
    assert window._settings_now()["advanced"] is True


def test_a_screen_button_opens_its_drawer_with_the_rows_source(advanced, clips, tick):
    window = advanced
    window.rail.buttons["Bottom"].click()
    tick(0.1)
    drawer = window.drawer
    assert drawer.isVisible() and drawer.key == "Bottom"
    assert drawer.title.text() == "BOT · Bottom"
    row = next(one for one in window.rows if one.title == "Bottom")
    assert drawer.card.file.text() == row.file.text() and row.file.text()
    # Against the rail, as tall as the picture.
    assert drawer.geometry().right() < window.rail.geometry().left() + 2
    assert drawer.height() == window.drawer_host.height()
    # The brightness is the row's: moved here, it moves there, and back.
    drawer.card.gain.setValue(140)
    assert row.gain.value() == 140
    row.gain.setValue(100)
    assert drawer.card.gain.value() == 100
    # The same button again puts it away; another opens its own.
    window.rail.buttons["Top"].click()
    tick(0.1)
    assert drawer.key == "Top" and window.rail.buttons["Top"].isChecked()
    window.rail.buttons["Top"].click()
    tick(0.1)
    assert not drawer.isVisible() and not any(b.isChecked() for b in window.rail.buttons.values())


def test_a_click_elsewhere_puts_the_drawer_away_unless_pinned(advanced, tick):
    window = advanced
    window.rail.buttons["Lamels"].click()
    tick(0.1)
    away = window.canvas.mapToGlobal(QPoint(10, 10))
    window.drawer.pin.setChecked(True)
    press_at(window, away)
    tick(0.05)
    assert window.drawer.isVisible()
    window.drawer.pin.setChecked(False)
    press_at(window, away)
    tick(0.05)
    assert not window.drawer.isVisible() and window.rail.open == ""


def test_back_to_simple_takes_it_all_away(advanced, tick):
    window = advanced
    window.rail.buttons["Top"].click()
    tick(0.1)
    window.ui_buttons["simple"].click()
    tick(0.1)
    assert not window.rail.isVisible() and not window.drawer.isVisible()
    assert window.advanced is False
