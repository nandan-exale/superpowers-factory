# Sync a Job Branch With the Base Outside the Sandbox — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A builder can sync its job branch with `origin/<base>` even when the base changed a file the agent sandbox may not write (`factory/runner-settings.json`).

**Architecture:** A new `job update-branch <job>` in the vendored `factory/bin/job` merges `origin/<base>` into the job worktree from the orchestrator's unsandboxed process. `Pipeline.builder()` runs it before every round-2+ builder spawn and tells the builder about a merge to finish. `builder.md` tells the builder never to merge the base itself.

**Tech Stack:** Python 3.10+ standard library; stdlib `unittest` with `tests/factory_project.py`.

Spec: `docs/superpowers/specs/2026-11-15-sync-base-outside-sandbox-design.md`.

---

## File structure

- Modify `vendor/factory/factory/bin/job`: `update_branch(job)` and `cmd_update_branch(job)` after `cmd_ensure_worktree`; a usage line; a dispatch branch in `main`.
- Modify `vendor/factory/factory/lib/orchestrator/pipeline.py`: `Pipeline.sync_base(job)`, called from `builder()`.
- Modify `vendor/factory/factory/lib/orchestrator/prompts.py`: `merged_base(base)` and `finish_merge(base, paths)`.
- Modify `vendor/factory/factory/agents/builder.md`: the no-merge paragraph.
- Create `tests/test_update_branch.py`; modify `tests/test_pipeline.py`; create `tests/test_builder_sync_wording.py`.
- Regenerate `vendor/known-hashes.json` with `scripts/known-hashes`.

---

### Task 1: `job update-branch` merges the base outside the sandbox

**Files:** `tests/test_update_branch.py`, `vendor/factory/factory/bin/job`

- [ ] Write the tests (real git through `FactoryProject`): protected file changed on the base only → `merged`, file content from base, `MERGE_HEAD` absent, HEAD has two parents; unprotected conflict → `conflicts: <path>`, `MERGE_HEAD` present; protected conflict (`factory/config.json`) → merge aborted, stage `needs-human`, path in `decision.md`; up to date; dirty worktree → `skipped`; merge in progress → `merge in progress`.
- [ ] Run `python3 -m unittest tests.test_update_branch` from `tests/`: fails (`cmd_update_branch` missing).
- [ ] Implement `update_branch` / `cmd_update_branch` per the spec; protected = `CONFIG["protected_paths"] + job.get("plan_paths")`, matched with `fnmatch` like the gate.
- [ ] Run the tests: pass. Commit `Merge the base into a job branch from bin/job`.

### Task 2: the orchestrator syncs before round-2+ builders

**Files:** `tests/test_pipeline.py`, `vendor/factory/factory/lib/orchestrator/pipeline.py`, `vendor/factory/factory/lib/orchestrator/prompts.py`

- [ ] Write tests: round 2 builder calls `update-branch` before `agent builder`; `merged` / `conflicts` / `merge in progress` add their prompt text (fresh and resumed prompts); `up to date` adds nothing; round 1 never calls it; a needs-human answer spawns nothing.
- [ ] Run: fail. Implement `sync_base` and the prompts. Run: pass. Commit `Sync the base before each builder round after the first`.

### Task 3: the builder never merges the base itself

**Files:** `tests/test_builder_sync_wording.py`, `vendor/factory/factory/agents/builder.md`

- [ ] Test that `builder.md` says never to merge or rebase the base and that the factory syncs before each round. Run: fail. Add the paragraph. Run: pass. Commit.

### Task 4: hashes and checks

- [ ] `scripts/known-hashes`; commit `vendor/known-hashes.json` separately from the vendored edits.
- [ ] `scripts/check`: pass.
