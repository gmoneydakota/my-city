# Job 15: Free movement around the city

## What changed
The 3D city is no longer locked onto one spot. You can roam it freely:

| Desktop | Phone / tablet |
|---|---|
| **Drag** to orbit | **One finger** to orbit |
| **Right-drag** or **Shift+drag** to pan across the ground | **Two fingers** to pan |
| **Scroll** to zoom (now much closer: down to street level) | **Pinch** to zoom |
| **W A S D** / **arrow keys** to fly, **Q / E** down / up, hold **Shift** to go faster | |
| **H** or **Home** to go back to the overview | |

- **⌂ Overview** button (top-left, under the AGENT CITY bar) flies you back to the starting view of the
  whole city and closes any open detail drawer. It glows when you've wandered away.
- **✥ Move** button shows or hides a short cheat-sheet of the controls. On your first visit it opens on
  its own for a few seconds. Phones get the touch version.
- Clicking or tapping a building still flies you in to it: Lucky Tower, Products, the Brain, CAD Studio and
  every agent tower work as before. Grabbing the city mid-flight now stops the fly-in, so you're never
  fighting the camera.
- Panning now moves along the ground, like walking the streets, instead of sliding the screen sideways.
- You can't wander off into the empty void: the focus point stays within the city (radius 230) and the
  camera stays above the ground.
- Pinches and two-finger pans no longer count as a tap, so they can't open a building by accident. A
  right-drag pan doesn't either.
- Keys are ignored while you type in the Make box, search, or settings, so typing "w" or "s" won't move
  the camera.
- The slow showcase spin still comes back after 12 seconds of no input.

## Files
- `index.html`: camera controls setup, keyboard flight (`flyKeys`), `goHome()`, the Overview/Move
  buttons and help card (HTML + CSS), and picking that is safe with multi-touch.
- `brain/skills/city-camera-controls.md`: new skill, the method for changing the city camera.
- `outputs/job-15/README.md`, `outputs/job-15/PROGRESS.md`.

## What you'll see after approving
Open the city and you'll see **⌂ Overview** and **✥ Move** under the top bar, plus the controls
cheat-sheet for a few seconds. Fly around with WASD or your fingers, click any building to zoom in, and
press Overview to come back.

## About "merge it automatically"
This job can't skip your approval. Upgrades always come to you as a pull request; that is a safety rule of
the city runner, and the workflow files under `.github/` can't be edited by a job. To have upgrade PRs
merge themselves, you would turn on **Settings → General → Allow auto-merge** in the GitHub repo and
change the upgrade workflow to run `gh pr merge --auto --squash <pr>` after it opens the PR. That change
has to be made by you, by hand. Be aware that it would also ship any broken upgrade without review.

## Assumptions
- I kept OrbitControls (already loaded) rather than adding a new controls library. It already handles
  pinch, two-finger pan and right-drag. I tuned it and added keyboard flight on top.
- Q/E are down/up rather than turning, because turning is already the mouse/finger drag.
- I checked that the JavaScript parses (`node --check`). I couldn't run a browser on the build server,
  so the controls haven't been tested by hand yet. Try it on your phone after approving.
