# Pop-Out Plug Door (replaces the louvre door of job 7)

Louvres are gone. The problem with most sliding doors is that they leak air and rub on their seals. This door works like a train or aircraft **plug door**: it is pressed onto a rubber gasket when closed, then a lever pushes it 40 mm clear so it can slide sideways with no friction.

Size: opening 900 x 2100 mm; assembly 2450 x 2400 x 200 mm. 24 parts.

## Parts
- **Wall:** left wall, right (parking) wall, header, 3 gasket strips
- **Floor:** flat guide plate (no step) + two lips forming a groove
- **Rail group:** pop-out rail, 3 fixed guide blocks, 2 roller trolleys
- **Door:** panel, glass window, pull bar + 2 posts, bottom brush seal, floor guide pin
- **Control:** cam hub + red cam lever

## What moves
1. **Cam lever** (0-90 deg) drives **Door pop-out** (0-40 mm outward, linked with `follows`).
2. **Door slide** (0-960 mm) moves the trolleys and door along the rail.
Do them in that order: lever up, then slide. Reverse to close.

## Changes from job 7
Louvres, dial and slats removed; new sealing + pop-out mechanism, glass window, floor groove guide.

## Assumptions
The cam/bell-crank behind the wall is simplified to a linked joint. The viewer lets you slide without popping (a real interlock would prevent it). Print parts flat on y = 0.

Open it in CAD Studio: `cad/?job=8` (or click the CAD tower in the city). Use ⬇ STL to 3D-print it.

Check result: `Pop-Out Plug Door: 24 parts, 3 joints, 2450.0 × 2400.0 × 200.0 mm (W×H×D)` / `✓ valid, no warnings`
