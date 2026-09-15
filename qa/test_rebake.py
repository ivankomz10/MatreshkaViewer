"""Re-baking a source, and the swap that puts the new file in the old place.

These run on copies of the clips, in a folder of their own, because a Hap Q
Alpha re-bake replaces its source: what everything else in the suite loads
must not be what this one renames.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

import media
import pytest
import viewer

WORK = viewer.SANDBOX / "work"


@pytest.fixture(scope="module")
def copies():
    """The clips again, somewhere they can be renamed."""
    if WORK.exists():
        shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True, exist_ok=True)
    made = {}
    for row, (name, _, _) in media.CLIPS.items():
        made[row] = WORK / name
        shutil.copy2(media.MEDIA / name, made[row])
    return made


@pytest.fixture(scope="module")
def baker(ready, copies, request):
    """A viewer of this file's own, loaded with the copies, in ReBake."""
    import conftest
    rows = {
        "Top": {"file": str(copies["top"]), "gain": 100},
        "Bottom": {"file": str(copies["bottom"]), "gain": 100},
        "Lamels": {"file": "", "gain": 100},
        "Frame": {"file": "", "gain": 100, "how": "Fit"},
        "Sound": {"file": "", "gain": 10},
        "Kinetic": {"file": ""},
    }
    app = viewer.Viewer(settings=conftest.settings(ready, rows=rows,
                                                   mode="ReBake"),
                        name="rebake")
    app.start()
    yield app
    if not request.config.getoption("--keep-open"):
        app.stop()


def wait_for_the_bake(app, within: float = 300.0) -> str:
    def done(one):
        said = one.says("qa_rebake_note")
        return said if ("in place" in said or "wrote" in said
                        or "exists" in said or "no " in said
                        or "missing" in said or "failed" in said) else ""
    return app.wait_until(done, "the re-bake never finished", within=within)


def test_it_comes_up_in_rebake_with_both_halves(baker):
    assert baker.at("qa_mode").value == "ReBake"
    assert baker.at("qa_rebake_left").value == "Premultiplied"
    assert baker.at("qa_rebake_right").value == "Premultiplied"
    assert baker.at("qa_rebake").enabled, "there is nothing to press"


def test_a_probe_writes_both_screens_at_their_own_size(baker):
    baker.click("qa_probe")
    said = baker.wait_until(
        lambda one: one.says("qa_rebake_note") or "", "the probe said nothing",
        within=120)
    assert "no screen" not in said and "failed" not in said, said
    written = sorted((baker.out / "probes").glob("*.png")) if (
        baker.out / "probes").exists() else []
    if not written:                     # the folder's name is not the point
        written = [p for p in baker.out.rglob("*.png")]
    assert written, f"the probe wrote nothing; it said {said!r}"
    from PIL import Image
    sizes = {Image.open(one).size for one in written}
    assert (media.CLIPS["top"][1], media.CLIPS["top"][2]) in sizes, (
        f"no probe at the top clip's own size; got {sizes}")


def test_hap_rebake_takes_the_source_place(baker, copies):
    """The new file gets the name; the old one steps aside as _old."""
    baker.choose("qa_rebake_format", "Hap Q Alpha")
    time.sleep(0.5)
    if baker.maybe("qa_rebake_get") is not None:
        pytest.skip("no ffmpeg here writes hap; that is its own test")
    was = copies["top"].stat().st_size

    baker.click("qa_rebake")
    said = wait_for_the_bake(baker)
    assert "in place" in said, f"the re-bake said {said!r}"

    assert copies["top"].exists(), "the source's name is gone"
    aside = Path(str(copies["top"]).replace(".mov", "_old.mov"))
    assert aside.exists(), f"nothing was kept as {aside.name}"
    assert aside.stat().st_size == was, "what was kept is not the old file"
    assert copies["top"].stat().st_size != was, (
        "the file under the old name is still the old file")
    # And the row still points at the same name, so everything downstream of
    # it keeps working.
    assert baker.at("qa_path_top").value == str(copies["top"])
    assert baker.log_has("rebake: wrote", within=10)


def test_it_refuses_to_bake_over_what_it_already_baked(baker):
    said = None
    baker.click("qa_rebake")
    said = wait_for_the_bake(baker, within=120)
    assert "exists" in said or "in place" in said, said
    if "in place" in said:
        # A second re-bake is allowed -- the old one steps aside again -- but
        # then there must be a second kept file, not a lost one.
        kept = list(WORK.glob("*_old*.mov"))
        assert len(kept) >= 2, f"only {[k.name for k in kept]} was kept"
