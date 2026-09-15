"""Loading a file the way a person does: the button, the picker, the name.

Typing a path into the box loads nothing on purpose -- the row waits to be
given a file, by the picker or by a drop -- so this goes through the picker,
which is also the only way to find out that the picker still opens.
"""
from __future__ import annotations

import time

import look
from conftest import PREVIEW
import media


def test_the_browse_button_loads_a_clip(app):
    app.choose("qa_mode", PREVIEW)
    app.click("qa_clear_lamels")
    time.sleep(0.5)
    assert app.at("qa_path_lamels").value == "", "the row did not empty"

    app.open_file("lamels", media.MEDIA / media.CLIPS["lamels"][0])
    loaded = app.wait_until(
        lambda one: one.at("qa_path_lamels").value.endswith("qa_lamels.mov"),
        "the picker loaded nothing", within=30)
    assert loaded
    note = app.says("qa_note_lamels")
    wide, tall = media.CLIPS["lamels"][1:]
    assert f"{wide}x{tall}" in note, f"the row says {note!r}"


def test_clearing_a_row_takes_it_off_the_screen(app):
    app.click("qa_clear_lamels")
    time.sleep(0.6)
    assert app.at("qa_path_lamels").value == ""
    assert app.says("qa_note_lamels") == "", (
        f"the row still says {app.says('qa_note_lamels')!r}")
    assert not app.at("qa_clear_lamels").enabled, (
        "an empty row still offers to be cleared")
    # Put it back for whatever runs next.
    app.open_file("lamels", media.MEDIA / media.CLIPS["lamels"][0])
    app.wait_until(
        lambda one: one.at("qa_path_lamels").value.endswith("qa_lamels.mov"),
        "the clip did not go back", within=30)


def test_a_brightness_slider_moves_and_says_so(app):
    import winput
    slider = app.at("qa_gain_top")
    was = app.says("qa_gainvalue_top")
    app.front()
    winput.click(slider.left + 10, slider.top + slider.tall // 2)
    time.sleep(0.4)
    now = app.says("qa_gainvalue_top")
    assert now != was, f"the slider did not move: it still says {was!r}"
    # A double click on the row itself puts it back to one. On the row, not on
    # one of its widgets: a field or a slider takes the click for itself.
    note = app.at("qa_note_top")
    app.front()
    winput.click(note.left + note.wide // 2, note.top + note.tall // 2, count=2)
    time.sleep(0.4)
    assert app.says("qa_gainvalue_top") == "1.00", (
        f"a double click left it at {app.says('qa_gainvalue_top')!r}")


def test_the_link_ties_the_two_sliders(app):
    """Linked, moving one moves the other and keeps the balance between them."""
    import winput
    if not app.at("qa_link").checked:
        app.click("qa_link")
    time.sleep(0.3)
    top_was = float(app.says("qa_gainvalue_top"))
    bottom_was = float(app.says("qa_gainvalue_bottom"))
    slider = app.at("qa_gain_top")
    app.front()
    winput.click(slider.left + slider.wide - 12, slider.top + slider.tall // 2)
    time.sleep(0.5)
    top_now = float(app.says("qa_gainvalue_top"))
    bottom_now = float(app.says("qa_gainvalue_bottom"))
    assert top_now != top_was, "the slider did not move"
    assert bottom_now != bottom_was, (
        f"the other slider stayed at {bottom_was}: the link does not tie them")
    app.click("qa_link")


def test_the_picture_answers_the_rows(app):
    """Whatever is loaded, something is drawn; an empty window would be a bug."""
    picture = app.picture_of("qa_canvas")
    assert look.spread(picture) > 6, "the picture is blank with clips loaded"
