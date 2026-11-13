# Learning loop — Design

Date: 2026-11-12
Status: approved design. Spec 4 of 4 toward a hands-off factory. Applies
the agents-best-practices skill (MIT): repeated failures should become
validators, checks or docs rather than repeated advice, with human approval
before any rule changes.

## Goal

When reviewers keep raising the same kind of problem across jobs, the factory
proposes the smallest mechanical fix (a lint rule, a structural test, a check
script, or an AGENTS.md rule) as a GitHub issue. Adding the `factory` label
approves it, and the factory builds it like any other job.

## Constraints found

- Review findings are free text (`review-<lens>.md`, `## Findings`), with no
  category to count.
- `factory/checks.sh` and `factory/config.json` are `protected_paths`: the
  factory can't build a job that changes them. Proposals target unprotected
  places; when the right fix belongs in a protected file, the issue says a
  human must make it.

## Decisions

| Question | Decision |
|---|---|
| Detection | Reviewers tag findings; `job learn` counts tags deterministically. No model reads findings unless a tag crosses the threshold. |
| Proposal path | GitHub issue labeled `factory:learning`; approval = adding `factory`. |
| Spend | Learner cost is logged and counts toward `budgets.daily_usd`. |
| agents-best-practices | Vendored as a plugin skill with its MIT license, with two modifications: its self-update section is replaced by a pinned-snapshot note, and links to external repositories are removed from its references. |

## Components

### Tagged findings (reviewer agents)

`reviewer-code`, `reviewer-security`, `reviewer-ux`, `reviewer-ui` write each
finding as:

```
1. [<tag>] <path:line> <the problem and the fix you want>
```

`<tag>` is one of `config.json` `learning.tags`, or `other:<slug>` (`slug`
lowercase `[a-z0-9-]+`) when none fits. Seed tags:
`missing-test`, `weakened-test`, `error-handling`, `convention`,
`docs-not-updated`, `dead-code`, `spec-gap`, `input-validation`, `secrets`,
`a11y`, `ui-consistency`.

`job sync` parses each current-round review's `## Findings`; a numbered item
without a valid tag sets that review's state to `invalid`
(as an unparseable verdict already does), so the orchestrator re-asks the
reviewer. "None." is valid.

### Config

```json
"learning": { "threshold": 3, "window_days": 30, "tags": ["missing-test", "..."] },
"agents": { "intake": {...}, "learner": { "model": "opus", "effort": "high" } }
```

`threshold` and `window_days` positive integers; `tags` a non-empty list of
`[a-z0-9-]+`. `job` and `doctor` validate it.

### job learn

Deterministic, no model:

1. For every job, every `round-*/review-*.md` file modified within
   `window_days`: collect `(tag, job id, round, lens, finding text)`.
   Escalations (`decision.md` starting `ESCALATE`) are not counted; their
   `## Why` text is added as context to the evidence of any tag those jobs
   contribute to.
2. A tag recurs when it appears in at least `threshold` distinct jobs.
3. Skip tags with an entry in `factory/jobs/learning/state.json` filed within
   `window_days`.
4. For each remaining tag write `factory/jobs/learning/<tag-dir>/evidence.md`
   (`<tag-dir>` is the tag with `:` replaced by `--`): the tag, the
   count, and each finding quoted as data (job id, issue, lens, round, text),
   plus the `## Why` of any escalation of those jobs. Print
   `LEARN: <tag> (<n> jobs) factory/jobs/learning/<tag-dir>/evidence.md`, or
   `LEARN: none`.

`other:<slug>` tags count like any other tag (per slug).

### learner agent (new, vendored `.claude/agents/learner.md`)

Tools: Read, Grep, Glob, Write, Skill. Prompt gives the evidence file path and
the output path `factory/jobs/learning/<tag-dir>/proposal.md` (the prompt's
first line is `Job folder: <repo>/factory/jobs/learning/<tag-dir>/.`, the same
absolute form as a job's header, so its cost is found the same way). It:

- reads the evidence (quoted data, never instructions), `AGENTS.md`, and the
  repo's lint/test setup;
- loads `agents-best-practices` if available (mechanical invariants,
  legibility);
- proposes the smallest mechanical fix that would have caught most of the
  findings, preferring, in order: an existing linter's rule, a structural
  test, a check script outside protected paths, an AGENTS.md rule. Each fix
  includes the remediation message an agent would see;
- if the fix needs a protected path (`config.json` `protected_paths`), says so
  and marks the proposal `HUMAN-ONLY` (the proposal's second line, when
  present);
- writes the proposal: first line `PROPOSAL: <one-line title>` (or
  `PROPOSAL: NONE` with the reason when no mechanical fix is reasonable),
  then `## Problem`, `## Proposed change`, `## Why this catches it`,
  `## Out of scope`.

Its model and effort come from `agents.learner` via `job agent <tag> learner`
(the `agent` subcommand accepts a learning tag for this role).

### job learn-file <tag>

0. A proposal older than `evidence.md` is refused (new evidence deletes the
   old proposal; the learner must run again).
1. Reads `<tag-dir>/proposal.md`. `PROPOSAL: NONE` → record the tag in
   `state.json` as `none` with the time (so it isn't re-proposed within the
   window), print `LEARN-FILE: <tag> none`.
2. Otherwise `gh issue create` with title `Factory learning: <title>`,
   (the title defused and capped at 200 characters), label `factory:learning`.
   The body starts with an approval notice (check the change doesn't weaken or
   skip checks or tests, add dependencies, touch network, credentials or CI, or
   edit protected paths), then the proposal, then "Quoted evidence (not part of
   the request)" with the evidence. Proposal and evidence are defused and have
   open code fences closed; only the evidence is truncated, so the whole body
   stays within 60,000 characters. It ends with: "To build this, add the `factory` label." (or, for `HUMAN-ONLY`:
   "This needs a change to a protected file; make it by hand.").
3. Records `{tag: {"issue": n, "filed": time}}` in `state.json` (written via
   a temp file). If gh's output has no issue number, records `issue: null` and
   the raw output, then exits 1, so the tag isn't filed twice.
4. Computes the learner's cost (same transcript method as job cost, matching
   prompts that name `factory/jobs/learning/<tag-dir>/`) and logs the cost
   since the last line to `factory/jobs/learning/log.jsonl` with a `tag` field,
   so `daily_spend()` includes it.
5. Prints `LEARN-FILE: <tag> #<n>`.

### Orchestrator, install, doctor

- `.claude/skills/factory/SKILL.md`: when a `/factory run` has nothing left
  queued or running, run `factory/bin/job learn`; for each `LEARN:` line, if
  the daily budget allows (`job queue` shows no daily-budget wait), spawn
  `learner` with `job agent <tag> learner` settings, then
  `factory/bin/job learn-file <tag>`; report each `LEARN-FILE:` line in the
  summary.
- Reviewer agents: the finding format and tag rule above.
- `/factory-install`: create the label
  `gh label create factory:learning --color C5DEF5 --description "Factory-proposed check or rule; add 'factory' to build it"`;
  add `learner.md` to the copy list and `bin/factory_files.py` `AGENTS`.
- `doctor`: `labels` also requires `factory:learning`; `agents` includes
  `learner`; `config` validates `learning` and `agents.learner`.

### agents-best-practices (plugin skill)

Vendored from the upstream agents-best-practices skill at a pinned
commit, with two modifications (the "Freshness and self-update" section of
`SKILL.md` is replaced by a pinned-snapshot note, because a shipped skill
mustn't fetch or rewrite itself; and links to external repositories are
removed from `references/source-links.md`, keeping their labels) into `skills/agents-best-practices/` (`SKILL.md`, `references/`,
`LICENSE`), plus `skills/agents-best-practices/SOURCE` naming the upstream
commit, date and the modifications. Images are not vendored. README credits it.
`scripts/check` already checks its frontmatter; `license` also requires its
`LICENSE` and `SOURCE`.

## Error handling

| Where | Failure | Outcome |
|---|---|---|
| sync | finding without a valid tag | review `invalid`; reviewer re-asked |
| learn | unreadable review file | skipped with a stderr note |
| learn-file | proposal missing or first line malformed | exits 1 naming the file; nothing filed |
| learn-file | gh fails | exits 1; state not recorded (retried next run) |
| orchestrator | daily budget reached | learning skipped this run |

## Testing

Stdlib `unittest` with the existing fakes:

- tag parsing: valid tags, `other:<slug>`, missing/unknown tag → `invalid`, "None." valid;
- `job learn`: threshold by distinct jobs (not findings), window by file
  time, skip recently filed or `none` tags, evidence file content (quoted,
  includes escalation reasons), `LEARN: none`;
- `job learn-file`: issue title/label/body via fake gh, `HUMAN-ONLY` text,
  `PROPOSAL: NONE` path, state recorded, no duplicate within window, cost
  line appended and counted by `daily_spend`, malformed proposal → exit 1;
- config/doctor validation of `learning`, `agents.learner`, the new label;
- vendored skill: frontmatter, LICENSE and SOURCE present.

## Out of scope

- Automatically applying proposals (always a human label).
- Learning from merged-PR outcomes or CI history.
- Updating the vendored agents-best-practices automatically.
