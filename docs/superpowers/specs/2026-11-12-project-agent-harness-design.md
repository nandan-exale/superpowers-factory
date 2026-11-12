# Project agent harness — Design

Date: 2026-11-12
Status: approved design. Second of two harness specs; the first
(`2026-11-12-repo-agent-harness-design.md`) covers this repo.

## Goal

A project with the factory installed gives every agent, not only the
factory's builder, the same rules and the same checks: interactive sessions
can't stop with failing `factory/checks.sh`, CI runs the same script on PRs,
Claude Code reads `AGENTS.md`, and one command tells you whether the install
is healthy.

## Decisions

| Question | Decision |
|---|---|
| Pieces | `CLAUDE.md` import, Stop hook for interactive sessions, CI running `checks.sh`, `factory/bin/doctor`. |
| Slow checks | The Stop hook caches by tree state: it runs `checks.sh` only when the tree differs from the last state that passed. |
| Approach | Two vendored stdlib scripts, tested in this repo, copied by `/factory-install`; the install skill wires them in. |

## Components

### factory/bin/stop-hook (new, vendored)

Stdlib Python, executable. `REPO` is two levels above the script, as in
`gate`. Registered as the project's Stop hook; reads the hook JSON on stdin.

1. Payload not a JSON object → treated as `{}`.
2. `git status --porcelain` in `REPO` fails → note on stderr, exit 0. Empty →
   exit 0.
3. Tree key: SHA-256 over `git rev-parse HEAD`, `git diff HEAD --binary`, and
   for each `git ls-files --others --exclude-standard -z` path, its name and
   bytes. `.worktrees/` and `factory/jobs/` are gitignored, so job state never
   counts.
4. Stamp file: `git rev-parse --git-path factory-stop-hook.pass`. If it holds
   the tree key → exit 0.
5. Run `bash factory/checks.sh` in `REPO`. Exit 0 → write the key to the stamp,
   exit 0.
6. Non-zero → print `factory/checks.sh failed (exit N); last lines:` plus the
   last 80 lines of combined output to stderr. Exit 2, unless
   `stop_hook_active` is true → exit 0 (never blocks twice in a row).
7. `checks.sh` missing, or `bash` can't start → note on stderr, exit 0. The hook
   never blocks on its own breakage. A hook killed by the 600 s timeout is a
   non-blocking error in Claude Code.

The builder keeps its own `gate --hook`; Claude Code fires subagent stops as
`SubagentStop`, so `stop-hook` only runs for the main session.

### factory/bin/doctor (new, vendored)

Stdlib Python, executable, `REPO` as in `gate`. Prints `PASS <name>`,
`WARN <name>: <reason>` or `FAIL <name>: <reason>` per problem. Exit 1 on any
`FAIL`, else 0. `--fast` skips `checks`.

| Check | Rule |
|---|---|
| `config` | `factory/config.json` parses; every `{model, effort}` in `agents`, `routing.<risk>`, `surface_reviewers` has a `model` in `model_aliases` and an `effort` in `effort_levels`. |
| `agents` | Each of the 8 factory agents in `.claude/agents/` exists, has a `---` frontmatter block with only `name`, `description`, `tools` (and `hooks` on `builder`), and no `model`. |
| `files` | `.claude/skills/factory/SKILL.md` exists; `factory/checks.sh` and `factory/bin/{job,gate,route,stop-hook,doctor}` exist and are executable. |
| `gitignore` | `git check-ignore -q` succeeds for `factory/jobs/x` and `.worktrees/x`. |
| `stop-hook` | `.claude/settings.json` parses and some `hooks.Stop[].hooks[].command` contains `factory/bin/stop-hook`. |
| `claude-md` | If both `AGENTS.md` and `CLAUDE.md` exist, `CLAUDE.md` contains a line `@AGENTS.md`. If neither exists, FAIL. Otherwise PASS. |
| `labels` | `gh label list --json name --limit 200` includes `factory`, `factory:needs-info`, `factory:needs-human`, `factory:planned`. `gh` missing or failing → WARN, not FAIL. |
| `checks` | `bash factory/checks.sh` exits 0 in `REPO`; on failure, the last 20 lines. |

A check that raises reports `FAIL` with the error; the others still run.

### Install changes (skills/factory-install/SKILL.md)

- **Copy:** add `factory/bin/stop-hook` and `factory/bin/doctor` to the copy
  list and the `chmod +x` line.
- **Stop hook:** merge into `.claude/settings.json`, creating it if absent and
  keeping every existing key and hook:

  ```json
  {"hooks": {"Stop": [{"hooks": [{"type": "command",
    "command": "\"$CLAUDE_PROJECT_DIR\"/factory/bin/stop-hook", "timeout": 600}]}]}}
  ```

  Append to an existing `hooks.Stop` list; never replace it.
- **CLAUDE.md:** after the AGENTS.md step: if the project has `AGENTS.md` and
  no `CLAUDE.md`, create `CLAUDE.md` containing `@AGENTS.md`. If it has both
  and `CLAUDE.md` lacks that line, append it. If it uses only `CLAUDE.md`,
  change nothing.
- **CI:** if the project's existing CI already runs the commands in
  `checks.sh` on pull requests, add nothing and say so. Otherwise create
  `.github/workflows/factory-checks.yml` that runs on `pull_request` and on
  `push` to the base branch: checkout, the toolchain setup steps copied from
  the project's existing workflows (or the stack's standard `setup-*` action
  if it has none), then `bash factory/checks.sh`. Show it to the user; it is
  part of the install diff.
- **Verify:** replace upstream step 3 with `factory/bin/doctor`, which must exit
  0. WARN lines are reported to the user.
- Never overwrite an existing file without asking; never commit (unchanged).

### This repo

- `scripts/check` `compile` check also compiles `factory/bin/stop-hook` and
  `factory/bin/doctor`.
- `vendor/factory/INSTALL.md` is upstream text and stays unchanged; the
  install skill's overrides carry the changes.
- README "Use it in a project" mentions `factory/bin/doctor`.

## Error handling

| Where | Failure | Outcome |
|---|---|---|
| stop-hook | checks fail | Blocks once with the last 80 lines. |
| stop-hook | own breakage (no git, no checks.sh, crash, timeout) | Never blocks. |
| doctor | `gh` unavailable | `labels` WARN; exit unaffected. |
| install | `.claude/settings.json` exists but doesn't parse | Stop and show the user; don't rewrite it. |
| install | existing CI already covers the checks | No workflow added; say so. |

## Testing

Stdlib `unittest` in this repo, on a throwaway project built with the existing
`tests/factory_project.py` (bare origin + vendored factory scripts), with
`factory/checks.sh` replaced by a script whose result a test controls (e.g. it
exits with the contents of a file `checks-result`).

`tests/test_stop_hook.py`:

- clean tree → exit 0, checks not run;
- dirty tree, checks pass → exit 0, stamp written;
- same dirty state again → exit 0, checks not run (cache hit);
- further edit after a pass → checks run again;
- an untracked file changes the key;
- checks fail → exit 2, output tail on stderr;
- checks fail with `stop_hook_active` → exit 0;
- `checks.sh` missing → exit 0 with a note;
- non-object payload → handled.

`tests/test_doctor.py`: a healthy install passes (`--fast`, `gh` stubbed via a
fake `gh` on `PATH`); then one seeded violation per check: bad config alias,
agent with `model`, a non-executable `bin/doctor`, missing gitignore entry,
missing Stop hook entry, `CLAUDE.md` without `@AGENTS.md`, a missing label,
`gh` missing (WARN, exit 0), failing `checks.sh` without `--fast`.

## Out of scope

- Changing upstream `INSTALL.md`.
- Hooks other than Stop; pre-commit hooks.
- Upgrading projects installed before this change (re-run `/factory-install`'s
  new steps by hand, or run `factory/bin/doctor` to see what's missing).
