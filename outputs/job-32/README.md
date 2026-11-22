# Job #32 · Brain dream (week of 15 to 22 Nov 2026)

A weekly review of what the city did, and the skills it took from it. Nothing in the city, the bets model or any app
changed. The deliverables are two skill files in the brain. The only date that matters is the review window, 15 to
22 Nov 2026 (UTC). No prices or news were used.

## What I reviewed
- `brain/INDEX.md`, all 14 files in `brain/skills/`, and `brain/skills/learn-a-skill.md` for the format.
- The newest job folders: `outputs/job-30` (a betting-model side-bias change), `outputs/job-29` (a skill-link checker
  script) and `outputs/job-27` (a betting change with an unconfirmed write).
- No "Skill learned:" notes were found this week, so the review used the job files and the code they describe.
- Checked `bets/betmodel/engine.py` by grep: `ONE_SIDED_HOLD` is present. `OVER_SHIFT`, `side_adjust` and the
  `OVER_BIAS` / `over_bias_adjust` names from job 27 are not. So job 30's side-bias change is not in the code.
- Did not run `outputs/job-29/check_skill_refs.py`: the shell blocked it with an approval prompt. Its skill links
  were checked by hand instead. All slugs in the new and changed files exist in `brain/INDEX.md`.

## Skill files written or changed

**1. `brain/skills/verify-a-job-landed.md`: new (learned_from: 32)**
Before a job says "done", grep for each changed constant, function or test name, check `git status`, and run the
named test command. Job 30's README described a fix that was not in the code, and job 27's last command was blocked
by an approval prompt. The file says to write "not confirmed" in those cases. Related: `betting-model-learning`,
`pause-and-resume`, `learn-a-skill`.

**2. `brain/skills/pause-and-resume.md`: improved (learned_from: 27, 30, 32; related adds verify-a-job-landed)**
This was the weakest file: five lines, no gotchas, and an empty `learned_from`. It now says to write a draft README
early, to name each code change in PROGRESS.md so a resumed run can grep for it, and to treat a blocked command as
"not confirmed". It also records the job 27 and job 30 cases.

## How to use them
- Any job that is about to report a change as made reads `verify-a-job-landed.md` first.
- Any job that writes several files, or is resumed, reads `pause-and-resume.md` first.
- Not done, for the owner to decide: job 30 says the bets side-bias shift is live. It is not in `bets/betmodel/`.
  The bets skill already warns about this. A coder job should add it or the README should be corrected. I did not
  change `bets/`, because it is outside this job's scope.

## Assumptions
- `learned_from: 32` follows the city's rule for this job. The evidence came from jobs 27 and 30 and the code check above.
- "Blocked by an approval prompt" is treated as "unverified". I could not find out why the prompts happen, and the
  skill says so.
- Date of the data: the repo state and job files as of 22 Nov 2026. No live facts were used.
- The brain index (`brain/INDEX.md`, `brain/brain.json`) was not edited. `scripts/brain.py` regenerates it after the job.
