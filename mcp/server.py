r"""An MCP server for the Zaryadye honeycomb: pose it, check it, look at it.

Start it over stdio with the viewer's own interpreter:

    ..\tool\.venv\Scripts\python.exe server.py

Everything it does runs in this process against the viewer's sources in
`tool/` -- no window is opened and nothing is taken from whoever is at the
machine. See README.md for the client configuration and KINETIC.md for what
the numbers mean.

The one thing worth saying twice, because it is the mistake that makes shapes
nobody can build: a cell tilts into the gap beside its ring, and that gap is
opened by a jack. Push the cells out and leave the jacks alone and the tilts
are not merely ugly, they are refused by the machine. `kinetic_fit` takes a
wanted pose and gives back the nearest one the thing can actually hold.
"""
from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bridge                                       # noqa: E402

from mcp.server.mcpserver import Image, MCPServer   # noqa: E402

INSTRUCTIONS = """\
The kinetic honeycomb on top of the Zaryadye building: 30 rings of 50 cells,
driven by 29 jacks, 300 pushers and 1500 tilts.

Call kinetic_machine once before anything else -- it is the whole specification
in one object. Then: kinetic_fit to turn a wanted pose into a legal one,
kinetic_render to look at it, kinetic_key to put it on the timeline,
kinetic_simulate to find out whether the machine can carry the piece out, and
kinetic_export to write the motor JSON the site plays.

A pose is three fields. Each takes one number for the whole structure, one per
ring (30), or the full array:
    lift  (30,)      jack state 0..3, whole numbers, row 1..29 (row 30 has none)
    push  (30, 10)   pusher 0..1, 1000 mm at 1
    tilt  (30, 50)   tilt -0.5..0.5, 90 degrees at 1, positive is face down

Tilt is the one with a catch. A cell swings into the gap beside its ring, and
that gap belongs to a jack: at jack state 0 a cell may move 2 degrees, at 1 ten
degrees, at 2 and 3 the whole 45. Face down uses the gap below the ring, face
up the gap above. Pushing a cell out does not give it room to turn -- raising
the jacks does.
"""

server = MCPServer(
    name="matreshka-kinetic",
    title="Matreshka kinetic and viewer",
    version="1.0",
    instructions=INSTRUCTIONS,
)


@contextlib.contextmanager
def _quiet():
    """Nothing the viewer's code prints may reach stdout: that is the wire."""
    with contextlib.redirect_stdout(io.StringIO()) as caught:
        yield
    said = caught.getvalue().strip()
    if said:
        print(said, file=sys.stderr)


def _png(image: np.ndarray, save_as: str | None) -> Image:
    from PIL import Image as Picture
    picture = Picture.fromarray(np.ascontiguousarray(image), "RGBA")
    if save_as:
        target = Path(save_as)
        target.parent.mkdir(parents=True, exist_ok=True)
        picture.save(target)
    data = io.BytesIO()
    picture.save(data, format="PNG")
    return Image(data=data.getvalue(), format="png")


# -- the specification ---------------------------------------------------------

@server.tool()
def kinetic_machine() -> dict:
    """Every fixed number about the structure and its motors.

    Read this first. It carries the ring and cell counts, each motor's range
    and what a unit of it is worth in millimetres or degrees, how long a full
    travel takes, the tilt rule, and how the jack rows of a file are numbered.
    """
    return bridge.machine()


@server.tool()
def kinetic_limits(lift=None, push=None) -> dict:
    """How far each ring's cells may tilt at this pose, in degrees.

    Positive is face down, into the gap below the ring; negative is face up.
    Give `lift` and `push` as one number, one per ring, or the full array.
    """
    with _quiet():
        return bridge.limits(lift, push)


@server.tool()
def kinetic_check(lift=None, push=None, tilt=None) -> dict:
    """Can the machine hold this pose, and if not, which cells and why.

    Each entry under `worst` says what the cell wants, what it is allowed and
    which rule is stopping it -- the gap beside its ring or the beam.
    """
    with _quiet():
        return bridge.check(lift, push, tilt)


@server.tool()
def kinetic_fit(lift=None, push=None, tilt=None,
                may_change: list[str] | None = None) -> dict:
    """The nearest pose the machine can actually hold, and what was changed.

    Raises the jacks the tilts need, pushes the pushers out far enough to
    clear the beam, and clamps only what no jack could ever allow. Nothing is
    lowered or pulled in. `may_change` narrows it, e.g. ["tilt"] to keep the
    jacks where they are and flatten the shape instead.
    """
    with _quiet():
        return bridge.fit(lift, push, tilt,
                          tuple(may_change or ("lift", "push", "tilt")))


@server.tool()
def kinetic_profile(points: list[list[float]],
                    close_the_top: bool = False) -> dict:
    """A silhouette as pusher values, one per ring, from a few control points.

    `points` are [height, reach] pairs: height 0 at the lowest ring and 1 at
    the top, reach 0..1 of the pusher's travel. The curve is monotone between
    them, so a vase drawn to 1.0 at its widest does not overshoot on the way.
    Feed the result to `kinetic_auto_tilt`, then to `kinetic_fit`.
    """
    with _quiet():
        return bridge.profile(points, close_the_top)


@server.tool()
def kinetic_auto_tilt(lift=None, push=None, gain: float = 1.0) -> dict:
    """Turn every cell to lie along the shape the jacks and pushers make.

    Houdini's own auto-rotate: a shape widening upwards tilts its cells face
    down. Nothing is limited here -- pass the result through `kinetic_fit`,
    which raises the jacks these tilts have just asked for.
    """
    with _quiet():
        return bridge.auto_tilt(lift, push, gain)


@server.tool()
def kinetic_geometry(lift=None) -> dict:
    """Where the rings stand in metres and where each cell stands in degrees.

    For aiming a shape at a place on the building rather than at a ring index.
    """
    with _quiet():
        return {"ring_heights_m": bridge.ring_heights(lift),
                "cell_azimuths_degrees": bridge.cell_azimuths(),
                "ring_pitch_m": bridge.km.RING_PITCH_M}


# -- the piece ------------------------------------------------------------------

@server.tool()
def kinetic_new(seconds: float = 20.0, name: str = "generated") -> dict:
    """Start an empty piece of this length. Everything rests at jack state 1."""
    with _quiet():
        return bridge.session().new(seconds, name)


@server.tool()
def kinetic_open(path: str) -> dict:
    """Open a piece: an editor project (.kin) or a motor JSON from the show."""
    with _quiet():
        return bridge.session().open(path)


@server.tool()
def kinetic_summary() -> dict:
    """What is open: its length, how many keys each family has, what is wrong."""
    with _quiet():
        return bridge.session().summary()


@server.tool()
def kinetic_pose_at(frame: float) -> dict:
    """Where every motor stands at this frame of the open piece, and whether
    that pose is legal."""
    with _quiet():
        return bridge.session().pose_at(frame)


@server.tool()
def kinetic_key(frame: int, lift=None, push=None, tilt=None,
                fit_first: bool = True) -> dict:
    """Put a key at one frame on the motors this call names.

    Motors not named carry on through the frame on their own -- that is what
    makes a piece writable a few cells at a time. With `fit_first` the pose is
    made legal before it is written, and the jacks and pushers it had to move
    are keyed as well, since otherwise the tilt could not be held.
    """
    with _quiet():
        return bridge.session().key(frame, lift, push, tilt, fit_first)


@server.tool()
def kinetic_simulate(plan: bool = True) -> dict:
    """What the motors would really do with these keys.

    The machine throws away a command that arrives while that motor is still
    moving or resting -- it does not queue it. Keys butted end to end
    therefore lose every second move. `plan` spaces them out first, which is
    what the export does too; run it with plan=false to see the raw damage.
    """
    with _quiet():
        return bridge.session().simulate(plan)


@server.tool()
def kinetic_save(path: str) -> dict:
    """Write the open piece as an editor project (.kin), keys and all."""
    with _quiet():
        return bridge.session().save(path)


@server.tool()
def kinetic_export(path: str, plan: bool = True) -> dict:
    """Write the motor JSON the site plays, in Houdini's own layout.

    Planned by default. Check `kinetic_simulate` first if the piece matters.
    """
    with _quiet():
        return bridge.session().export(path, plan)


# -- looking at it ---------------------------------------------------------------

@server.tool()
def kinetic_render(lift=None, push=None, tilt=None, frame: float | None = None,
                   view: str = "honeycomb", width: int = 540, height: int = 720,
                   paint: str | None = None, mark_over_limit: bool = True,
                   pieces: str = "honeycomb", save_as: str | None = None) -> Image:
    """A picture of a pose, or of the open piece at `frame`.

    `view`: honeycomb (framed on the cells), camera (the show's own 9x16
    projection camera -- the framing every reference render uses), or orbit.
    `pieces`: honeycomb, building, or all.
    `paint`: lift, push or tilt to colour the cells by that motor instead of
    showing video on them.
    Cells past their limit are washed red unless `mark_over_limit` is false.

    Ring lift is drawn at a tenth of the site's travel (the rigged geometry
    moves that way), so judge jacks by number, not by the gaps in the picture.
    """
    with _quiet():
        if frame is not None:
            pose = bridge.session().project.pose(float(frame))
        else:
            pose = bridge.pose_from(lift, push, tilt)
        image = bridge.session().studio.draw(
            pose, width, height, view=view, pieces=pieces, paint=paint,
            mark_over_limit=mark_over_limit)
    return _png(image, save_as)


# -- the building ----------------------------------------------------------------

@server.tool()
def viewer_screens() -> dict:
    """The three screens: their names, and how each unrolls in metres.

    `Screen_Top` feeds the honeycomb as well as the drum beneath it, so a
    picture put there shows on the cells.
    """
    with _quiet():
        studio = bridge.session().studio
        return {
            "screens": list(studio.mesh.screens),
            "honeycomb_wears": "Screen_Top",
            "unrolled": {name: dict(zip(
                ("arc_m", "height_m", "azimuth_at_u0_rad", "sweep_rad", "base_z_m"),
                [round(v, 4) for v in values]))
                for name, values in studio.mesh.unrolled.items()},
            "camera": studio.mesh.camera,
            "camera_frame": list(studio.mesh.frame),
        }


@server.tool()
def viewer_put_picture(screen: str, path: str) -> dict:
    """Put a still on one screen. It stays there until it is replaced."""
    with _quiet():
        studio = bridge.session().studio
        picture = bridge._read_png(Path(path))
        studio.put_picture(screen, picture)
    return {"screen": screen, "from": path,
            "size": [int(picture.shape[1]), int(picture.shape[0])]}


@server.tool()
def viewer_calibration(on: bool = True) -> dict:
    """The baked test cards on all three screens, for finding one's bearings."""
    with _quiet():
        bridge.session().studio.calibration(on)
    return {"calibration": bool(on)}


@server.tool()
def viewer_render(frame: float | None = None, lift=None, push=None, tilt=None,
                  view: str = "camera", width: int = 540, height: int = 960,
                  save_as: str | None = None) -> Image:
    """The whole building -- screens, lamellas and honeycomb -- in one picture.

    `camera` is the show's own 9x16 projection camera, which is the framing
    every reference render of this building uses. Put content on the screens
    with `viewer_put_picture` first.
    """
    with _quiet():
        if frame is not None:
            pose = bridge.session().project.pose(float(frame))
        else:
            pose = bridge.pose_from(lift, push, tilt)
        image = bridge.session().studio.draw(
            pose, width, height, view=view, pieces="all",
            mark_over_limit=False)
    return _png(image, save_as)


def main(argv: list[str] | None = None) -> int:
    """Over a pipe by default; over HTTP when something else must reach it.

    A desktop client (Claude, Cursor) starts this itself and talks down a
    pipe, which is the simplest thing that works. OpenAI's Responses API
    cannot: its `mcp` tool fetches a URL, so for that the server has to be
    listening. `--http` is for that, and for any client not on this machine.
    """
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--http", action="store_true",
                        help="listen over HTTP instead of talking down a pipe")
    parser.add_argument("--host", default="127.0.0.1",
                        help="only with --http; 0.0.0.0 to let other machines in")
    parser.add_argument("--port", type=int, default=8765)
    asked = parser.parse_args(argv)

    if not asked.http:
        server.run("stdio")
        return 0
    # Said on stderr: stdout is kept clean whichever way this runs.
    print(f"matreshka-kinetic on http://{asked.host}:{asked.port}/mcp",
          file=sys.stderr)
    server.run("streamable-http", host=asked.host, port=asked.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
