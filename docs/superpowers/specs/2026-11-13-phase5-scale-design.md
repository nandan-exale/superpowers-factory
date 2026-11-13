# Phase 5: scale — Design

Date: 2026-11-13
Status: draft for review. Phase 5 of 5 (see `2026-11-13-roadmap.md`).
Three parts, each its own plan and PR-sized change: 5a multi-part plans,
5b Linux systemd runner, 5c GitHub Actions runner.

## Decisions

| Question | Decision |
|---|---|
| Large plans | Split at handoff into ordered parts, one issue and one PR each; a part starts only after the previous part merged. No stacked PRs. |
| Runners | Both Linux systemd and GitHub Actions, alongside macOS launchd. |
| Tokens | Never in the repo or config. systemd: `secret-tool` or a 0600 file. Actions: repo secrets. |
| Job state on Actions | Persisted on an orphan branch `factory-state`, because runners are ephemeral. |

## 5a. Multi-part plans

### Handoff (plugin skill `factory-handoff`)

When the plan has more than `handoff.max_tasks_per_part` tasks (config,
default 8), or the user asks, the skill proposes parts: consecutive task
ranges, each ending at a point where tests pass and the change is
reviewable on its own. The user confirms or edits the split. It then files
one issue per part, in order, each with a `factory-plan` block that adds:

```
part: 2/3
tasks: 4-7
depends: #41
```

`depends` is the previous part's issue (absent on part 1). Titles get a
`(part 2/3)` suffix.

### Factory (vendored `job`, builder prompt)

- `parse_plan_block` accepts `part`, `tasks` (`N-M`, within the plan's task
  count) and `depends` (`#N`, an issue in this repo).
- `job queue`: a planned issue whose `depends` issue isn't closed with its
  job `merged` shows `wait depends #N` and doesn't start. If the dependency
  job is `rejected` or the issue was closed without a merge, the part goes
  to needs-human: "part 1 (#41) didn't merge; re-plan or remove the
  dependency".
- `job planned` copies the whole spec and plan (context) and writes the
  task range into `intake.md` and the job header (`Tasks: 4-7 of 12`).
- Builder prompt: "carry out only the tasks in `Tasks:`; earlier tasks are
  already merged on base; don't start later ones".
- Reviewers and approver: plan conformance is judged against the range.

## 5b. Linux systemd runner (vendored `runner`)

- `runner install` on Linux writes
  `~/.config/systemd/user/factory-<repo-hash>.service` (`Type=oneshot`,
  `ExecStart=<python> <repo>/factory/bin/runner tick`,
  `WorkingDirectory=<repo>`) and `.timer` (`OnBootSec=5min`,
  `OnUnitActiveSec=<interval_minutes>min`, `Persistent=true`), then
  `systemctl --user daemon-reload` and `enable --now` the timer.
  `uninstall` disables and deletes both; `status` shows `systemctl --user
  list-timers` for it plus the log tail.
- Token, in order: `secret-tool lookup service <keychain_service>` if
  `secret-tool` exists and returns one; else `~/.config/factory/claude-token`
  if its mode is exactly 0600 and owner is the user (refuse otherwise, with
  the `chmod` fix). Passed only through the child's environment, as on
  macOS.
- Sandbox: Claude Code's Linux sandbox needs `bubblewrap` (and `socat`);
  `doctor` checks they're on `PATH` and FAILs the runner check without them.
- `doctor` notes `loginctl enable-linger $USER` so the timer runs while
  logged out.
- macOS stays launchd; the platform switch is one function.

## 5c. GitHub Actions runner (installed workflow, vendored `runner`, `job`)

### Workflow

`/factory-install` offers it (off by default) and writes
`.github/workflows/factory-runner.yml`:

- triggers: `schedule` (cron from `runner.interval_minutes`, min 15) and
  `workflow_dispatch`; `concurrency: {group: factory-runner,
  cancel-in-progress: false}`;
- `permissions: {contents: write, issues: write, pull-requests: write,
  actions: read}`;
- steps: checkout with full history; setup Python and Node; install
  `bubblewrap socat`; install Claude Code pinned to the version recorded at
  install time; configure git identity from the token's user; run
  `factory/bin/runner tick --ci`, with env `CLAUDE_CODE_OAUTH_TOKEN:
  ${{ secrets.FACTORY_CLAUDE_TOKEN }}` and `GH_TOKEN: ${{
  secrets.FACTORY_GH_TOKEN }}`;
- `timeout-minutes` = `runner.max_minutes` + 10.

`FACTORY_GH_TOKEN` must be a fine-grained PAT (or GitHub App token) for
this repo only, with contents, issues and pull requests read/write and
actions read. `GITHUB_TOKEN` is not enough: pushes and PRs it makes don't
trigger the project's CI. The install skill tells the user to create both
secrets themselves and never asks for their values.

Install refuses on public repos unless the user confirms after a warning
(scheduled workflows on public repos run with secrets the repo's
maintainers control; a fork can't reach them, but anyone with write access
can change the workflow).

### `runner tick --ci`

Same tick, except: no lock file (the workflow's concurrency group is the
lock), no launchd/systemd checks, token from `CLAUDE_CODE_OAUTH_TOKEN` in
the environment (then scrubbed from the child env as today and passed
explicitly), and state persistence around the run:

- **restore:** fetch `factory-state`; if it exists, copy its tree into
  `factory/jobs/` (which is gitignored on main);
- **save (always, also after failures):** commit `factory/jobs/` (minus
  `*.lock` and transcripts over 1 MB) to `factory-state` as a single new
  commit on top of the previous one, and push it. A rejected push (someone
  else wrote it) → fetch, re-apply, retry once.

`factory-state` is an orphan branch that only the runner writes. `doctor
--ci` checks branch protection doesn't block the token from pushing to it.

### Worktrees on a fresh machine (vendored `job`)

Each Actions run starts with no `.worktrees/`. New helper
`ensure_worktree(job)`: if a non-terminal job's worktree is missing,
recreate it from `origin/<branch>` when the branch exists, else from
`origin/<base>` on a new branch. `/factory run` calls it before spawning any
agent for the job. Work not pushed before a run ended is lost; the builder
already pushes before the gate, so at most one build attempt is repeated.

## Error handling

| Where | Failure | Outcome |
|---|---|---|
| 5a | dependency rejected | part → needs-human |
| 5a | `tasks` out of range | `job planned` refuses (escalates like other bad blocks) |
| 5b | token file too open | runner refuses with the `chmod 600` fix |
| 5b | bubblewrap missing | doctor FAIL; tick skips with a log line |
| 5c | state push rejected twice | job state for that run is kept as a workflow artifact; next run warns |
| 5c | worktree recreate fails | job → needs-human with the git error |

## Testing

5a: plan-block parsing of the new keys; queue waits and the needs-human
path with faked issue states; header and intake carry the range.
5b: unit file contents and install/uninstall commands with `systemctl`
faked; token source order and the 0600 check; doctor bubblewrap check.
5c: workflow file rendered from config (YAML parsed with a small
stdlib-safe check of the keys we need, no new dependency); `--ci` token
handling; state restore/save against a bare origin (orphan branch created,
second run appends, push conflict retried); `ensure_worktree` from existing
and missing branches.

## Out of scope

- Stacked PRs or parallel parts.
- Other CI providers.
- Windows.
