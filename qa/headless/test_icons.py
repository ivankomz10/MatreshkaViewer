"""Every icon a page asks for is found, and found in its own set.

The viewer and the remap each have a folder called `icons`, with eight names
in common drawn differently. Built, the viewer's is the bundle's `icons` and
the remap's is `remap/icons`; the remap once looked in the bundle's first and
came up with eight of its thirty, in the viewer's drawing.
"""
from __future__ import annotations

import re
import sys

from conftest import TOOL


def remap_names() -> set:
    asked = set()
    for path in (TOOL / "remap").glob("*.py"):
        asked |= set(re.findall(r'"([a-z_]+)"', path.read_text("utf-8")))
    have = {one.stem for one in (TOOL / "remap" / "icons").glob("*.png")}
    return asked & have


def test_the_remap_finds_its_own_icons_when_built(monkeypatch, tmp_path, window):
    from remap import icons
    bundle = tmp_path / "_internal"
    (bundle / "icons").mkdir(parents=True)        # the viewer's, built
    for name in ("back", "play", "pause"):
        (bundle / "icons" / f"{name}.png").write_bytes(
            (TOOL / "icons" / f"{name}.png").read_bytes())
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    assert icons._where() == TOOL / "remap" / "icons"


def test_every_icon_the_remap_names_is_there(window):
    from remap import icons
    names = remap_names()
    assert len(names) >= 29
    assert [one for one in sorted(names) if icons.get(one).isNull()] == []


def test_every_icon_the_viewer_names_is_there():
    have = {one.stem for one in (TOOL / "icons").glob("*.png")}
    text = (TOOL / "main.py").read_text("utf-8")
    asked = set(re.findall(r'\bicon\(\s*"([a-z_]+)"', text))
    asked |= set(re.findall(r'"([a-z_]+)"', text)) & have
    assert asked and asked <= have
    assert (TOOL / "icons" / "down.png").is_file()
