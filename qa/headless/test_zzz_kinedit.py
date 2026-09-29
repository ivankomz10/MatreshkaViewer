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
from kinetic import PER_ROW, ROWS

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
    editor.set_layer("rgb")
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
    assert np.allclose(tilt[10], 0.0), "a ring with a closed gap tilted"
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
    fresh.set_layer("push")
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
    fresh._move_keys([("tilt", 600)], 60)
    assert track.frames == [0, 660]
    assert fresh.timeline.chosen == {("tilt", 660)}
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
