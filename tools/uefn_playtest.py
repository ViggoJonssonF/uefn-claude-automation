"""Unattended UEFN playtest: compile, launch a session, collect the Verse AutoTest report, tear down.

Flow:
  1. Health check (uefn_watch) - refuses to start with a modal dialog open or UEFN down.
  2. Turns `AutoTestEnabled` on in the project's AutoTest.verse and compiles via MCP BuildAll.
  3. Starts a play-in-client session and the match through Epic's SessionToolset.
  4. Tails the editor log (Verse Print lands there) for `AUTOTEST:` lines until `AUTOTEST: END`,
     plus any Verse runtime errors, with a timeout.
  5. Screenshots the Fortnite client window, stops the match and the session.
  6. ALWAYS restores `AutoTestEnabled = false` and recompiles, even on failure.

Usage:
    python uefn_playtest.py --project C:\\...\\MyIsland\\Content [--timeout 420] [--keep-session]

Writes <out>/report.json and <out>/client_*.png (default out: %TEMP%[ERROR]uefn_playtest\\<timestamp>).
Exit code: 0 all passed, 1 a test failed / no END seen, 2 could not run.

Note: the session takes over this machine's Fortnite client.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uefn_mcp_client import UefnMcp, McpError  # noqa: E402

SESSION = "ValkyrieToolset.SessionToolset"
VERSE = "ValkyrieToolset.VerseToolset"
EDITOR_LOG = os.path.expandvars(r"%LOCALAPPDATA%\UnrealEditorFortnite\Saved[ERROR]ogs\UnrealEditorFortnite.log")
FLAG_RE = re.compile(r"^(AutoTestEnabled<public>\s*:\s*logic\s*=\s*)(true|false)", re.M)
# Lines your own Verse start-up validation prints, collected into report["validation_errors"]
# without failing the run. Override with --validation-pattern (one capture group = the message).
DEFAULT_VALIDATION_PATTERN = r"LogVerse: : \[ERROR\] (.*)"
VALIDATION_RE = re.compile(DEFAULT_VALIDATION_PATTERN)
ERROR_RE = re.compile(r"LogVerse: Error|Verse runtime error|VerseRuntimeError|Script Stack|Unhandled exception", re.I)
HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def find_autotest_file(content_dir):
    for root, _, files in os.walk(content_dir):
        if "AutoTest.verse" in files:
            return os.path.join(root, "AutoTest.verse")
    raise FileNotFoundError("AutoTest.verse not found under " + content_dir)


def set_flag(path, value):
    text = open(path, encoding="utf-8").read()
    new, n = FLAG_RE.subn(lambda m: m.group(1) + ("true" if value else "false"), text)
    if n != 1:
        raise RuntimeError("could not find exactly one AutoTestEnabled line in " + path)
    if new != text:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(new)


def build(mcp):
    diags = mcp.call(VERSE, "BuildAll")["returnValue"]
    return [d for d in diags if d["severity"] == "Error"]


def wait_for(fn, want, timeout, step=2.0):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        last = fn()
        if last in want:
            return last
        time.sleep(step)
    return last


def tail_log(offset, timeout, on_line):
    """Feed new editor-log lines to on_line until it returns True or the timeout hits."""
    end = time.time() + timeout
    pending = ""
    while time.time() < end:
        size = os.path.getsize(EDITOR_LOG)
        if size < offset:        # log rotated
            offset = 0
        if size > offset:
            with open(EDITOR_LOG, "rb") as f:
                f.seek(offset)
                chunk = f.read(size - offset)
            offset = size
            pending += chunk.decode("utf-8", errors="replace")
            lines = pending.split("\n")
            pending = lines.pop()
            for line in lines:
                if on_line(line.rstrip("\r")):
                    return True
        time.sleep(1.0)
    return False


def screenshot(out_dir, name):
    path = os.path.join(out_dir, name)
    r = subprocess.run([PY, os.path.join(HERE, "grab_window.py"), "--title", "Fortnite  ",
                        "--out", path, "--client-only"], capture_output=True, text=True)
    return path if r.returncode == 0 and os.path.exists(path) else None


def main():
    # The Windows console defaults to cp1252; Verse prints are UTF-8 (å/ä/ö in test details).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True, help="the project's Content directory")
    ap.add_argument("--timeout", type=float, default=420, help="seconds to wait for AUTOTEST: END")
    ap.add_argument("--out", default=os.path.join(os.environ.get("TEMP", "."), "uefn_playtest",
                                                  time.strftime("%Y%m%d-%H%M%S")))
    ap.add_argument("--keep-session", action="store_true", help="leave the session running afterwards")
    ap.add_argument("--validation-pattern", default=DEFAULT_VALIDATION_PATTERN,
                    help="regex for start-up validation lines to collect (group 1 = message)")
    args = ap.parse_args()
    global VALIDATION_RE
    VALIDATION_RE = re.compile(args.validation_pattern)
    os.makedirs(args.out, exist_ok=True)

    health = subprocess.run([PY, os.path.join(HERE, "uefn_watch.py")], capture_output=True, text=True)
    log(health.stdout.strip().splitlines()[0] if health.stdout else "health check produced no output")
    if health.returncode in (2, 3):
        log("aborting: editor is not in a state to run a session")
        return 2

    flag_file = find_autotest_file(args.project)
    report = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "results": [], "runtime_errors": [],
              "validation_errors": [],
              "screenshots": [], "ended": False}
    mcp = UefnMcp()
    code = 2
    try:
        if mcp.call(SESSION, "GetSessionStatus")["returnValue"] != "Disconnected":
            log("a session is already running - stopping it first")
            mcp.call(SESSION, "StopSession")
            time.sleep(3)

        set_flag(flag_file, True)
        errors = build(mcp)
        if errors:
            report["compile_errors"] = errors
            log(f"compile failed with {len(errors)} error(s) - not starting a session")
            for e in errors[:10]:
                log(f"  {e['filePath']}:{e['span']['startLine'] + 1} {e['message'][:160]}")
            return 2
        log("compiled with AutoTestEnabled = true")

        offset = os.path.getsize(EDITOR_LOG)
        t0 = time.time()
        log("starting session (uploads the project, launches the Fortnite client)...")
        mcp.call(SESSION, "StartSession")
        status = wait_for(lambda: mcp.call(SESSION, "GetSessionStatus")["returnValue"], {"Connected"}, 600)
        report["session_status"] = status
        if status != "Connected":
            log(f"session never connected (last status {status})")
            return 2
        state = wait_for(lambda: mcp.call(SESSION, "GetGameState")["returnValue"], {"CanStart", "Running"}, 300)
        if state == "CanStart":
            mcp.call(SESSION, "StartGame")
        log(f"session connected after {time.time() - t0:.0f} s, match {state} -> started; waiting for AUTOTEST: END")

        def on_line(line):
            if "AUTOTEST:" in line:
                body = line.split("AUTOTEST:", 1)[1].strip()
                log("  " + body)
                m = re.match(r"(PASS|FAIL|SKIP) (\S+)(?: [ERROR] (.*))?", body)
                if m:
                    report["results"].append({"status": m.group(1), "id": m.group(2), "detail": m.group(3) or ""})
                if body.startswith("END"):
                    report["ended"] = True
                    report["summary"] = body
                    return True
            elif VALIDATION_RE.search(line):
                # The project's own start-up validation. Reported, not failing: static validators
                # often flag content that is only spawned at runtime.
                msg = VALIDATION_RE.search(line).group(1)[:300]
                if msg not in report["validation_errors"]:
                    report["validation_errors"].append(msg)
            elif ERROR_RE.search(line):
                report["runtime_errors"].append(line[:400])
                log("  RUNTIME: " + line[:200])
            return False

        tail_log(offset, args.timeout, on_line)
        shot = screenshot(args.out, "client_end.png")
        if shot:
            report["screenshots"].append(shot)
        failed = [r for r in report["results"] if r["status"] == "FAIL"]
        code = 0 if report["ended"] and not failed and not report["runtime_errors"] else 1
        if report["validation_errors"]:
            log(f"start-up validation reported {len(report['validation_errors'])} line(s) - see report.json")
        if not report["ended"]:
            log(f"no AUTOTEST: END within {args.timeout:.0f} s")
    except McpError as e:
        report["mcp_error"] = str(e)
        log("MCP error: " + str(e))
    finally:
        if not args.keep_session:
            try:
                mcp.call(SESSION, "StopGame")
                mcp.call(SESSION, "StopSession")
                log("session stopped")
            except McpError as e:
                log("could not stop session: " + str(e))
        try:
            set_flag(flag_file, False)
            leftover = build(mcp)
            log("AutoTestEnabled restored to false" + (f" (but {len(leftover)} compile errors!)" if leftover else ""))
        except Exception as e:  # never leave the flag on silently
            log(f"WARNING: could not restore AutoTestEnabled=false in {flag_file}: {e}")
        report["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
        report["exit_code"] = code
        with open(os.path.join(args.out, "report.json"), "w", encoding="utf-8") as f:
            json.dump(report, f, indent=1, ensure_ascii=False)
        log(f"report: {os.path.join(args.out, 'report.json')}  exit={code}")
    return code


if __name__ == "__main__":
    sys.exit(main())
