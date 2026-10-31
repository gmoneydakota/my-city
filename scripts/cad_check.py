#!/usr/bin/env python3
"""Checks an Agent City CAD model (agent-city-cad/1, see cad/SCHEMA.md). No model calls, stdlib only.

    python3 scripts/cad_check.py outputs/job-12/model.json        # human report, exit 1 on errors
    python3 scripts/cad_check.py model.json --json                 # machine-readable report

Errors = the CAD Studio can't build it correctly. Warnings = it builds, but probably doesn't make
physical sense yet (floating parts, not standing on the floor, hinge pivots nowhere near their part).
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

FORMAT = "agent-city-cad/1"
SHAPES = {
    "box": ("w", "h", "d"),
    "cylinder": ("h",),          # plus r, or rTop/rBottom
    "cone": ("r", "h"),
    "sphere": ("r",),
    "capsule": ("r", "h"),
    "torus": ("r", "tube"),
    "tube": ("r", "ri", "h"),
    "gear": ("r", "teeth", "h"),
    "extrude": ("points", "depth"),
    "lathe": ("points",),
}
NUMERIC_SIZE = {"w", "h", "d", "r", "rTop", "rBottom", "tube", "ri", "teeth", "depth", "sides", "bore"}
MATERIALS = {"metal", "plastic", "wood", "rubber", "glass", "fabric", "stone", "paint", "emissive"}
JOINTS = {"revolute", "continuous", "prismatic"}
ID_RE = re.compile(r"^[a-z0-9_-]{1,64}$")
COLOR_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
MAX_PARTS = 400


def num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def vec3(v) -> bool:
    return isinstance(v, list) and len(v) == 3 and all(num(x) for x in v)


def rot_matrix(deg):
    """Three.js Euler 'XYZ': M = Rx * Ry * Rz."""
    x, y, z = (math.radians(a) for a in deg)
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    rx = [[1, 0, 0], [0, cx, -sx], [0, sx, cx]]
    ry = [[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]
    rz = [[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]]
    mul = lambda a, b: [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]  # noqa: E731
    return mul(mul(rx, ry), rz)


def local_box(shape: str, s: dict):
    """Axis-aligned bounds of the shape in its own frame: (min xyz, max xyz)."""
    if shape == "box":
        hx, hy, hz = s["w"] / 2, s["h"] / 2, s["d"] / 2
        return (-hx, -hy, -hz), (hx, hy, hz)
    if shape in ("cylinder", "cone", "capsule", "tube"):
        r = max(s.get("r", 0), s.get("rTop", 0), s.get("rBottom", 0))
        return (-r, -s["h"] / 2, -r), (r, s["h"] / 2, r)
    if shape == "sphere":
        r = s["r"]
        return ((-r, 0, -r), (r, r, r)) if s.get("half") else ((-r, -r, -r), (r, r, r))
    if shape == "torus":
        o = s["r"] + s["tube"]
        return (-o, -s["tube"], -o), (o, s["tube"], o)
    if shape == "gear":
        o = s["r"] + 2 * s["r"] / s["teeth"]
        return (-o, -s["h"] / 2, -o), (o, s["h"] / 2, o)
    if shape == "extrude":
        xs, ys = [p[0] for p in s["points"]], [p[1] for p in s["points"]]
        return (min(xs), min(ys), -s["depth"] / 2), (max(xs), max(ys), s["depth"] / 2)
    if shape == "lathe":
        r = max(abs(p[0]) for p in s["points"])
        ys = [p[1] for p in s["points"]]
        return (-r, min(ys), -r), (r, max(ys), r)
    raise ValueError(shape)


def world_box(part: dict):
    lo, hi = local_box(part["shape"], part["size"])
    m = rot_matrix(part.get("rot") or [0, 0, 0])
    p = part["pos"]
    pts = []
    for cx in (lo[0], hi[0]):
        for cy in (lo[1], hi[1]):
            for cz in (lo[2], hi[2]):
                pts.append([p[i] + m[i][0] * cx + m[i][1] * cy + m[i][2] * cz for i in range(3)])
    return [min(q[i] for q in pts) for i in range(3)], [max(q[i] for q in pts) for i in range(3)]


def boxes_touch(a, b, tol: float) -> bool:
    return all(a[0][i] - tol <= b[1][i] and b[0][i] - tol <= a[1][i] for i in range(3))


def dist_to_box(p, box) -> float:
    return math.sqrt(sum(max(box[0][i] - p[i], 0, p[i] - box[1][i]) ** 2 for i in range(3)))


def check_size(pid: str, shape: str, s, err) -> bool:
    if not isinstance(s, dict):
        err(f"part '{pid}': size must be an object")
        return False
    ok = True
    for key in SHAPES[shape]:
        if key not in s:
            err(f"part '{pid}' ({shape}): size.{key} is missing")
            ok = False
    if not ok:
        return False
    if shape == "cylinder" and not any(num(s.get(k)) and s.get(k) > 0 for k in ("r", "rTop", "rBottom")):
        err(f"part '{pid}' (cylinder): needs size.r, or size.rTop / size.rBottom")
        return False
    for key, v in s.items():
        if key not in NUMERIC_SIZE:
            continue
        if key in ("rTop", "rBottom", "bore"):
            if not num(v) or v < 0:
                err(f"part '{pid}': size.{key} must be a number ≥ 0")
                ok = False
        elif not num(v) or v <= 0:
            err(f"part '{pid}': size.{key} must be a positive number (got {v!r})")
            ok = False
    if not ok:
        return False
    if shape in ("extrude", "lathe"):
        pts, need = s["points"], 3 if shape == "extrude" else 2
        if not (isinstance(pts, list) and len(pts) >= need and all(
                isinstance(p, list) and len(p) == 2 and all(num(c) for c in p) for p in pts)):
            err(f"part '{pid}' ({shape}): points must be a list of ≥{need} [x, y] pairs")
            return False
        if shape == "lathe" and any(p[0] < 0 for p in pts):
            err(f"part '{pid}' (lathe): every point's radius (first number) must be ≥ 0")
            return False
        if shape == "lathe" and max(p[0] for p in pts) <= 0:
            err(f"part '{pid}' (lathe): profile has zero radius everywhere")
            return False
    if shape == "tube" and s["ri"] >= s["r"]:
        err(f"part '{pid}' (tube): inner radius ri must be smaller than r")
        return False
    if shape == "capsule" and s["h"] < 2 * s["r"]:
        err(f"part '{pid}' (capsule): h is the total height and must be ≥ 2·r")
        return False
    if shape == "gear":
        if int(s["teeth"]) != s["teeth"] or not 6 <= s["teeth"] <= 400:
            err(f"part '{pid}' (gear): teeth must be a whole number from 6 to 400")
            return False
        if s.get("bore", 0) >= s["r"] * 0.8:
            err(f"part '{pid}' (gear): bore is too big for the gear")
            return False
    if shape == "torus" and s["tube"] >= s["r"]:
        err(f"part '{pid}' (torus): tube radius must be smaller than ring radius r")
        return False
    return True


def check(model) -> dict:
    errors, warnings = [], []
    err, warn = errors.append, warnings.append
    if not isinstance(model, dict):
        return {"errors": ["the file must be a JSON object"], "warnings": [], "summary": {}}
    if model.get("format") != FORMAT:
        warn(f"format should be \"{FORMAT}\"")
    for key in ("name", "description"):
        if not isinstance(model.get(key), str) or not model[key].strip():
            err(f"'{key}' must be a non-empty string")
    if model.get("units", "mm") != "mm":
        err("units must be \"mm\"")
    hiw = model.get("how_it_works")
    if not (isinstance(hiw, list) and hiw and all(isinstance(x, str) and x.strip() for x in hiw)):
        warn("how_it_works should be a list of plain-language steps explaining how the thing works")

    parts = model.get("parts")
    if not isinstance(parts, list) or not parts:
        err("'parts' must be a non-empty list")
        return {"errors": errors, "warnings": warnings, "summary": {}}
    if len(parts) > MAX_PARTS:
        err(f"too many parts ({len(parts)}); keep it under {MAX_PARTS}")

    byid, good = {}, []
    for i, p in enumerate(parts):
        if not isinstance(p, dict):
            err(f"parts[{i}] must be an object")
            continue
        pid = p.get("id")
        if not isinstance(pid, str) or not ID_RE.match(pid):
            err(f"parts[{i}]: id must be lowercase letters, digits, _ or - (got {pid!r})")
            continue
        if pid in byid:
            err(f"duplicate part id '{pid}'")
            continue
        byid[pid] = p
        if not isinstance(p.get("name"), str) or not p["name"].strip():
            err(f"part '{pid}': name is missing")
        if not isinstance(p.get("role"), str) or not p["role"].strip():
            warn(f"part '{pid}': add a 'role' saying what it is for")
        shape = p.get("shape")
        if shape not in SHAPES:
            err(f"part '{pid}': unknown shape {shape!r} (use one of {', '.join(SHAPES)})")
            continue
        if not vec3(p.get("pos")):
            err(f"part '{pid}': pos must be [x, y, z] numbers")
            continue
        if "rot" in p and p["rot"] is not None and not vec3(p["rot"]):
            err(f"part '{pid}': rot must be [x, y, z] degrees")
            continue
        if "color" in p and not (isinstance(p["color"], str) and COLOR_RE.match(p["color"])):
            warn(f"part '{pid}': color should look like \"#3a7bd5\"")
        if "material" in p and p["material"] not in MATERIALS:
            warn(f"part '{pid}': unknown material {p['material']!r} (use one of {', '.join(sorted(MATERIALS))})")
        if check_size(pid, shape, p.get("size"), err):
            good.append(pid)

    # parent chains
    for pid, p in byid.items():
        par = p.get("parent")
        if par is None:
            continue
        if par not in byid:
            err(f"part '{pid}': parent '{par}' does not exist")
            continue
        seen, cur = {pid}, par
        while cur is not None and cur in byid:
            if cur in seen:
                err(f"part '{pid}': parent chain loops back on itself")
                break
            seen.add(cur)
            cur = byid[cur].get("parent")

    boxes = {pid: world_box(byid[pid]) for pid in good}
    summary = {"parts": len(parts), "joints": 0}
    if boxes:
        lo = [min(b[0][i] for b in boxes.values()) for i in range(3)]
        hi = [max(b[1][i] for b in boxes.values()) for i in range(3)]
        dims = [hi[i] - lo[i] for i in range(3)]
        diag = math.sqrt(sum(d * d for d in dims)) or 1.0
        summary.update({"size_mm": {"x": round(dims[0], 1), "y": round(dims[1], 1), "z": round(dims[2], 1)},
                        "bottom_y": round(lo[1], 1)})
        if abs(lo[1]) > max(2.0, diag * 0.02):
            warn(f"the model's lowest point is at y = {lo[1]:.1f} mm; it should rest on the floor (y = 0)")
        if diag < 1 or diag > 1e6:
            warn(f"overall size {diag:.1f} mm looks wrong; units are millimetres")
        for pid, b in boxes.items():
            pd = max(b[1][i] - b[0][i] for i in range(3))
            if pd < diag * 0.0015:
                warn(f"part '{pid}' is tiny ({pd:.2f} mm) compared with the whole model; will it be visible?")

        # connectivity: every non-loose part should touch the rest (rotated boxes, so this is lenient)
        tol = max(0.5, diag * 0.004)
        ids = [pid for pid in boxes if not byid[pid].get("loose")]
        adj = {pid: set() for pid in ids}
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                if boxes_touch(boxes[a], boxes[b], tol) or byid[a].get("parent") == b or byid[b].get("parent") == a:
                    adj[a].add(b)
                    adj[b].add(a)
        groups, seen = [], set()
        for pid in ids:
            if pid in seen:
                continue
            stack, comp = [pid], []
            seen.add(pid)
            while stack:
                cur = stack.pop()
                comp.append(cur)
                for nb in adj[cur] - seen:
                    seen.add(nb)
                    stack.append(nb)
            groups.append(comp)
        groups.sort(key=len, reverse=True)
        summary["connected_groups"] = len(groups)
        for comp in groups[1:]:
            names = ", ".join(sorted(comp)[:8]) + (" …" if len(comp) > 8 else "")
            warn(f"floating: [{names}] doesn't touch the main body. Move it into contact, add a "
                 f"connecting part, or mark it \"loose\": true if it really is separate")

    # joints
    joints = model.get("joints") or []
    if not isinstance(joints, list):
        err("'joints' must be a list")
        joints = []
    summary["joints"] = len(joints)
    jids, moved = {}, {}
    for i, j in enumerate(joints):
        if not isinstance(j, dict):
            err(f"joints[{i}] must be an object")
            continue
        jid = j.get("id")
        if not isinstance(jid, str) or not ID_RE.match(jid):
            err(f"joints[{i}]: id must be lowercase letters, digits, _ or -")
            continue
        if jid in jids:
            err(f"duplicate joint id '{jid}'")
            continue
        jids[jid] = j
        jt, part = j.get("type"), j.get("part")
        if jt not in JOINTS:
            err(f"joint '{jid}': type must be one of {', '.join(sorted(JOINTS))}")
        if part not in byid:
            err(f"joint '{jid}': part '{part}' does not exist")
        elif part in moved:
            err(f"joints '{moved[part]}' and '{jid}' both move part '{part}'; one joint per part "
                f"(add a small hinge/axle part to stack motions)")
        else:
            moved[part] = jid
        axis = j.get("axis")
        if not vec3(axis) or math.sqrt(sum(a * a for a in axis)) < 1e-9:
            err(f"joint '{jid}': axis must be a non-zero [x, y, z]")
        if jt in ("revolute", "continuous"):
            if not vec3(j.get("pivot")):
                err(f"joint '{jid}': pivot must be [x, y, z]")
            elif part in boxes:
                d = dist_to_box(j["pivot"], boxes[part])
                if boxes and d > max(5.0, diag * 0.05):
                    warn(f"joint '{jid}': pivot is {d:.0f} mm away from part '{part}'; "
                         f"a hinge or axle normally sits on the part it turns")
        if jt in ("revolute", "prismatic"):
            lo_, hi_ = j.get("min"), j.get("max")
            if not (num(lo_) and num(hi_)) or lo_ >= hi_:
                err(f"joint '{jid}': needs numeric min < max")
            elif num(j.get("default", 0)) and not lo_ <= j.get("default", 0) <= hi_:
                err(f"joint '{jid}': default must be inside min..max")
        if jt == "continuous" and "rpm" in j and not num(j["rpm"]):
            err(f"joint '{jid}': rpm must be a number")
        if "period" in j and not (num(j["period"]) and j["period"] > 0):
            err(f"joint '{jid}': period must be a positive number of seconds")
    for jid, j in jids.items():
        f = j.get("follows")
        if f is None:
            continue
        if not isinstance(f, dict) or f.get("joint") not in jids or f.get("joint") == jid:
            err(f"joint '{jid}': follows.joint must name another joint")
            continue
        if not num(f.get("ratio", 1)) or not num(f.get("offset", 0)):
            err(f"joint '{jid}': follows.ratio / follows.offset must be numbers")
        seen, cur = {jid}, f["joint"]
        while cur in jids:
            if cur in seen:
                err(f"joint '{jid}': follows chain loops back on itself")
                break
            seen.add(cur)
            cur = (jids[cur].get("follows") or {}).get("joint")
    if not joints:
        warn("no joints: nothing moves. Most real objects have a hinge, wheel, slider or lid; add joints "
             "unless this object is genuinely solid")
    return {"errors": errors, "warnings": warnings, "summary": summary}


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print(__doc__.strip())
        return 2
    path = Path(args[0])
    try:
        model = json.loads(path.read_text())
    except FileNotFoundError:
        print(f"✗ {path}: file not found")
        return 1
    except json.JSONDecodeError as e:
        print(f"✗ {path}: not valid JSON ({e})")
        return 1
    rep = check(model)
    if "--json" in argv:
        print(json.dumps(rep, indent=2, ensure_ascii=False))
    else:
        s = rep["summary"]
        if s.get("size_mm"):
            sz = s["size_mm"]
            print(f"{model.get('name', path.name)}: {s['parts']} parts, {s['joints']} joints, "
                  f"{sz['x']} × {sz['y']} × {sz['z']} mm (W×H×D)")
        for e in rep["errors"]:
            print(f"✗ ERROR   {e}")
        for w in rep["warnings"]:
            print(f"⚠ warning {w}")
        if not rep["errors"]:
            print("✓ valid" + (" (fix the warnings above if you can)" if rep["warnings"] else ", no warnings"))
    return 1 if rep["errors"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
