"""PROTOTYPE -- throwaway. Reduces motor scores to what the tilt model needs.

Nothing here is meant to ship. It answers one question: does a two-degree
inclinometer model, fed by the real scores, behave in a way worth building --
and what do the masses have to be for the numbers to mean anything.

The split is deliberate. Everything that depends on the geometry and on the
1500 cells is done here, once: for every frame, how far the average cell is
moved by each of the three motors separately. Everything that somebody wants
to turn by hand -- the mass of a ring, of a segment, of a beam, of a module,
the stiffness, the damping -- is left to the page, where it costs nothing to
try another number.

    python make_data.py            the real scores and the made-up ones
    python make_data.py --quick    every other frame, for a fast look

Writes inclinometer_proto.html beside itself: one file, self-contained, open
it in a browser.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent
sys.path.insert(0, str(TOOL))

import kinetic                          # noqa: E402

BAKED = TOOL / "baked" / "scene_mesh.npz"
TEMPLATE = HERE / "template.html"
OUT = HERE / "inclinometer_proto.html"

SCORES = {
    "Loveday_top_001": r"D:\Content\2026-dates\LoveDay\Loveday_top_001.json",
    "CharCity_kinetic": r"D:\Content\2026-dates\CharacterCity\CharCity_kinetic.json",
    "velofest_2_kinetic": r"D:\Content\2026-dates\VeloFest_2\velofest_2_kinetic.json",
    "Matreshka_Graf_OUT_PIPE_v01":
        r"D:\Content\Matreshka_Graf_kinetics_OUT PIPE_v01.json",
}

EVERY = 2 if "--quick" in sys.argv else 1


def cells_at_rest():
    """Where the 1500 cells sit, and which (row, id) each one is."""
    data = np.load(BAKED)
    points, cell = data["screen__points"], data["screen__cell"]
    together = np.concatenate(
        [cell.reshape(-1, 1).astype(np.float64), points.astype(np.float64)],
        axis=1)
    once = np.unique(together, axis=0)
    which = once[:, 0].astype(np.int64)
    summed = np.zeros((int(which.max()) + 1, 3))
    np.add.at(summed, which, once[:, 1:])
    centres = (summed / np.bincount(which).reshape(-1, 1)).astype(np.float32)
    return centres, kinetic.cell_addresses(centres)


def sweep(centres, addresses, motors, only: str):
    """How far the average cell is moved, frame by frame, by one motor alone.

    `only` is "jack", "push" or "tilt"; the other two are held at rest. Kept
    apart because the masses that follow each are different -- a ring rises
    with its jack and knows nothing of a tilt -- and the page multiplies them
    out.
    """
    kept = (motors.tilt.copy(), motors.pusher.copy(), motors.jack.copy())
    if only != "tilt":
        motors.tilt[:] = 0.0
    if only != "push":
        motors.pusher[:] = 0.0
    if only != "jack":
        motors.jack[:] = float(kinetic.JACK_REST_STATE)

    home = np.concatenate(
        [centres, np.ones((len(centres), 1), np.float32)], axis=1)
    series = []
    for frame in range(0, motors.frames, EVERY):
        m = kinetic.transforms(centres, addresses, motors, frame)
        now = np.einsum("cij,cj->ci", m, home)[:, :3]
        # The average cell's displacement, and the average of its radial
        # component -- the second is what a one-sided score does not cancel.
        series.append((now - centres).mean(axis=0))
    motors.tilt[:], motors.pusher[:], motors.jack[:] = kept
    return np.array(series)


def made_up(centres, addresses, motors, kind: str, turn: int = 240):
    """A score written here rather than found: the cases worth provoking."""
    motors.tilt[:] = 0.0
    motors.jack[:] = float(kinetic.JACK_REST_STATE)
    rows, groups, frames = motors.pusher.shape
    if kind == "all out together":
        motors.pusher[:] = np.clip(
            np.sin(np.arange(frames) / frames * 2 * np.pi)[None, None, :],
            0, None)
    elif kind == "half the ring":
        motors.pusher[:] = 0.0
        # Groups run round the ring, so half of them is half of it.
        motors.pusher[:, : groups // 2, :] = np.clip(
            np.sin(np.arange(frames) / frames * 2 * np.pi)[None, None, :],
            0, None)
    else:                                # a wave, `turn` frames to the lap
        phase = (np.arange(groups)[:, None] / groups
                 - np.arange(frames)[None, :] / turn) * 2 * np.pi
        motors.pusher[:] = np.clip(np.cos(phase), 0.0, None)[None, :, :] ** 2
    return motors


def reduce_one(centres, addresses, motors, name: str, note: str) -> dict:
    out = {"name": name, "note": note, "fps": motors.fps / EVERY,
           "frames": len(range(0, motors.frames, EVERY))}
    for only in ("jack", "push", "tilt"):
        series = sweep(centres, addresses, motors, only)
        # Millimetres, rounded: the page has no use for half a micron and the
        # file is smaller for it.
        out[only] = [[round(float(v) * 1000, 3) for v in row] for row in series]
    reach = max(max(abs(v) for v in row)
                for only in ("jack", "push", "tilt") for row in out[only])
    print(f"   {name:30} {out['frames']:5} frames, biggest mean move "
          f"{reach:7.1f} mm")
    return out


def main() -> int:
    centres, addresses = cells_at_rest()
    print(f"{len(centres)} cells out of {BAKED.name}")
    scores = []

    print("the real ones:")
    for name, path in SCORES.items():
        if not Path(path).exists():
            print(f"   {name:30} not on this machine, skipped")
            continue
        motors = kinetic.Motors(path)
        scores.append(reduce_one(centres, addresses, motors, name,
                                 f"{motors.frames / motors.fps:.1f} s, "
                                 f"tilt {motors.tilt.min():+.2f}..{motors.tilt.max():+.2f}, "
                                 f"push {motors.pusher.max()*1000:.0f} mm, "
                                 f"jack {motors.jack.min():.0f}..{motors.jack.max():.0f}"))

    print("and the made-up ones:")
    shape = next(iter(SCORES.values()))
    for label, kind, turn in (
            ("wave, 4 s a lap", "wave", 240),
            ("wave, 2 s a lap", "wave", 120),
            ("wave, 1 s a lap", "wave", 60),
            ("all out together", "all out together", 0),
            ("half the ring", "half the ring", 0)):
        motors = kinetic.Motors(shape)
        motors.frames = min(motors.frames, 1200)
        for field in ("tilt", "pusher", "jack"):
            setattr(motors, field,
                    getattr(motors, field)[..., :motors.frames].copy())
        made_up(centres, addresses, motors, kind, turn)
        note = ("a hump of pushers running round the ring"
                if kind == "wave" else
                "every pusher out and back at once -- should stay balanced"
                if kind == "all out together" else
                "one half of the ring out and back")
        scores.append(reduce_one(centres, addresses, motors,
                                 f"made up: {label}", note))

    template = TEMPLATE.read_text(encoding="utf-8")
    OUT.write_text(
        template.replace("/*SCORES*/", json.dumps(scores, separators=(",", ":"))),
        encoding="utf-8")
    print(f"\nwrote {OUT}  ({OUT.stat().st_size/1e6:.2f} MB) -- open it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
