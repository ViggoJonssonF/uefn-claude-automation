"""Gauntlet: evidence-gated multi-agent workflow for UEFN work.

Nothing is "done" because an agent says so. A task is done when:
  1. the deterministic gate (this tool, not an agent) recorded PASS evidence for it, and
  2. every required reviewer - never the task's own owner - recorded a PASS verdict AFTER that
     evidence was produced.
The TaskCompleted hook (`gauntlet.py check`) refuses to close a gauntlet task until both hold.

State lives in <project root>/.gauntlet/<run-id>/ :
  SPEC.md          what "done" means - acceptance criteria and reference "bars"
  LEDGER.md        every ruling: what was decided, why, what it costs if wrong
  tasks/<T>.json   id, title, owner, required reviews, gates
  evidence/<T>.gate.json + screenshots   written ONLY by `gauntlet.py gate`
  reviews/<T>.<role>.json                written by `gauntlet.py verdict`
.gauntlet/CURRENT holds the active run id. .gauntlet/editor.lock serializes editor mutations.

Commands (run from anywhere inside the project, or pass --root):
  init "<title>"                                   new run, becomes CURRENT
  task add T1 --title ".." --owner uefn-ui-builder --reviews spec,visual,skeptic --gates compile,playtest
  gate T1 [--playtest] [--viewport x,y,z,pitch,yaw] [--client-shot]
  verdict T1 --role spec --by uefn-spec-reviewer --pass|--fail --notes ".." [--evidence path ...]
  ruling "<what> -- <why> -- <cost if wrong>"
  status [T1]
  lock acquire <who> "<reason>" [--ttl 900] | lock release <who> | lock status
  check                                            (TaskCompleted hook: reads hook JSON on stdin)

Task subjects in Claude Code's task list must start with "[G:<id>]" for the hook to gate them.
"""

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
PY = sys.executable

REVIEW_ROLES = {"spec", "visual", "skeptic", "test"}
GATES = {"compile", "playtest", "visual"}
TASK_RE = re.compile(r"^\s*\[G:([A-Za-z0-9_-]+)\]")


# --- paths -------------------------------------------------------------------------------------
def find_root(start=None):
    """Project root = nearest ancestor with a *.uefnproject file (or an existing .gauntlet dir)."""
    d = os.path.abspath(start or os.getcwd())
    while True:
        if os.path.isdir(os.path.join(d, ".gauntlet")) or any(
                f.endswith(".uefnproject") for f in os.listdir(d)):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            raise SystemExit("gauntlet: no UEFN project root found (no *.uefnproject above here); pass --root")
        d = parent


def gdir(root):
    path = os.path.join(root, ".gauntlet")
    os.makedirs(path, exist_ok=True)
    return path


def current_run(root):
    p = os.path.join(gdir(root), "CURRENT")
    if not os.path.exists(p):
        raise SystemExit("gauntlet: no active run - use `gauntlet.py init \"<title>\"`")
    run = open(p, encoding="utf-8").read().strip()
    return run, os.path.join(gdir(root), run)


def now_iso():
    return dt.datetime.now().isoformat(timespec="seconds")


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)


# --- init / tasks / ledger ---------------------------------------------------------------------
SPEC_TEMPLATE = """# {title}

Run: {run} - started {when}

## Goal
<one paragraph, in the user's words>

## Acceptance criteria (each must be checkable by a gate, a test or a reviewer)
- [ ] ...

## Bars (concrete references the visual critic compares against)
- <existing widget / screenshot path / named reference>

## Out of scope
- ...

## Open questions asked up front (and answers)
- ...
"""


def cmd_init(args, root):
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    slug = re.sub(r"[^a-z0-9]+", "-", args.title.lower()).strip("-")[:40] or "run"
    run = f"{stamp}-{slug}"
    rdir = os.path.join(gdir(root), run)
    for sub in ("tasks", "evidence", "reviews"):
        os.makedirs(os.path.join(rdir, sub), exist_ok=True)
    with open(os.path.join(rdir, "SPEC.md"), "w", encoding="utf-8") as f:
        f.write(SPEC_TEMPLATE.format(title=args.title, run=run, when=now_iso()))
    with open(os.path.join(rdir, "LEDGER.md"), "w", encoding="utf-8") as f:
        f.write(f"# Ledger - {args.title}\n\nFormat: `time | Ruling: what -- why -- cost if wrong`\n\n")
    with open(os.path.join(gdir(root), "CURRENT"), "w", encoding="utf-8") as f:
        f.write(run)
    print(f"run {run} created at {rdir}")


def cmd_task(args, root):
    run, rdir = current_run(root)
    reviews = [r.strip() for r in (args.reviews or "spec,skeptic").split(",") if r.strip()]
    gates = [g.strip() for g in (args.gates or "compile").split(",") if g.strip()]
    bad = [r for r in reviews if r not in REVIEW_ROLES] + [g for g in gates if g not in GATES]
    if bad:
        raise SystemExit(f"gauntlet: unknown review/gate names: {bad} (reviews {sorted(REVIEW_ROLES)}, gates {sorted(GATES)})")
    task = {"id": args.id, "title": args.title, "owner": args.owner, "reviews": reviews,
            "gates": gates, "created": now_iso(), "fix_round": 0}
    write_json(os.path.join(rdir, "tasks", f"{args.id}.json"), task)
    print(f"task {args.id} -> owner {args.owner}, gates {gates}, reviews {reviews}")
    print(f'Claude Code task subject must start with: [G:{args.id}]')


def cmd_ruling(args, root):
    run, rdir = current_run(root)
    with open(os.path.join(rdir, "LEDGER.md"), "a", encoding="utf-8") as f:
        f.write(f"- {now_iso()} | Ruling: {args.text}\n")
    print("ledger updated")


# --- the deterministic gate --------------------------------------------------------------------
def run_py(script, *argv, timeout=None):
    r = subprocess.run([PY, os.path.join(HERE, script), *argv], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return r.returncode, r.stdout, r.stderr


def cmd_gate(args, root):
    run, rdir = current_run(root)
    task = read_json(os.path.join(rdir, "tasks", f"{args.id}.json"))
    if not task:
        raise SystemExit(f"gauntlet: unknown task {args.id}")
    ev_dir = os.path.join(rdir, "evidence")
    evidence = {"task": args.id, "run": run, "started": now_iso(), "checks": {}, "artifacts": []}
    ok = True

    code, out, _ = run_py("uefn_watch.py")
    evidence["checks"]["health"] = {"exit": code, "summary": out.strip().splitlines()[0] if out else ""}
    if code in (2, 3):
        ok = False

    if ok and ("compile" in task["gates"] or args.compile):
        from uefn_mcp_client import UefnMcp
        diags = UefnMcp().call("ValkyrieToolset.VerseToolset", "BuildAll")["returnValue"]
        errors = [d for d in diags if d["severity"] == "Error"]
        evidence["checks"]["compile"] = {
            "errors": len(errors), "warnings": sum(1 for d in diags if d["severity"] == "Warning"),
            "first_errors": [f"{e['filePath']}:{e['span']['startLine'] + 1} {e['message'][:200]}" for e in errors[:10]]}
        ok = ok and not errors

    if ok and ("playtest" in task["gates"] or args.playtest):
        out_dir = os.path.join(ev_dir, f"{args.id}-playtest")
        project_content = os.path.join(root, "Content")
        code, out, err = run_py("uefn_playtest.py", "--project", project_content, "--out", out_dir,
                                "--timeout", str(args.playtest_timeout))
        report = read_json(os.path.join(out_dir, "report.json"), {})
        evidence["checks"]["playtest"] = {
            "exit": code, "summary": report.get("summary"),
            "failed": [r["id"] for r in report.get("results", []) if r["status"] == "FAIL"],
            "runtime_errors": len(report.get("runtime_errors", [])),
            "report": os.path.join(out_dir, "report.json")}
        evidence["artifacts"] += report.get("screenshots", [])
        ok = ok and code == 0

    if args.viewport:
        from uefn_mcp_client import UefnMcp
        x, y, z, pitch, yaw = [float(v) for v in args.viewport.split(",")]
        png = UefnMcp().call_image("EditorToolset.EditorAppToolset", "CaptureViewport", {
            "captureTransform": {"location": {"x": x, "y": y, "z": z},
                                 "rotation": {"pitch": pitch, "yaw": yaw, "roll": 0},
                                 "scale": {"x": 1, "y": 1, "z": 1}}})
        if png:
            path = os.path.join(ev_dir, f"{args.id}-viewport-{int(time.time())}.png")
            open(path, "wb").write(png)
            evidence["artifacts"].append(path)
        else:
            evidence["checks"]["viewport"] = "capture returned no image"
            ok = False

    if args.client_shot:
        path = os.path.join(ev_dir, f"{args.id}-client-{int(time.time())}.png")
        code, _, _ = run_py("grab_window.py", "--title", "Fortnite  ", "--out", path, "--client-only")
        if code == 0 and os.path.exists(path):
            evidence["artifacts"].append(path)
        else:
            evidence["checks"]["client_shot"] = "no Fortnite client window to capture"

    if "visual" in task["gates"] and not evidence["artifacts"]:
        evidence["checks"]["visual"] = "visual gate needs at least one screenshot (--viewport / --client-shot / playtest)"
        ok = False

    evidence["status"] = "PASS" if ok else "FAIL"
    evidence["finished"] = now_iso()
    evidence["finished_ts"] = time.time()
    write_json(os.path.join(ev_dir, f"{args.id}.gate.json"), evidence)
    print(json.dumps(evidence, indent=1, ensure_ascii=False))
    return 0 if ok else 1


# --- reviewer verdicts -------------------------------------------------------------------------
def cmd_verdict(args, root):
    run, rdir = current_run(root)
    task = read_json(os.path.join(rdir, "tasks", f"{args.id}.json"))
    if not task:
        raise SystemExit(f"gauntlet: unknown task {args.id}")
    if args.role not in REVIEW_ROLES:
        raise SystemExit(f"gauntlet: role must be one of {sorted(REVIEW_ROLES)}")
    if args.by == task["owner"]:
        raise SystemExit("gauntlet: the owner of a task can never review it")
    gate = read_json(os.path.join(rdir, "evidence", f"{args.id}.gate.json"))
    if args.passed and not gate:
        raise SystemExit("gauntlet: no gate evidence yet - a PASS verdict needs evidence to judge")
    verdict = {"task": args.id, "role": args.role, "by": args.by,
               "verdict": "PASS" if args.passed else "FAIL", "notes": args.notes,
               "evidence": args.evidence or [], "at": now_iso(), "at_ts": time.time(),
               "gate_seen": gate.get("finished") if gate else None}
    write_json(os.path.join(rdir, "reviews", f"{args.id}.{args.role}.json"), verdict)
    if not args.passed:
        task["fix_round"] = task.get("fix_round", 0) + 1
        write_json(os.path.join(rdir, "tasks", f"{args.id}.json"), task)
    print(f"{args.id} {args.role}: {verdict['verdict']} (fix round {task.get('fix_round', 0)})")


def task_state(rdir, task_id):
    """(done, problems) - the single source of truth for 'is this task finished'."""
    task = read_json(os.path.join(rdir, "tasks", f"{task_id}.json"))
    if not task:
        return False, [f"no gauntlet task {task_id} in this run"]
    problems = []
    gate = read_json(os.path.join(rdir, "evidence", f"{task_id}.gate.json"))
    if not gate:
        problems.append("no gate evidence - run `gauntlet.py gate`")
    elif gate.get("status") != "PASS":
        problems.append(f"gate evidence is {gate.get('status')}: {json.dumps(gate.get('checks'))[:300]}")
    for role in task["reviews"]:
        v = read_json(os.path.join(rdir, "reviews", f"{task_id}.{role}.json"))
        if not v:
            problems.append(f"missing {role} review")
        elif v["verdict"] != "PASS":
            problems.append(f"{role} review is FAIL: {v.get('notes', '')[:200]}")
        elif v["by"] == task["owner"]:
            problems.append(f"{role} review was written by the owner")
        elif gate and v.get("at_ts", 0) < gate.get("finished_ts", 0):
            problems.append(f"{role} review predates the latest gate evidence - re-review needed")
    return not problems, problems


def cmd_status(args, root):
    run, rdir = current_run(root)
    ids = [args.id] if args.id else sorted(f[:-5] for f in os.listdir(os.path.join(rdir, "tasks")) if f.endswith(".json"))
    print(f"run {run}")
    for tid in ids:
        task = read_json(os.path.join(rdir, "tasks", f"{tid}.json"), {})
        done, problems = task_state(rdir, tid)
        print(f"  {tid} [{'DONE' if done else 'OPEN'}] {task.get('title', '')} (owner {task.get('owner')}, fix round {task.get('fix_round', 0)})")
        for p in problems:
            print(f"      - {p}")


def cmd_check(args, root):
    """TaskCompleted hook. Exit 2 (stderr = feedback to Claude) blocks completing a gated task."""
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    m = TASK_RE.match(payload.get("task_subject", "") or "")
    if not m:
        return 0                      # not a gauntlet task - never interfere
    try:
        run, rdir = current_run(root)
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        return 2
    done, problems = task_state(rdir, m.group(1))
    if done:
        return 0
    print(f"Gauntlet refuses to complete {m.group(1)}: " + "; ".join(problems), file=sys.stderr)
    return 2


# --- editor lock -------------------------------------------------------------------------------
def cmd_lock(args, root):
    path = os.path.join(gdir(root), "editor.lock")
    held = read_json(path)
    expired = held and time.time() > held.get("expires", 0)
    if args.action == "status":
        print(json.dumps(held, indent=1) if held and not expired else "free")
        return 0
    if args.action == "acquire":
        if held and not expired and held["who"] != args.who:
            print(f"LOCKED by {held['who']} ({held['reason']}) until {time.ctime(held['expires'])}")
            return 1
        write_json(path, {"who": args.who, "reason": args.reason or "", "since": now_iso(),
                          "expires": time.time() + args.ttl})
        print(f"lock acquired by {args.who}")
        return 0
    if args.action == "release":
        if held and held["who"] != args.who and not expired:
            print(f"not released: held by {held['who']}")
            return 1
        if os.path.exists(path):
            os.remove(path)
        print("lock released")
        return 0


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", help="UEFN project root (the folder with the .uefnproject)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init"); p.add_argument("title")
    p = sub.add_parser("task"); p.add_argument("action", choices=["add"]); p.add_argument("id")
    p.add_argument("--title", required=True); p.add_argument("--owner", required=True)
    p.add_argument("--reviews"); p.add_argument("--gates")
    p = sub.add_parser("gate"); p.add_argument("id"); p.add_argument("--compile", action="store_true")
    p.add_argument("--playtest", action="store_true"); p.add_argument("--playtest-timeout", type=int, default=900)
    p.add_argument("--viewport"); p.add_argument("--client-shot", action="store_true")
    p = sub.add_parser("verdict"); p.add_argument("id"); p.add_argument("--role", required=True)
    p.add_argument("--by", required=True); g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--pass", dest="passed", action="store_true"); g.add_argument("--fail", dest="passed", action="store_false")
    p.add_argument("--notes", default=""); p.add_argument("--evidence", nargs="*")
    p = sub.add_parser("ruling"); p.add_argument("text")
    p = sub.add_parser("status"); p.add_argument("id", nargs="?")
    p = sub.add_parser("lock"); p.add_argument("action", choices=["acquire", "release", "status"])
    p.add_argument("who", nargs="?", default=""); p.add_argument("reason", nargs="?", default="")
    p.add_argument("--ttl", type=int, default=900)
    sub.add_parser("check")

    args = ap.parse_args()
    if args.cmd == "check":
        try:
            root = find_root(args.root or os.environ.get("CLAUDE_PROJECT_DIR"))
        except SystemExit:
            return 0                  # outside a UEFN project the hook is a no-op
    else:
        root = find_root(args.root)
    handler = {"init": cmd_init, "task": cmd_task, "gate": cmd_gate, "verdict": cmd_verdict,
               "ruling": cmd_ruling, "status": cmd_status, "check": cmd_check, "lock": cmd_lock}[args.cmd]
    return handler(args, root) or 0


if __name__ == "__main__":
    sys.exit(main())
