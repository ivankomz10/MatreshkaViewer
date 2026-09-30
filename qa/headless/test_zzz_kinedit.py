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
    editor.set_brush_target("keys")
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
    """A band pushed 900 mm in a second, and pulled back while moving -- the
    keys as they are, with no plan of moves to make them what the machine
    carries out."""
    editor.set_plan(False)
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


# -- handles in 3D, and Blender's G R H -----------------------------------------------------

def _handles(fresh, grain, cells):
    fresh._choose_tool("select")
    fresh.unwrap.grain = grain
    fresh._select(cells, "set")
    fresh.set_gizmos(True)
    fresh._rebuild_handles()
    return fresh.handles


def test_the_handles_follow_selections_size(fresh):
    import kin_gizmo
    front = int(round(fresh.unwrap.front / 7.2)) % PER_ROW
    rings = np.zeros((ROWS, PER_ROW), bool)
    rings[[8, 12]] = True
    handles = _handles(fresh, "ring", rings)
    assert sorted({(h.element, h.family) for h in handles}) == sorted(
        {(("ring", r), f) for r in (8, 12) for f in ("lift", "push", "tilt")})
    cells = np.zeros((ROWS, PER_ROW), bool)
    places, faces, _ = fresh._cells_on_screen()
    seen = [tuple(int(v) for v in fresh.cell_is[i]) for i in np.nonzero(faces)[0]]
    ring, cell = seen[len(seen) // 2]
    cells[ring, cell] = True
    handles = _handles(fresh, "group", cells)
    assert {h.family for h in handles} == {"push", "tilt"}
    handles = _handles(fresh, "cell", cells)
    assert [h.family for h in handles] == ["tilt"]
    fresh.set_gizmos(False)
    fresh._rebuild_handles()
    assert fresh.handles == []
    fresh.set_gizmos(True)
    fresh.select_none()


def test_dragging_a_rings_arrow_moves_that_ring_or_with_shift_all(fresh):
    import kin_gizmo
    rings = np.zeros((ROWS, PER_ROW), bool)
    rings[[8, 12]] = True
    handles = _handles(fresh, "ring", rings)
    lift = next(h for h in handles if h.family == "lift" and h.element == ("ring", 12))
    assert kin_gizmo.picked(handles, lift.tip) is lift
    fresh.go_to(60)
    x, y = lift.tip
    fresh._grab_start(lift, x, y, everyone=False)
    fresh._grab_move(x, y - 2 * kin_gizmo.PIXELS_A_STATE, fine=False)
    fresh.end_edit()
    got = fresh.pose_now()["lift"]
    assert got[12] == 3 and got[8] == 1
    fresh._grab_start(lift, x, y, everyone=True)
    fresh._grab_move(x, y + kin_gizmo.PIXELS_A_STATE, fine=False)
    fresh.end_edit()
    got = fresh.pose_now()["lift"]
    assert got[12] == 2 and got[8] == 0
    # The tilt's arc: turned down the arc, the face goes down, within its gaps.
    fresh._rebuild_handles()
    arc = next(h for h in fresh.handles if h.family == "tilt" and h.element == ("ring", 12))
    start = arc.anchor + np.array([kin_gizmo.ARC_RADIUS, 0.0])
    turned = arc.anchor + kin_gizmo.ARC_RADIUS * np.array([np.cos(0.3), np.sin(0.3)])
    fresh._grab_start(arc, *start, everyone=False)
    fresh._grab_move(*turned, fine=False)
    fresh.end_edit()
    tilt = fresh.pose_now()["tilt"]
    assert (tilt[12] > 0).all() and not tilt[8].any()
    fresh.select_none()


def test_g_pulls_the_chosen_pushers_and_esc_puts_them_back(fresh, tick):
    """Where the hand is, handed over: the suite never moves the pointer."""
    cells = np.zeros((ROWS, PER_ROW), bool)
    cells[5, 0:10] = True
    fresh._select(cells, "set")
    fresh.go_to(30)
    before = fresh.project.tracks["push"].frames.copy()
    fresh._start_modal("push", x=400)
    fresh._modal_move(False, x=500)
    assert fresh.pose_now()["push"][5, :2] == pytest.approx(0.4, abs=1e-4)
    fresh._end_modal(False)
    assert fresh.project.tracks["push"].frames == before
    assert not fresh.pose_now()["push"].any()
    fresh._start_modal("push", x=400)
    fresh._modal_move(False, x=450)
    fresh._end_modal(True)
    assert fresh.pose_now()["push"][5, 0] == pytest.approx(0.2, abs=1e-4)
    fresh._step_undo(True)
    assert not fresh.pose_now()["push"].any()
    fresh.select_none()


# -- masks and primitives -------------------------------------------------------------------

def _front_cell(fresh):
    """A cell in the middle of what the camera sees."""
    places, faces, _ = fresh._cells_on_screen()
    wide, tall = fresh.canvas.get_logical_size()
    gap = np.hypot(places[:, 0] - wide / 2, places[:, 1] - tall / 2)
    best = int(np.argmin(np.where(faces, gap, np.inf)))
    return tuple(int(v) for v in fresh.cell_is[best])


def test_a_mask_keeps_every_edit_to_its_cells(fresh):
    cells = np.zeros((ROWS, PER_ROW), bool)
    cells[4:8, :] = True
    fresh._select(cells, "set")
    name = fresh.new_mask("низ")
    assert fresh.edit_mask == "низ" and "низ" in fresh.mask_names()
    assert fresh.masks.choice.currentText() == "низ"
    # Everything chosen, but the value lands on the mask's rings alone.
    fresh.select_all()
    fresh.go_to(120)
    fresh.set_selected("push", 0.5)
    push = fresh.pose_now()["push"]
    assert np.allclose(push[4:8], 0.5) and not np.delete(push, range(4, 8), axis=0).any()
    # K keys only what the mask has.
    fresh.go_to(300)
    fresh.key_all(False)
    track = fresh.project.tracks[fresh.family]
    keyed = track.keyed[track.index(300)].reshape(ROWS, -1)
    assert keyed[4:8].all() and not np.delete(keyed, range(4, 8), axis=0).any()
    # A part-weighted cell goes part of the way, however many steps a drag takes.
    weights = fresh.project.masks[name].reshape(ROWS, PER_ROW).copy()
    weights[4] = 0.5
    fresh.project.masks[name] = weights.reshape(-1)
    fresh.project.changed()
    fresh.go_to(400)
    fresh.begin_edit()
    for value in (0.2, 0.6, 1.0):
        fresh.set_selected("push", value, live=True)
    fresh.end_edit()
    push = fresh.pose_now()["push"]
    was = fresh.project.pose(120)["push"][4, 0]
    assert push[5, 0] == pytest.approx(1.0) and push[4, 0] == pytest.approx(
        was + (1.0 - was) * 0.5, abs=1e-4)
    # Outside it nothing happens, and the window says so.
    only = np.zeros((ROWS, PER_ROW), bool)
    only[20] = True
    fresh._select(only, "set")
    fresh.set_selected("tilt", 0.05)
    assert "Вне маски" in fresh.status.text()
    assert not fresh.pose_now()["tilt"][20].any()
    fresh.set_edit_mask("")
    fresh.set_selected("tilt", 0.05)
    assert np.allclose(fresh.pose_now()["tilt"][20], 0.05)
    fresh.select_none()


def test_the_brush_paints_a_mask_and_the_selection_goes_in_and_out(fresh, tick):
    fresh.set_brush_target("mask")
    assert "маска" in fresh.panels["brush"].title.text()
    fresh.brush_strength = 1.0
    fresh.brush_mode = "paint"
    fresh.begin_edit()
    fresh._dab(fresh._weights_at((15, 25)))
    fresh.end_edit()
    assert fresh.edit_mask, "a stroke with no mask makes one"
    weights = fresh.mask_weights().reshape(ROWS, PER_ROW)
    assert weights[15, 25] == pytest.approx(1.0) and weights[0, 0] == 0.0
    # Painting a mask keys nothing.
    assert all(track.frames == [0] for track in fresh.project.tracks.values())
    fresh._step_undo(True)
    assert not fresh.project.masks, "the stroke was not one undo step"
    fresh.set_brush_target("keys")
    cells = np.zeros((ROWS, PER_ROW), bool)
    cells[2, :5] = True
    fresh._select(cells, "set")
    fresh.selection_to_mask(True)
    name = fresh.edit_mask
    assert (fresh.mask_weights().reshape(ROWS, PER_ROW) >= 0.5).sum() == 5
    fresh.select_none()
    fresh.select_mask()
    assert fresh.selection.sum() == 5
    fresh._select(cells[:, :] & (np.arange(PER_ROW) < 2), "set")
    fresh.selection_to_mask(False)
    assert (fresh.mask_weights() >= 0.5).sum() == 3
    fresh.drop_mask()
    assert name not in fresh.project.masks and not fresh.edit_mask
    fresh.select_none()


def test_a_primitive_is_put_where_the_cells_are_chosen_and_lies_over_the_keys(fresh, tick):
    ring, cell = _front_cell(fresh)
    cells = np.zeros((ROWS, PER_ROW), bool)
    cells[ring, cell] = True
    fresh._select(cells, "set")
    fresh.go_to(60)
    fresh.add_primitive("sphere")
    one = fresh.primitive()
    assert fresh.tool == "prims" and one.kind == "sphere" and one.frames == [60]
    import kin_prims as kp
    values = one.at(60)
    assert values[kp.HEIGHT] == pytest.approx(ring)
    gap = (values[kp.AZIMUTH] - km.cell_azimuths()[ring, cell] + 180) % 360 - 180
    assert abs(gap) < 1e-3
    fresh.set_prim_value(kp.OFFSET, 0.0)
    fresh.set_prim_value(kp.WIDTH, 0.7)
    # The keys are as they were; what is shown has the bulge.
    assert not fresh.pose_now()["push"].any()
    shown = fresh.shown_now()["push"]
    assert shown[ring, cell // PER_PUSHER] == pytest.approx(0.7, abs=1e-3)
    # It has a lane of its own under the families, in both ways of looking.
    keys = [lane.key for lane, _ in fresh.timeline.lanes()]
    assert keys[:3] == [("lift",), ("push",), ("tilt",)] and ("prim", 0) in keys
    # The panel says where it stands; the strip rings it.
    panel = fresh.panels["prims"]
    panel.refresh()
    assert panel.boxes[kp.WIDTH].value() == pytest.approx(0.7)
    assert panel.labels[kp.WIDTH].text() == "Радиус"
    assert fresh.unwrap.marker is not None
    # The simulation and the export run it.
    motion = fresh.composed()
    assert motion is not fresh.project
    assert motion.pose(60)["push"][ring, cell // PER_PUSHER] == pytest.approx(0.7, abs=1e-3)
    written = fresh.export_to(OUT / "sphere_1_of_1.json")
    back, _ = km.from_motor_json(written)
    assert back.pose(60)["push"][ring, cell // PER_PUSHER] == pytest.approx(0.7, abs=1e-3)
    fresh.select_none()


def test_a_primitive_is_moved_by_hand_keyed_and_its_keys_on_the_timeline(fresh, tick):
    import kin_prims as kp
    fresh.add_primitive("box")
    one = fresh.primitive()
    assert fresh.panels["prims"].labels[kp.WIDTH].text() == "Ширина"
    # On the strip: a press puts it, a drag carries it, one undo step.
    fresh.go_to(0)
    fresh.unwrap.stroke_started.emit()
    fresh.unwrap.placed.emit(100.0, 5.0)
    fresh.unwrap.placed.emit(120.0, 7.5)
    fresh.unwrap.stroke_finished.emit()
    values = one.at(0)
    assert values[kp.AZIMUTH] == pytest.approx(120.0) and values[kp.HEIGHT] == 7.5
    fresh._step_undo(True)
    assert fresh.primitive().at(0)[kp.AZIMUTH] != pytest.approx(120.0)
    fresh._step_undo(False)
    one = fresh.primitive()
    # In 3D: a cell pressed.
    ring, cell = _front_cell(fresh)
    fresh._place_at_cell((ring, cell))
    assert one.at(0)[kp.HEIGHT] == ring
    # Keys: one more further on; moved and deleted on its lane.
    fresh.go_to(240)
    fresh.set_prim_value(kp.TALL, 1.5)
    assert one.frames == [0, 240]
    fresh._move_keys([(("prim", 0), 240)], 60)
    assert one.frames == [0, 300]
    fresh.timeline.chosen = {(("prim", 0), 300)}
    fresh.delete_keys()
    assert one.frames == [0]
    fresh.timeline.chosen = {(("prim", 0), 0)}
    fresh.delete_keys()
    assert one.frames == [0], "a primitive keeps its last key"
    # Its lane picks it; its drawing in 3D is its twelve edges.
    fresh._lane_picked(("prim", 0))
    assert fresh.prim_index == 0
    assert len(fresh.prim_outline(one)) == 12
    from kin_overlay import Shapes
    shapes = Shapes(*fresh.canvas.get_logical_size())
    fresh._draw_prims(shapes)
    assert len(shapes.rows) > 0
    fresh.touch()
    tick(0.1)


def test_a_primitive_keeps_to_its_mask_turns_off_and_bakes(fresh):
    import kin_prims as kp
    ring, cell = _front_cell(fresh)
    cells = np.zeros((ROWS, PER_ROW), bool)
    cells[ring, cell] = True
    fresh._select(cells, "set")
    fresh.add_primitive("sphere")
    fresh.set_prim_value(kp.OFFSET, 0.0)
    fresh.set_prim_value(kp.WIDTH, 0.9)
    everywhere = int((fresh.shown_now()["push"] > 0).sum())
    upper = np.zeros((ROWS, PER_ROW), bool)
    upper[ring:] = True
    fresh._select(upper, "set")
    fresh.new_mask("верх")
    fresh.set_edit_mask("")
    fresh.set_prim_property("mask", "верх")
    shown = fresh.shown_now()["push"]
    assert 0 < int((shown > 0).sum()) < everywhere
    assert not shown[:ring].any()
    fresh.set_prim_property("polarity", "negative")
    assert not fresh.shown_now()["push"].any(), "pressed in from nothing is nothing"
    fresh.set_prim_property("polarity", "positive")
    fresh.set_prim_property("on", False)
    assert not fresh.shown_now()["push"].any()
    fresh.set_prim_property("on", True)
    wanted = fresh.shown_now()["push"].copy()
    fresh.bake_primitives()
    assert not fresh.primitive().on
    assert np.allclose(fresh.pose_now()["push"], wanted, atol=1e-4)
    assert "запечены" in fresh.status.text()
    fresh._step_undo(True)
    assert fresh.primitive().on and not fresh.pose_now()["push"].any()
    # Dropping the mask lets the primitive go everywhere again.
    fresh.drop_mask("верх")
    assert fresh.primitive().mask == ""
    fresh.drop_primitive()
    assert not fresh.project.primitives and fresh.prim_index == -1
    fresh.select_none()


def test_masks_and_primitives_are_kept_in_the_project_file(fresh):
    import kin_prims as kp
    cells = np.zeros((ROWS, PER_ROW), bool)
    cells[10:12] = True
    fresh._select(cells, "set")
    fresh.new_mask("пояс")
    fresh.add_primitive("sphere")
    fresh.set_prim_property("mask", "пояс")
    fresh.set_prim_step(15)
    path = OUT / "shapes.kin"
    fresh.project.path = path
    assert fresh.save()
    fresh.dirty = False
    fresh.new_project()
    assert fresh.open_any(str(path))
    assert fresh.mask_names() == ["пояс"] and fresh.project.prim_step == 15
    assert fresh.primitive() is not None and fresh.primitive().mask == "пояс"
    assert fresh.panels["prims"].step.value() == 15 or fresh.tool != "prims"
    del kp
    fresh.select_none()


# -- the video on the strip, the viewer asked first, a window that holds still ---------------

def test_the_video_is_on_the_strip_as_on_the_cells(fresh, tick):
    import media
    import kinedit
    assert fresh.sampler is not None
    # With no video, the strip shows what the cells show: the calibration.
    fresh.set_mask(False)
    calibration = fresh.video_cells()
    assert calibration is not None and calibration.std() > 0.05
    assert np.allclose(fresh.unwrap.colours, calibration)
    fresh.load_video(str(media.build()["top"]))
    try:
        fresh.go_to(0)
        fresh.touch()
        tick(0.6)
        first = fresh.video_cells()
        assert np.allclose(fresh.unwrap.colours, first)
        # A quarter of the clip is transparent -- black on the cells -- and
        # the rest is lit.
        assert (first.max(axis=-1) < 0.03).sum() > 100
        assert first[..., 0].max() > 0.5
        # A band of blue walks in as the clip runs: the strip follows the frame.
        fresh.go_to(59)
        fresh.touch()
        tick(0.6)
        later = fresh.video_cells()
        assert later[..., 2].mean() > first[..., 2].mean() + 0.2
        assert np.allclose(fresh.unwrap.colours, later)
        fresh.set_mask(True)
        assert not np.allclose(fresh.unwrap.colours, later)
    finally:
        fresh.stream.stop()
        fresh.stream = fresh.screen = fresh.held = None
        fresh._video_cells = None
        fresh.solid.clear_video(kinedit.TOP)
        fresh.set_mask(True)


def test_the_viewer_is_opened_only_when_asked(fresh, monkeypatch):
    import kinedit
    from PySide6.QtWidgets import QPushButton
    launched = []
    monkeypatch.setattr(kinedit.subprocess, "Popen",
                        lambda command, **_: launched.append(command))
    # The warning closed without "Open": nothing is written, nothing started.
    monkeypatch.setattr(kinedit.QMessageBox, "exec", lambda self: 0)
    assert fresh.show_in_viewer() is False and not launched
    assert fresh.show_in_viewer(asked=True) and "--motors" in launched[0]
    # It stands with the files now, by the export, away from «Вид».
    button = fresh.findChild(QPushButton, "qa_kin_viewer")
    export = fresh.findChild(QPushButton, "qa_kin_export")
    home = fresh.findChild(QPushButton, "qa_kin_home")
    assert button.text() == "Во вьюере…"
    assert 0 < button.x() - export.x() < 250 and home.x() - button.x() > 600


def test_long_words_under_the_pointer_do_not_move_the_3d_view(fresh, tick):
    tick(0.2)
    before = fresh.body.sizes()
    fresh.hover_label.setText("кольцо 16, сота 19: зазор под ним 1300 мм " * 8)
    fresh.status.setText("Моторы: пропущено команд 5, опоздали ходов 12 " * 8)
    fresh.warn_button.setText("Вне предела: 12345")
    fresh.warn_button.setVisible(True)
    fresh.go_to(123456)
    tick(0.3)
    assert fresh.body.sizes() == before
    fresh.hover_label.setText("")
    fresh.status.setText("")
    fresh._changed(keys=True)


# -- layers under the keys, as Blender's NLA -----------------------------------------------

def _a_wave(fresh, ring=6, at=120):
    push = fresh.project.tracks["push"]
    mask = np.zeros(push.size, bool)
    mask[ring * km.GROUPS:(ring + 1) * km.GROUPS] = True
    for frame, value in ((at, 0.0), (at + 60, 0.5), (at + 120, 0.0)):
        push.write(frame, np.full(push.size, value), mask)
    fresh._changed(keys=True)


def test_the_keys_go_into_a_clip_and_the_timeline_shows_the_layers(fresh, tick):
    _a_wave(fresh)
    before = fresh.project.pose(180)["push"].copy()
    fresh.push_down()
    assert fresh.tool == "layers" and fresh.timeline.layered
    assert fresh.timeline_mode.buttons[2].isChecked()
    assert fresh.strip_key == (0, 0) and fresh.strip().clip in fresh.project.clips
    assert np.allclose(fresh.pose_now()["push"] if fresh.frame == 180 else
                       fresh.project.pose(180)["push"], before)
    keys = [lane.key for lane, _ in fresh.timeline.lanes()]
    assert keys[:2] == [("keys",), ("layer", 0)]
    # A second, from the chosen keys alone, goes on top.
    _a_wave(fresh, ring=12, at=400)
    fresh.timeline.chosen = {(("push",), 400), (("push",), 460)}
    fresh.push_down()
    assert len(fresh.project.layers) == 2
    assert fresh.project.tracks["push"].frames == [520], "the unchosen key stays"
    keys = [lane.key for lane, _ in fresh.timeline.lanes()]
    assert keys[:3] == [("keys",), ("layer", 1), ("layer", 0)]
    # The panel says it; one undo step puts the keys back.
    panel = fresh.panels["layers"]
    panel.refresh()
    assert panel.body.isEnabled() and "Слой 2" in panel.title.text()
    fresh._step_undo(True)
    assert len(fresh.project.layers) == 1 and 460 in fresh.project.tracks["push"].frames
    fresh.touch()
    tick(0.1)


def test_a_strip_is_set_up_dragged_and_stretched(fresh):
    _a_wave(fresh)
    fresh.push_down()
    fresh.add_layer()
    assert len(fresh.project.layers) == 2 and fresh.layer_index == 1
    strip = fresh.strip()
    fresh.set_strip_property("mode", "add")
    fresh.set_strip_value("influence", 0.5)
    fresh.set_strip_value("fade_in", 30)
    assert (strip.mode, strip.influence, strip.fade_in) == ("add", 0.5, 30)
    panel = fresh.panels["layers"]
    panel.refresh()
    assert panel.mode.buttons[1].isChecked() and panel.boxes["influence"].value() == 50
    # Dragged along and onto the layer above; stretched by its right end.
    fresh.timeline.strip_moved.emit((0, 0), 1, 60)
    assert fresh.strip_key == (1, 0) and not fresh.project.layers[0].strips
    strip = fresh.strip()
    assert strip.start == 180
    clip = fresh.project.clips[strip.clip]
    fresh.timeline.strip_stretched.emit((1, 0), clip.length * 2)
    assert strip.speed == pytest.approx(0.5) and strip.length(clip) == clip.length * 2
    # Delete takes the strip when the layers are shown.
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier)
    assert fresh._key(event)
    assert not fresh.project.layers[1].strips and fresh.strip() is None
    # A layer's switch mutes it; its name makes it the one clips go on.
    fresh.timeline.layer_muted.emit(0)
    assert fresh.project.layers[0].muted
    fresh.timeline.layer_picked.emit(0)
    assert fresh.layer_index == 0


def test_a_clip_goes_to_the_library_and_back_anywhere(fresh):
    import kinedit
    _a_wave(fresh)
    fresh.push_down()
    fresh.save_clip("волна")
    assert "волна" in fresh.clip_names() and (HOME / kinedit.CLIPS).is_file()
    # Into a new piece: its rest would hide the clip, so it goes.
    fresh.dirty = False
    fresh.new_project()
    fresh.go_to(600)
    fresh.put_clip("волна")
    assert all(not len(track) for track in fresh.project.tracks.values())
    strip = fresh.strip()
    assert strip.start == 600 and "поставлен" in fresh.status.text()
    assert fresh.project.pose(660)["push"][6, 0] == pytest.approx(0.5)
    # Moved round and up from the panel.
    fresh.set_strip_value("round", 1)
    fresh.set_strip_value("rings", 2)
    assert fresh.project.pose(660)["push"][8, 0] == pytest.approx(0.5)
    # Keys over it are said.
    fresh.key_all(True)
    fresh.put_clip("волна")
    assert "перекрывают" in fresh.status.text()
    fresh.drop_clip("волна")
    assert "волна" not in fresh.clip_names()


def test_the_simulation_and_the_export_play_the_layers(fresh):
    _a_wave(fresh)
    fresh.push_down()
    fresh.set_strip_value("rings", 3)
    meant = fresh.desired()
    assert not meant.layers
    assert meant.pose(180)["push"][9, 0] == pytest.approx(0.5)
    # Exported as the machine can carry it out: the wave is quicker than a
    # pusher, so its top is as far as the pusher gets in the time.
    written = fresh.export_to(OUT / "layers_1_of_1.json")
    back, _ = km.from_motor_json(written)
    assert 0.3 < back.pose(180)["push"][9, 0] <= 0.5 + 1e-3
    fresh.set_plan(False)
    written = fresh.export_to(OUT / "layers_1_of_1.json")
    back, _ = km.from_motor_json(written)
    assert back.pose(180)["push"][9, 0] == pytest.approx(0.5, abs=1e-3)


def test_a_strip_comes_back_as_keys_and_the_layers_bake(fresh):
    _a_wave(fresh)
    fresh.push_down()
    fresh.set_strip_value("start", 300)
    fresh.strip_to_keys()
    assert fresh.project.tracks["push"].frames == [300, 360, 420]
    assert not fresh.project.layers[0].strips
    fresh.push_down()
    wanted = fresh.project.pose(360)["push"].copy()
    fresh.bake_layers()
    assert not fresh.project.layers and "сведены" in fresh.status.text()
    assert np.allclose(fresh.project.pose(360)["push"], wanted)
    fresh.set_timeline_view("simple")
    assert not fresh.timeline.layered


# -- the picture on the strip, the plan of moves, noise ------------------------------------

def test_the_strip_runs_as_the_3d_view_and_shows_each_cells_patch(fresh, tick):
    import media
    import kinedit
    places, faces, _ = fresh._cells_on_screen()
    row = 15
    index = fresh.index_of[row]
    seen = faces[index]
    order = np.argsort(places[index, 0][seen])
    across = fresh.unwrap.places[row, :, 0][seen][order]
    assert (np.diff(across) > 0).all(), across
    # In Video the strip is a picture: each cell its own patch.
    fresh.set_mask(False)
    assert fresh.unwrap.picture is not None
    fresh.load_video(str(media.build()["top"]))
    try:
        fresh.go_to(20)
        fresh.touch()
        tick(0.6)
        picture = fresh.unwrap.picture
        assert picture is not None
        ratio = picture.devicePixelRatio()
        assert abs(picture.width() / ratio - fresh.unwrap.width()) <= 1
        # Across a cell the picture changes, as it does on the building: not
        # one flat colour a cell.
        screen = fresh.unwrap.screen_places()
        size = fresh.unwrap._cell()
        x, y = screen[row, 30]
        left = picture.pixelColor(int((x - size * 0.3) * ratio), int(y * ratio))
        right = picture.pixelColor(int((x + size * 0.3) * ratio), int(y * ratio))
        assert left.alpha() == 255 and right.alpha() == 255
        assert (left.red(), left.green(), left.blue()) != (right.red(), right.green(),
                                                           right.blue())
        # Moved, drawn again for where it is now.
        before = fresh.unwrap.picture
        fresh.unwrap.zoom_at(fresh.unwrap._middle(), 2.0)
        assert fresh.unwrap.picture is not before
        fresh.unwrap.reset_view()
        fresh.set_mask(True)
        assert fresh.unwrap.picture is None
    finally:
        fresh.stream.stop()
        fresh.stream = fresh.screen = fresh.held = None
        fresh._video_cells = None
        fresh.solid.clear_video(kinedit.TOP)
        fresh.set_mask(True)


def test_the_plan_of_moves_leaves_nothing_dropped(fresh):
    _too_fast(fresh)
    assert fresh.simulation().dropped
    fresh.set_plan(True)
    fresh._resimulate()
    result = fresh.simulation()
    assert not result.dropped
    panel = fresh.panels["motors"]
    panel.refresh()
    assert panel.plan.isChecked()
    # The picture's warnings are the piece's own, not the plan's.
    assert fresh.desired() is not fresh.composed()
    fresh._step_undo(True)
    assert not fresh.project.plan


def test_noise_from_the_panel(fresh, tick):
    import kin_prims as kp
    fresh.add_primitive("noise")
    one = fresh.primitive()
    assert one.kind == "noise" and fresh.tool == "prims"
    panel = fresh.panels["prims"]
    panel.refresh()
    assert panel.labels[kp.AZIMUTH].text() == "По кругу"
    assert panel.seed.isVisible() or not panel.isVisible()
    first = fresh.shown_now()["push"].copy()
    fresh.go_to(90)
    assert np.abs(fresh.shown_now()["push"] - first).mean() > 0.01
    # It has no place: a click on the strip leaves it as it is.
    fresh._place_primitive(10.0, 3.0)
    assert "Шум" in fresh.status.text()
    assert fresh.prim_outline(one) == []
    fresh.set_prim_property("seed", 42)
    assert fresh.primitive().seed == 42
    fresh.touch()
    tick(0.1)


def test_the_motion_is_worked_out_while_the_window_goes_on(fresh, tick):
    import time
    import kin_prims as kp
    fresh.add_primitive("noise")
    fresh.set_prim_value(kp.OFFSET, 0.4)
    fresh.sim_timer.stop()
    assert fresh.simulation() is None
    started = time.perf_counter()
    fresh._resimulate_later()
    handed = time.perf_counter() - started
    assert fresh._job is not None and handed < 0.2, handed
    # An edit while it counts: that count is thrown away and made again.
    fresh.go_to(300)
    fresh.set_prim_value(kp.OFFSET, 0.2)
    fresh.sim_timer.stop()
    fresh._resimulate_later()
    for _ in range(300):
        tick(0.05)
        if fresh.simulation() is not None and fresh._job is None:
            break
    result = fresh.simulation()
    assert result is not None, "never worked out"
    assert fresh._sim_for == fresh._sim_key()
    assert not result.dropped                    # the plan's, for this piece
    panel = fresh.panels["motors"]
    panel.refresh()
    assert "считается" not in panel.summary.text()
