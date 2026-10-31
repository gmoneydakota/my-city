# Job #3 · City upgrade: the CAD Tower and CAD Studio

**Request:** "Add a CAD Tower where I can click on the tower and it takes me into an application where I can ask
for it to make me a 3D model of anything, and it makes it function and make sense."

## What you'll see after you merge

1. **A new tower in the ring: CAD** (purple, Sonnet tier). It's a slim building topped with a 3D-printer-style
   gantry, a spinning cyan wireframe hologram, and a glowing scan layer that sweeps up through it. The sweep speeds up
   while it's designing something.
2. **Click the tower** (the building or its label). The camera swoops in, the screen fades, and you land in
   **CAD Studio** (`/cad/`). Use **← City** to go back.
3. **In CAD Studio:**
   - **Make a 3D model of anything:** type a request (or tap an idea such as a clock, a drone or a treasure chest)
     and press **Design it ▶**. This sends a job to the new **CAD** agent. When the model is ready (usually 3–10 min),
     the studio loads it by itself if you've saved a token in ⚙ Settings. Without a token, GitHub opens in a new tab;
     click *Create*, then open the model from **Your models** once it says *done*.
   - **It plays straight away:** hinges swing, wheels and gears spin, and lids open. Linked parts move together (gear
     ratios, both front wheels steering). **▶ Play / ❚❚ Pause**, speed, one slider per joint, and **⟲ Reset pose**.
   - **It explains itself:** a *How it works* list, each part's purpose (click a part in 3D or in the list), the
     overall size in mm and inches, and **Checks**: every part connected, standing on the floor, joints where they
     belong.
   - **Exploded view**, **X-ray**, **Edges**, **Fit view**.
   - **Export:** ⬇ **STL** (3D printers and slicers), ⬇ **GLB** (Blender, AR, game engines, saved at real size),
     ⬇ **JSON**. Exports use the pose on screen.
   - **✏️ Change this model** sends a follow-up that edits the earlier design instead of starting over.
   - **Examples work right away**, even without a connected repo: an articulated desk lamp, a hand-crank gear train
     and an explorer rover.
   - The studio works on phones: there are **🛠 Make / 🧊 Model** toggles at the top.
4. Requests in the city's normal **Make** box that mention "3D model", "3D print", "CAD" or "STL" are now routed to the
   CAD agent for free (keyword rule). The job drawer for those jobs has an **🧊 Open in CAD Studio** button, and the
   GitHub "done" comment links straight to the model.

## How "it makes it function and make sense" is enforced

- The CAD agent writes a structured model (`model.json`) instead of loose geometry. It has real millimetre sizes, a
  floor at y = 0, a `parent` for every part that is "attached to" another, and **joints** (hinge, spin or slide, with
  limits, rpm and links between joints) that make it work.
- Before it can finish, it must run **`scripts/cad_check.py`**. This free Python checker rejects broken files and
  flags physical nonsense: floating parts, a model that isn't on the floor, hinges placed nowhere near their part,
  missing joints, and bad gear or follow chains. The agent fixes these and re-checks until the file passes.
- The studio repeats the key checks in your browser and shows them under **Checks**.

## Files

| File | What |
|---|---|
| `index.html` | New `cad` tower (AGENTS entry, `cad` shape in `buildTower`, scan animation). Clicking a tower with an `app` flies in and opens it. CAD keyword rule in `RULES`, a new idea chip, an "Open in CAD Studio" button on CAD jobs, and `#settings` opens Settings. |
| `cad/index.html` | **CAD Studio** (Three.js 0.160, same CDN as the city, no build step). |
| `cad/SCHEMA.md` | The `agent-city-cad/1` model format: shapes, parts, joints and gear rules. |
| `cad/examples/{lamp,gearbox,rover}.json` | Working reference models. They are the demo content and the agent's templates. |
| `agents/cad.md` | The new **CAD** agent (Sonnet; Read/Write/Edit/Bash/Grep/Glob/WebSearch). |
| `scripts/cad_check.py` | Model checker (stdlib only, no model calls). |
| `scripts/city_job.py` | Loads agents from `.claude/agents/` **and** `agents/`. Adds the CAD keyword rule (it beats generic "make/build" words, like quant), `has_model` in `job.json`, and a CAD Studio link in the done comment. |
| `sw.js` | Caches the studio and examples for offline use (cache `v2`). Offline links like `cad/?job=5` still open. |
| `README.md`, `CLAUDE.md` | Document the tenth agent and CAD Studio. |

No `.github/` changes are needed. CAD jobs run through the existing `city-job.yml`.

## Checked

- `python3 -m py_compile scripts/city_job.py scripts/cad_check.py`: passes.
- The module scripts of `index.html` and `cad/index.html` pass `node --check`. `sw.js` passes too.
- All three examples pass `cad_check.py` with no warnings. A deliberately broken file gets 8 clear errors and
  6 warnings, with exit code 1.
- I ran the studio's model code against the real three@0.160 in Node. Turning the crank 90° turns the middle gear
  −45° and the output gear +60°, which is the correct 2:3 train. Steering carries the front wheels, the rover's lid
  opens upward, and the lamp's arm chain moves together. Broken input is drawn with warnings instead of crashing.
- Headless Chrome (real WebGL):
  - The city shows the CAD tower, and clicking its label flies in and navigates to `/cad/`.
  - The studio loads the lamp, gearbox and rover. The checks read "✓ All 11 parts are connected / ✓ Stands on the
    floor / ✓ 5 moving joints", and the models animate.
  - The gear teeth visibly interlock. Exploded view, STL and GLB export, and part selection all work.
  - A missing job shows a friendly message, and the phone layout works.
  - No console errors apart from that deliberate 404.
- Routing: "Make me a 3D model of a working clock", "design a 3d-printable phone stand" and "I need an STL of a
  gear" go to **cad**. "make a 3d game" still goes to **coder**, and the NVDA request still goes to **quant**.

## Assumptions

- **The agent file is `agents/cad.md`, not `.claude/agents/cad.md`.** This upgrade job wasn't permitted to write inside
  `.claude/`, so I taught the job runner to read both folders. To use CAD as a Claude Code subagent on your own
  machine, run `cp agents/cad.md .claude/agents/` (optional).
- CAD runs on **Sonnet** (standard tier), following the "lightest agent that could do it" rule. Escalation to
  `coder` is only for requests that aren't really 3D objects.
- Models are built from parametric primitives (box, cylinder, cone, sphere/dome, capsule, torus, tube, gear, extruded
  outline, lathe profile). That keeps them reliable, animatable and checkable, rather than free-form sculpted meshes.
- Clicking the CAD tower opens the studio in the same tab, as "takes me into" suggests. The tower's jobs are listed in
  the studio under **Your models** rather than in the city's side drawer.
