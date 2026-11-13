# Phase 4: safety after the merge — Design

Date: 2026-11-13
Status: draft for review. Phase 4 of 5 (see `2026-11-13-roadmap.md`).

## Goal

Two gaps:
1. Nothing watches the base branch after the factory merges. If `main`
   goes red, the factory keeps merging on top of it.
2. Risky changes (dependencies, CI, secrets) reach merge on the reviewers'
   attention alone.

## Decisions

| Question | Decision |
|---|---|
| Red main after a factory merge | Open a revert PR (never merged automatically), pause the queue, mark the job needs-human. You merge the revert or fix forward, then resume. |
| Pause | A file, `factory/jobs/paused.json`; `job queue` starts nothing while it exists; only `job resume` (a human) clears it. |
| Risky diffs | Flag, don't fail: they're allowed through review but stop at merge as needs-human. Secrets are the exception: blocked before push. |

## Components

### 1. Pause and resume (vendored `job`)

- `paused.json`: `{"reason", "job", "sha", "time"}`, written via a temp file.
- `job pause <reason>` / `job resume` (resume prints what it cleared).
- `job queue`: when paused, prints `PAUSED: <reason> (since <time>; run
  factory/bin/job resume after fixing)` and lists nothing to start; jobs
  already in flight still finish their current step but `advance` refuses
  `approve → merging` while paused.
- `runner tick`: paused counts as idle (no Claude session).
- `doctor`: WARN when paused, with the reason.
- `job summary` and the dashboard show the paused banner.

### 2. Watching the base branch (vendored `job`, orchestrator skill)

After `cmd_merge` succeeds, the job records:

```json
"watch": {"sha": "<merge commit on base>", "since": "<time>", "state": "watching"}
```

(`gh pr view --json mergeCommit`; for rebase merges, the PR's last commit
as it landed on base.)

`job watch` (called at the start of every `/factory run` and every runner
tick, before the queue) checks each job with `watch.state == "watching"`:

- `gh run list --branch <base> --commit <sha> --json
  status,conclusion,workflowName,url` (retried, read-only);
- all completed and none `failure`/`timed_out`/`cancelled` (`skipped` and
  `neutral` are fine) → `state: "green"`;
- any failed → `state: "red"` and the revert procedure below;
- no runs yet → keep watching; after `watch.max_minutes` (config,
  default 60) with no runs → `state: "no-ci"` with a `NOTE:`.

Config:

```json
"watch": { "enabled": true, "max_minutes": 60, "ignore_workflows": [] }
```

`ignore_workflows` names workflows whose failure doesn't count (for example
a flaky nightly).

### 3. Revert procedure (vendored `job`)

On red:
1. `job pause "main failed after #<pr> (<workflow>)"` with the job and sha.
2. Create the branch `factory/revert-<job-id>` from `origin/<base>` in a
   fresh worktree; `git revert --no-edit` the merge: `-m 1 <sha>` for a
   merge commit, `<sha>` for squash, the PR's commit range for rebase.
   Conflicts → abort, skip to step 4 with "revert didn't apply cleanly".
3. Push it and `gh pr create` titled `Revert "<original title>"`, body
   naming the failing run URLs and the original PR, label
   `factory:revert`. Not draft, never auto-merged.
4. Comment on the original PR and issue (failing runs, the revert PR or why
   there isn't one, and "the queue is paused; `factory/bin/job resume` when
   main is green"). Label the issue `factory:needs-human`.
5. The job's stage stays `merged`; `watch.state = "red"`,
   `watch.revert_pr = <n>`.

Nothing here deletes branches or force-pushes.

### 4. Risky-change checks (vendored `gate`, `job`)

Config:

```json
"risky_paths": [".github/workflows/**", "**/package.json", "**/package-lock.json",
  "**/pnpm-lock.yaml", "**/yarn.lock", "**/pyproject.toml", "**/requirements*.txt",
  "**/poetry.lock", "**/uv.lock", "**/Cargo.toml", "**/Cargo.lock", "**/go.mod",
  "**/go.sum", "**/Gemfile", "**/Gemfile.lock", "Dockerfile", "**/*.tf"]
```

`gate` adds a `## Risky changes` section to `checks.md` listing changed
files matching `risky_paths` (added, modified or deleted). The checks still
decide PASS/FAIL. Reviewers see the section (their prompt already reads
`checks.md`).

At merge, `cmd_merge` refuses with needs-human when the job's latest
`checks.md` lists risky changes and the issue doesn't carry the label
`factory:risk-ok`: "This PR changes dependencies or CI: <files>. Review it,
then add `factory:risk-ok` to the issue and run the factory again, or merge
it yourself." Adding the label and running again lets the merge proceed.

### 5. Secret scan before push (vendored `job`, builder prompt)

`job push <id>`: scans `git diff origin/<base>...HEAD` added lines in the
job's worktree for:

- private key blocks (`-----BEGIN [A-Z ]*PRIVATE KEY-----`),
- AWS access keys (`AKIA[0-9A-Z]{16}`),
- GitHub tokens (`gh[pousr]_[A-Za-z0-9]{36,}`, `github_pat_[A-Za-z0-9_]{50,}`),
- Anthropic keys (`sk-ant-[A-Za-z0-9_-]{20,}`),
- Slack tokens (`xox[baprs]-[A-Za-z0-9-]{10,}`),
- generic `(api[_-]?key|secret|token|password)\s*[:=]\s*["'][^"']{16,}["']`
  (case-insensitive),

skipping files matching `secret_scan.allow` globs (config, default
`["**/*.test.*", "**/fixtures/**"]`). A hit → exit 1 listing `file:line`
and the rule, with the matched value masked; nothing is pushed. No hit →
`git push origin <branch>` (retried).

The builder prompt changes from "push the branch" to "push with
`factory/bin/job push <id>`; if it reports a secret, remove it from the
commits (amend or rebase locally; the branch isn't pushed yet) and try
again". The gate repeats the scan as a backstop: a hit there fails the
gate and the job goes to needs-human with "a possible secret reached the
remote branch; rotate it".

`/factory-install` creates the `factory:revert` and `factory:risk-ok`
labels; `doctor` checks them and validates `watch`, `risky_paths`,
`secret_scan`.

## Error handling

| Where | Failure | Outcome |
|---|---|---|
| watch | gh fails | keep watching; next run retries |
| revert | conflict or push fails | no revert PR; queue still paused; comment says why |
| merge | risky without `factory:risk-ok` | needs-human, nothing merged |
| push | secret found | exit 1, nothing pushed |
| gate | secret found on remote branch | gate FAIL, needs-human, "rotate it" |

## Testing

Stdlib unit tests: pause file round trip, queue and runner idle while
paused, `approve → merging` refused while paused; watch state transitions
from faked `gh run list` (green, red, ignored workflow, no-ci timeout);
revert command per merge method in a `FactoryProject` with a real bare
origin (squash and merge-commit cases, conflict case); risky-path matching
and the merge refusal/label override; secret rules (each rule hits, masks
the value, `allow` skips, clean diff pushes) with test strings built at
runtime so no real-looking secret sits in the repo.

## Out of scope

- Auto-merging reverts or auto-resuming.
- Watching non-factory commits on main.
- A full secret scanner; this is a pattern backstop, not a replacement for
  GitHub secret scanning.
