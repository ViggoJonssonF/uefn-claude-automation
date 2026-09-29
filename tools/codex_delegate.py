"""Delegate a task to a Codex agent (e.g. GPT-6 Astra) via `codex exec`, on the user's Codex usage.

Claude stays the director/verifier; Codex does the token-heavy work (e.g. Blender modelling through
Codex's own Blender + UEFN MCP servers). Everything is logged under the current gauntlet run.

  py -3 codex_delegate.py --task T5 --brief brief.md [--model gpt-6-astra] [--effort high] [--cwd <Content dir>]
        [--asset-job] [--max-tokens 3000000] [--timeout 14400] [--append-skill uefn-blender-assets]
        [--full-access]

--max-steps   kills Codex after N tool calls (live; token usage is only reported per turn).
--asset-job   refuses to run unless the user approved new assets for this run
              (`gauntlet.py assets approve ...`), and counts against that approval.
--max-tokens  kills Codex when its reported token usage passes this cap (default from the approval).
Exit: 0 Codex finished, 1 Codex failed/killed, 3 not approved, 4 Codex CLI not found.
Writes .gauntlet/<run>/codex/<task>/{prompt.md,events.jsonl,last_message.md,usage.json}.
"""

import argparse
import glob
import json
import os
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gauntlet  # noqa: E402  (shares run/approval state)

CODEX_GLOB = os.path.expandvars(r"%LOCALAPPDATA%\OpenAI\Codex\bin\*\codex.exe")
SKILLS_DIR = os.path.expanduser(r"~/.claude/skills")

CONTRACT = """

---
## Delegation contract (from the Claude Code director - follow exactly)
- You are a delegated worker. Do ONLY what the brief asks. Do not create any asset, file or UEFN
  content that the brief does not list. Stop and report instead of improvising scope.
- Put every file you create under the work folder named in the brief.
- Before finishing, verify your own output the way the conventions below describe (dimensions,
  import readback, preview image). A separate reviewer will re-check everything independently.
- End your final message with a fenced ```json block:
  {"status": "DONE|BLOCKED", "deliverables": [paths], "uefn_assets": [object paths],
   "previews": [png paths], "notes": "what is not verified"}
"""


def find_codex():
    found = sorted(glob.glob(CODEX_GLOB), key=os.path.getmtime, reverse=True)
    return found[0] if found else None


def usage_from_event(ev, current):
    """Best-effort: pick the largest cumulative token count any event reports."""
    best = current
    stack = [ev]
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("total_tokens", "tokens_used") and isinstance(v, (int, float)):
                    best = max(best, int(v))
                elif isinstance(v, (dict, list)):
                    stack.append(v)
            if isinstance(o.get("input_tokens"), (int, float)) and isinstance(o.get("output_tokens"), (int, float)):
                best = max(best, int(o["input_tokens"] + o["output_tokens"]))
        elif isinstance(o, list):
            stack.extend(o)
    return best


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--brief", required=True, help="markdown file with the task brief")
    ap.add_argument("--model", default="gpt-6-astra")
    ap.add_argument("--effort", default="high", choices=["minimal", "low", "medium", "high", "xhigh"],
                    help="Codex model_reasoning_effort (default high = the user's choice for Blender work)")
    ap.add_argument("--cwd", help="working dir for Codex (default: <project>/Content)")
    ap.add_argument("--root", help="UEFN project root")
    ap.add_argument("--asset-job", action="store_true")
    ap.add_argument("--max-tokens", type=int, help="checked when Codex reports usage (end of each turn)")
    ap.add_argument("--max-steps", type=int, help="kill after this many tool calls - enforced live, mid-turn")
    ap.add_argument("--timeout", type=int, default=4 * 3600)
    ap.add_argument("--append-skill", action="append", default=[])
    ap.add_argument("--full-access", action="store_true",
                    help="--dangerously-bypass-approvals-and-sandbox (only if the sandbox blocks Blender/UEFN)")
    args = ap.parse_args()

    root = gauntlet.find_root(args.root)
    run, rdir = gauntlet.current_run(root)
    cwd = args.cwd or os.path.join(root, "Content")
    out_dir = os.path.join(rdir, "codex", args.task)
    os.makedirs(out_dir, exist_ok=True)

    cap = args.max_tokens
    if args.asset_job:
        ok, why, approval = gauntlet.consume_asset_approval(root, args.task, dry_run=True)
        if not ok:
            print(f"REFUSED: {why}\nAsk the user first; they approve with: "
                  f"py -3 ~/.claude/uefn-tools/gauntlet.py assets approve --count N --max-tokens T --note \"...\"")
            return 3
        cap = cap or approval.get("max_tokens_per_job")
        args.max_steps = args.max_steps or approval.get("max_steps_per_job")

    codex = find_codex()
    if not codex:
        print("Codex CLI not found under %LOCALAPPDATA%\\OpenAI\\Codex\\bin")
        return 4

    prompt = open(args.brief, encoding="utf-8").read()
    for skill in args.append_skill:
        path = os.path.join(SKILLS_DIR, skill, "SKILL.md")
        if os.path.exists(path):
            prompt += f"\n\n---\n## Conventions: {skill}\n\n" + open(path, encoding="utf-8").read()
    prompt += CONTRACT
    with open(os.path.join(out_dir, "prompt.md"), "w", encoding="utf-8") as f:
        f.write(prompt)

    last = os.path.join(out_dir, "last_message.md")
    cmd = [codex, "exec", "-m", args.model, "-c", f'model_reasoning_effort="{args.effort}"', "--json", "--skip-git-repo-check", "-C", cwd, "-o", last]
    if args.full_access:
        cmd.append("--dangerously-bypass-approvals-and-sandbox")
    else:
        cmd += ["-s", "workspace-write", "-c", 'approval_policy="never"',
                "-c", "sandbox_workspace_write.network_access=true"]
    cmd.append("-")  # prompt from stdin

    if args.asset_job:
        gauntlet.consume_asset_approval(root, args.task, dry_run=False)

    started = time.time()
    tokens = 0
    steps = 0
    killed = None
    events_path = os.path.join(out_dir, "events.jsonl")
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            cwd=cwd, text=True, encoding="utf-8", errors="replace")
    proc.stdin.write(prompt)
    proc.stdin.close()

    timer = threading.Timer(args.timeout, lambda: proc.kill())
    timer.start()
    with open(events_path, "w", encoding="utf-8") as log:
        for line in proc.stdout:
            log.write(line)
            log.flush()
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            tokens = usage_from_event(ev, tokens)
            # Codex reports tokens only at turn.completed; tool calls are the live cost signal.
            if ev.get("type") == "item.started" and (ev.get("item") or {}).get("type") not in (None, "agent_message", "reasoning"):
                steps += 1
                if args.max_steps and steps > args.max_steps:
                    killed = f"step cap {args.max_steps} exceeded"
                    proc.kill()
                    break
            if cap and tokens > cap:
                killed = f"token cap {cap} exceeded ({tokens})"
                proc.kill()
                break
    proc.wait()
    timer.cancel()
    if time.time() - started >= args.timeout and not killed:
        killed = f"timeout {args.timeout}s"

    usage = {"task": args.task, "model": args.model, "effort": args.effort, "tokens": tokens, "cap": cap, "steps": steps, "max_steps": args.max_steps,
             "seconds": round(time.time() - started), "exit": proc.returncode, "killed": killed}
    gauntlet.write_json(os.path.join(out_dir, "usage.json"), usage)
    print(json.dumps(usage, indent=1))
    if os.path.exists(last):
        print("--- Codex final message ---")
        print(open(last, encoding="utf-8", errors="replace").read()[-4000:])
    return 0 if proc.returncode == 0 and not killed else 1


if __name__ == "__main__":
    sys.exit(main())
