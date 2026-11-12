# Hands-off running — Design

Date: 2026-11-12
Status: approved design. Spec 2 of 4 toward a hands-off factory (after
budgets and evidence; then auto setup + handoff, learning loop).

## Goal

Once a project has the factory installed and the runner enabled, new and
resumable `factory` issues get built without anyone typing `/factory run`,
without permission prompts, and without ever skipping permissions.

## Findings that shape the design

- Headless `claude -p` failed in the agent shell with "Invalid API key":
  `ANTHROPIC_API_KEY` and `ANTHROPIC_BASE_URL` are set there and override the
  user's login. The supported headless credential is a long-lived token from
  `claude setup-token`, passed as `CLAUDE_CODE_OAUTH_TOKEN`.
- Job state (`factory/jobs/`, `.worktrees/`) is local and gitignored, so the
  runner must run where that checkout persists. Cloud runners would lose it.
- Unattended agents must run project commands (tests, builds) that no static
  allowlist can foresee.

## Decisions

| Question | Decision |
|---|---|
| Host | This Mac, via a launchd LaunchAgent. |
| Permissions | Claude Code's sandbox (writes confined to the project, network limited to listed hosts) so sandboxed commands run without prompts, plus allow rules for `factory/bin/*`, `git`, `gh`. Everything else is denied, never prompted. Never `--dangerously-skip-permissions`. |
| Credential | `claude setup-token`, stored by the user in the macOS Keychain; read by the runner at run time only. |
| Checkout | A dedicated clone for the runner is recommended; the runner refuses to work in a checkout that isn't clean and on the base branch. |

## Components

### factory/bin/runner (new, vendored, stdlib Python)

`REPO` is two levels above the script, as in `gate`. Subcommands:

**`runner tick`** — one scheduled run:

1. **Lock:** `fcntl.flock(LOCK_EX | LOCK_NB)` on `<git dir>/factory-runner.lock`. Held → log `busy`, exit 0.
2. **Preflight:** if `.git/hooks` holds an executable non-sample file, or
   `core.hooksPath` or `core.fsmonitor` is set in the clone's local config,
   log `error: git hooks or fsmonitor configured in this clone; remove them`
   and exit 1 (sandboxed Bash can write `.git`, and a hook would run outside
   the sandbox). Every git command the runner runs passes
   `-c core.hooksPath=/dev/null -c core.fsmonitor=false` and runs with
   `GIT_TERMINAL_PROMPT=0` and `GIT_SSH_COMMAND="ssh -o BatchMode=yes"`.
   Then the current branch must be `config.base_branch` and
   `git status --porcelain` empty (gitignored job state doesn't count).
   Otherwise log `skipped: <reason>`, exit 0. The runner never stashes,
   resets or checks out anything.
3. **Update:** `git pull --ff-only origin <base>`. Failure → log
   `skipped: pull failed: <stderr first line>`, exit 0.
4. **Idle check:** run `factory/bin/job queue`. If no row's action is
   `resume` or `new`, log `idle`, exit 0 (no model spend). Daily-budget
   `wait` rows count as idle. A failing `job queue` → log `error: queue: …`,
   exit 1.
5. **Token:** `security find-generic-password -s <runner.keychain_service> -w`.
   Missing → log `error: no token in Keychain item <service>; run claude
   setup-token and store it` and exit 1. The token is passed only through the
   child's environment; it never appears in argv, files or logs.
6. **Run:** `claude -p "/factory run" --output-format json` in `REPO`, in its
   own process group, with environment = the runner's environment minus
   `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, plus
   `CLAUDE_CODE_OAUTH_TOKEN` and `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` (Claude
   Code then strips credentials from the environment of the Bash commands,
   hooks and MCP servers it starts; the variable exists in the installed
   binary). claude's stdout and stderr go to files, not pipes, so a process
   that outlives claude with them open can't hold the tick; the runner waits
   with `runner.max_minutes` as the timeout, then kills the whole group and
   logs `timeout` (exit 1). A `claude` that can't be started logs `error:
   claude not found on PATH` (exit 1). On SIGTERM (launchd unloading the
   agent) the runner kills the group, logs `stopped` and exits 1.
7. **Record:** claude's output goes to `factory/jobs/runs/<UTC time>.json` and
   `<UTC time>.stderr.log`; only the newest 50 runs (pairs) are kept. One line
   goes to `factory/jobs/runner.log`:
   `<time> ran exit=<code> <seconds>s cost=$<total_cost_usd or ?>`.

Every tick appends exactly one line to `runner.log`, starting with the UTC
time and one of `busy`, `skipped`, `idle`, `ran`, `timeout`, `stopped`,
`error`. An invalid `runner` config during `tick` logs `error: config: <what
is wrong>` and exits 1; the other subcommands print it to stderr and exit 1.

**`runner install [--dry-run]`** — writes
`~/Library/LaunchAgents/com.superpowers-factory.<repo-slug>-<hash>.plist`
(`<repo-slug>`: the checkout's absolute path with non-alphanumerics replaced
by `-`, lowercase; `<hash>`: the first 8 hex digits of the SHA-256 of that
path, so two paths with the same slug don't collide; `doctor` carries a copy
of the label function and a test keeps the two equal) with `ProgramArguments` = `[<python3 path>, <REPO>/factory/bin/runner, tick]`,
`WorkingDirectory` = `REPO`, `StartInterval` = `runner.interval_minutes * 60`,
`RunAtLoad` true, `StandardOutPath`/`StandardErrorPath` =
`factory/jobs/runner.launchd.log`, and `EnvironmentVariables.PATH` set to the
installing shell's `PATH` (so `git`, `gh`, `claude` resolve). Then
`launchctl bootstrap gui/<uid> <plist>`: after `bootout` it polls `launchctl
print` until the old agent is gone (up to 3 s), then bootstraps, retrying up
to 3 times.
`--dry-run` prints the plist and changes nothing.

**`runner uninstall`** — `launchctl bootout`, delete the plist.

**`runner status`** — loaded or not (`launchctl print gui/<uid>/<label>`
exit code), the plist path, and the last 10 lines of `runner.log`.

Non-macOS: `install`/`uninstall`/`status` exit 1 with "launchd only";
`tick` works anywhere.

### Config

`factory/config.json` gains:

```json
"runner": { "interval_minutes": 15, "max_minutes": 120, "keychain_service": "factory-claude-token" }
```

Positive integers and a non-empty string; `runner` validates them and exits 1
naming the bad key.

### Runner settings (factory/runner-settings.json)

Vendored and passed with `--settings`, not merged into the project's
`.claude/settings.json`: interactive sessions stay unsandboxed, and
`sandbox.network.strictAllowlist` (ignored in project settings) applies.
Contents: sandbox enabled, `autoAllowBashIfSandboxed: true`,
`allowUnsandboxedCommands: false`, network `allowedDomains` GitHub hosts plus
the project's package hosts (the install agent adds them),
`allowLocalBinding: true` (dev servers bind to localhost; the key exists in the
installed binary), `strictAllowlist: true`; `permissions.allow` for `Edit`,
`Write` and `Bash(...)` rules for `factory/bin/job`, `gate`, `route`, `git`,
`gh`, `bash factory/checks.sh`.

`permissions.deny`:

- reads of `.env`, `.env.*`, `secrets/**`, `~/.ssh/**`, `~/.aws/**`;
- `Edit` and `Write` of `./.git/**`, `./factory/bin/**`,
  `./factory/runner-settings.json`, `./factory/config.json`,
  `./factory/checks.sh`, `./.claude/**`, and of `~/.ssh/**`, `~/.claude/**`,
  `~/Library/LaunchAgents/**`. (A blanket `~/**` deny would also match the
  project when it lives under the home directory, so the home paths that
  matter are listed instead; the sandbox already limits writes to the
  project.) Sandboxed Bash can still write inside the repo, which is why the
  runner also disables hooks and fsmonitor and refuses a clone that has them;
- destructive git and gh: force pushes in every spelling (`--force`, `-f`,
  `+refspec`, `--force-with-lease`), `gh repo delete`, `gh repo edit`, and
  `gh api` with `DELETE`. These are speed bumps, not a boundary: the
  boundary is branch protection on the base branch (see doctor).

The runner passes `--permission-mode dontAsk`, so anything else is denied.
Verified against code.claude.com/docs (sandboxing, permissions,
permission-modes, headless, authentication), 2026-11.

Changes to `factory/bin/runner`, `factory/runner-settings.json` and the rest
of the factory only take effect through the base branch: the runner requires a
clean tree on the base branch and pulls, so such a change arrives only by a
merged PR, which the approver and the human review.

### Token-free checks

`factory/checks.sh` runs project code, so `gate`, `stop-hook` and `doctor`
run it with `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_API_KEY`,
`ANTHROPIC_AUTH_TOKEN` and `ANTHROPIC_BASE_URL` removed from its environment.
This is independent of `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB`.

### doctor (new check `runner`)

- FAIL if `factory/runner-settings.json` is missing, has the sandbox off or
  `allowUnsandboxedCommands` not false, or lacks any of the Bash allow rules
  above.
- WARN if the base branch has no protection against force pushes and
  deletion: `gh api repos/{owner}/{repo}/branches/<base>/protection` fails with
  404 or reports `allow_force_pushes` or `allow_deletions` enabled ("base
  branch <b> has no protection against force-push/deletion; enable branch
  protection on GitHub"). If gh can't tell (403, network), WARN "could not
  read branch protection", never FAIL.
- WARN if `security find-generic-password -s <service>` (no `-w`; the secret
  is never read) exits non-zero.
- WARN if the LaunchAgent is not loaded (only on macOS; skipped elsewhere).

### Install skill and docs

`/factory-install` gains a "Hands-off running" step: add the project's
package hosts to the vendored runner settings; tell the user to (1) make a dedicated clone for the runner, (2) run
`claude setup-token` and `security add-generic-password -s
factory-claude-token -a "$USER" -w` themselves, (3) run
`factory/bin/runner install` in that clone. It never handles the token.
README gains a "Hands-off running" section with the same steps and
`factory/bin/runner status`.

## Error handling

| Where | Failure | Outcome |
|---|---|---|
| tick | another tick running | `busy`, exit 0 |
| tick | user's checkout dirty / not on base | `skipped`, nothing touched |
| tick | no token | `error`, exit 1; doctor WARNs |
| tick | claude exceeds max_minutes | group killed, `timeout` |
| tick | claude exits non-zero | `ran exit=N`, output kept in runs/ |
| install | not macOS | exit 1, "launchd only" |

## Testing

`tests/test_runner.py` on the `InstalledProject` helper, with fake `claude`,
`gh` and `security` scripts on `PATH` that record argv and environment:

- lock held → `busy`, no claude call;
- dirty tree, and wrong branch → `skipped`, tree untouched;
- idle queue → `idle`, no claude call; daily-budget waits count as idle;
- queued work → claude called with `-p "/factory run" --output-format json`,
  env has `CLAUDE_CODE_OAUTH_TOKEN` and lacks `ANTHROPIC_API_KEY`; token not in
  runner.log or argv; output saved under runs/; log line has exit and cost;
- missing Keychain item → `error`, exit 1;
- timeout (max_minutes overridden small via an env var for tests) → group
  killed, `timeout`;
- `install --dry-run` plist content (label, interval, args, PATH, log paths);
- invalid `runner` config → exit 1 naming the key.

`tests/test_doctor.py`: missing sandbox/allow rules FAIL; missing Keychain
item WARN (fake `security`).

## Residual risks

- Tests and hooks the agent runs through `bash factory/checks.sh` or project
  scripts are not sandboxed. The token is removed from their environment, but
  they keep network and disk access as the user.
- The allowed `gh` and `git` can still post to GitHub (comments, issues,
  pushes to other branches, PRs). Branch protection on the base branch is the
  backstop for the branch that matters.
- A change to `factory/bin/runner`, `factory/runner-settings.json` or the
  checks, merged by a human, takes effect on the next tick.
- The LaunchAgent records the `python3` and `PATH` it was installed with;
  reinstall (`runner install`) if either changes.

## Out of scope

- Linux/cron/systemd hosts; cloud runners.
- Notifications beyond GitHub's own (labels, comments, PRs).
- Specs 3–4.
