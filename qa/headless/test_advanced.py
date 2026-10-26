"""The advanced mode, step by step (docs/advanced_mode.md), in the window.

Step 1: the switch, the column of screens and the drawer. Simple is the
viewer as it was: nothing of the advanced mode shows in it.
"""
from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QWidget

from conftest import PREVIEW


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


# -- step 2: the compositor in the quick look ---------------------------------------

def _pictures(window, tick):
    """The building as the file camera sees it, and every screen's strip."""
    window.touch()
    tick(0.4)
    window.touch()
    tick(0.2)
    building = window.solid.to_array(270, 480).astype(np.float32)
    strips = {name: window._screen_to_array(name, *window._pixels(name)).astype(np.float32)
              for name in ("Screen_Top", "Screen_Bottom", "Lamel_screen")}
    return building, strips


def test_advanced_with_no_layers_shows_what_simple_shows(window, tick):
    window.set_advanced(False)
    tick(0.3)
    assert not window.composers
    building, strips = _pictures(window, tick)
    window.set_advanced(True)
    tick(0.3)
    try:
        # Every screen through a compositor of its own, and the scene on it.
        assert set(window.composers) == {"Screen_Top", "Screen_Bottom", "Lamel_screen"}
        building2, strips2 = _pictures(window, tick)
        # The strips are the same to a hair. The building only nearly: the
        # test clips are a tenth of the screens' size and the composite is
        # the screen's full size, so the honeycomb's fine pattern, shrunk
        # into a small picture with no mip levels, shimmers differently. A
        # movie the size of its screen has no such difference.
        assert np.abs(building2 - building).mean() < 4.0
        for name, strip in strips.items():
            assert strips2[name].shape == strip.shape
            assert np.abs(strips2[name] - strip).mean() < 0.1, name
    finally:
        window.set_advanced(False)
        tick(0.3)
    assert not window.composers


# -- step 3: picture layers ------------------------------------------------------------

def test_a_picture_layer_lies_on_its_screen_and_is_kept(advanced, tick, tmp_path):
    from PIL import Image
    window = advanced
    red = np.zeros((40, 40, 4), np.uint8)
    red[..., 0], red[..., 3] = 255, 255
    path = tmp_path / "red.png"
    Image.fromarray(red).save(path)
    window.rail.buttons["Bottom"].click()
    tick(0.1)
    stack = window.drawer.stack
    assert stack is not None and not stack.rows()
    try:
        made = stack.add_pictures([str(path)])
        tick(0.3)
        assert len(made) == 1 and len(stack.rows()) == 1
        layer = made[0]
        across, down = window._pixels("Screen_Bottom")
        strip = window._screen_to_array("Screen_Bottom", across, down).astype(np.float32)
        # Fitted whole: a square in the middle of the wide frame, red on it.
        middle = strip[down // 2, across // 2]
        assert middle[0] > 240 and middle[1] < 15 and middle[2] < 15
        edge = strip[down // 2, 5]
        assert not (edge[0] > 240 and edge[1] < 15)            # the video beside it
        # Half opacity: half red.
        layer.opacity = 0.5
        window.touch()
        tick(0.3)
        half = window._screen_to_array("Screen_Bottom", across, down)[down // 2, across // 2]
        assert 100 < half[0] < 250
        # Hidden, and the video is back.
        layer.visible = False
        window.touch()
        tick(0.3)
        hidden = window._screen_to_array("Screen_Bottom", across, down)[down // 2, across // 2]
        assert not (hidden[0] > 240 and hidden[1] < 15)
        layer.visible = True
        assert window._settings_now()["layers"]["Bottom"][0]["path"] == str(path)
        # Simple mode lays no layers at all.
        window.set_advanced(False)
        tick(0.3)
        plain = window._screen_to_array("Screen_Bottom", across, down)[down // 2, across // 2]
        assert not (plain[0] > 240 and plain[1] < 15)
    finally:
        window.layer_stacks = __import__("layers").Stacks()
        window.set_advanced(False)
        tick(0.2)


# -- step 4: the transform -------------------------------------------------------------

def test_a_picture_is_dragged_scaled_and_turned_where_it_is_seen(advanced, tick, tmp_path):
    from PIL import Image
    import layers as stacks
    window = advanced
    Image.fromarray(np.full((40, 40, 4), 255, np.uint8)).save(tmp_path / "white.png")
    window.mode.setCurrentText("Flat")
    tick(0.3)
    window.rail.buttons["Bottom"].click()
    tick(0.1)
    stack = window.drawer.stack
    try:
        layer = stack.add_pictures([str(tmp_path / "white.png")])[0]
        tick(0.2)
        assert stack.transform.isVisible() and stack.transform.layer is layer
        stack.move_button.setChecked(True)
        assert window.layer_tool
        wide, tall = window.canvas.get_logical_size()
        boxes = dict(window._strips(window._flat_showing(), int(wide), int(tall)))
        left, top, across, down = boxes["Screen_Bottom"]
        frame = window._pixels("Screen_Bottom")
        at = (left + across * 0.5, top + down * 0.5)
        window._canvas_event({"event_type": "pointer_down", "x": at[0], "y": at[1], "button": 1})
        window._canvas_event({"event_type": "pointer_move", "x": at[0] + across * 0.1, "y": at[1], "buttons": (1,)})
        window._canvas_event({"event_type": "pointer_up", "x": at[0] + across * 0.1, "y": at[1], "button": 1})
        assert abs(layer.x - frame[0] * 0.1) < 2 and abs(layer.y) < 2
        assert abs(stack.transform.fields["x"].value() - layer.x) < 0.11
        window._canvas_event({"event_type": "wheel", "x": at[0], "y": at[1], "dy": -120})
        assert abs(layer.scale - 1.06) < 1e-6
        window._canvas_event({"event_type": "pointer_down", "x": at[0], "y": at[1], "button": 1,
                              "modifiers": ("Shift",)})
        window._canvas_event({"event_type": "pointer_move", "x": at[0] + 50, "y": at[1], "buttons": (1,)})
        window._canvas_event({"event_type": "pointer_up", "x": at[0] + 50, "y": at[1], "button": 1})
        assert abs(layer.rotation - 20.0) < 1e-6
        # Typed in the panel, and back to fitted.
        stack.transform.fields["y"].setValue(-30)
        assert layer.y == -30
        stack.transform.findChild(QWidget, "qa_transform_fit").click()
        assert (layer.x, layer.y, layer.scale, layer.rotation) == (0, 0, 1.0, 0)
        # The tool off, and the hand moves the view again.
        stack.move_button.setChecked(False)
        assert not window.layer_tool
    finally:
        window.layer_stacks = stacks.Stacks()
        window.mode.setCurrentText(PREVIEW)


# -- step 5: the remap by the camera ---------------------------------------------------

def test_a_remapped_picture_lies_as_the_camera_sees_it_and_drags_there(advanced, tick, tmp_path):
    from PIL import Image
    import layers as stacks
    window = advanced
    red = np.zeros((90, 160, 4), np.uint8)
    red[..., 0], red[..., 3] = 255, 255
    Image.fromarray(red).save(tmp_path / "red.png")
    window.rail.buttons["Bottom"].click()
    tick(0.1)
    stack = window.drawer.stack
    try:
        layer = stack.add_pictures([str(tmp_path / "red.png")])[0]
        tick(0.2)
        panel = stack.transform
        assert not layer.remap and "кадра" in panel.head.text()
        layer.x = 40.0
        panel.bind.setCurrentIndex(panel.bind.findData("camera"))
        assert layer.remap and layer.x == 0.0 and "камере" in panel.head.text()
        tick(0.3)
        across, down = window._pixels("Screen_Bottom")
        got = window._screen_to_array("Screen_Bottom", across, down)
        reddish = (got[..., 0] > 240) & (got[..., 1] < 15)
        # Only where the camera sees the screen: some of it, never all of it.
        assert 0.01 < reddish.mean() < 0.9, reddish.mean()
        assert window._settings_now()["layers"]["Bottom"][0]["bind"] == "camera"
        # Dragged on the flat strip, it moves in the camera's pixels.
        window.mode.setCurrentText("Flat")
        tick(0.3)
        stack.move_button.setChecked(True)
        wide, tall = window.canvas.get_logical_size()
        boxes = dict(window._strips(window._flat_showing(), int(wide), int(tall)))
        left, top, strip, high = boxes["Screen_Bottom"]
        at = (left + strip * 0.45, top + high * 0.5)
        start = window._camera_under({"x": at[0], "y": at[1]})
        to = (at[0] + strip * 0.05, at[1] - high * 0.2)
        end = window._camera_under({"x": to[0], "y": to[1]})
        assert start is not None and end is not None
        window._canvas_event({"event_type": "pointer_down", "x": at[0], "y": at[1], "button": 1})
        window._canvas_event({"event_type": "pointer_move", "x": to[0], "y": to[1], "buttons": (1,)})
        window._canvas_event({"event_type": "pointer_up", "x": to[0], "y": to[1], "button": 1})
        assert abs(layer.x - (end[1][0] - start[1][0])) < 1e-6
        assert abs(layer.y + (end[1][1] - start[1][1])) < 1e-6
        assert end[1][1] < start[1][1] and layer.y > 0       # dragged up: plus
        # Back to the frame's pixels, fitted again.
        panel.bind.setCurrentIndex(panel.bind.findData("frame"))
        assert not layer.remap and (layer.x, layer.y) == (0.0, 0.0)
        stack.move_button.setChecked(False)
    finally:
        window.layer_stacks = stacks.Stacks()
        window.mode.setCurrentText(PREVIEW)
        tick(0.2)


# -- step 6: decal and the view's projector ---------------------------------------------

def test_a_decal_is_put_where_pointed_and_a_projector_thrown_from_the_view(advanced, tick, tmp_path):
    from PIL import Image
    import layers as stacks
    window = advanced
    red = np.zeros((90, 160, 4), np.uint8)
    red[..., 0], red[..., 3] = 255, 255
    Image.fromarray(red).save(tmp_path / "red.png")
    window.rail.buttons["Bottom"].click()
    tick(0.1)
    stack = window.drawer.stack
    try:
        layer = stack.add_pictures([str(tmp_path / "red.png")])[0]
        tick(0.2)
        panel = stack.transform
        panel.bind.setCurrentIndex(panel.bind.findData("decal"))
        assert layer.bind == "decal" and layer.anchor is not None and layer.normal is not None
        assert "поверхности" in panel.head.text() and not panel.aim.isVisible()
        tick(0.3)
        across, down = window._pixels("Screen_Bottom")
        got = window._screen_to_array("Screen_Bottom", across, down)
        reddish = (got[..., 0] > 240) & (got[..., 1] < 15)
        assert 0.001 < reddish.mean() < 0.5, reddish.mean()
        # Dragged on the strip, its middle goes where the hand is.
        window.mode.setCurrentText("Flat")
        tick(0.3)
        stack.move_button.setChecked(True)
        wide, tall = window.canvas.get_logical_size()
        boxes = dict(window._strips(window._flat_showing(), int(wide), int(tall)))
        left, top, strip, high = boxes["Screen_Bottom"]
        at = (left + strip * 0.3, top + high * 0.5)
        window._canvas_event({"event_type": "pointer_down", "x": at[0], "y": at[1], "button": 1})
        window._canvas_event({"event_type": "pointer_up", "x": at[0], "y": at[1], "button": 1})
        want = window._rest_under({"x": at[0], "y": at[1]})
        assert np.allclose(layer.anchor, want[2]) and np.allclose(layer.normal, want[3])
        saved = window._settings_now()["layers"]["Bottom"][0]
        assert saved["bind"] == "decal" and len(saved["anchor"]) == 3
        stack.move_button.setChecked(False)
        # Thrown from the view: the projector is the view's camera as it stands.
        window.mode.setCurrentText(PREVIEW)
        tick(0.3)
        panel.bind.setCurrentIndex(panel.bind.findData("view"))
        assert layer.bind == "view" and panel.aim.isVisible()
        assert np.allclose(np.reshape(layer.projector, (4, 4)), window.mesh.view_projection())
        tick(0.3)
        got = window._screen_to_array("Screen_Bottom", across, down)
        assert ((got[..., 0] > 240) & (got[..., 1] < 15)).mean() > 0.001
        back = stacks.Layer.from_dict(layer.to_dict())
        assert back.bind == "view" and np.allclose(back.projector, layer.projector)
    finally:
        window.layer_stacks = stacks.Stacks()
        window.mode.setCurrentText(PREVIEW)
        tick(0.2)


# -- step 7: video in layers -----------------------------------------------------------

def test_a_movie_dropped_in_a_drawer_plays_on_its_screen(advanced, clips, tick):
    import layers as stacks
    window = advanced
    window.rail.buttons["Bottom"].click()
    tick(0.1)
    stack = window.drawer.stack
    across, down = window._pixels("Screen_Bottom")
    window._move(0.0)
    tick(0.3)
    plain = window._screen_to_array("Screen_Bottom", across, down)
    try:
        layer = stack.add_pictures([str(clips["top"])])[0]
        assert layer.kind == "video"
        panel = stack.transform
        assert panel.isVisible() and panel.start.isVisible() and panel.loop.isVisible()
        for _ in range(40):
            tick(0.05)
            if window._pictures().movies.get(layer).showing:
                break
        tick(0.2)
        first = window._screen_to_array("Screen_Bottom", across, down)
        assert np.abs(first - plain).mean() > 0.01            # the movie is over the source
        window._move(0.6)
        for _ in range(40):
            tick(0.05)
            movie = window._pictures().movies.get(layer)
            if movie.on_card is not None and movie.on_card >= movie.stream.index_at(0.6):
                break
        tick(0.2)
        later = window._screen_to_array("Screen_Bottom", across, down)
        assert np.abs(later - first).mean() > 0.001           # and it moved on with the clock
        # Started later than the clock: nothing of it yet.
        panel.start.setValue(30.0)
        assert layer.offset == 30.0
        tick(0.3)
        assert not window._pictures().movies.get(layer).showing
        saved = window._settings_now()["layers"]["Bottom"][0]
        assert saved["kind"] == "video" and saved["offset"] == 30.0
        # Gone from the stack, the movie is let go of.
        stack.choose(layer)
        stack.findChild(QWidget, "qa_stack_delete").click()
        tick(0.2)
        assert not window._pictures().movies._held
    finally:
        window.layer_stacks = stacks.Stacks()
        window._move(0.0)
        tick(0.2)


# -- step 8: masks and effects ---------------------------------------------------------

def test_a_mask_and_effects_from_the_drawer(advanced, tick, tmp_path):
    from PIL import Image
    import layers as stacks
    import logfile
    window = advanced
    red = np.zeros((90, 160, 4), np.uint8)
    red[..., 0], red[..., 3] = 255, 255
    Image.fromarray(red).save(tmp_path / "red.png")
    window.rail.buttons["Bottom"].click()
    tick(0.1)
    stack = window.drawer.stack
    across, down = window._pixels("Screen_Bottom")
    try:
        layer = stack.add_pictures([str(tmp_path / "red.png")])[0]
        layer.scale = 4.0                                   # over the whole frame
        stack.changed_picture()
        tick(0.3)
        middle = window._screen_to_array("Screen_Bottom", across, down)[down // 2, across // 2]
        assert middle[0] > 0.9 and middle[1] < 0.05
        # An HSL effect, chosen as it is made: its numbers below the stack.
        effect = stack.add_effect("hsl")
        assert stack.effect_panel.isVisible() and stack.effect_panel.effect is effect
        assert stack.findChild(QWidget, f"qa_effect_{effect.key}") is not None
        stack.effect_panel.fields["saturation"].setValue(-100)
        assert effect.saturation == -1.0
        tick(0.3)
        grey = window._screen_to_array("Screen_Bottom", across, down)[down // 2, across // 2]
        assert abs(grey[0] - grey[1]) < 0.02 and abs(grey[1] - grey[2]) < 0.02
        # A mask: the brush's target goes to it, the orange line with it.
        stack.choose(layer)
        stack.findChild(QWidget, "qa_stack_mask").click()
        assert layer.mask and layer.target == "mask"
        row = stack.findChild(QWidget, f"qa_layer_{layer.ident}")
        assert "f0883e" in row.mask_thumb.styleSheet() and "f0883e" not in row.thumb.styleSheet()
        mask = window._pictures().rasters.mask(layer, (across, down))
        mask.array[:, : across // 2, :3] = 0                # the left half hidden
        mask.touch()
        tick(0.3)
        got = window._screen_to_array("Screen_Bottom", across, down)
        assert np.abs(got[down // 2, across // 4] - middle).max() > 0.2      # what is under, at the left
        assert abs(got[down // 2, 3 * across // 4][0] - grey[0]) < 0.02    # grey at the right
        # Kept: the stack in the settings, the mask beside them.
        window._remember(now=True)
        saved = window._settings_now()["layers"]["Bottom"][0]
        assert saved["mask"] and saved["effects"][0]["kind"] == "hsl"
        assert (logfile.app_dir() / "layers" / layer.mask_raster).exists()
        # Paint as the target: chosen from its row.
        paint = stack.add_effect("paint")
        assert layer.target == f"paint:{paint.key}"
        stack.findChild(QWidget, f"qa_effect_{paint.key}").findChild(QWidget, "qa_effect_drop").click()
        assert paint not in layer.effects and layer.target == "content"
    finally:
        window.layer_stacks = stacks.Stacks()
        tick(0.2)
