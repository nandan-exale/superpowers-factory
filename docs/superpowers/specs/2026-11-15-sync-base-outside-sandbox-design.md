# Sync a job branch with the base outside the sandbox — Design

Date: 2026-11-15
Status: approved design, ready for a plan.

## Problem

Since 0.5.0 every agent is a sandboxed `claude -p`. The deny rules in
`factory/runner-settings.json` (`Edit(./factory/runner-settings.json)`,
`Edit(./factory/bin/**)`, `Edit(./factory/config.json)`,
`Edit(./factory/checks.sh)`, `Edit(./.claude/**)`) also become sandbox write
denies, relative to the worktree. So when the base branch changes one of those
files, no sandboxed `git merge origin/<base>` can finish in a job worktree:
git can't replace the file.

Observed on job `016-scan-merge-commits-and` (issue #42, PR #53): `job merge`
found a conflict with `main` and escalated; the human's feedback asked the
builder to merge `origin/main`; after PR #51 changed
`factory/runner-settings.json` on `main`, the builder's merge aborted with
`error: unable to unlink old 'factory/runner-settings.json': Operation not
permitted`. Every update of the installed factory strands every open job
branch that has to sync.

`job merge` already syncs with the base and works: `factory/bin/job` runs in
the orchestrator's process, outside the agent sandbox.

## Decisions

| Question | Decision |
|---|---|
| Who merges the base | `factory/bin/job`, run by the orchestrator, never the builder. A new command, `job update-branch <job>`. |
| When | Before every builder spawn for round 2 and later (gate failures, review changes, PR comments, feedback). Round 1 starts from a fresh `origin/<base>`, and its resume matches `git log` against plan tasks, which base commits would muddle. |
| Clean merge | Committed in the worktree (`git merge --no-edit`). The builder pushes it with its round's work. |
| Conflict in unprotected files | The merge is left in progress. The builder resolves only the conflicted files, stages them and runs `git commit --no-edit`. Git has already written every other file, protected ones included, outside the sandbox. |
| Conflict in a protected file | Abort the merge and escalate: an agent may not resolve it. Protected = `protected_paths` plus a planned job's `plan_paths`, the gate's own list. The gate already fails any branch that changes such a file, so this only happens when a human edited one on the branch. |
| Uncommitted changes in the worktree | Skip with a `NOTE:`: never merge over a crashed builder's unfinished work. |
| A merge already in progress | Leave it: the builder is told to finish it. |
| Push | Not here. The builder pushes through `job push`, which scans for secrets. |
| Protected paths for agents | Unchanged. The deny rules and the gate stay; only the factory's own process writes protected files, and only by taking the base's version. |

## Behaviour (vendored `factory/bin/job`)

`job update-branch <job>` (locks the job, reads `job.json`, never writes it,
except through `stop_for_human`):

1. `git fetch origin <base>` (retried like every network call).
2. A merge already in progress (`MERGE_HEAD` exists) → print
   `UPDATE-BRANCH: <id> merge in progress` and exit 0.
3. `git status --porcelain` not empty → print
   `UPDATE-BRANCH: <id> skipped` and a `NOTE:` line, exit 0.
4. `origin/<base>` already in `HEAD` → `UPDATE-BRANCH: <id> up to date`.
5. `git merge --no-edit origin/<base>`:
   - success → `UPDATE-BRANCH: <id> merged origin/<base> (<short sha>)`;
   - conflicts (`git diff --name-only --diff-filter=U`):
     - any protected → `git merge --abort`, then `stop_for_human` with the
       paths; prints the usual `<id>: needs-human: …` line;
     - otherwise → `UPDATE-BRANCH: <id> conflicts: <path> <path>…`.
   - any other failure → `stop_for_human` with git's output.

A git command that can't run (`Refused`) also goes to `stop_for_human`, the way
`ensure-worktree` handles it.

## Orchestrator (`factory/lib/orchestrator/pipeline.py`)

`Pipeline.builder()`, when the job's round is above 1, runs
`job update-branch <id>` first:

- no `UPDATE-BRANCH:` line → the job went to needs-human; spawn nothing;
- `merged` → add to the builder's prompt: `The factory merged origin/<base>
  into the branch; push that merge with your work.`;
- `conflicts: …` → add: `The factory started merging origin/<base> into the
  branch and it conflicts in <paths>. Resolve only those files, stage them,
  run git commit --no-edit, then do the rest of this round.`;
- `merge in progress` → add the same instruction without the path list;
- `up to date`, `skipped` → nothing added; a `NOTE:` line is printed through `say`.

The builder that the Stop hook or the checks nudge sends back (`again`) is the
same round and doesn't sync again.

## Builder prompt (`factory/agents/builder.md`)

A short paragraph under **Build**: never merge or rebase the base branch
yourself; the factory syncs the branch with the base before each round after the
first, and the prompt says when a merge is waiting for you. When feedback asks
for a merge with the base, that merge is the one the prompt names.

## `job merge`

Unchanged. Its conflict escalation now has a working path back: the human's
feedback starts a new round, which begins by syncing and hands the conflict to
the builder.

## Tests

- `tests/test_update_branch.py` (real git, `FactoryProject`): base changed a
  protected file (`factory/runner-settings.json`) and the branch didn't →
  merged, the file has the base's content, merge committed; conflict in an
  unprotected file → merge left in progress, the path printed; conflict in a
  protected file → merge aborted, job in needs-human; up to date; dirty
  worktree skipped; merge already in progress left alone.
- `tests/test_pipeline.py`: round 2+ builder runs `update-branch` before
  `agent builder`, and each outcome's prompt text; round 1 doesn't run it;
  needs-human spawns nothing.
- `tests/test_builder_*_wording.py`-style check that `builder.md` tells the
  builder not to merge the base itself.

## Out of scope

- Sending `job merge` conflicts straight back to build without a human.
- Conflicts in sandbox-denied files that aren't in `protected_paths`
  (`factory/bin/**` in a project whose `protected_paths` omit it). The builder
  can't resolve those and writes BLOCKED, as today.
