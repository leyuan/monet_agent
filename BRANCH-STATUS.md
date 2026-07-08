# Branch status — `feat/reviewer-agent`

**Status: ⏸️ PAUSED (pending updates) — last updated 2026-07-08**

This branch is paused for further updates. Notes for whoever picks it up next.

## What this branch adds so far

- **A post-operation review agent** — a reviewer subsystem that audits autonomous
  factor-loop runs *after* they execute (tool-fidelity, operation-success, and
  strategy-conformance checks). This is the branch's primary deliverable.
- **`tools.py` split into a `tools/` package** — the stock agent's monolithic
  `tools.py` was broken into several focused modules under
  `agent/src/stock_agent/tools/` (e.g. `factors.py`, `trading.py`, `strategy_health.py`,
  `_shared.py`, …). Behavior is unchanged; this is a structural refactor.

## Already landed elsewhere (cherry-picked to `feat/telegram-bridge-endpoint`, Jul 7 2026)

Two pieces of this branch were extracted (hunk-level, from WIP commit `23a6f46`) onto
`feat/telegram-bridge-endpoint` because that branch — cut from `main` — needed them:

- **Studio auth fix** (`auth.py` `@auth.on.assistants` → `None`): fixes LangGraph Studio
  showing "No assistants found" against the local dev server (the global `add_owner`
  handler owner-filtered assistants; Studio's fixed identity matched none). Landed there
  as `e9d2068`.
- **Gitignore rules**: root `.gitignore` (`.private/`, `agent/scripts/run_*_local.py`)
  plus `.codegraph/.gitignore` — stops local-only artifacts polluting `git status` on
  branches cut from `main`. Landed there as `dc0695b`.

The changes are byte-identical to this branch's versions, so when both branches merge,
git reconciles them cleanly — no conflict, no action needed. The rest of `23a6f46`
(env examples, agent docs, `tools copy.py`, AGENTS.md) remains only on this branch.

## Merge status

- **Not merged to `main`.** This branch requires **future review and approval** before
  merging. Do not merge without sign-off.

## Picking it back up

Remaining work and validation notes live with the reviewer docs
(`agent/docs/REVIEWER-TEST-PROD.md`) and the branch's proposal/spec files. Confirm the
`tools/` split and reviewer skills are current before resuming.
