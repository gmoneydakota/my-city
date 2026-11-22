---
title: Survive a usage limit mid-job
tags: progress, checkpoint, resume, limits
agents: coder, quant, cad, forge, analyst
learned_from: 27, 30, 32
related: escalate-one-hop, verify-a-job-landed
---
## When to use
Any job that writes several files or changes code. A usage limit, or an unattended stop, can end it halfway.

## How
1. Save files as you go, never all at the end. Write a draft README early and finish it last.
2. Keep `outputs/job-N/PROGRESS.md` up to date with done / still-to-do. Update it after each file or code change, one line each.
3. In PROGRESS.md, name each code change by its constant, function or test (e.g. `SideBias`), so a resumed run can grep for it.
4. When a job is resumed, read PROGRESS.md and the restored files first. Check each "done" item with `verify-a-job-landed` before you build on it. Continue; don't start over.
5. If a Bash call returns an approval prompt instead of output, mark that step "not confirmed" in PROGRESS.md and carry on with the rest. Never write "done" for a step whose output you did not see.

## Gotchas
- Job 27 wrote its README and skill edit, but its last command came back as an approval prompt, so those writes were never confirmed.
- Job 30 described a code change that was not in `bets/betmodel/`. Check claims with `verify-a-job-landed`.
- The file a resumed run reads first is PROGRESS.md. If it is missing or stale, the resumed run will redo or skip work.
