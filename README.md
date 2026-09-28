# uefn-claude-automation

Let Claude Code build **and test** a UEFN island while you're away: compile Verse, launch a real
play-in-client session, run scripted gameplay scenarios inside the game, read the results from
the log, screenshot the Fortnite client, and tear everything down, all through Epic's UEFN MCP
(UEFN 42.00+).

```
compile ─► start session ─► start match ─► Verse AutoTest runs in-game ─► AUTOTEST: END in log
   ▲                                                                              │
   └──────── restore flag, stop session ◄── screenshot client ◄── report.json ◄──┘
```

One run ≈ 3–6 minutes. Example output:

```
[17:53:07] session connected after 153 s, match CanStart -> started; waiting for AUTOTEST: END
[17:53:25]   PASS T01-opening | opening finished after 16 s (limit 120 s)
[17:53:26]   PASS T02-claim | step=yes hasPlot=yes owner=yes floorBought=yes
[17:53:30]   PASS T04-purchase | CONVEYOR G: bought=yes balance 999999999 -> 999999499 (price 500 cash)
[17:56:34]   PASS T06a-build-purchases | bought 232 parts via the buttons
[17:56:34]   FAIL T06b-nothing-stuck | owned 234/235; available but no button sells it (1): TELEPORTER 6
[17:56:37]   END passed=8 failed=1
```

## What's in here

| Path | What |
|---|---|
| `skills/uefn-mcp-automation/SKILL.md` | The Claude Code skill: which channel to use for what, the playtest loop, how to write scenarios, visual checks, what never to automate. |
| `tools/uefn_playtest.py` | The unattended playtest runner (flag on → compile → session → collect `AUTOTEST:` lines → screenshot → teardown → flag off). |
| `tools/uefn_mcp_client.py` | Tiny dependency-free client for Epic's MCP at `127.0.0.1:8000/mcp`, so scripts can call toolsets without an agent. |
| `tools/uefn_watch.py` | Editor health check: process alive, modal dialog blocking the game thread, fresh crash reports, which ports are up. |
| `tools/uefn_exec.py` | Run a Python file inside the editor through the optional 8765 listener. |
| `tools/grab_window.py` | Screenshot one window (the Fortnite client, an undocked UMG designer…) to PNG. |
| `tools/Invoke-UefnVerseBuild.ps1` | Compile Verse through UEFN's Verse Workflow Server (port 1962) and print errors. |
| `tools/uefn_nightly.ps1` | Wrapper for a scheduled nightly run with a history log. |
| `verse/AutoTest.verse` | In-game test harness template: log-line contract, report class, example scenarios. |

## Setup

1. **UEFN:** Project Settings → enable **Python Editor Script Plugin** and **UEFN MCP Toolsets**
   (Beta). Keep the project open.
2. **Claude Code:** add `.mcp.json` to your project root:
   ```json
   { "mcpServers": { "unreal-mcp": { "type": "http", "url": "http://127.0.0.1:8000/mcp" } } }
   ```
3. **This repo:** `powershell -ExecutionPolicy Bypass -File install.ps1`
   (needs Python 3.10+ on PATH and `pip install pillow` for screenshots).
4. **Your island:** copy `verse/AutoTest.verse` into your Verse source and start it from a device
   that is always in the level:
   ```verse
   OnBegin<override>()<suspends>:void=
       if (AutoTestEnabled?):
           spawn{ RunAutoTests(GetPlayspace()) }
   ```
   Replace the example scenarios with your own (the skill explains how to write good ones).
5. Run it:
   ```
   python %USERPROFILE%\.claude\uefn-tools\uefn_playtest.py --project "C:\...\MyIsland\Content"
   ```
   or just ask Claude to "run the playtest".

### Optional: raw Python in the editor (port 8765)

Epic's MCP doesn't expose everything, and UEFN doesn't let projects register their own MCP
toolsets. For the rest, run the MIT-licensed listener from
[KirChuvakov/uefn-mcp-server](https://github.com/KirChuvakov/uefn-mcp-server): copy
`uefn_listener.py` and `init_unreal.py` into `<Project>/Content/Python/`. If auto-start fails with
`module 'uefn_listener' has no attribute '_server'`, change `init_unreal.py` to check
`getattr(unreal, "_mcp_server", None)` instead. `uefn_exec.py` then runs any file inside the editor.

## Important

- **A session takes over your Fortnite client.** Don't run it while you're playing.
- **Never send synthetic keyboard/mouse input to the Fortnite client.** EasyAntiCheat is active in
  UEFN sessions. All gameplay in these tests is driven from Verse.
- Scenarios change the playtest account's save data like a manual test would. Snapshot and restore
  what you touch, and keep `AutoTestEnabled = false` in anything you publish.
- Built on a beta Epic feature; tool names and behaviour may change between UEFN releases.

## License

MIT, see `LICENSE`.
