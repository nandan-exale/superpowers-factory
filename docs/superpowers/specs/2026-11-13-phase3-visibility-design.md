# Phase 3: visibility — Design

Date: 2026-11-13
Status: draft for review. Phase 3 of 5 (see `2026-11-13-roadmap.md`).

## Goal

See how the factory is doing across jobs, not one job at a time, and find
what needs you without hunting. Everything stays on GitHub and in the local
dashboard; no new services.

## Decisions

| Question | Decision |
|---|---|
| Channels | GitHub only: a daily digest comment, plus the existing PR/issue comments and labels. |
| Known limit | GitHub doesn't notify you about comments made by your own account, and the factory acts as you. The digest and a saved needs-human filter are where you look; nothing pings you. A push channel can be added later. |
| Data source | Only `factory/jobs/` (job.json, log.jsonl, decision.md, reviews). No GitHub calls to build the report. |

## Components

### 1. `job report` (vendored `job`)

```
factory/bin/job report [--days 7] [--json] [--write]
```

Reads every job folder and the learning log, for jobs created or active in
the last `--days` days, and prints:

- **Spend:** total, per day (the last N days), per job (top 5), learner
  spend separately; daily cap and today's use.
- **Throughput:** jobs by final stage (merged, rejected, needs-human,
  needs-info, in progress); median and max rounds per merged job; median
  hours from intake to merge.
- **Attention:** jobs now in `needs-human` or `needs-info` with issue/PR
  numbers, how long they've waited, and the first line of the reason.
- **Escalations:** count by first line of `decision.md`'s `## Why`
  (normalised: lowercased, numbers stripped), top 5.
- **Findings:** count by tag across current-round reviews, top 10.
- **Gate:** first-attempt pass rate (round 1 `checks.md` PASS / total).

`--json` prints the same data as one object (stable keys, documented in the
docstring). `--write` also writes it to `factory/jobs/report.json` for the
dashboard. Read-only otherwise; never takes the job lock for longer than a
read.

### 2. Daily digest (vendored `job` and `runner`, config)

Config:

```json
"digest": { "enabled": true, "hour": 9, "days": 1 }
```

`job digest` posts `job report --days <days>` (markdown) as a comment on the
repo's digest issue: the open issue labeled `factory:digest`, created on
first use with title "Factory digest" and pinned
(`gh issue pin`, best-effort). It records the post time in
`factory/jobs/digest.json` and does nothing if a digest was posted in the
last 20 hours or the local hour is before `hour`.

Callers:
- `runner tick` calls `job digest` after its preflight, every tick (it's a
  no-op most of the time). It runs outside the Claude session, costs
  nothing, and needs only `gh`.
- `/factory run` calls it at the end of a run (interactive users without a
  runner still get it).
- `/factory report` (new orchestrator command in the factory skill) prints
  `job report` without posting.

The digest comment starts with a line listing what needs you:
"Needs you: #12 (needs-human, 2d), #15 (needs-info, 5h)" or "Needs you:
nothing". A closed digest issue is reopened; a deleted one is recreated.

`/factory-install` creates the `factory:digest` label; `doctor` checks it
and validates `digest`.

### 3. Finding what needs you

README gets a "What needs me?" section with the GitHub search link pattern
`is:open label:factory:needs-human,factory:needs-info` (repo-scoped) and
tells users to save it as a filter and check the pinned digest issue. It
says plainly that comments the factory posts as you don't notify you.

### 4. Dashboard (vendored `dashboard.html`)

- Auto-refresh every 30 s (it already fetches with `cache: no-store`),
  with a visible "updated hh:mm:ss" and a pause toggle.
- A summary strip from `jobs/report.json` when present: today's spend vs
  cap, jobs needing you, merged this week, top finding tag. Hidden when the
  file is missing.
- `job report --write` runs from `/factory run` and `runner tick`, so the
  strip stays current.

## Error handling

| Where | Failure | Outcome |
|---|---|---|
| report | unreadable job folder | skipped, counted under "unreadable" |
| digest | gh fails | exit 0 with a `NOTE:`; retried next tick (state not recorded) |
| digest | label missing | created on the fly |
| dashboard | report.json missing/invalid | strip hidden |

## Testing

Stdlib unit tests with `FactoryProject` job folders built in temp dirs:
spend per day and cap, stage counts, rounds and durations, escalation
grouping, tag counts, `--json` keys; digest timing (hour, 20 h window),
issue create vs reuse vs reopen with fake `gh`; doctor config validation.
Dashboard: a test that `dashboard.html` references `report.json` and
handles its absence (string checks; no browser).

## Out of scope

- Push notifications (macOS, webhooks, email).
- A bot account so comments notify you.
- Historical charts beyond what the dashboard table shows.
