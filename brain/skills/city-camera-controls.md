---
title: Change how you move around the city (camera controls)
tags: city, three.js, camera, orbitcontrols, mobile, touch, keyboard, upgrade
agents: coder
learned_from: 15
related: add-city-building, static-job-page
---
## When to use
The owner wants different navigation in the 3D city: free movement, fly keys, touch gestures, a home or
overview view, or limits on where the camera can go.

## How
1. The camera code is the `OrbitControls` block right after `labelRenderer` in `index.html`, and the
   "picking + camera focus" section (`flyTo`, `tween`, `pointerup`). Tune OrbitControls first, before you
   write your own: `screenSpacePanning=false` pans along the ground, `mouseButtons`/`touches` map the
   gestures (`TOUCH.DOLLY_PAN` = pinch zoom plus two-finger pan), and Shift/Ctrl+left-drag already pans.
2. For keyboard flight, keep a `Set` of held `e.code`s (keydown/keyup, and clear it on window `blur`).
   Each frame in `animate()`, move **both** `controls.target` and `camera.position` by the same vector
   (camera forward flattened to XZ, plus the right vector). Scale the speed with camera-to-target
   distance. Skip keys while an INPUT/TEXTAREA/SELECT has focus or the modal is open.
3. Clamp roaming in a `controls 'change'` listener: push target and camera by the same correction so the
   orbit offset is unchanged.
4. Any user input (`controls 'start'`, a fly key) should set `tween = null` so it cancels a running `flyTo`.
5. Overview or home: keep the start view in a `HOME` constant and `flyTo(HOME...)`, then restart the
   auto-spin timer.
6. Check that the module parses (`node --check` on the extracted module script).

## Gotchas
- Tap detection on touch: use `e.isPrimary` on pointerdown. A primary pointer starts a new gesture; a
  non-primary one means multi-touch, so skip the pick on pointerup. Don't count pointers up and down:
  a lost pointerup leaves the count stuck.
- `e.button > 0` on pointerup means a right or middle drag, never a pick.
- `minDistance` clamps `flyTo` close-ups too, because `controls.update()` runs after the tween.
- Don't judge "away from home" by camera position: the idle auto-rotate circles the camera. Compare the
  target and the zoom distance instead.
- `foo?.()` on an undeclared name still throws a ReferenceError. Look up the real helper name.
- On phones the side panel takes the bottom 46vh. Put floating buttons under the top bar, not at the
  bottom.
- Chrome may not be allowed on the job server. If it isn't, say the change is untested in a browser.
