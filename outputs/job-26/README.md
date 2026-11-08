# Job #26 · Brain dream (week of 1 to 8 Nov 2026)

A weekly review of what the city did, and the skills it took from it. Nothing in the city, the bets model or any
app changed. The deliverables are two skill files in the brain. No prices or news were used; the only date that
matters is the review window, 1 to 8 Nov 2026 (UTC).

## What I reviewed
- `brain/INDEX.md`, `brain/skills/` (13 files), and `brain/brain.json` (not edited)
- The newest job folders: `outputs/job-22` (betting-model fix), `job-21` (Lucky Tower factor study), `job-19`
  (mouse panning), `job-18` (an escalation, no build), `job-16` (last week's dream) and `job-15` (an escalation)
- No "Skill learned:" notes were found this week. The review used the job files and the code they describe.
- Checked that `brain/skills/city-camera-controls.md` already covers job 19's mouse-panning notes. No change needed.

## Skill files written or changed

**1. `brain/skills/betting-model-learning.md`: improved (learned_from: 2, 6, 26)**
The file was five lines. Job 22 showed two things worth keeping: bucket graded bets by market-implied probability
(the model floored long shots at 10% and they won 5.5%, while the average looked fine), and check for one-sided
markets (props that post only a "yes" price, so the model ran alone). The file now has both steps, the test command,
and a warning that two days of data is not a trend. It links to the new factor skill.

**2. `brain/skills/factor-edge-test.md`: new (learned_from: 26)**
The method job 21 used to test weather, defense form and rest against the line on 2,310 NFL games. It covers:
break-even from the odds (-110 is 52.4%), walk-forward fitting, standard error, and a verdict rule that needs
about 2 SE out of sample. It also covers the traps: many rules tried, small subgroups and the market already
pricing public factors. It works for stocks too, with 20-day forward returns in place of closing lines.
Related: `betting-model-learning`, `stock-signal-model`.

## How to use them
- Any job that asks "does factor X predict the result?" reads `factor-edge-test.md` first, then
  `betting-model-learning.md` if it touches `bets/`.
- Links were checked by hand: `factor-edge-test`, `betting-model-learning`, `stock-signal-model` are all real
  slugs. The runner regenerates `brain/INDEX.md` after the job.

## Assumptions
- `learned_from: 26` on the new skill follows the city's rule for this job. The evidence came from jobs 21 and 22.
- The 2 SE threshold and the "many rules tried" warning are my conventions, drawn from job 21's own caveats. They
  are not taken from a published standard.
- The NFL/NBA hold figure (10%) in the betting skill is still a typical value, not measured, as job 22 said.
- Date of the data: the review covers job files dated 31 Oct to 8 Nov 2026; no live facts were used.
