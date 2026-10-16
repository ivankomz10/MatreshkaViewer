# The Zaryadye building — putting content on it and looking at the result

A brief for a program that generates pictures for this building. The
companion document, `KINETIC.md`, covers the moving honeycomb and its limits;
this one covers the screens, the camera and what the audience actually sees.

---

## 1. Three screens and a honeycomb

Four surfaces, fed by **three** video feeds:

| feed | surface | shape, unrolled | aspect |
|---|---|---|---|
| `Screen_Bottom` | the big drum at the bottom | 30.75 m round × 10.56 m tall | 2.91 : 1 |
| `Screen_Top` | the drum above the lamellas **and the honeycomb cells** | 18.09 m round × 9.32 m tall | 1.94 : 1 |
| `Lamel_screen` | the lamella slats of the canopy | 47.09 m round × 9.81 m tall | 4.80 : 1 |

**`Screen_Top` feeds two surfaces.** The drum under the honeycomb and the 1500
moving cells show the same picture. That is why, in a finished render, the
matryoshka head and the ring beneath it are always the same material.

The bottom screen is **4608 × 1584** on the wall. Content for it is authored at
**2000 × 2360** and reprojected — that is a separate tool
(`Matreshka_Remap`), not this one. For the other two, match the aspect above;
the viewer stretches whatever it is given onto the surface.

Nothing moves except the honeycomb. The drums, the canopy and the lamellas are
fixed.

## 2. What the audience sees

The scene carries the show's own camera, `Zaryadye_ProjectionCamera_9x16_v1`,
a portrait 9:16 view from across the square. Every reference render of this
building is made from it, and it is the default of `viewer_render`.

**The lamellas eat a band of the bottom screen.** From that camera the canopy
slats stand in front of it. Measured 2026-10-14 off the geometry itself:

| | metres up the bottom screen | on a 2000 × 2360 canvas |
|---|---|---|
| nothing hidden | below 6.0 m | below row ≈ 420 |
| anything hidden at all | 6.2 – 9.1 m | rows ≈ 420 – 830 |
| more than half hidden | 6.7 – 8.7 m | |
| worst line | about 89 % gone | |

**16.7 %** of the bottom screen's pixels visible from that camera are covered.
Put nothing that has to be read — a word, a face, a logo — in that band.
Texture and gradient survive it; detail does not.

## 3. Looking at it

| tool | what it does |
|---|---|
| `viewer_screens` | the three feeds, their unrolled sizes, the camera |
| `viewer_put_picture(screen, path)` | a still on one screen; it stays until replaced |
| `viewer_calibration(on)` | the baked test cards on all three, for bearings |
| `viewer_render(...)` | the whole building in one picture |

`viewer_render` takes either a pose (`lift`, `push`, `tilt` — see
`KINETIC.md`) or a `frame` of the piece open in the kinetic tools. `view` is
`camera` (the show's own, the default), `honeycomb` or `orbit`; with `orbit`
you may pass `yaw`, `pitch` and `distance`.

### A finished look, start to finish

```
viewer_put_picture  screen="Screen_Bottom", path="bottom.png"
viewer_put_picture  screen="Screen_Top",    path="top.png"
viewer_put_picture  screen="Lamel_screen",  path="lamels.png"

kinetic_profile     points=[[0,0.1],[0.45,0.85],[1,0.05]]
kinetic_auto_tilt   lift=1, push=<that>
kinetic_fit         lift=1, push=<that>, tilt=<that>

viewer_render       <the fitted pose>, view="camera", width=720, height=1280
```

The picture that comes back is framed exactly as the show's reference renders
are.

## 4. Things worth knowing before judging a render

* **Ring lift is drawn at a tenth of the site's travel.** The geometry this
  draws is the rig's, and the rig moves its jacks by a tenth. Rings that look
  almost touching in a render are 330 or 660 mm apart in life. Judge jacks by
  their state, never by the gap in a picture.
* **A cell shows the part of `Screen_Top` it sits on.** Pushing cells out and
  tilting them does not re-map the picture; each cell keeps its own patch of
  the image and carries it. A shape made of cells is therefore a *relief* in
  the top screen's content, not a new frame.
* **The honeycomb at rest is nearly a cylinder.** At jack state 1, pushers 0
  and tilts 0 — the pose a fresh piece starts at — it reads as a plain drum.
* **`mark_over_limit` is off in `viewer_render`** and on in `kinetic_render`.
  Use the kinetic one while fixing a pose, the viewer one for the final look.

## 5. What this cannot do

It renders stills. Loading a HAP movie, playing it, the show timeline, the
unwrap view, the inspector and writing a video out are all the viewer window's
own work — run `MatreshkaViewer.exe` for those; the kinetic editor is a page
of that same window, and the remap opens in a window over it. This server
exists so that a generator can see what it is making without a window and
without anyone's mouse.
