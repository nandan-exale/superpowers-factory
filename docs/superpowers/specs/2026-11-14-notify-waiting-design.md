# Notify when a job waits on a human — Design

Date: 2026-11-14
Status: approved design, ready for a plan.

## Goal

When a job moves to `needs-human` or `needs-info`, the factory posts a
comment and adds a label, both from the operator's own `gh` account. GitHub
sends no notification for your own comments, so nothing tells the operator a
job is waiting. In the factory's last 13 jobs, escalations waited 1 to 350
minutes (about 650 in total), and part jobs waited on each other's merges.

This adds an optional command the factory runs whenever a job starts waiting
on a human, so the operator can be told by desktop notification, phone push,
chat, or anything a command can do.

## Decisions

| Question | Decision |
|---|---|
| Channel | A command the operator configures. Nothing built in; off until set. |
| Which states | Both waiting states: `needs-human` (every route into it) and `needs-info`. |
| Interface | An argv list, run without a shell. The job's details arrive as environment variables, so untrusted issue text never becomes shell code. |
| Failure | Never blocks the factory: a `NOTE:` line, and the job still moves. |
| Install | `/factory-install` is unchanged. The README documents the key with examples. |

## Config

`factory/config.json`, absent by default:

```json
"notify": {"command": ["/path/to/program", "arg", "..."]}
```

`command` is a non-empty list of strings. With no `notify` key, or no
`command` in it, the factory behaves exactly as today.

## Behaviour (vendored `factory/bin/job`)

### When it runs

Once per move into a waiting state, after the existing comment and label:

- **needs-human**: inside `notify_needs_human(job)`, which every route already
  calls: the approver's escalation (`approve → needs-human` in the advance
  path), budget stops, and `stop_for_human` (which `job escalate` uses when
  the orchestrator gives up on an agent).
- **needs-info**: in the `intake → needs-info` branch of the advance path,
  after the intake comment and the `needs_info` label.

### What it runs

`notify_waiting(job, stage)`:

1. Reads `notify.command` from the config. Returns at once when it's absent.
2. Builds the environment: the factory's own environment minus the credential
   variables (the same `runtimes.credential_vars(CONFIG)` list the gate
   removes), plus:

   | Variable | Value |
   |---|---|
   | `FACTORY_NOTIFY_TITLE` | `Factory: #<issue> needs you` |
   | `FACTORY_NOTIFY_MESSAGE` | `<stage>: <issue title>`, a blank line, then the first 5 non-empty lines of the reason section, each cut to 200 characters |
   | `FACTORY_NOTIFY_URL` | the PR's URL when the job has one, else the issue's |
   | `FACTORY_NOTIFY_STAGE` | `needs-human` or `needs-info` |
   | `FACTORY_NOTIFY_JOB` | the job id |

   The reason section is the one `WAITING_REASON` already names:
   `decision.md`'s `## Why` for needs-human, `intake.md`'s `## Questions` for
   needs-info. When the file or section is missing, the message is the first
   line alone.
3. Runs the command with `subprocess.run(command, env=env, timeout=30,
   capture_output=True, stdin=DEVNULL)`, without a shell, from the repo root.

### Failures

The factory prints `NOTE: notify: <reason>` and carries on, whatever happens:

- the program is missing or can't be started (`OSError`): the reason is
  `can't run <program>: <error>`;
- the command exits non-zero: `<program> exited <code>`, plus the last line
  of its stderr when there is one;
- the command runs past 30 seconds: `<program> timed out after 30s`.

The job's move to its waiting state is never refused or undone because of a
notification.

## Doctor (vendored `factory/bin/doctor`)

When `notify` is present:

- FAIL if it isn't an object, or `notify.command` isn't a non-empty list of
  strings.
- WARN if `notify.command[0]` is neither an executable path nor found by
  `shutil.which`.

## Docs

`README.md`'s config table gets a `notify` row, and a short section shows two
commands:

- a macOS desktop notification, reading the variables in AppleScript:
  `["osascript", "-e", "display notification (system attribute \"FACTORY_NOTIFY_MESSAGE\") with title (system attribute \"FACTORY_NOTIFY_TITLE\")"]`
- a phone push through ntfy.sh, with a small script that `curl`s the title,
  message and URL to a topic.

The section says the command runs wherever the factory runs: a desktop
notification works for an interactive session or the macOS runner, not on
GitHub Actions.

## Security

- `factory/config.json` is a protected path: agents can't edit it
  (`protected_paths` and runner-settings' deny rules), so they can't choose the
  command.
- The command runs without a shell, and the job's details reach it only as
  environment variable values.
- Credential variables are removed from its environment.

## Out of scope

- A notification offer in `/factory-install`.
- Notifications for other events: merges, watch reverts, the daily digest.
- Retrying a failed notification.

## Testing (stdlib `unittest`, `tests/factory_project.py`)

- `notify_waiting` sets the five variables as above. needs-human runs the
  command once through `notify_needs_human`, which the approver path, budget
  stops and `stop_for_human` all call; the test drives it with
  `stop_for_human`.
- needs-info runs it once, with `FACTORY_NOTIFY_STAGE=needs-info` and the
  intake questions in the message.
- The command's environment has no credential variable even when the
  factory's own environment has one.
- A missing program, a non-zero exit and a command that runs past the timeout
  (patched short) each print one `NOTE: notify:` line, and the job still
  reaches its waiting state.
- With no `notify` key, no command runs.
- `doctor`: FAIL for a non-list, an empty list and a list with a non-string;
  WARN for a program that isn't found; nothing for a valid command.
