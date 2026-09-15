"""What the window remembers between one run and the next.

Settings live in a file beside the application, written when it closes, so
this test closes it -- properly, with Alt+F4 -- and starts it again on the
same folder. The point is not the file; it is that a person who arranged the
window a certain way finds it that way tomorrow.
"""
from __future__ import annotations

import json

import viewer
from conftest import PREVIEW

CHANGED = {
    "qa_mode": "Inspection",
    "qa_alpha": "Straight",
    "qa_behind": "Black",
    "qa_sync": "30 fps",
}


def test_the_window_comes_back_as_it_was_left(fresh):
    app = fresh()
    for qa, wanted in CHANGED.items():
        app.choose(qa, wanted)
    app.type_into("qa_out_name", "kept_name.mp4")
    app.click("qa_link")
    linked = app.at("qa_link").checked
    assert linked, "the link did not come on"

    assert app.quit(), "it would not close"
    kept = json.loads((viewer.SANDBOX / "settings.json").read_text("utf-8"))
    assert kept["mode"] == "Inspection", kept["mode"]
    assert kept["out_name"] == "kept_name.mp4", kept["out_name"]
    assert kept["linked"] is True

    again = viewer.Viewer(settings=None, clean=False, name="settings_again")
    try:
        again.start()
        for qa, wanted in CHANGED.items():
            assert again.at(qa).value == wanted, (
                f"{qa} came back as {again.at(qa).value!r}, not {wanted!r}")
        assert again.at("qa_out_name").value == "kept_name.mp4"
        assert again.at("qa_link").checked, "the link came back off"
        for row in ("top", "bottom", "lamels"):
            assert again.at(f"qa_path_{row}").value.endswith(f"qa_{row}.mov"), (
                f"{row} came back holding {again.at(f'qa_path_{row}').value!r}")
    finally:
        again.stop()


def test_a_folder_with_no_settings_starts_anyway(fresh):
    """Deleting the file is the way back to the defaults, and must be safe."""
    app = fresh(checked_machine=False)
    app.wait_for("qa_checks_close", within=30)
    app.click("qa_checks_close")
    app.wait_gone("qa_checks_close", within=15)
    assert app.at("qa_mode").showing
    assert app.answering()


def test_a_settings_file_from_before_the_rename_still_opens(fresh):
    """The mode was called Geometry; a folder worked in then still works now.

    Settings are written by name, so a rename that did not carry the old name
    along would open every existing folder in whatever mode happened to be
    first in the list.
    """
    app = fresh(mode="Geometry")
    assert app.at("qa_mode").value == PREVIEW, (
        f"it opened in {app.at('qa_mode').value!r}")
    assert app.at("qa_frame_edge").showing, (
        "the framing line belongs to this mode and is not up")
