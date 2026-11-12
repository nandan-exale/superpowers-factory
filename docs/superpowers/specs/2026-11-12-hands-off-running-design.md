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
2. **Preflight:** current branch must be `config.base_branch` and
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
   `CLAUDE_CODE_OAUTH_TOKEN`. Timeout `runner.max_minutes` → kill the group,
   log `timeout`, exit 1.
7. **Record:** the JSON output goes to `factory/jobs/runs/<UTC time>.json`;
   one line goes to `factory/jobs/runner.log`:
   `<time> ran exit=<code> <seconds>s cost=$<total_cost_usd or ?>`.

Every tick appends exactly one line to `runner.log`, starting with the UTC
time and one of `busy`, `skipped`, `idle`, `ran`, `timeout`, `error`.

**`runner install [--dry-run]`** — writes
`~/Library/LaunchAgents/com.superpowers-factory.<repo-slug>.plist`
(`<repo-slug>`: the checkout's absolute path with non-alphanumerics replaced
by `-`, lowercase) with `ProgramArguments` = `[<python3 path>, <REPO>/factory/bin/runner, tick]`,
`WorkingDirectory` = `REPO`, `StartInterval` = `runner.interval_minutes * 60`,
`RunAtLoad` true, `StandardOutPath`/`StandardErrorPath` =
`factory/jobs/runner.launchd.log`, and `EnvironmentVariables.PATH` set to the
installing shell's `PATH` (so `git`, `gh`, `claude` resolve). Then
`launchctl bootstrap gui/<uid> <plist>` (after `bootout` if already loaded).
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

### Settings merged by /factory-install

Into `.claude/settings.json`, keeping everything already there:

- sandbox enabled for Bash, with sandboxed commands auto-allowed, filesystem
  writes limited to the project directory, and network allowed only to
  `github.com`, `api.github.com`, `*.githubusercontent.com` and the package
  hosts the project's stack needs (the install agent derives them from the
  lockfiles and `checks.sh`, and lists them for the user);
- `permissions.allow`: `Bash(factory/bin/job:*)`, `Bash(factory/bin/gate:*)`,
  `Bash(factory/bin/route:*)`, `Bash(git:*)`, `Bash(gh:*)`, `Bash(bash factory/checks.sh)`;
- `permissions.deny` for `.env*`, `secrets/**` reads, and `git push --force*`.

The exact key names are verified against the current Claude Code settings
documentation during planning; the plan quotes the source. If the installed
Claude Code has no sandbox for this platform, the install says so and
installs the allowlist only.

### doctor (new check `runner`)

- FAIL if `.claude/settings.json` lacks the sandbox block or any of the
  allow rules above.
- WARN if `security find-generic-password -s <service>` (no `-w`; the secret
  is never read) exits non-zero.
- WARN if the LaunchAgent is not loaded (only on macOS; skipped elsewhere).

### Install skill and docs

`/factory-install` gains a "Hands-off running" step: merge the settings
above; tell the user to (1) make a dedicated clone for the runner, (2) run
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

## Out of scope

- Linux/cron/systemd hosts; cloud runners.
- Notifications beyond GitHub's own (labels, comments, PRs).
- Specs 3–4.
