---
name: uefn-mcp-automation
description: How to drive a live UEFN editor end-to-end without the user present — which of the three local channels (Verse Workflow Server 1962, Epic's native unreal-mcp 8000, an in-editor Python listener 8765) to use for what, the unattended playtest loop (compile → play-in-client session → Verse AutoTest report in the log → client screenshot → teardown) via uefn_playtest.py, how to write Verse AutoTest scenarios, visual verification, editor health checks, and the things that must NOT be automated (input into the Fortnite client, asset reload). Read BEFORE starting a playtest, verifying gameplay, placing devices/entities through MCP, taking screenshots of the editor or game, or doing any multi-step editor work while the user is away. Applies to any UEFN project.
---

# Driving UEFN unattended

Verified live on UEFN 42.00 (September 2026). Older advice that "PIE cannot be started from
Python" or "screenshots are impossible" is obsolete.

Tools referenced below live in `~/.claude/uefn-tools/` (installed by this repo's `install.ps1`).

## Three channels into the same editor process

| Port | What | Use it for |
|---|---|---|
| 1962 | Verse Workflow Server (built into UEFN) | `Invoke-UefnVerseBuild.ps1` — compile check; works even when MCP is wedged. |
| 8000 | Epic's native MCP (`unreal-mcp` in `.mcp.json`) | Everything it covers: Verse read/write/BuildAll, devices, Scene Graph entities, UMG/MVVM/Verse fields, play sessions, logs, captures. |
| 8765 | Optional in-editor Python listener (`uefn_listener.py`, see README) | Raw `unreal.*` Python for what native toolsets lack: `python ~/.claude/uefn-tools/uefn_exec.py script.py` (assign to `result`). |

You cannot add your own toolsets to port 8000: UEFN's C++ ToolsetPolicy allowlist silently drops
project-registered `unreal.ToolsetDefinition` classes (registration logs "Registering Toolset" but
the class never becomes registered or visible). Engine toolsets present in the binary but not
exposed (Cheats, AutomationTest, SlateInspector, Profiler, PCG, StateTree…) are unreachable too.
So the 8765 listener is the escape hatch, not a stopgap.

Scripts can use Epic's MCP without an agent: `uefn_mcp_client.py` → `UefnMcp().call(toolset, tool, args)`.
Batch many native calls in one round trip with `ProgrammaticToolset.execute_tool_script` (sandboxed:
only json/math/re/time/datetime/copy + `execute_tool`); it's also the way to filter BuildAll down to
errors when a project has many known warnings.

## The playtest loop

```
python ~/.claude/uefn-tools/uefn_playtest.py --project <Project>\Content [--timeout 720] [--out DIR]
```

Health check → sets `AutoTestEnabled = true` in `AutoTest.verse` → BuildAll (aborts on errors) →
`StartSession` → waits `Connected` → `StartGame` → tails the editor log for `AUTOTEST:` lines,
Verse runtime errors and start-up validation lines until `AUTOTEST: END` → screenshots the client
→ stops game+session → ALWAYS restores the flag to false and recompiles. Writes `report.json`.
Exit 0 = all pass, 1 = a FAIL / runtime error / no END, 2 = could not run.

Things that matter when you run it:
- **It takes over the user's Fortnite client.** Make sure nobody is playing, and check for another
  agent session working in the same project before starting.
- Session start is ~150 s when Verse changed (the server cooks), seconds when nothing changed. The
  match needs `StartGame` once the state is `CanStart`.
- Verse `Print` from the running game lands in the **editor** log
  (`%LOCALAPPDATA%\UnrealEditorFortnite\Saved\Logs\UnrealEditorFortnite.log`, `LogVerse: :`).
  `LogsToolset.GetLogEntries(pattern=...)` reads it too. `SessionToolset.GetClientLogEntries`
  answered "No client log was found" during a live session — don't rely on it.
- For a quick iteration inside a running session, `PushChanges(bVerseOnly=true)` is much faster
  than a new session; restart the match to re-run `OnBegin`.

## Writing AutoTest scenarios (Verse side)

Start from the template `AutoTest.verse` in this repo. The rules that make it worth running:

- Drive the game through the **same code path a player triggers**, not a shortcut. For step
  buttons, add a public `SimulateStep(Player)` on the button component that signals the same event
  a real step signals, so every downstream system runs unchanged.
- Report with the fixed contract `AUTOTEST: PASS|FAIL|SKIP <id> | <detail>` and a final
  `AUTOTEST: END passed=N failed=N`. Put observed values in the detail — a FAIL must be
  diagnosable from the log alone.
- Wait on state with a cap, not on fixed sleeps. SKIP (don't FAIL) when a precondition is
  legitimately absent.
- Tests mutate real playtest save data: snapshot what you change, restore it before END.
- The highest-value scenario for content-heavy islands is **"do everything reachable"**: e.g. buy
  every purchasable thing through its real button until nothing is left, then classify every
  catalog entry that is still unowned as "available but nothing sells it" or "locked after
  everything reachable was bought". That catches content bugs (a catalog entry with no button in
  the world, a prerequisite nothing can satisfy) that compile fine and that manual testers rarely
  reach. In one tycoon island it did ~230 purchases in ~3 min and found a missing rooftop button.
- End with a teleport of the player to a vantage point (`fort_character.TeleportTo` with
  `/UnrealEngine.com/Temporary/SpatialMath` coordinates — convert Scene Graph transforms with
  `FromTransform`) and a short sleep, so the runner's END screenshot shows the result.

Test players (Island Settings › Debug › Test Players on Start, up to 98) are `agent`s, not
`player`s — invisible to `GetPlayers()` and to player-keyed save data. Useful only for code that
works on agents.

## Building Scene Graph content and prefabs (verified on UEFN 42.00)

- Entities/components: `EntityToolset` — plain entity class `/EntityFramework/_Verse/VNI/Entity.entity`;
  a mesh component is the mesh asset's own class (`/<Project>/_Verse/Assets.<Folder>-<Mesh>`);
  your Verse components and their enum properties (`"MyEnumValue"`) are set by friendly name.
  `CreateEntity` with `parentEntity` treats the transform as **relative** (the docs say world) —
  correct it with `SetEntityTransform`, which is world.
- New prefab asset (8765 Python): `unreal.get_editor_subsystem(unreal.SceneGraphScriptSubsystem)`
  → `create_empty_prefab(name, "/Project/Folder/Name")` (the second argument is the FULL package
  name, not a folder) → `create_prefab_from_entities([sub.find_entity(level, "ShortName")], prefab)`
  with `level = LevelEditorSubsystem.get_current_level()`. New instances via `CreateEntity(<prefab>_C)`
  carry every component and value.
- Change **properties** inside an existing prefab: edit the template object
  `/Pkg.Default__X_C:<Entity>.<Component>_0` in Python — real field name via
  `SceneGraphScriptSubsystem.get_real_property_name(cls, "FriendlyName")`, then `modify()`,
  `set_editor_property`, `BlueprintEditorLibrary.compile_blueprint`, save. Propagates to existing
  and new instances. (Epic's EntityToolset refuses archetype objects by design.)
- Change **structure** inside an existing prefab: not possible this way — a component added to the
  template vanishes on compile and triggers an EntityFramework ensure. Instead add entities as
  children of the prefab *instance* in the level, or spawn a small prefab from Verse at runtime.

## MVVM event parameters (Param0) — scriptable

A parameterised event binding (button `OnClicked` → `MyEvent : event(tuple(int))`) stores its literal
in `SavedPins`, which is read-only to scripts. The value can still be set through the event's
generated wrapper graph:
1. Open the widget (`EditorAppToolset.OpenEditorForAsset`) so its MVVM wrapper graphs exist.
2. `view = find_object("<WBP>.<WBP>:MVVMWidgetBlueprintExtension_View_0.MVVMBlueprintView_0")`;
   for each event: `event_path.export_text()` names the widget, `get_editor_property('graph_name')`
   names its graph.
3. `unreal.BlueprintGraphEditor.get_graph_editor(find_object("<WBP>.<WBP>:<graph_name>")).list_all_nodes()`
   → the `K2Node_CallFunction` → `list_all_pins()` → pin `Param0` → `set_pin_value("N")`.
4. `BlueprintEditorLibrary.compile_blueprint(wbp)` — this rewrites `SavedPins` — then save.
Read/audit without writing: `event.get_editor_property('saved_pins')[0].export_text()` → `DefaultString="N"`.

## Seeing the result

- `EditorAppToolset.CaptureViewport` — PNG of the level viewport; with `annotations` it draws a
  world grid and labelled actors, which is what you need before placing things spatially.
- `CaptureEditorImage` (whole editor), `CaptureAssetImage` (mesh/material/texture thumbnail).
- `python ~/.claude/uefn-tools/grab_window.py --title "Fortnite  " --out x.png --client-only`
  captures the running game (HUD included; works with EasyAntiCheat). Then Read the PNG.
- UMG designer: undock the widget tab and capture that window with `grab_window.py`.

## Editor health — check before and after batches

`python ~/.claude/uefn-tools/uefn_watch.py` → exit 0 ok, 2 a modal dialog is open (every MCP call
will just time out — ask the user to close it), 3 UEFN not running, 4 a crash report newer than the
process. With the 8765 listener you can also stop the editor from throttling itself in the
background (MCP calls crawl otherwise); it lasts until the editor restarts:
`unreal.find_object(None, '/Script/UnrealEd.Default__EditorPerformanceSettings').set_editor_property('bThrottleCPUWhenNotForeground', False)`
(the snake_case property name does not work here).

## Never automate these

- **Synthetic keyboard/mouse input into the Fortnite client.** EasyAntiCheat runs in Creative/UEFN
  sessions and bans are account- and hardware-level. Drive the game from Verse instead.
- **Asset reload** through MCP — known to hang UEFN.
- **Deleting a prefab or any asset that generates Verse types, then compiling Verse in the same
  editor session** — verified crash (access violation right after a successful compile, during type
  regeneration). Delete such assets last, then restart UEFN before the next build.
- Anything in your own project notes marked as a crash mode (e.g. material recompile after certain
  graph edits, byte-patching nested widget event bindings, saving very large prefabs).
- Clicking UMG buttons: whether a button's click reaches its Verse event can't be tested from
  Verse. Keep that on the human checklist.

## Scheduling

`uefn_nightly.ps1 -Project <Content dir>` wraps the runner for Task Scheduler: skips when UEFN is
closed or blocked, keeps each run in `uefn-tools/playtest-history/`, one summary line per run in
`history.log`. Registering the task is persistence — leave that to the user.
