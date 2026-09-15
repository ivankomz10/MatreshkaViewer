"""Switching modes: each one brings its own controls, and takes them away.

The one that caught something real is the ReBake half: it used to come up
blank on the right and only draw once a setting was touched. So the test does
not touch anything -- it looks at the picture the moment the mode is up, and
then again after a setting has gone away and come back, and the two must be
the same picture.
"""
from __future__ import annotations

import time

import look
from conftest import PREVIEW

FLAT_SIZES = ["Родное", "Половина", "Четверть"]
ALPHA_FORMATS = ["ProRes 4444 alpha", "PNG alpha"]


def test_flat_brings_its_own_sizes_and_formats(app):
    app.choose("qa_mode", "Flat")
    assert app.offered("qa_size") == FLAT_SIZES
    formats = app.offered("qa_format")
    for one in ALPHA_FORMATS:
        assert one in formats, f"Flat does not offer {one}: {formats}"
    # Every screen is written under its own name, so there is no name to type.
    assert not app.at("qa_out_name").enabled, "the name box is still live"
    assert not app.at("qa_bump").enabled, "the version button is still live"


def test_leaving_flat_puts_everything_back(app):
    app.choose("qa_mode", "Flat")
    app.choose("qa_mode", PREVIEW)
    sizes = app.offered("qa_size")
    assert sizes[0] == "1080x1920", sizes
    assert "Full 4096x4096" in sizes, sizes
    formats = app.offered("qa_format")
    for one in ALPHA_FORMATS:
        assert one not in formats, f"{one} is a Flat format: {formats}"
    assert app.at("qa_out_name").enabled
    assert app.at("qa_bump").enabled


def test_rebake_brings_its_own_bar(app):
    app.choose("qa_mode", "ReBake")
    for qa in ("qa_rebake_bar", "qa_rebake_what", "qa_rebake_format",
               "qa_rebake", "qa_probe", "qa_rebake_left", "qa_rebake_right",
               "qa_rebake_before", "qa_rebake_after"):
        assert app.wait_for(qa, within=10).showing, f"{qa} is not up"
    # Nothing about the building applies to a file, and it all goes away.
    for qa in ("qa_match", "qa_alpha", "qa_solid_top", "qa_layer_top"):
        assert app.maybe(qa) is None, f"{qa} is still up in ReBake"
    # The link ties the two sliders, which are there in every mode.
    assert app.at("qa_link").showing, "the link went away with the scene bar"
    app.choose("qa_mode", PREVIEW)


def test_rebake_draws_the_result_at_once(app):
    """Entering ReBake must show the re-baked half without being nudged."""
    app.choose("qa_mode", PREVIEW)
    app.choose("qa_mode", "ReBake")
    time.sleep(1.5)
    on_entry = app.picture_of("qa_canvas")
    left, right = look.halves(on_entry)
    assert look.spread(right) > 6, ("the re-baked half is blank on entry "
                                    f"(spread {look.spread(right):.1f})")
    # A setting away and back changes nothing -- unless the picture on entry
    # was not the picture the settings describe, which is the bug this is for.
    app.choose("qa_rebake_colour", "Keep")
    time.sleep(0.8)
    app.choose("qa_rebake_colour", "Multiply")
    time.sleep(1.5)
    settled = app.picture_of("qa_canvas")
    apart = look.difference(on_entry, settled)
    assert apart < 3.0, (f"the picture changed by {apart:.1f} per pixel after a "
                         "setting was touched and put back -- what was shown "
                         "on entry was not what the settings said")
    app.choose("qa_mode", PREVIEW)


def test_the_timeline_survives_a_mode_change(app):
    """Modes are switched, not restarted: the clock stays where it was."""
    app.choose("qa_mode", PREVIEW)
    app.click("qa_on")                      # a frame in, so zero proves nothing
    app.click("qa_on")
    was, last = look.frame_now(app)
    assert was > 0, "stepping did not move the timeline"
    for mode in ("Flat", "Inspection", "ReBake", PREVIEW):
        app.choose("qa_mode", mode)
        now, still = look.frame_now(app)
        assert (now, still) == (was, last), (
            f"{mode} moved the timeline from {was}/{last} to {now}/{still}")
