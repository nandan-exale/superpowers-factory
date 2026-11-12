# Budgets and evidence — Design

Date: 2026-11-12
Status: approved design. Spec 1 of 4 toward a hands-off factory (then:
hands-off running, auto setup + handoff, learning loop). Draws on
DenisSergeevitch/agents-best-practices (MIT): runtime policy enforced outside
the model, explicit budgets and stop rules, a durable progress log, and final
evidence for every change.

## Goal

The factory can't spend without limit, and every PR it opens or escalates
says why the factory thinks the work is done, or why it stopped.

## Decisions

| Question | Decision |
|---|---|
| Where limits live | `factory/bin/job` (deterministic code), not the orchestrator's instructions. |
| Limits | Per-job cost, per-job wall-clock time, daily spend across all jobs. |
| Over a job limit | The job escalates to `needs-human` with the reason posted. |
| Over the daily limit | Nothing new starts and no job advances into a budgeted stage until 24 h spend drops; no escalation. |

## Config

`factory/config.json` gains:

```json
"budgets": { "job_usd": 25, "job_hours": 6, "daily_usd": 100 }
```

Each value is a positive number or `null` (that limit off). `job` refuses to
start (`die`) if `budgets` is missing or a value is neither. `doctor`'s
`config` check validates the same.

## Spend log

`factory/jobs/<id>/log.jsonl`, append-only, one JSON object per line:

```json
{"t": "2026-11-12T15:00:00Z", "event": "advance", "stage": "review", "round": 2, "cost_usd": 4.12, "delta_usd": 1.07}
```

- `job` appends a line on every `save` where the stage or `cost_usd` changed
  since the last line (`event`: the subcommand, e.g. `advance`, `sync`,
  `feedback`). `delta_usd` is the cost added since the job's previous line
  (first line: the whole cost).
- **Daily spend** = sum of `delta_usd` over every job's lines with `t` in the
  last 24 h.
- The log is never rewritten. A missing log reads as empty.
- Reading is tolerant: an unterminated final line (a write cut short) is
  skipped silently; any other line that isn't JSON or lacks `t`, `stage`,
  `cost_usd` or `delta_usd` prints `job: <path>: skipping bad line <n>` to
  stderr and is skipped. A later append starts on a fresh line.
- Cost never decreases: `sync` keeps `max(previous cost_usd, measured cost)`,
  and `delta_usd` is clamped at 0 or more. Because cost is monotonic, after
  Claude Code cleans up old transcripts a resumed job's new spend is
  undercounted until the recomputed cost passes the stored maximum.

## Enforcement

A helper `budget_problem(job)` returns `None` or a reason string, after
`sync(job)` has refreshed the cost:

- **Job cost:** `cost_usd - budget_base_usd > job_usd` → `"budget: $27.10 of $25.00 used"`.
- **Job time:** hours since `budget_base_time` (default: `started`) `> job_hours`
  → `"budget: 6.4 h of 6 h used"`.

`budget_base_usd` (default 0) and `budget_base_time` live in `job.json`.

**Budgeted moves** are `advance` into `gate`, `review` or `approve`, and into
`build` from `gate` or `review` (a rebuild round). Before such a move:

1. If daily spend `>= daily_usd`, raise `Refused("daily budget: $X of $Y in the last 24 h; the job resumes when it drops")`. The job's stage is unchanged.
2. Else if `budget_problem(job)` returns a reason, write `decision.md` via
   `escalate(job, reason + "\n\nRaise budgets.job_usd / budgets.job_hours in factory/config.json, or give feedback to continue with a fresh allowance.")`,
   advance to `needs-human` (legal from every source of a budgeted move), and
   print `BUDGET: <job> → needs-human (<reason>)`. The requested move does
   not happen.

**Time base:** `budget_base_time` is also set on `spec → build` (which
`job planned` passes through), so time spent queued or in intake and spec does
not count against the job. The cost base is unchanged.

**PR lookup:** before a budget stop at `build → gate` (no PR recorded yet),
`find_pr(job)` records the branch's PR if exactly one is open, so the stop is
posted on the PR and the evidence goes in its body. A lookup failure or zero
or several open PRs leaves `pr` unset and the stop posts on the issue. The
normal `build → gate` path uses the same helper and still requires exactly one.

**Fresh allowance:** `needs-human → build` (via `job feedback` or
`job pr-feedback`) sets `budget_base_usd = cost_usd` and
`budget_base_time = now`, alongside the existing fresh round budget.

**Queue:** when daily spend `>= daily_usd`, `job queue` turns every `resume`
and `new` row into `wait … daily budget: $X of $Y in the last 24 h`.

## Evidence

`job evidence <job>` writes `factory/jobs/<id>/evidence.md` and, if the job
has a PR, puts it in the PR body. It is also called by `advance` whenever a
job with a PR enters `approve` or `needs-human` (including a budget stop).
The block is wrapped in `<!-- factory evidence -->` … `<!-- /factory evidence -->`
markers. Sections, each always present:

```markdown
<!-- factory evidence -->
## Factory evidence — <job id>, round <n>

### Files changed
<`git diff --stat origin/<base>...HEAD` in the worktree, or "none">

### Checks
<GATE line from round-N/checks.md> — last 15 lines of its output, or "not run">

### Acceptance criteria
<build.md "## Acceptance criteria" section, or "none recorded">

### Plan tasks and deviations
<build.md "## Plan tasks" and "## Deviations", or "not a planned job">

### Reviews
<one line per reviewer: name — PASS / CHANGES / pending>

### Budget
Rounds <n> of <round_limit> · cost $<spent> of $<job_usd> since the last allowance ($<total> total) · time <h> h of <job_hours> h since the last allowance

Closes #<issue>
<!-- /factory evidence -->
```

**Body.** The PR body is read first. If it holds a previous evidence block
(between the markers), that block is replaced in place; otherwise the new
block goes first and the old body follows after a blank line. Human text is
never lost, and publishing twice never duplicates the block.

**Size.** Each section body is cut at 8,000 characters and the whole block at
60,000, with the line `(truncated; full text in factory/jobs/<id>/evidence.md)`.
`evidence.md` on disk keeps the full text. Files changed uses
`git diff --stat=120 --stat-count=50`.

**Defusing.** Text copied from `build.md` and `checks.md` is data, not
instructions: GitHub closing keywords followed by an issue reference
(`close/closes/closed`, `fix/fixes/fixed`, `resolve/resolves/resolved`, an
optional colon, `#N` or `owner/repo#N`) are wrapped in backticks, `@` gets a
zero-width space after it, and `<!--` is escaped so agent text can't forge the
markers. The checks output sits in a code fence longer than any backtick run in
it. Only the factory's own `Closes #<issue>` line closes the issue.

**Best effort.** Evidence never blocks a transition. If `gh` refuses the
body read or edit, `job` prints `job: evidence not published: <reason>` to
stderr, records `evidence_error` in `job.json`, and the transition completes
and is saved. A later successful publish clears `evidence_error`.

## Orchestrator and dashboard

- `.claude/skills/factory/SKILL.md`: a `BUDGET:` line from `job advance` is an
  escalation: the job is finished for this run. A `daily budget` refusal or
  `wait … daily budget` queue row ends the run after the one-line summary.
- `job summary` cost column shows `$<cost>/$<job_usd>`; the dashboard shows
  the same.

## Error handling

| Where | Failure | Outcome |
|---|---|---|
| config | `budgets` missing or invalid | `job` dies with the key named; doctor FAILs `config`. |
| evidence | worktree missing | `Files changed` says `none`; evidence.md still written. |
| evidence | gh body read or edit fails | evidence.md still written; `evidence_error` recorded, warning on stderr, transition completes. |
| log | bad or partial line | Partial final line skipped silently; any other bad line skipped with a stderr warning naming file and line. |

## Testing

`tests/test_budgets.py` (stdlib `unittest`, `gh` and cost faked as in the
existing `FactoryProject` tests):

- over `job_usd` at review → `needs-human`, reason in `decision.md` and the gh comment, `BUDGET:` printed;
- over `job_hours` (fake `started`) → same;
- `null` disables each limit;
- feedback resets the allowance and the job can advance again;
- daily spend over `daily_usd` → `advance` refused, stage unchanged; `queue` rows are `wait … daily budget`;
- log deltas sum to the job's cost; only stage/cost changes append;
- invalid `budgets` → dies.

`tests/test_evidence.py`: every section present for a full job; "none" lines
for a job with no build.md, no checks, no worktree; PR body replaced via the
fake gh; called on entering `approve` and `needs-human`.

`doctor` tests: invalid `budgets` value FAILs `config`.

## Out of scope

- Token-level budgets inside a single agent turn (Claude Code owns that).
- Spend outside factory agents (the orchestrator session itself).
- Specs 2–4.
