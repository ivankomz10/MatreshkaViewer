# The Zaryadye kinetic honeycomb — what it is and what it will refuse

A brief for a program that generates shapes for this machine. Everything here
is read off the code that drives it (`tool/kinetic.py`, `tool/kin_model.py`),
which is the same code the show's editor and the viewer run, and every number
is checked by `test_bridge.py` beside this file.

**The one thing to take away.** A cell cannot turn unless there is a gap for
it to turn into, and that gap is opened by a jack. Pushing the cells outward
does not make room — raising the rings does. A generator that writes pushers
and leaves the jacks where they were produces poses the machine will simply
not perform. Call `kinetic_fit` and it will raise the jacks for you.

---

## 1. The shape of the thing

A drum of **30 rings**, stacked, each carrying **50 hexagonal cells**, 1500
cells in all. It sits on top of the building; everything below it is fixed
screen and does not move.

| | |
|---|---|
| rings (rows) | 30, numbered 1 at the bottom to 30 at the top |
| cells per ring | 50, ids 1…50 going round |
| cells per pusher | 5 — so **10 pushers** per ring, ids 1…10 |
| ring pitch at rest | 0.278 m |
| hinge radius | 2.4266 m from the axis |
| id 1 sits at | 77.6° on even rows, 59.6° on odd; 7.2° per id |
| frame rate | 60 fps |

Pusher *g* (1-based) carries cells `5·(g−1)+1 … 5·g`. One pusher moves its
five cells together; they cannot be pushed apart from one another.

## 2. The three motors

| motor | one per | JSON range | what 1.0 means | full travel | rest after |
|---|---|---|---|---|---|
| `jack` | gap between two rings | 0…3, **whole numbers** | see below | 15 s | 0.5 s |
| `pusher` | 5 cells of a ring | 0.0…1.0 | 1000 mm straight out | 4 s | 0.5 s |
| `tilt` | one cell | −0.5…+0.5 | 90° — but see below | 1.5 s for −30…+30 | 0.2 s |

**The tilt motor reaches ±30°, not ±45°.** The file format can hold ±0.5, which
would be 45°, and the gap rules below speak of 45 — but no such motor exists.
Never write a tilt outside **−0.3333 … +0.3333**. Its speed inside that range
is not linear; the simulator treats it as linear, so a move near the ends may
in life take a little longer than it reports.

**Jack states are positions, not a continuous travel.** A jack has four places
and no position in between:

| state | gap |
|---|---|
| 0 | 0 mm |
| 1 | 330 mm |
| 2 | 660 mm |
| 3 | 1300 mm |

A key must be a whole number. State **1 is the rest pose** — that is where the
geometry is modelled and where a fresh piece starts.

**State 0 is the machine's technological position** — rings shut — and the
specification names it so. **Do not compose in it.** Build from state 1
upwards; nothing can tilt more than 2° at 0 anyway, so there is nothing to be
had there.

It is not forbidden, and a file that uses it plays as it is: six of the 133
shows on disk drive down into 0 mid-performance and come back out, and four
sit there for their whole length. Those predate the rule. New work should not.

The four states sit at **0, ¼, ½ and all** of the jack's travel, so a move
from 0 to 1 takes a quarter of the 15 seconds, and 0 to 3 all of them.

**Tilt sign: positive is face down.** A cell at `+0.2` has its face turned
down by 18°, towards the ring below it.

### Which jack belongs to which gap

The jacks are numbered the way TouchDesigner counts them on site and the way
Houdini's exporter writes them:

> **`row_N`'s jack opens the gap between ring N and ring N+1.**

So there are **29 jacks**, in file rows 1…29. **`row_30` has no jack at all** —
writing one is an error. The bottom ring stands on the base.

This has been the rule since 2026-10-03, when it was settled against the site's
own controller. Files written by Cinema 4D number the jacks one ring higher —
rows 2…30, with row 1 held still — and 14 of the 154 show files on disk are
like that. Read one of those as if it were a Houdini file and every ring lifts
one ring off. `kinetic_open` says so when it sees a moving `row_30`.

For a cell in ring *R*:

* the gap **below** it is jack `row_{R−1}` — ring 1 has none
* the gap **above** it is jack `row_R` — ring 30 has none

## 3. The tilt rule — the part that gets generators wrong

A cell tilting **face down** (positive) swings into the gap **below** its
ring. A cell tilting **face up** (negative) swings into the gap **above** it.
Each gap allows a swing by its jack state:

| jack state of that gap | gap allows | motor reaches |
|---|---|---|
| 0 (0 mm) | 2° | **2°** |
| 1 (330 mm) | 10° | **10°** |
| 2 (660 mm) | 45° | **30°** |
| 3 (1300 mm) | 45° | **30°** |

Straight between, by millimetres, while a jack is on its way. The bottom ring
has nothing underneath, so face-down is unlimited there; likewise face-up at
the top ring.

**And then the beam.** Separately, a cell near the structure is blocked by its
own support:

| pusher out | beam allows | motor reaches |
|---|---|---|
| ≤ 0.1 | 30° | **30°** |
| 0.15 | 37.5° | **30°** |
| ≥ 0.2 | 45° | **30°** |

Since the motor stops at 30°, the beam never actually binds — it is kept here
because it is part of the rule the show runs on, and because the gap is what
you will meet in practice.

**The smallest of the three wins.** So:

* the widest a cell ever goes is **30°**, and that needs jack state ≥ 2 on
  that side
* at jack state 1 — the rest pose — nothing may exceed **10°**, however far
  out the pushers are
* at jack state 0 nothing exceeds **2°**: the machine is shut

### The mistake, in numbers

Pushers out to 0.8 on rings 11–20, cells tilted 27°, jacks left at rest:

```
1000 of 1500 cells are past the limit
the gap below ring 6 is at jack state 1, which allows 10.0 degrees
```

Raise those gaps to state 2 and the same tilts are legal, with the silhouette
untouched. That is exactly what `kinetic_fit` does.

## 4. Time, and why dense keys lose moves

A piece is **keys**: a frame and, for some motors, where they must be then.
Motors not keyed at a frame carry on through it, which is what lets you write
three cells without freezing the other 1497. Between two of its own keys a
motor eases (smoothstep); before its first it waits, after its last it holds.

The machine takes **commands**, and this is the trap:

> A command that arrives while that motor is still moving, or still resting
> after a move, is **thrown away**. It is not queued.

A jack takes 15 s for its whole travel and rests 0.5 s afterwards. Keys butted
end to end therefore lose every second move and the motor stops halfway. Call
`kinetic_simulate` to count the damage; `kinetic_export` plans the moves by
default, spreading them out so none is dropped.

Rules of thumb: leave a jack a full second per state it changes by, and never
key a tilt at the same frame as the jack that gives it room — raise the jack
**first**, let it arrive, then tilt.

## 5. The file the site plays

```json
{
  "name": "mypiece",
  "type": "kinematic_preset",
  "data": {
    "row_1": {
      "pusher": { "id_1": [ {"frame": 0, "start": 0.0, "dest": 0.8, "length": 240} ], ... "id_10": [...] },
      "tilt":   { "id_1": [...], ... "id_50": [...] },
      "jack":   { "id_1": [...] }
    },
    ...
    "row_30": { "pusher": {...}, "tilt": {...} }
  },
  "info": { "created_at": "...", "version": "1", "export_range": {"start": 0, "end": 480},
            "total_frames": 480, "part": 1, "total_parts": 1, "fps": 60 }
}
```

A segment is one command: start at `frame`, move from `start` to `dest` over
`length` frames, easing smoothly. `length: 0` is a statement of position.
Rows run `row_1`…`row_30` in order; inside a row the order is `pusher`,
`tilt`, `jack`; `row_30` carries no `jack`.

Do not write this by hand — `kinetic_export` writes it byte-identical to
Houdini's exporter, and names the file `<name>_1_of_1.json`, which is what the
site expects.

## 6. The tools

Call `kinetic_machine` first; it returns every fixed number above as data.

**Making a shape**

| tool | what it does |
|---|---|
| `kinetic_profile(points)` | a silhouette as a pusher value per ring, from `[height, reach]` control points (height 0 at the bottom ring, 1 at the top) |
| `kinetic_auto_tilt(lift, push, gain)` | turns every cell to lie along the surface the jacks and pushers make — Houdini's own auto-rotate |
| `kinetic_fit(lift, push, tilt)` | **the important one.** Raises the jacks the tilts need, pushes out far enough to clear the beam, clamps only what no jack could allow, and says what it changed |
| `kinetic_check(lift, push, tilt)` | which cells are impossible and which rule stops each |
| `kinetic_limits(lift, push)` | the allowed swing per ring, in degrees |
| `kinetic_geometry(lift)` | ring heights in metres, cell azimuths in degrees |

**Building a piece**

`kinetic_new`, `kinetic_key`, `kinetic_pose_at`, `kinetic_summary`,
`kinetic_open`, `kinetic_save`, `kinetic_simulate`, `kinetic_export`.

`kinetic_key` fits before it writes by default, and keys the jacks and pushers
the fit had to move as well — otherwise the tilt you asked for could not be
held.

**Looking**

`kinetic_render` draws a pose. `view`: `honeycomb` (framed on the cells),
`camera` (the show's own 9×16 projection camera, the framing every reference
render of this building uses), `orbit`. `paint`: `lift`, `push` or `tilt` to
colour cells by that motor. Cells past their limit are washed **red**.

> The drawn ring lift is a **tenth** of the site's travel, because the rigged
> geometry this draws moves that way. Judge jacks by their state, never by how
> far the rings part in a picture.

### A whole shape in four calls

```
kinetic_profile  points=[[0,0.05],[0.5,0.9],[1,0.1]]     -> push, one per ring
kinetic_auto_tilt lift=1, push=<that>                    -> tilt, widest 15.7 deg
kinetic_fit      lift=1, push=<that>, tilt=<that>        -> legal; 20 jacks raised
kinetic_render   <the fitted pose>, view="honeycomb"     -> a picture
```

Then `kinetic_new`, `kinetic_key` at a few frames, `kinetic_simulate`,
`kinetic_export`.

## 7. Five ways to get it wrong

1. **Pushers without jacks.** The commonest. Pushing a cell out gives it no
   room to turn. Raise the jacks, or let `kinetic_fit` do it.
2. **A jack at a fractional state.** Keys must be 0, 1, 2 or 3.
3. **A jack in `row_30`.** There is no thirtieth jack.
4. **Tilting at the same frame the jack moves.** The gap is not open yet, and
   the simulator reports a clash along the way. Raise first, then tilt.
5. **Keys butted together.** The machine drops commands that arrive while a
   motor is busy. Export with the plan on, and check `kinetic_simulate`.
