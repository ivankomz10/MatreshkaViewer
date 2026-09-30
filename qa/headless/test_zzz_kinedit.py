"""The kinetic editor's window, built in this process like the viewer's.

Last of the suite on purpose, after test_zz_language_window.py: the editor has
a canvas of its own, and a second canvas takes the drawing over from the
suite's window for good (rendercanvas draws the newest canvas it has).

Nothing here clicks: the tests call what the tools, the timeline and the 3D
view call, and read what the window then holds, draws and writes -- the
writing into the sandbox, like everything else in the suite.
"""
from __future__ import annotations

import re

import numpy as np
import pytest

from conftest import HOME, TOOL, settle

import kin_model as km
from kinetic import PER_PUSHER, PER_ROW, ROWS

OUT = HOME / "kinedit"
CYR = re.compile("[А-Яа-яЁё]")
# Said as the window goes: the clock, the line under the pointer, the status.
VOLATILE = {"qa_kin_clock", "qa_kin_hover", "qa_kin_status", "qa_kin_project"}


@pytest.fixture(scope="module")
def editor():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    import theme
    import kinedit
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    theme.load_fonts(TOOL / "fonts")
    app.setFont(theme.app_font())
    app.setStyleSheet(theme.sheet())
    one = kinedit.KineticEditor(language="ru")
    one.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
    one.show()
    settle(app, 1.5)
    yield one
    one.dirty = False
    one.close()
    one.deleteLater()
    settle(app, 0.3)


@pytest.fixture
def fresh(editor, tick):
    """The editor on a new, resting piece, the brush chosen, nothing picked."""
    editor.dirty = False
    editor.new_project()
    editor._choose_tool("brush")
    editor.select_none()
    editor.set_mask(True)
    editor.set_show_all(True)
    editor.go_to(0)
    tick(0.1)
    return editor


def test_the_editor_opens_on_a_resting_piece(fresh):
    assert fresh.solid is not None, fresh.failure
    for family in km.FAMILIES:
        track = fresh.project.tracks[family]
        assert track.frames == [0] and track.keyed_count(0) == track.size
    assert fresh.timeline.project is fresh.project
    assert fresh.windowTitle().startswith("Matreshka Kinetic")


def test_a_brush_stroke_keys_what_it_touched_at_the_playhead(fresh, tick):
    fresh.set_family("push")
    fresh.brush_push = 0.7
    fresh.brush_strength = 1.0
    fresh.go_to(240)
    fresh.begin_edit()
    fresh._dab(fresh._weights_at((12, 20)))
    fresh.end_edit()
    track = fresh.project.tracks["push"]
    assert track.frames == [0, 240]
    touched = track.keyed_count(1)
    assert 0 < touched < track.size, "a stroke keyed every pusher"
    assert fresh.pose_now()["push"][12, 4] == pytest.approx(0.7)
    fresh._step_undo(True)
    assert track.frames == [0]
    fresh._step_undo(False)
    assert track.frames == [0, 240] and track.keyed_count(1) == touched


def test_edits_are_held_to_the_gaps_as_they_are_made(fresh):
    rings = np.zeros(ROWS, bool)
    rings[10] = True
    fresh.set_rings(rings, 0)                # the gap above ring 11 closed
    cells = np.zeros((ROWS, PER_ROW), bool)
    cells[10, :] = cells[5, :] = True
    fresh._select(cells, "set")
    fresh.set_selected("tilt", 0.3)
    tilt = fresh.pose_now()["tilt"]
    # Face down into a closed gap: Houdini's 2 degrees; into 330 mm, 10.
    assert np.allclose(tilt[10], 2 / 90), "a ring over a closed gap tilted"
    assert np.allclose(tilt[5], 10 / 90), "not held to 10 degrees at state 1"


def test_the_vase_pushes_every_ring_and_lays_the_cells_along_it(fresh):
    fresh._choose_tool("profile")
    fresh.begin_edit()
    fresh.apply_profile([(0.0, 0.0), (1.0, 0.6)], True)
    fresh.end_edit()
    pose = fresh.pose_now()
    assert pose["push"][0].max() == pytest.approx(0.0, abs=1e-6)
    assert pose["push"][-1].min() == pytest.approx(0.6, abs=1e-4)
    inner = pose["tilt"][1:-1]
    assert (inner > 0).all() and (inner <= 10 / 90 + 1e-5).all()


def test_the_3d_view_finds_the_cell_under_the_pointer(fresh):
    places, faces, _ = fresh._cells_on_screen()
    wide, tall = fresh.canvas.get_logical_size()
    seen = np.nonzero(faces & (places[:, 0] > 0) & (places[:, 0] < wide)
                      & (places[:, 1] > 0) & (places[:, 1] < tall))[0]
    assert len(seen) > 100, "hardly any cells face the camera"
    for pick in seen[:: max(1, len(seen) // 12)]:
        got = fresh._cell_under(*places[pick])
        assert got == tuple(int(v) for v in fresh.cell_is[pick])


def test_the_mask_is_what_the_cells_show(fresh, tick):
    track = fresh.project.tracks["push"]
    track.write(0, np.full(track.size, 1.0), np.ones(track.size, bool))
    fresh.set_family("push")
    fresh.set_show_all(False)
    fresh._changed(keys=True)
    tick(0.2)
    picture = fresh.solid.to_array(480, 480)[..., :3].astype(int)
    green = ((picture[..., 1] > picture[..., 0] + 50)
             & (picture[..., 1] > picture[..., 2] + 50)).sum()
    fresh.set_mask(False)
    tick(0.1)
    plain = fresh.solid.to_array(480, 480)[..., :3].astype(int)
    green_off = ((plain[..., 1] > plain[..., 0] + 50)
                 & (plain[..., 1] > plain[..., 2] + 50)).sum()
    assert green > 2000 and green_off < green / 10, (green, green_off)


def test_keys_move_and_go_from_the_timeline(fresh):
    fresh.set_family("tilt")
    fresh.go_to(600)
    fresh.key_all(False)
    track = fresh.project.tracks["tilt"]
    assert track.frames == [0, 600]
    fresh._move_keys([(("tilt",), 600)], 60)
    assert track.frames == [0, 660]
    assert fresh.timeline.chosen == {(("tilt",), 660)}
    fresh.delete_keys()
    assert track.frames == [0]


def test_what_is_exported_opens_again_as_the_same_piece(fresh):
    fresh.set_family("tilt")
    fresh.go_to(300)
    fresh.auto_rotate(1.0)
    fresh.set_family("push")
    fresh.brush_push = 0.5
    fresh._dab(fresh._weights_at((20, 30)))
    fresh.project.name = "roundtrip"
    written = fresh.export_to(OUT / "roundtrip_1_of_1.json")
    before = fresh.project.pose(400)
    fresh.dirty = False
    assert fresh.open_any(str(written))
    after = fresh.project.pose(400)
    for family in km.FAMILIES:
        assert np.allclose(before[family], after[family], atol=1e-4), family


def _words(window):
    from PySide6.QtWidgets import (QAbstractButton, QComboBox, QLabel,
                                   QWidget)
    found = []
    for number, widget in enumerate([window] + window.findChildren(QWidget)):
        name = widget.objectName() or f"{type(widget).__name__}#{number}"
        if name in VOLATILE or widget.property("fixed_words"):
            continue
        if isinstance(widget, (QAbstractButton, QLabel)) and widget.text():
            found.append((name, widget.text()))
        if isinstance(widget, QComboBox):
            found += [(name, widget.itemText(i)) for i in range(widget.count())]
        if widget.toolTip():
            found.append((name + ".tip", widget.toolTip()))
    return found


def test_the_language_turns_where_the_window_stands(fresh, tick):
    import lang
    before = _words(fresh)
    try:
        fresh.choose_language("en")
        tick(0.2)
        left = [(where, what[:50]) for where, what in _words(fresh)
                if CYR.search(what)]
        assert not left, "still in Russian:\n" + "\n".join(map(str, left))
        assert fresh.tool_buttons["brush"].text() == "Brush"
    finally:
        fresh.choose_language("ru")
        tick(0.2)
    assert lang.language() == "ru"
    assert _words(fresh) == before


def test_the_viewer_hands_the_editor_its_flags(monkeypatch):
    import main
    monkeypatch.setattr("sys.argv", ["x", "--motors", "a.json", "--top", "b.mov"])
    assert main._asked_for("--motors") == "a.json"
    assert main._asked_for("--top") == "b.mov"
    assert main._asked_for("--sound") is None


# -- the motors' own motion ------------------------------------------------------

def _too_fast(editor):
    """A band pushed 900 mm in a second, and pulled back while moving."""
    cells = np.zeros((ROWS, PER_ROW), bool)
    cells[5:25, 5:30] = True
    editor._select(cells, "set")
    editor.go_to(60)
    editor.set_selected("push", 0.9)
    editor.go_to(100)
    editor.set_selected("push", 0.2)
    editor.select_none()
    editor._resimulate()


def test_the_simulation_is_drawn_with_the_keys_as_its_ghost(fresh, tick):
    _too_fast(fresh)
    result = fresh.simulation()
    assert result is not None and result.dropped and result.late
    fresh.go_to(150)
    fresh.set_view("both")
    tick(0.2)
    assert fresh.solid.ghost, "no ghost in Both"
    solid, ghost = fresh._shown()
    assert not np.allclose(solid["push"], ghost["push"])
    assert np.allclose(ghost["push"], fresh.pose_now()["push"]), \
        "the ghost is not the keys"
    both = fresh.solid.to_array(480, 480)[..., :3].astype(int)
    fresh.set_view("sim")
    tick(0.2)
    assert not fresh.solid.ghost
    alone = fresh.solid.to_array(480, 480)[..., :3].astype(int)
    assert np.abs(both - alone).sum(axis=2).astype(bool).sum() > 500, \
        "the ghost drew nothing"
    fresh.set_ghost("sim")
    fresh.set_view("both")
    solid, ghost = fresh._shown()
    assert np.allclose(solid["push"], fresh.pose_now()["push"])
    fresh.set_ghost("keys")
    fresh.set_view("keys")
    assert not fresh.solid.ghost
    assert fresh.unwrap.lag.sum() == 0


def test_the_simulation_goes_onto_the_keys_and_back(fresh):
    _too_fast(fresh)
    before = fresh.project.tracks["push"].frames
    fresh.bake_simulation()
    fresh._resimulate()
    assert not fresh.simulation().dropped and not fresh.simulation().late
    assert fresh.project.tracks["push"].frames != before
    fresh._step_undo(True)
    assert fresh.project.tracks["push"].frames == before


def test_the_background_is_grey_and_the_backs_are_dark(fresh, tick):
    import kinedit
    picture = fresh.solid.to_array(320, 320)[..., :3].astype(int)
    corner = picture[2, 2]
    want = np.round(np.array(kinedit.BACKGROUND) * 255).astype(int)
    assert np.abs(corner - want).max() <= 2, corner
    assert fresh.solid.backs_dark == 1.0
    assert fresh.cull and fresh.solid.cull_far_side == 1.0
    fresh.set_backs(True)
    assert not fresh.cull and fresh.solid.cull_far_side == 0.0
    tick(0.1)
    fresh.set_backs(False)
    assert fresh.cull


# -- the timeline's two ways to look ------------------------------------------------

def test_the_simple_timeline_is_three_lanes_and_the_detailed_one_opens(fresh, tick):
    timeline = fresh.timeline
    fresh.set_detailed(False)
    timeline.expanded = {("tilt",), ("tilt", "r", 12)}
    assert [lane.key for lane, _ in timeline.lanes()] == [("lift",), ("push",), ("tilt",)]
    fresh.set_detailed(True)
    keys = [lane.key for lane, _ in timeline.lanes()]
    assert ("tilt", "r", 29) in keys and ("tilt", "g", 12, 0) in keys
    assert ("tilt", "c", 12, 0) not in keys
    timeline.toggle(("tilt", "g", 12, 0))
    keys = [lane.key for lane, _ in timeline.lanes()]
    assert [key for key in keys if key[1:2] == ("c",)] ==         [("tilt", "c", 12, cell) for cell in range(5)]
    # The lift opens to rings only, and the lowest ring, with no jack, is not one.
    timeline.toggle(("lift",))
    lift = [lane for lane, _ in timeline.lanes() if lane.family == "lift"]
    assert all(not lane.opens for lane in lift[1:]) and len(lift) == 1 + 29
    timeline.expanded = set()
    fresh.set_detailed(False)
    tick(0.1)


def test_a_rings_part_of_a_key_moves_and_goes_on_its_own(fresh):
    import kinedit
    fresh.set_detailed(True)
    fresh.set_family("tilt")
    cells = np.zeros((ROWS, PER_ROW), bool)
    cells[3, :] = cells[7, :] = True
    fresh._select(cells, "set")
    fresh.go_to(300)
    fresh.set_selected("tilt", 0.05)
    track = fresh.project.tracks["tilt"]
    assert track.frames == [0, 300] and track.keyed_count(1) == 2 * PER_ROW
    # Ring 8's share of the key, dragged on ring 8's lane.
    fresh._move_keys([(("tilt", "r", 7), 300)], 120)
    assert track.frames == [0, 300, 420]
    assert track.keyed_count(1) == PER_ROW and track.keyed_count(2) == PER_ROW
    assert track.keyed[2].reshape(ROWS, PER_ROW)[7].all()
    assert fresh.timeline.chosen == {(("tilt", "r", 7), 420)}
    # One cell of ring 4 taken out of its key.
    fresh.timeline.chosen = {(("tilt", "c", 3, 10), 300)}
    fresh.delete_keys()
    assert track.keyed_count(1) == PER_ROW - 1
    fresh._step_undo(True)
    assert track.keyed_count(1) == PER_ROW
    fresh.set_detailed(False)


def test_a_lanes_name_picks_its_cells(fresh):
    fresh._lane_picked(("push", "g", 5, 2))
    assert fresh.family == "push"
    chosen = fresh.selection
    assert chosen.sum() == 5 and chosen[5, 10:15].all()
    fresh._lane_picked(("tilt", "r", 9))
    assert fresh.family == "tilt" and fresh.selection[9].all()         and fresh.selection.sum() == PER_ROW
    fresh.select_none()


# -- selection's sizes and the layers on the keyboard; the strip's view ---------------

def _press(editor, key):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    return editor._key(QKeyEvent(QEvent.Type.KeyPress, key,
                                 Qt.KeyboardModifier.NoModifier))


def test_one_two_three_are_selections_sizes_and_q_w_e_the_layers(fresh):
    from PySide6.QtCore import Qt
    cells = np.zeros((ROWS, PER_ROW), bool)
    cells[4, 12] = True
    fresh._select(cells, "set")
    assert _press(fresh, Qt.Key.Key_2)
    assert fresh.tool == "select" and fresh.unwrap.grain == "group"
    assert fresh.selection.sum() == 5 and fresh.selection[4, 10:15].all()
    assert _press(fresh, Qt.Key.Key_1)
    assert fresh.unwrap.grain == "ring" and fresh.selection[4].all() \
        and fresh.selection.sum() == PER_ROW
    assert _press(fresh, Qt.Key.Key_3) and fresh.unwrap.grain == "cell"
    for key, family in ((Qt.Key.Key_Q, "lift"), (Qt.Key.Key_W, "push"),
                        (Qt.Key.Key_E, "tilt")):
        assert _press(fresh, key) and fresh.family == family
    fresh.select_none()


def test_the_strip_zooms_where_it_points_and_goes_round(fresh, tick):
    from PySide6.QtCore import QPointF
    strip = fresh.unwrap
    strip.reset_view()
    tick(0.05)
    point = QPointF(strip.width() * 0.6, strip.height() * 0.4)
    before = strip.to_cells(point)
    strip.zoom_at(point, 3.0)
    after = strip.to_cells(point)
    assert strip.zoom == pytest.approx(3.0)
    assert abs((after[0] - before[0] + 25) % 50 - 25) < 1e-6 \
        and after[1] == pytest.approx(before[1], abs=1e-6)
    # Every cell is found where it is drawn, zoomed in and moved round past
    # the seam.
    strip.centre = [0.3, strip.centre[1]]
    strip._hold()
    screen = strip.screen_places()
    for row, which in ((0, 0), (12, 49), (20, 25), (29, 1)):
        x, y = screen[row, which]
        if 0 <= x < strip.width() and 0 <= y < strip.height():
            assert strip.cell_at(QPointF(x, y)) == (row, which)
    # A box round the seam takes cells from both ends of the strip.
    middle = strip._middle()
    size = strip._cell()
    across = strip.places[..., 0]
    box = (QPointF(middle.x() - 2 * size, 0), QPointF(middle.x() + 2 * size,
                                                    strip.height()))
    reach = size * 0.5
    got = ((screen[..., 0] >= box[0].x() - reach) & (screen[..., 0] <= box[1].x() + reach))
    assert (across[got] < 3).any() and (across[got] > 47).any()
    strip.reset_view()
    assert strip.zoom == 1.0


# -- the panel: what is chosen, poses, the tools ------------------------------------------

def test_the_inspector_says_and_sets_what_is_chosen(fresh):
    ins = fresh.inspector
    assert "1 кольца" in ins.title.text() and not ins.tilt.isEnabled()
    cells = np.zeros((ROWS, PER_ROW), bool)
    cells[6, :] = True
    fresh._select(cells, "set")
    assert ins.title.text() == "Выбрано: колец 1 · групп 10 · сот 50"
    assert ins.lift.buttons[1].isChecked()          # every jack at 330 mm
    # The tilt's slider shows the gaps' stretch: 10 degrees either way.
    low, high = ins.tilt.slider.allowed
    assert (low * 0.5 - 45, high * 0.5 - 45) == pytest.approx((-10, 10))
    fresh.go_to(120)
    fresh.set_selected("push", 0.4)
    assert "разные" not in ins.push_note.text()
    assert fresh.pose_now()["push"][6].min() == pytest.approx(0.4)
    fresh.go_to(240)
    fresh.key_selected("push")
    track = fresh.project.tracks["push"]
    assert 240 in track.frames and track.keyed_count(track.index(240)) == km.GROUPS
    fresh.select_none()


def test_the_brush_can_keep_to_what_is_chosen(fresh):
    cells = np.zeros((ROWS, PER_ROW), bool)
    cells[10, :] = True
    fresh._select(cells, "set")
    fresh.set_family("tilt")
    fresh.brush_tilt = 0.08
    fresh.brush_strength = 1.0
    fresh.brush_inside = True
    fresh.go_to(60)
    weights = np.ones((ROWS, PER_ROW), np.float32)
    fresh._dab(weights)
    tilt = fresh.pose_now()["tilt"]
    assert np.allclose(tilt[10], 0.08) and not np.delete(tilt, 10, axis=0).any()
    fresh.brush_inside = False
    fresh.select_none()


def test_the_jacks_are_set_down_the_strips_column(fresh):
    fresh.go_to(90)
    strip = fresh.unwrap
    strip.jacks_started.emit()
    for ring in (14, 15, 16):
        strip.jack_set.emit(ring, 3)
    strip.jacks_finished.emit()
    lift = fresh.pose_now()["lift"]
    assert (lift[14:17] == 3).all() and lift[13] == 1 and lift[17] == 1
    assert strip.lift[15] == 3
    fresh._step_undo(True)
    assert (fresh.pose_now()["lift"][14:17] == 1).all(), "the drag was not one step"


def test_a_pose_is_kept_and_put_back(fresh):
    import kinedit
    fresh.go_to(0)
    track = fresh.project.tracks["push"]
    track.write(0, np.full(track.size, 0.35), np.ones(track.size, bool))
    fresh._changed(keys=True)
    fresh.save_pose("тест")
    assert "тест" in fresh.pose_names()
    assert (HOME / kinedit.POSES).is_file()
    cells = np.zeros((ROWS, PER_ROW), bool)
    cells[2] = True
    fresh._select(cells, "set")
    fresh.go_to(600)
    track.write(600, np.zeros(track.size), np.ones(track.size, bool))
    fresh.go_to(900)
    fresh.put_pose("тест")
    push = fresh.pose_now()["push"]
    assert np.allclose(push[2], 0.35) and np.allclose(push[3], 0.0)
    fresh.drop_pose("тест")
    assert "тест" not in fresh.pose_names()
    fresh.select_none()


def test_a_problem_clicked_goes_to_its_frame_and_its_cells(fresh):
    _too_fast(fresh)
    fresh._choose_tool("motors")
    panel = fresh.panels["motors"]
    panel.refresh()
    assert panel.problems.count() > 0
    first = panel.problems.item(0)
    problem = first.data(Qt_user_role())
    fresh.show_problem(problem)
    assert fresh.frame == problem[3]
    assert fresh.selection.sum() == PER_PUSHER


def Qt_user_role():
    from PySide6.QtCore import Qt
    return Qt.ItemDataRole.UserRole


def test_the_keys_card_opens_on_question_mark(fresh):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Question,
                      Qt.KeyboardModifier.NoModifier, "?")
    assert fresh._key(event) and fresh.keys_card.isVisible()
    assert "1 2 3" in fresh.keys_card.text() and "Q W E" in fresh.keys_card.text()
    fresh._key(event)
    assert not fresh.keys_card.isVisible()


def test_a_number_is_pulled_by_the_mouse(fresh):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    number = fresh.panels["brush"].hardness
    number.set(50)
    got = []
    number.moved.connect(got.append)
    line = number.lineEdit()

    def mouse(kind, x, buttons, mods=Qt.KeyboardModifier.NoModifier):
        return QMouseEvent(kind, QPointF(5, 5), QPointF(x, 5), Qt.MouseButton.LeftButton,
                           buttons, mods)

    held = Qt.MouseButton.LeftButton
    number.eventFilter(line, mouse(QEvent.Type.MouseButtonPress, 100, held))
    number.eventFilter(line, mouse(QEvent.Type.MouseMove, 130, held))
    assert number.value() == pytest.approx(50 + 10 * 5)       # 30 px, 3 a step
    number.eventFilter(line, mouse(QEvent.Type.MouseMove, 115, held,
                                   Qt.KeyboardModifier.ShiftModifier))
    # A tenth of a step a few pixels, shown to the number's own places.
    assert number.value() == pytest.approx(50 + 0.5 * 5, abs=0.51)
    number.eventFilter(line, mouse(QEvent.Type.MouseButtonRelease, 115,
                                   Qt.MouseButton.NoButton))
    assert got and got[-1] == pytest.approx(number.value())
    number.moved.disconnect(got.append)
