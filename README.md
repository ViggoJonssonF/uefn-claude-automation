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

## The gauntlet: a team of agents that checks each other

For bigger features ("build a shop with three tabs"), the `uefn-gauntlet` skill turns the main
Claude session into a **director** that plans and dispatches but never implements or grades:

```
SPEC (acceptance criteria + visual "bars", one question round with you)
  → builders:  uefn-verse-builder · uefn-ui-builder · uefn-level-builder   (one owner per file/asset,
                                                                            editor lock for mutations)
  → uefn-test-author writes AutoTests from the SPEC, not from the code
  → gauntlet per task:
       1. gate (a script, not an agent): health · Verse compile · playtest · screenshots  → evidence
       2. uefn-spec-reviewer   (criterion by criterion, evidence or FAIL)
       3. uefn-visual-critic   (blind A/B pick against the bar, no scores)
       4. uefn-skeptic         (tries to break it: multiplayer, rejoin, edge cases, crash modes)
  → FAIL → fix loop (same builder ×3, fresh builder ×2, then a written ruling) → re-gate → re-review
```

`tools/gauntlet.py` keeps the state in `<project>/.gauntlet/<run>/` (SPEC, tasks, evidence, reviews,
ledger) and enforces the rules: the owner of a task can never review it, a PASS needs gate evidence,
and a review older than the latest evidence no longer counts. Wire it to Claude Code's task list so a
task literally cannot be closed without passing:

```json
{ "hooks": { "TaskCompleted": [ { "hooks": [ { "type": "command",
  "command": "py -3 \"C:/Users/<you>/.claude/uefn-tools/gauntlet.py\" check", "timeout": 30 } ] } ] } }
```

Only task subjects that start with `[G:<id>]` are gated; everything else passes through untouched.
The agents preload `uefn-mcp-automation`; add your own specialist skills (Verse, UI conventions,
lighting…) to their `skills:` lists.

## Using your Codex usage too (and new 3D assets)

`tools/codex_delegate.py` hands a brief to a Codex agent (e.g. `gpt-6-astra`) through
`codex exec`, so token-heavy work runs on your ChatGPT/Codex plan while Claude directs and verifies:

```
py -3 codex_delegate.py --task T5 --brief brief.md [--model gpt-6-astra] [--max-steps 120] [--asset-job]
```

It logs prompt, events, final message and usage under `.gauntlet/<run>/codex/<task>/`, and has two
brakes: `--max-steps` kills Codex live after N tool calls, `--max-tokens` checks the usage Codex
reports at the end of each turn. New Blender meshes are the most expensive thing in the workflow,
so `--asset-job` refuses to run unless the user approved assets for this run
(`gauntlet.py assets approve --count N --max-tokens T --max-steps S`). The `uefn-asset-builder`
agent writes the brief, delegates the modelling to Codex (which drives Blender through the
[Blender MCP bridge](https://github.com/djeada/blender-mcp-server)), and verifies the result in UEFN;
`uefn-blender-assets` holds the proven Blender → FBX (cm) → UEFN conventions.

Note: if `codex exec` fails with "Error loading rules … starlark", your `~/.codex/rules/default.rules`
has stray bytes (the desktop app tolerates them, the CLI doesn't) — back it up and clean it.

## What's in here

| Path | What |
|---|---|
| `skills/uefn-mcp-automation/SKILL.md` | The Claude Code skill: which channel to use for what, the playtest loop, how to write scenarios, building entities/prefabs, MVVM Param0, visual checks, what never to automate. |
| `skills/uefn-gauntlet/SKILL.md` | Director protocol for the multi-agent gauntlet. |
| `skills/uefn-blender-assets/SKILL.md` | Blender → centimetre FBX → UEFN import/materials/LODs conventions, with the cost rule. |
| `agents/uefn-*.md` | Ten subagents: four specialist builders (incl. the Codex-backed asset builder), two lower-effort generic builders, a test author, three reviewers. All pinned to Opus 5.5 / high; the director may downgrade builders per task (see the gauntlet skill). |
| `tools/codex_delegate.py` | Delegate a brief to Codex (`codex exec`) with step/token caps and the asset-approval check. |
| `tools/gauntlet.py` | Gauntlet state, deterministic gate, verdicts, ledger, editor lock, TaskCompleted hook. |
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
