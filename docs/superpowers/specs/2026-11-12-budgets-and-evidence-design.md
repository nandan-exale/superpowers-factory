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

**Fresh allowance:** `needs-human → build` (via `job feedback` or
`job pr-feedback`) sets `budget_base_usd = cost_usd` and
`budget_base_time = now`, alongside the existing fresh round budget.

**Queue:** when daily spend `>= daily_usd`, `job queue` turns every `resume`
and `new` row into `wait … daily budget: $X of $Y in the last 24 h`.

## Evidence

`job evidence <job>` writes `factory/jobs/<id>/evidence.md` and, if the job
has a PR, replaces the PR body with it (`gh pr edit <pr> --body-file`). It is
also called by `advance` whenever a job with a PR enters `approve` or
`needs-human`. Sections, each always present:

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
Rounds <n> of <round_limit> · cost $<cost> of $<job_usd> · time <h> h of <job_hours> h

Closes #<issue>
```

Text taken from agent-written files is copied verbatim; it is not parsed for
instructions.

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
| evidence | worktree missing, gh edit fails | evidence.md still written; the gh error propagates as a `job` error. |
| log | unreadable line | `job` dies naming the file and line (no silent skip). |

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
