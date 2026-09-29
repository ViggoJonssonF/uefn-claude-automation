"""Health check for an unattended UEFN session: process alive, modal dialogs, fresh crashes.

A modal dialog (save prompt, error box) blocks the editor's game thread, so every MCP call
just times out with no error. A crash kills the process and all three ports with it. Run this
before a batch of editor work and whenever an MCP call times out.

Usage:
    python uefn_watch.py            # human-readable report, exit code below
    python uefn_watch.py --json

Exit codes: 0 = healthy, 2 = a dialog is open (ask the user / close it), 3 = UEFN not running,
4 = a crash report newer than the running process exists.
"""

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import os
import socket
import subprocess
import sys
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)

PROCESS_NAME = "UnrealEditorFortnite-Win64-Shipping.exe"
PORTS = {"verse_workflow": 1962, "epic_mcp": 8000, "python_listener": 8765}
CRASH_DIR = os.path.expandvars(r"%LOCALAPPDATA%\UnrealEditorFortnite\Saved\Crashes")


def editor_pid():
    out = subprocess.run(
        ["tasklist", "/FI", f"IMAGENAME eq {PROCESS_NAME}", "/FO", "CSV", "/NH"],
        capture_output=True, text=True).stdout.strip()
    if not out or "No tasks" in out:
        return None
    return int(out.splitlines()[0].split('","')[1])


def process_start_time(pid):
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"(Get-Process -Id {pid}).StartTime.ToUniversalTime().ToString('o')"],
        capture_output=True, text=True).stdout.strip()
    try:
        from datetime import datetime
        return datetime.fromisoformat(out.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def windows_of(pid):
    """Visible, titled top-level windows owned by the process."""
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def callback(hwnd, _):
        owner = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid or not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        rect = wt.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w, h = rect.right - rect.left, rect.bottom - rect.top
        if w > 50 and h > 50:
            found.append({"title": buf.value, "w": w, "h": h,
                          "enabled": bool(user32.IsWindowEnabled(hwnd))})
        return True

    user32.EnumWindows(callback, 0)
    return found


def port_open(port):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def newest_crash():
    if not os.path.isdir(CRASH_DIR):
        return None
    dirs = [os.path.join(CRASH_DIR, d) for d in os.listdir(CRASH_DIR)]
    dirs = [d for d in dirs if os.path.isdir(d)]
    if not dirs:
        return None
    d = max(dirs, key=os.path.getmtime)
    info = {"path": d, "mtime": os.path.getmtime(d), "ensure": False, "message": ""}
    ctx = os.path.join(d, "CrashContext.runtime-xml")
    if os.path.exists(ctx):
        text = open(ctx, encoding="utf-8", errors="replace").read()
        info["ensure"] = "<IsEnsure>true" in text
        start = text.find("<ErrorMessage>")
        if start >= 0:
            info["message"] = text[start + 14:text.find("</ErrorMessage>", start)][:200]
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    report = {"time": time.strftime("%Y-%m-%d %H:%M:%S")}
    pid = editor_pid()
    report["pid"] = pid
    crash = newest_crash()
    code = 0

    if pid is None:
        report["status"] = "UEFN is not running"
        code = 3
    else:
        started = process_start_time(pid)
        wins = windows_of(pid)
        report["windows"] = wins
        report["ports"] = {name: port_open(p) for name, p in PORTS.items()}
        # The main editor window is disabled while a modal child is up; any extra titled
        # window that is enabled while the main one is not is the dialog.
        main_disabled = any(not w["enabled"] for w in wins)
        if main_disabled:
            report["status"] = "MODAL DIALOG OPEN - editor is blocked"
            code = 2
        else:
            report["status"] = "ok"
        if crash and started and crash["mtime"] > started:
            if crash["ensure"]:
                # Non-fatal engine ensure while this editor kept running - worth reading, not an outage.
                report["status"] += " (an ENSURE was reported during this editor session)"
            else:
                report["status"] += " (a crash report is newer than this process)"
                code = code or 4
    report["newest_crash"] = crash

    if args.json:
        print(json.dumps(report, indent=1))
    else:
        print(f"[{report['time']}] {report['status']}  pid={pid}")
        for w in report.get("windows", []):
            print(f"  window: {w['title']!r} {w['w']}x{w['h']} enabled={w['enabled']}")
        for name, ok in report.get("ports", {}).items():
            print(f"  port {name}: {'open' if ok else 'CLOSED'}")
        if crash:
            kind = "ensure" if crash["ensure"] else "crash"
            print(f"  newest {kind} report: {crash['path']} ({time.ctime(crash['mtime'])})")
            if crash["message"]:
                print(f"    {crash['message']}")
    return code


if __name__ == "__main__":
    sys.exit(main())
