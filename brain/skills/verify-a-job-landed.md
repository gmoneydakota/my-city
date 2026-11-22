---
title: Check that a job's change really landed
tags: verify, grep, git, tests, review, job-report
agents: coder, quant, analyst, forge, cad
learned_from: 32
related: betting-model-learning, pause-and-resume, learn-a-skill
---
## When to use
Before you write "done" or "changed" in a README, PROGRESS.md or reply, and before you build on a change a
previous job says it made. Job 30's README described an `OVER_SHIFT` side-bias fix in `bets/betmodel/engine.py`.
A grep for `OVER_SHIFT` and `side_adjust` in `bets/` found nothing on 22 Nov 2026, so the change was never in the code.

## How
1. Write down the names you changed: the constant, function and test class (e.g. `ONE_SIDED_HOLD`, `SideBias`).
2. Grep for each name in the folder the job touched: `grep -rn "NAME" bets/`. No hit means it did not land.
3. Check the working tree: `git status --short` lists new and changed files. A tracked file you edited must show up.
4. Run the test command the job named (e.g. `cd bets && python3 test_betmodel.py`). Quote its last line, including the test count. The count should match the number in the README.
5. Only then write "landed". If a check failed or never ran, write "not confirmed" and name the command.
6. Before you build on a previous job's claim, repeat steps 2 to 4 and cite the grep you ran.

## Gotchas
- A job's README can describe code that is not in the files. The brain can also say a fix exists when the code has none.
- A passing test only proves the tests you wrote. Check that the diff contains the change the README claims.
- Unattended runs: a Bash call can come back as an approval prompt instead of output. Job 27's last command was
  blocked this way, so its README and skill edit were never confirmed. Nobody answers in an unattended run, so
  treat a blocked command as unverified and say so. In job 32 even a single `python3 -I` call needed approval.
- If the change is missing, do not patch it silently in a docs job. Note it for the owner or a coder job.
