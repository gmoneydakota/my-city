# Agent City CAD model format (`agent-city-cad/1`)

The CAD agent writes one file per job, `outputs/job-<n>/model.json`. The CAD Studio
(`cad/index.html`) renders it, lets you move its joints, play its motion, explode it,
and export STL / GLB. `scripts/cad_check.py` validates it.

Worked examples: `cad/examples/lamp.json` (hinged arm), `cad/examples/gearbox.json`
(meshing gears that drive each other), `cad/examples/rover.json` (wheels, steering, a lid).

## Coordinates

- Units are **millimetres**. **Y is up.** The floor is `y = 0`: the model should rest on it.
- **Every `pos`, `pivot` and `axis` is in assembly (world) coordinates, in the rest pose.**
  You never do parent-relative maths: place every part where it really sits.
- `pos` is the centre of the shape (see the table for each shape's local origin).
- `rot` is `[x, y, z]` in **degrees**, applied in Three.js `XYZ` Euler order.
  Leave it `[0,0,0]` when you can.

## File

```json
{
  "format": "agent-city-cad/1",
  "name": "Desk lamp",
  "description": "One sentence: what it is and what it does.",
  "units": "mm",
  "how_it_works": ["Short plain-language steps, in order, that explain the mechanism."],
  "assumptions": ["Anything you had to guess."],
  "parts": [ /* Part */ ],
  "joints": [ /* Joint, optional */ ]
}
```

## Part

| field | required | meaning |
|---|---|---|
| `id` | yes | unique, lowercase `a-z 0-9 _ -` |
| `name` | yes | human name ("Left rear wheel") |
| `shape` | yes | one of the shapes below |
| `size` | yes | the shape's dimensions (mm) |
| `pos` | yes | `[x, y, z]` centre, mm |
| `rot` | no | `[x, y, z]` degrees |
| `color` | no | `"#rrggbb"` |
| `material` | no | `metal`, `plastic`, `wood`, `rubber`, `glass`, `fabric`, `stone`, `paint`, `emissive` (glows) |
| `parent` | no | id of the part it is attached to. **A part moves with its parent.** Root parts use `null`. |
| `role` | yes | what the part is for ("Holds the bulb and directs light down") |
| `loose` | no | `true` for parts that are meant to be separate (a ball, a lid that lifts off). Skips the "floating part" check. |

### Shapes

| shape | `size` | local origin / orientation |
|---|---|---|
| `box` | `w` (x), `h` (y), `d` (z) | centre |
| `cylinder` | `r`, `h` — or `rTop`, `rBottom`, `h`; optional `sides` (6 = hex) | centre, axis along Y |
| `cone` | `r`, `h` | centre, tip points +Y |
| `sphere` | `r`; optional `half: true` | centre. With `half`, a dome from `y=0` up to `y=r` |
| `capsule` | `r`, `h` (total height, ≥ 2r) | centre, axis along Y |
| `torus` | `r` (ring radius), `tube` (tube radius) | centre, lies flat (axis Y) |
| `tube` | `r` (outer), `ri` (inner), `h` | centre, hollow pipe along Y |
| `gear` | `r` (pitch radius), `teeth`, `h`; optional `bore` (hole radius) | centre, axis along Y |
| `extrude` | `points` `[[x,y],…]` (≥3, a closed 2D outline in the XY plane), `depth` | outline in XY, extruded along Z from `-depth/2` to `+depth/2` |
| `lathe` | `points` `[[radius,y],…]` (≥2, radius ≥ 0) | profile spun around the Y axis (vases, bottles, knobs) |

To lay a cylinder/gear/wheel on its side, rotate it: axis along X = `rot: [0,0,90]`, axis along Z = `rot: [90,0,0]`.

**Gears that mesh** must share a module (`2r / teeth` equal), sit `r1 + r2` apart centre to centre,
and their joints must be linked with `follows` and `ratio = -teeth_driver / teeth_driven`.
If the driven gear has an even number of teeth, rotate it by half a tooth (`180 / teeth` degrees about its axis) so teeth interlock.

## Joint (what makes it *work*)

A joint moves one part (`part`) **and every part whose `parent` chain leads to it**.

| field | meaning |
|---|---|
| `id`, `name` | unique id, human name ("Lid hinge") |
| `type` | `revolute` (hinge with limits), `continuous` (spins forever: wheels, fans, gears), `prismatic` (slides) |
| `part` | id of the moving part. One joint per part. |
| `pivot` | `[x,y,z]` point on the rotation axis (revolute / continuous) |
| `axis` | `[x,y,z]` direction of the hinge axis, or the slide direction (prismatic) |
| `min`, `max` | limits: degrees for revolute, mm for prismatic |
| `default` | starting value (inside min..max), default 0 = the pose you modelled |
| `rpm` | continuous joints: turning speed when the model is played |
| `period` | seconds for one back-and-forth swing when played (default 4) |
| `follows` | `{ "joint": "<id>", "ratio": -0.5, "offset": 0 }`: this joint is driven by another (gears, linkages, both doors at once). Value = leader × ratio + offset. |

Rotation direction follows the right-hand rule around `axis`.
Model every part in the rest pose (all joints at 0); `default` only changes the starting pose.

## Check it

```bash
python3 scripts/cad_check.py outputs/job-<n>/model.json
```

Errors (exit 1) must be fixed. Warnings (floating parts, model not on the floor, pivots far from
their part, odd proportions) usually mean the design doesn't make physical sense yet: fix them
unless there's a real reason, and say why in the README.
