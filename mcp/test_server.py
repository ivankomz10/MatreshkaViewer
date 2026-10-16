r"""The server, driven over a real stdio connection the way a client drives it.

    ..\tool\.venv\Scripts\python.exe -m pytest -q test_server.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
OUT = HERE / "scratch"

mcp_client = pytest.importorskip("mcp.client.stdio")
from mcp import ClientSession, StdioServerParameters      # noqa: E402
from mcp.client.stdio import stdio_client                 # noqa: E402

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def _talk(body):
    settings = StdioServerParameters(
        command=sys.executable, args=[str(HERE / "server.py")], cwd=str(HERE))
    async with stdio_client(settings) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await body(session)


def _said(result):
    """The JSON a tool answered with."""
    for block in result.content:
        if getattr(block, "type", "") == "text":
            return json.loads(block.text)
    raise AssertionError("no text came back")


async def test_every_tool_is_offered():
    async def body(session):
        return [tool.name for tool in (await session.list_tools()).tools]
    names = await _talk(body)
    for wanted in ("kinetic_machine", "kinetic_fit", "kinetic_check",
                   "kinetic_key", "kinetic_simulate", "kinetic_export",
                   "kinetic_render", "viewer_render", "viewer_screens"):
        assert wanted in names, names


async def test_the_machine_comes_back_whole():
    async def body(session):
        return _said(await session.call_tool("kinetic_machine", {}))
    facts = await _talk(body)
    assert facts["rings"] == 30 and facts["cells_total"] == 1500
    assert facts["tilt_rule"]["gap_degrees_by_jack_state"] == [2.0, 10.0, 45.0, 45.0]


async def test_fitting_over_the_wire_raises_the_jacks():
    async def body(session):
        return _said(await session.call_tool(
            "kinetic_fit", {"lift": 1, "push": 0.8, "tilt": 0.3}))
    fitted = await _talk(body)
    assert fitted["check"]["legal"]
    assert fitted["changed"]["lift"] > 0
    assert fitted["changed"]["tilt"] == 0


async def test_a_render_comes_back_as_a_picture():
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / "wire.png"

    async def body(session):
        result = await session.call_tool("kinetic_render", {
            "lift": 2, "push": 0.7, "tilt": 0.2, "width": 240, "height": 320,
            "save_as": str(target)})
        return [getattr(block, "type", "") for block in result.content]
    kinds = await _talk(body)
    assert "image" in kinds, kinds
    assert target.is_file() and target.stat().st_size > 1000


async def test_a_whole_piece_can_be_built_and_exported():
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / "wire_export.json"

    async def body(session):
        await session.call_tool("kinetic_new", {"seconds": 8})
        await session.call_tool("kinetic_key", {"frame": 0, "push": 0.0, "tilt": 0.0})
        await session.call_tool("kinetic_key", {"frame": 240, "push": 0.8, "tilt": 0.35})
        played = _said(await session.call_tool("kinetic_simulate", {}))
        written = _said(await session.call_tool(
            "kinetic_export", {"path": str(target)}))
        standing = _said(await session.call_tool("kinetic_pose_at", {"frame": 240}))
        return played, written, standing
    played, written, standing = await _talk(body)
    assert played["dropped"] == 0
    assert standing["check"]["legal"]
    # The exporter names the file itself: a piece goes out as one part of
    # however many, `<name>_1_of_1.json`, which is what the site expects.
    landed = Path(written["written"])
    assert landed.is_file() and landed.name == "wire_export_1_of_1.json"
    data = json.loads(landed.read_text(encoding="utf-8"))
    assert data["type"] == "kinematic_preset"
    assert "jack" not in data["data"]["row_30"]


async def test_a_silhouette_becomes_a_legal_pose_in_three_calls():
    async def body(session):
        curve = _said(await session.call_tool("kinetic_profile", {
            "points": [[0.0, 0.05], [0.5, 0.9], [1.0, 0.1]]}))
        tilted = _said(await session.call_tool("kinetic_auto_tilt", {
            "lift": 1, "push": curve["push"]}))
        return curve, tilted, _said(await session.call_tool("kinetic_fit", {
            "lift": 1, "push": curve["push"], "tilt": tilted["tilt"]}))
    curve, tilted, fitted = await _talk(body)
    assert len(curve["per_ring"]) == 30
    assert max(curve["per_ring"]) <= 1.0
    assert tilted["degrees_widest"] > 5
    assert fitted["check"]["legal"]
    assert fitted["changed"]["tilt"] == 0
