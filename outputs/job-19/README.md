# Job 19: easy mouse movement in the city

## What changed
Panning (sliding around the city) now works well with a mouse, not just with touch and keys:

- **Drag to pan, like a map.** A left-drag now slides the city under the cursor (the cursor shows a grab hand).
  Right-drag orbits (turns around).
- **✋ Pan / ⟲ Orbit button** next to ⌂ Overview (and the **M** key) switches back to the old setup, where left-drag
  orbits and right-drag pans. The browser remembers your choice. The button only shows on devices with a mouse;
  phones keep one finger to orbit and two fingers to pan.
- **Middle-drag (wheel button) pans** in both modes. Scrolling still zooms.
- **Scroll zooms toward the mouse pointer.** Point at a spot and scroll to travel there.
- **Double-click empty ground** to glide there. The viewing angle and zoom stay the same. Double-clicking a building
  still flies in, as a single click always did.
- Shift/Ctrl + drag still does the other action. WASD/arrows, Q/E, H/Home, click-to-fly and the roaming limit all
  work as before.
- The **✥ Move** help card now lists the mouse controls for whichever drag mode is on.

## Files
- `index.html`: grab cursor CSS, the drag-mode button, help text, `setDragMode`/`toggleDragMode`, `zoomToCursor`,
  the M key and the double-click glide.
- `brain/skills/city-camera-controls.md`: added notes on mouse panning.

## What you'll see after approving
Open the city with a mouse. Dragging moves you across the streets right away. The ✋ Pan button sits next to
⌂ Overview. Click it (or press M) if you'd rather drag to orbit.

## Assumptions
- Mouse users get **pan** as the default left-drag. That's what "easy for a mouse user to move" seemed to ask for. Orbit
  is one click away and the choice is remembered.
- Middle-drag used to dolly (zoom). It pans now, because the scroll wheel already zooms.
- Not tested in a real browser: Chrome isn't allowed on the job server. The JavaScript passes `node --check`, and all
  the OrbitControls options used (`zoomToCursor`, `mouseButtons`) exist in the pinned three.js 0.160.
