# Factory fixes from the first self-build — Design

Date: 2026-11-13
Status: approved design. Fixes the problems found when the factory built
Phase 1 on its own repo (issue #1, PR #2).

## Problems found

1. The builder edited the approved spec (plan Task 9 asked it to), and the
   approver accepted it. A planned job's spec and plan should be fixed.
2. A plan step ran `git tag`. A worktree shares refs with the main checkout,
   so the builder rightly skipped it, but nothing told the planner or the
   human up front.
3. The approver's project rules made the job escalate no matter what; nobody
   knew that until the end.
4. The factory skill says "Name the builder `builder-<id>`", but the Agent
   tool has no name parameter.
5. The skill says the header is "built from `job.json`", but `Base` comes from
   `factory/config.json` `base_branch`.
6. Per-reviewer cost was read from sync deltas, which mix parallel reviewers;
   the numbers were wrong.
7. `test_runner.SpecGapTest.test_queue_failure_is_an_error` now sleeps 7 s
   through real network retries.

## Decisions

| Problem | Fix |
|---|---|
| 1 | Mechanical: `job planned` records the spec and plan paths; the gate treats them as protected for that job. Builder prompt says so. |
| 2 | Builder prompt: skip steps that create tags or change refs or files outside the job branch and worktree; list them under `## Deviations` as "for the human". `/factory-handoff` warns before filing when the plan has such steps. |
| 3 | `/factory-handoff` reads the approver's ESCALATE list and tells the human when the plan touches it. |
| 4, 5 | Skill wording. |
| 6 | Cost by model, per transcript: `job costs <id>` and the evidence block. No per-agent figures. |
| 7 | The test makes `job queue` fail without a retryable error. No test-only knob in vendored code. |

## Components

### 1. Pinned spec and plan are protected (vendored `job`, `gate`, builder prompt)

- `cmd_planned` stores `job["plan_paths"] = [plan["spec"], plan["plan"]]`.
- `gate`: new `protected_patterns(job)` returns `CONFIG["protected_paths"]`
  plus `job.get("plan_paths", [])`; `protected_changes(worktree, patterns)`
  uses it. The `checks.md` protected-paths section lists hits as today.
- Builder prompt, Planned jobs: "Never edit the spec or plan files the job
  was planned from (they're listed in `intake.md`); the gate fails if you do.
  If a task asks you to, skip that step and record it under `## Deviations`."

### 2. Steps outside the job branch (builder prompt, handoff skill)

- Builder prompt, Planned jobs, the skip list becomes: "skip any step that
  creates a branch, worktree or tag, merges, opens a PR, pushes anything other
  than your job branch, or changes files outside your worktree. List each
  skipped step under `## Deviations` as `For the human: <step>`."
- `/factory-handoff` §2 adds a check: grep the plan for `git tag`,
  `git push` (other than the job's own push), `--force`, `git checkout main`,
  `git checkout <base>` and `git merge`. If any match, show the lines and say
  the factory will skip them and list them for the human; ask whether to file
  anyway or fix the plan first.

### 3. Escalation warning (handoff skill)

`/factory-handoff` §3 (risk and surfaces), after proposing them: read
`.claude/agents/approver.md`'s ESCALATE lists (the generic one and any
"In this project" list). If the plan's files or behaviour clearly fall under
one, say: "This plan touches <rule>; the approver will escalate, so the job
will stop at needs-human for you to merge." Information only; filing goes on.

### 4–5. Skill wording (vendored factory skill)

- Replace the "Name the builder…" paragraph with: "When this session spawned
  the job's builder, resume it with `SendMessage` to the agent id its spawn
  result gave; otherwise spawn a new `builder`. Start every message to it with
  `<header>` too." In **build**, "Spawn or resume `builder-<id>`" becomes
  "Spawn or resume the job's builder".
- "Every prompt starts with the job's header, built from `job.json`" becomes
  "built from `job.json` and `base_branch` in `factory/config.json`".

### 6. Cost by model (vendored `job`)

- `cost_by_model(needle)` → `{model: usd}` (rounded to cents), the per-model
  split of what `cost_for_needle` sums today; `cost_for_needle` becomes
  `round(sum(cost_by_model(needle).values()), 2)`.
- `job costs <job>` prints one line per model, largest first
  (`claude-opus-5-5  $4.97`), then `total $x.xx`.
- Evidence block, Budget section: append ` · by model: opus-5-5 $4.97,
  sonnet-5-5 $0.60` (model names without the `claude-` prefix, largest first).

### 7. Runner test (plugin tests)

`test_queue_failure_is_an_error` writes `not json` to the fake issues file
instead of setting `FAKE_GH_EXIT`, so `gh issue list` succeeds and `job queue`
fails parsing it. The assertion (exit 1, ` error: queue: ` in the log) stays.

## Testing

- `job planned` stores `plan_paths`; `gate.protected_patterns` includes them
  for planned jobs and not for others; `protected_changes` flags a modified
  plan file.
- `cost_by_model` with two transcripts on different models; `cost_for_needle`
  equals the sum; `job costs` output; evidence line text.
- Skill and prompt texts: string tests that the old `builder-<id>` wording is
  gone and the new deviation rule is present.
- The runner test runs without sleeping (well under 2 s).

## Out of scope

- Changing Superpowers `writing-plans` (core is never modified).
- Per-agent cost attribution.
- Updating this repo's installed copy: that happens through `/factory-update`
  after merge.
