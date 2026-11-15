"""Check that the file paths and ALL_CAPS identifiers cited in brain/skills/*.md still exist in the repo.

Run from the repo root:  python3 -I outputs/job-29/check_skill_refs.py
Prints one line per problem and a total. No model calls, stdlib only.
"""
import pathlib
import re

ROOT = pathlib.Path(".")
SKILLS = sorted(pathlib.Path("brain/skills").glob("*.md"))
PATH_RE = re.compile(r"\.(py|md|json|csv|html|ts|js)$")
CONST_RE = re.compile(r"[A-Z][A-Z0-9_]{3,}")

# Code text, read once, used to test whether a named constant or function exists.
CODE = "\n".join(
    q.read_text(errors="ignore") for q in ROOT.rglob("*.py") if ".git" not in q.parts
)

problems = []
for skill in SKILLS:
    body = skill.read_text()
    for tok in sorted(set(re.findall(r"`([^`\n]+)`", body))):
        t = tok.strip()
        if " " in t or t.startswith(("http", "-")):
            continue
        if "/" in t or PATH_RE.search(t):
            path = t.split(":")[0].rstrip("/")
            # Skip templates like outputs/job-N/ and placeholders like <slug>.
            if "<" in path or "job-N" in path or "job-" in path:
                continue
            if PATH_RE.search(path) or path.endswith("/"):
                if not (ROOT / path).exists():
                    problems.append(f"{skill.name}: path `{path}` not found")
        elif CONST_RE.fullmatch(t):
            if t not in CODE:
                problems.append(f"{skill.name}: name `{t}` not found in any .py file")

for p in problems:
    print(p)
print(f"checked {len(SKILLS)} skill files; problems: {len(problems)}")
