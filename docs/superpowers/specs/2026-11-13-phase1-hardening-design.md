# Phase 1 hardening — Design

Date: 2026-11-13
Status: approved design. Fixes the rough edges found in the first real run
(factory-e2e) and adds the missing lifecycle pieces: uninstall and releases.

## Goal

Five small, independent changes:

1. `/factory-update` stops asking for hand merges of files that are unedited
   old copies when the project has no manifest entry for them.
2. After the factory merges a PR, the main checkout is fast-forwarded when
   that is safe.
3. Idempotent network calls in `job` are retried, so one network blip doesn't
   fail a stage move.
4. `/factory-uninstall` removes the factory from a project, keeping job
   history and GitHub labels.
5. `CHANGELOG.md` and `scripts/release` make version bumps repeatable.

## Decisions

| Question | Decision |
|---|---|
| No-manifest classification | Ship a list of every hash each vendored file has had; a match is an unedited old copy (`safe`). |
| Uninstall and history | Keep `factory/jobs/` and the labels; print how to delete them. |
| What gets retried | Only idempotent calls: `git fetch`, `git push`, `git ls-remote`, read-only `gh`. Never writes such as `issue create` or `pr merge`. |
| Pull after merge | Fast-forward only, only when the main checkout is on the base branch and clean; otherwise a `NOTE:` line. Never fails the merge. |
| Release | Local commit and tag; never pushes. |

## Components

### 1. Known hashes (plugin side)

- `scripts/known-hashes` walks `git log` of `vendor/factory/` and, for every
  path in `bin/factory_files.py` `FILES`, collects the SHA-256 of each version
  the file has had (`git show <commit>:<path>`). It writes
  `vendor/known-hashes.json`: `{"<rel path>": ["<sha256>", ...]}`, sorted, with
  the current version included. `--check` exits 1 if a current vendored
  file's hash is missing from the list (a full comparison would fail in
  shallow CI clones and repo copies).
- `bin/factory_files.py` gains `known_hashes()` (reads the JSON; `{}` when
  missing).
- `bin/factory-update-plan` `classify()`: in the branch where the manifest has
  no entry for the file (`was is None`) and the file differs from upstream,
  the file is `safe` when its hash is in `known_hashes()[rel]`, otherwise
  `merge`. Everything else is unchanged. `config.json`,
  `runner-settings.json` and `checks.sh` keep their own rules.
- `scripts/check` adds a `hashes` check: `scripts/known-hashes --check`.

### 2. Pull main after merge (vendored `job`, own commit)

At the end of the merge path, after the job is saved as `merged`, call
`sync_main()`:

- skip with `NOTE: main checkout is on <branch>, not <base>; not pulled` when
  `git rev-parse --abbrev-ref HEAD` in `REPO` isn't the base branch;
- skip with `NOTE: main checkout has local changes; not pulled` when
  `git status --porcelain` (ignoring untracked files) is non-empty;
- otherwise `git fetch origin <base>` then `git merge --ff-only origin/<base>`;
  on failure, `NOTE: <base> can't fast-forward to origin/<base>; not pulled`.

`sync_main()` never raises. The runner already pulls at the start of each
tick, so this matters mostly for interactive `/factory run`.

### 3. Retried network calls (vendored `job`, its own commit)

`run_net(cmd, cwd=REPO, check=True)` wraps `run()`: up to 3 attempts, each
with `timeout=120`, sleeping 2 s then 5 s between attempts. It retries on a
non-zero exit or a `subprocess.TimeoutExpired`; after the last attempt it
raises `Refused` with the last error (as `run()` does). Sleep is
`time.sleep`, patched in tests.

Used for: `git fetch`, `git push` of the job branch (the best-effort branch
delete after a merge stays on `run`: once GitHub has deleted the branch it
fails every time), `git ls-remote`, and `gh` calls whose subcommand is
`view`, `list`, `status`,
`checks`, or `api` without `-X`/`--method`. `gh()` decides by its arguments:
read-only calls go through `run_net`, all others through `run`. The `git(job,
...)` helper does the same for `fetch` and `push`.

### 4. `/factory-uninstall` (new plugin skill `skills/factory-uninstall/`)

The skill tells the agent to:

1. Refuse if `factory/` isn't installed (no `factory/bin/job`).
2. Refuse while any job worktree exists (`git worktree list` shows a path
   under `.worktrees/`): list them and say to finish or reject those jobs
   first.
3. Run `factory/bin/runner uninstall` if `factory/bin/runner status` reports
   it installed.
4. Remove the files in `factory/manifest.json` `files` (or, without a
   manifest, `bin/factory_files.py` `FILES`), except `factory/checks.sh` when
   it differs from the vendored copy (it's the project's own; say so). Remove
   `factory/manifest.json` and any directories left empty.
5. Run the plugin's `bin/factory-uninstall-settings .`: in
   `.claude/settings.json` it removes only the Stop hook entries whose command
   runs `factory/bin/stop-hook`, drops `hooks.Stop` / `hooks` only if left
   empty, keeps the file's indent, and changes nothing else. Invalid JSON →
   exit 1 without writing; the skill stops and shows the human.
6. Remove the `## Software factory` section from `AGENTS.md` (heading to the
   next `## ` heading), including the planned-issues paragraph. Leave
   `CLAUDE.md` alone.
7. Remove `.github/workflows/factory-checks.yml` only if it exists and runs
   `factory/checks.sh`; if it was edited beyond that, ask first.
8. Keep `.gitignore`'s `/factory/jobs/` and `/.worktrees/` lines (history is
   kept, so it must stay ignored).
9. Run `bin/factory-state decline`, so the session hook stops offering the
   install.
10. Show `git status` and `git diff`; suggest `chore: uninstall software
    factory`; commit nothing. Print, without running:
    `rm -rf factory/jobs` and
    `gh label delete factory --yes` (and the other four `factory*` labels).

The session hook (`hooks/factory-session`) mentions `/factory-uninstall` in
its context for installed projects. README gains an "Uninstall" section.

### 5. CHANGELOG and `scripts/release`

- `CHANGELOG.md` in Keep a Changelog style, newest first, with `0.2.0` and
  `0.1.0` sections written from git history.
- `scripts/release <X.Y.Z>`:
  1. refuses on a dirty tree, a non-`X.Y.Z` argument, or a version not higher
     than `plugin.json`'s;
  2. sets `version` in `.claude-plugin/plugin.json` and the plugin entry of
     `.claude-plugin/marketplace.json`;
  3. runs `scripts/known-hashes` to refresh the list;
  4. prepends `## [X.Y.Z] - <today>` with the commit subjects since the
     latest `v*` tag (all history when none), grouped under Added (`feat`),
     Fixed (`fix`), Changed (everything else except `chore: release`);
  5. opens `CHANGELOG.md` in `$EDITOR` when set and stdin is a TTY;
  6. runs `scripts/check`; on failure, leaves the changes uncommitted and
     exits 1;
  7. commits `chore: release X.Y.Z`, tags `vX.Y.Z`, and prints
     `git push origin main vX.Y.Z`.
- `scripts/check` `json` check also requires the two manifest versions to
  match.

## Error handling

| Where | Failure | Outcome |
|---|---|---|
| update-plan | `known-hashes.json` missing or unreadable | treated as empty: old behaviour (`merge`) |
| sync_main | any git failure | `NOTE:` line, merge still succeeds |
| run_net | all attempts fail | `Refused` with the last error, as today |
| uninstall | worktrees exist / bad settings JSON | stop and tell the human |
| release | dirty tree, bad version, check fails | exit 1, nothing committed |

## Testing

Stdlib `unittest` with the existing helpers (`installed_project.py`,
`factory_project.py`, fake `gh`/`git` on `PATH`):

- known hashes: generated list contains every historical version; an old
  unedited copy with no manifest is `safe`; an edited one is `merge`;
  `--check` catches a stale list;
- sync_main: clean on base → fast-forwarded; other branch, dirty tree and
  diverged history → `NOTE:` and no change; merge result unaffected;
- run_net: a fetch that fails once then succeeds passes; three failures →
  `Refused`; a timeout counts as a failure; `gh issue create` and
  `gh pr merge` are called exactly once on failure;
- uninstall: the skill itself has no automated test; `bin/factory-uninstall-settings`
  is tested (removes only the factory Stop hook, keeps other hooks and keys,
  removes empty containers, refuses invalid JSON, no-op when absent);
  `scripts/check` checks the new skill's frontmatter;
- release: refusals, both versions bumped, changelog grouping, tag created,
  nothing pushed — in a temp clone.

## Out of scope

- Deleting job history or labels automatically.
- Retrying non-idempotent GitHub writes.
- Publishing releases to GitHub (release notes, `gh release`).
