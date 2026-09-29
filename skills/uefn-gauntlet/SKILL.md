---
name: uefn-gauntlet
description: Director protocol for building a UEFN feature with a team of specialist agents whose work is always verified by others - spec with acceptance criteria and visual bars, task graph with one owner per file/asset, builder subagents (uefn-verse-builder, uefn-ui-builder, uefn-level-builder), an independent test author, and a gauntlet of deterministic gates (compile, playtest, screenshots via gauntlet.py) plus reviewers (uefn-spec-reviewer, uefn-visual-critic, uefn-skeptic) that must pass before a task may close. Use when the user asks to build a system, shop, UI, prefab setup or other multi-part feature in a UEFN project "for real", with little or no manual work on their side, or says "gauntlet". Not for one-line fixes.
---

# UEFN Gauntlet — director protocol

You are the director. You plan, dispatch, run gates, and keep the ledger. **You do not
implement and you do not grade.** Builders build, the test author writes tests from the spec,
reviewers judge, `gauntlet.py` records evidence, and the `TaskCompleted` hook refuses to close
a `[G:<id>]` task until the evidence and every required review are PASS.

Tool: `py -3 ~/.claude/uefn-tools/gauntlet.py …` (run inside the UEFN project; state in
`<project>/.gauntlet/<run>/`). Read the `uefn-mcp-automation` skill first — it has the channels,
playtest loop, crash modes and what cannot be automated.

## Phase 0 — preflight
- `uefn_watch.py` exit 0, `ListAgents` shows no other session working in this project (ask it).
- Save nothing you didn't change. Note unsaved packages before you start.

## Phase 1 — spec (the only planned human touchpoint)
1. `gauntlet.py init "<feature>"`, then write `SPEC.md`: goal in the user's words, acceptance
   criteria that a gate/test/reviewer can check, **bars** (concrete references for anything
   visual — an existing widget, a screenshot, a named screen), out of scope.
2. Collect every ambiguity and ask the user ONCE, together. Record answers in the SPEC.
3. Anything the tools cannot do (see "What still needs the human") becomes an explicit manual
   step in the SPEC, not a surprise at the end.

## Phase 2 — plan
- Split into tasks small enough for one agent and one clear deliverable (a system, a widget, a
  set of placed devices). **One owner per file and per asset** — .uasset files can't be merged.
- Order: Verse interfaces first (builders need names), then UI/level in parallel, tests alongside.
- Register each: `gauntlet.py task add T3 --title … --owner uefn-ui-builder --reviews spec,visual,skeptic --gates compile,visual`
  (logic tasks: `--reviews spec,skeptic --gates compile,playtest`).
- Mirror each in the Claude Code task list with subject `[G:T3] <title>` so the hook guards it.
- Record non-obvious decisions: `gauntlet.py ruling "<what> -- <why> -- <cost if wrong>"`.

## Phase 3 — build
Dispatch each task to its builder subagent with: task id, brief, SPEC path, owned files/assets,
interfaces from earlier tasks. Nothing else — no hints about how reviewers will judge.
- Parallel only when owned files are disjoint AND at most one of them mutates the editor at a
  time (`gauntlet.py lock` — builders take it themselves). Verse text edits can overlap with
  editor work; compiles are global, so integrate Verse builders one at a time.
- Dispatch `uefn-test-author` from the SPEC in parallel with the builders.
- Builder reports NEEDS_CONTEXT/BLOCKED → answer from the SPEC or ask the user; never guess.

## Phase 4 — the gauntlet (per task, in this order)
1. **Gate** (you run it, it's a script): `gauntlet.py gate T3 [--playtest] [--viewport x,y,z,pitch,yaw] [--client-shot]`.
   Batch playtests: once several tasks are integrated, one `--playtest` run serves all of them
   (a run is ~3–6 min and takes over the Fortnite client).
2. **Reviews**, each a fresh subagent that never saw an earlier draft: `uefn-spec-reviewer`,
   then `uefn-visual-critic` for visual tasks, then `uefn-skeptic` last. Give them task id,
   SPEC path, builder report, evidence path. They record verdicts themselves.
3. `gauntlet.py status T3`. All PASS → mark `[G:T3]` complete (the hook re-checks).

## Phase 5 — fix loop
Any FAIL → send the findings verbatim to the SAME builder (rounds 1–3), then a FRESH builder
instance (rounds 4–5). Every fix → new gate run → all reviews again (the hook rejects reviews
older than the latest gate evidence). After round 5: rule on each open finding in the ledger
(accept with cost, or escalate to the user) — never silently drop one.

## Phase 6 — integrate and report
- Final `gauntlet.py gate` with `--playtest` over everything; the whole AutoTest suite is the
  regression suite. `uefn-skeptic` once more over the integrated result.
- Report to the user: what was built, the evidence (report.json, screenshots), rulings, and the
  exact manual steps left for them. Only claim what the evidence shows.

## Red flags — stop and fix the process
- You're about to write code or a verdict yourself. → Dispatch instead.
- "It should work", "the builder said it passed". → Evidence or it didn't happen.
- A reviewer that saw the previous attempt is reviewing the retry. → Fresh instance.
- Two agents own the same asset. → Re-plan.
- A builder deleted a prefab/Verse-generating asset and someone is about to compile. → Stop;
  restart UEFN first (verified crash mode).

## What still needs the human
Taste and fun; clicking a UMG button in a live session to confirm the click reaches Verse;
anything the project memory lists as manual (e.g. structural changes inside an existing large
prefab); publishing. Say so in the SPEC up front.
