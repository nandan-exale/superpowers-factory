# Repo agent harness — Design

Date: 2026-11-12
Status: approved design. First of two harness specs; the second covers what
`/factory-install` sets up in target projects.

## Goal

An agent working on superpowers-factory learns the repo's rules from one file,
checks its work with one command, and cannot end a session that left the
checks failing. CI runs the same command.

## Decisions

| Question | Decision |
|---|---|
| Approach | One stdlib Python script, `scripts/check`, holds every rule. CI and the Stop hook only call it. No new dependencies. |
| Instructions file | `AGENTS.md` is the source; `CLAUDE.md` is the single line `@AGENTS.md`. |
| Hook | Stop hook, blocks only when the working tree has changes and a check fails. |

## Components

### AGENTS.md

- **Map:** `skills/` (plugin skills), `vendor/factory/` (vendored factory with
  edits), `tests/`, `scripts/`, `docs/superpowers/specs` and `plans`.
- **Invariants:**
  - `factory/bin/job` is the only writer of `job.json`.
  - Factory code and repo scripts are stdlib only.
  - No agent or skill frontmatter sets `model`; models and effort come from
    `factory/config.json`.
  - Keep `LICENSE` and `vendor/factory/NOTICE`. `NOTICE` says every commit
    after the unmodified import is a modification, so vendored edits need no
    `NOTICE` change, but they go in their own commits.
  - No upstream branding.
  - Superpowers core is never modified.
- **Workflow:** run `scripts/check` before claiming work is done; features go
  through Superpowers brainstorming → writing-plans; don't commit or push
  unless asked.

### scripts/check

Stdlib Python 3.11, executable, run from anywhere (it resolves the repo root
from its own path). Takes `--root <dir>` (default: the repo root) so tests can
point it at a copy, `--fast` to skip the unit tests, and
`--extra-forbidden-hash <sha256>` (repeatable, for tests) to add to the
branding set.

Each check prints `PASS <name>` or `FAIL <name>: <reason>`, one reason line
per problem. Exit 0 if all pass, 1 otherwise.

| Check | Rule |
|---|---|
| `tests` | `python3 -m unittest discover -s tests` exits 0. Skipped with `--fast`. |
| `compile` | `vendor/factory/factory/bin/{job,gate,route}` compile (`compile()` on the source, no `.pyc` written); `bash -n vendor/factory/factory/checks.sh` exits 0. |
| `json` | `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `vendor/factory/factory/config.json` parse. |
| `config` | Every `{model, effort}` in `agents`, `routing.<risk>` and `surface_reviewers` has a `model` listed in `model_aliases` and an `effort` listed in `effort_levels`. |
| `frontmatter` | Every `skills/*/SKILL.md`, `vendor/factory/.claude/skills/*/SKILL.md` and `vendor/factory/.claude/agents/*.md` starts with a `---` block that has non-empty `name` and `description` and no `model` key. Parsed line by line (top-level `key:` lines), no YAML library. |
| `license` | `LICENSE` and `vendor/factory/NOTICE` exist and are non-empty. |
| `branding` | No tracked file (`git ls-files`) contains a forbidden token. Files are split into lowercase `[a-z0-9]+` tokens; a token is forbidden if its SHA-256 is in a set stored in the script, so the script itself names nothing. |

### CI — .github/workflows/check.yml

On `push` to `main` and on `pull_request`: checkout, `actions/setup-python`
with 3.11, `git config` a test identity (the tests create commits), run
`scripts/check`.

### Hook — .claude/settings.json + scripts/check-hook

`.claude/settings.json` registers one Stop hook:
`"$CLAUDE_PROJECT_DIR"/scripts/check-hook`.

`scripts/check-hook` (stdlib Python) reads the hook JSON from stdin, then:

1. If `git status --porcelain` is empty, exits 0.
2. Runs `scripts/check`. If it passes, exits 0.
3. On failure, writes the `FAIL` lines to stderr. Exits 2 (blocks the stop) unless
   `stop_hook_active` is true, in which case it exits 0 so it can't loop; the
   agent has already seen the failures once.

## Error handling

| Where | Failure | Outcome |
|---|---|---|
| `scripts/check` | a check raises (missing file, bad UTF-8) | That check reports `FAIL` with the error; the others still run. |
| `check-hook` | `git` missing or not a repo | Exits 0 with a stderr note; the hook never blocks on its own breakage. |
| CI | any `FAIL` | Job fails; the log shows each `FAIL` line. |

## Testing

`tests/test_check.py`, stdlib `unittest`. Each test copies the tracked files
into a temporary git repo, seeds one violation, runs `scripts/check --fast
--root <tmp>`, and asserts exit 1 plus the expected `FAIL <name>` line:

- the clean copy passes;
- an agent with `model:` in its frontmatter;
- a skill missing `description`;
- `config.json` that doesn't parse;
- a routing entry with an unknown alias, and one with an unknown effort;
- a forbidden token in a tracked file: the test seeds the fixture word
  `harnessprobe` and passes its SHA-256 with `--extra-forbidden-hash`, so the
  test exercises the real matching code without naming a real forbidden word;
- `NOTICE` deleted;
- a syntax error in `bin/route`.

`check-hook` tests: clean tree → 0; failing check → 2; failing check with
`stop_hook_active: true` → 0.

## Out of scope

- The harness `/factory-install` puts in target projects (next spec).
- Pre-commit hooks, linters or formatters.
