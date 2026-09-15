"""The machine checks, and what the window does when a piece is missing.

The missing piece is arranged rather than waited for: the application is
started with a PATH that has no ffmpeg on it, which is the state a mac was in
when it found ffmpeg for the preview and none for the re-bake. Nothing is
uninstalled and nothing is downloaded -- the Download button is looked at,
not pressed.
"""
from __future__ import annotations

import time

import pytest
from conftest import PREVIEW

# Enough to start a program and no more; certainly no ffmpeg.
BARE_PATH = r"C:\Windows\system32;C:\Windows"


@pytest.fixture
def bare(fresh):
    """A viewer that cannot find ffmpeg anywhere."""
    return fresh(checked_machine=False, mode="ReBake",
                 env={"PATH": BARE_PATH})


def test_the_checks_come_up_on_a_first_run(fresh):
    """No settings beside it means nobody has seen this list yet."""
    app = fresh(checked_machine=False)
    app.wait_for("qa_checks_close", within=30)
    assert app.checks_up(), f"windows up: {app.other_windows()}"
    for row in ("qa_check_gpu", "qa_check_ffmpeg"):
        assert app.at(row).showing, f"{row} is not in the list"
    assert app.at("qa_check_gpu").name == "found", (
        f"the GPU line says {app.at('qa_check_gpu').name!r}")
    app.click("qa_checks_close")
    app.wait_gone("qa_checks_close", within=15)
    # And with the window out of the way, the application works.
    app.choose("qa_mode", "Flat")
    assert app.at("qa_mode").value == "Flat"


def test_a_second_run_does_not_ask_again(fresh):
    app = fresh(checked_machine=True)
    time.sleep(1.0)
    assert not app.checks_up(), "the checks came up again unasked"


def test_without_ffmpeg_the_checks_say_so_and_offer_it(bare):
    app = bare
    app.wait_for("qa_checks_close", within=30)
    said = app.at("qa_check_ffmpeg").name
    assert said in ("MISSING", "absent"), f"the ffmpeg line says {said!r}"
    getter = app.maybe("qa_checks_get")
    assert getter is not None and getter.showing, (
        "no way offered to fetch it from the window that noticed it is gone")
    assert getter.enabled, "the Download button is there but dead"
    app.click("qa_checks_close")


def test_without_ffmpeg_rebake_offers_it_too(bare):
    """The way out belongs where the trouble is, not three windows away."""
    app = bare
    app.wait_for("qa_checks_close", within=30)
    app.click("qa_checks_close")
    app.wait_gone("qa_checks_close", within=15)

    app.choose("qa_mode", "ReBake")
    app.choose("qa_rebake_format", "Hap Q Alpha")
    getter = app.wait_for("qa_rebake_get", within=15)
    assert getter.showing, "ReBake does not offer the ffmpeg it needs"
    assert "ffmpeg" in app.log().lower()


def test_without_ffmpeg_it_still_shows_the_picture(bare):
    """Nothing to write with is not nothing to look at."""
    app = bare
    app.wait_for("qa_checks_close", within=30)
    app.click("qa_checks_close")
    app.choose("qa_mode", PREVIEW)
    import look
    picture = app.picture_of("qa_canvas")
    assert look.spread(picture) > 6, "the picture is blank without ffmpeg"


def test_without_ffmpeg_a_render_says_why(bare):
    app = bare
    app.wait_for("qa_checks_close", within=30)
    app.click("qa_checks_close")
    app.choose("qa_mode", PREVIEW)
    app.click("qa_render")
    said = app.wait_until(lambda one: one.says("qa_eta"),
                          "the render said nothing at all", within=60)
    assert "ffmpeg" in said.lower(), f"it said {said!r} instead"
    assert not list(app.out.glob("*.mp4")), "it wrote something anyway"
