# Auto setup and handoff — Design

Date: 2026-11-12
Status: approved design. Spec 3 of 4 toward a hands-off factory (after
budgets and evidence, hands-off running; then the learning loop).

## Goal

With the plugin enabled, opening a Claude Code session in any GitHub project
is enough: Claude offers to install the factory where it's missing, offers to
update it where it's stale, and, where it's current, offers the factory as a
third way to execute a finished plan. Nothing changes without the user's yes.

## Findings

- Superpowers injects its bootstrap through a plugin `SessionStart` hook
  (`hooks/hooks.json`, `additionalContext`). This plugin can do the same
  without changing Superpowers core.
- `superpowers:writing-plans` ends with a fixed two-option execution choice.
  A third option can only come from session context.
- `/factory-install` refuses to overwrite existing files, so installed
  projects can't pick up fixes. "Outdated" needs an update path.

## Decisions

| Question | Decision |
|---|---|
| Setup | Detect at session start and offer; never install or update unasked. |
| Handoff | In factory projects, the execution choice gains option 3: the factory. |
| Staleness | Exact: a hash over the plugin's vendored files vs. the one recorded at install. |

## Components

### Vendored file set

The files `/factory-install` copies from `vendor/factory/` (one list, defined
once in `bin/factory_files.py` and imported by every plugin script):
`.claude/skills/factory/SKILL.md`, the 8 `.claude/agents/*.md`,
`factory/config.json`, `factory/checks.sh`, `factory/bin/{job,gate,route,stop-hook,doctor,runner}`,
`factory/runner-settings.json`, `factory/dashboard.html`.

`vendor_hash` = SHA-256 over, for each path in sorted order, the path, a NUL,
and the file's bytes.

### factory/manifest.json (in the project, committed)

```json
{"vendor_hash": "<hex>", "files": {"factory/bin/job": "<sha256 of the copy as installed>", "...": "..."}}
```

Written by the plugin script `bin/factory-manifest <project>` from the
plugin's vendored files (not the project's possibly adapted copies), so each
entry is the pristine content the project started from.

### Plugin SessionStart hook

`hooks/hooks.json` registers `hooks/factory-session` (stdlib Python, run with
`python3`) for `SessionStart` with matcher `startup|clear|compact`. It reads
the hook JSON on stdin, uses `CLAUDE_PROJECT_DIR` (else cwd), and prints
`{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "<text>"}}`
or nothing. It never writes files and finishes in well under a second (file
reads and ~20 hashes). Any internal error prints nothing and exits 0.

States, first match wins:

1. Not a git work tree, or `origin` isn't a GitHub URL → nothing.
2. `factory/bin/job` missing:
   - `<git dir>/factory-declined` exists → nothing.
   - else → context: the factory isn't installed here; once, early in the
     session (not if already asked), ask whether to run `/factory-install`;
     if the user declines, run `"<plugin root>/bin/factory-state" decline`,
     which stops future offers in this clone.
3. Installed, and `factory/manifest.json` missing or its `vendor_hash` differs
   from the plugin's → context: the installed factory is older than the
   plugin; once per session offer `/factory-update`.
4. Installed and current → context: in this project, when
   `superpowers:writing-plans` offers its execution choice, add
   **"3. Factory — file this plan as a `factory:planned` issue and let the
   factory build it unattended (`/factory-handoff`)"**; if chosen, invoke
   `factory-handoff`. `factory/bin/doctor` checks the install.

States 3 and 4 both include the option-3 text (an outdated factory still
builds).

### bin/factory-state (plugin)

`factory-state decline` writes `<git dir>/factory-declined` (in the git dir,
so it never shows in the tree); `factory-state reset` removes it.

### /factory-install changes

After copying the vendored files and before adapting them, run
`"<plugin root>/bin/factory-manifest" .`. The manifest is part of the
install diff. Add `factory/manifest.json` to doctor's `files` check.

### /factory-update (new skill) and bin/factory-update-plan

`bin/factory-update-plan <project> [--apply-safe]` prints one line per
vendored file, `<group>\t<path>`, then applies when asked. Groups:

| Group | Condition | `--apply-safe` |
|---|---|---|
| `new` | missing in the project | copy in |
| `unchanged` | vendored hash == manifest hash | nothing |
| `safe` | vendored changed, project copy == manifest hash | replace |
| `merge` | vendored changed and project copy differs from manifest | nothing (skill handles) |
| `owned` | `factory/checks.sh` | never touched |
| `config` | `factory/config.json` | add keys missing in the project, recursively; never change existing values |
| `settings` | `factory/runner-settings.json` | take the vendored file, keeping the union of both `sandbox.network.allowedDomains` lists |

With no manifest, every existing file whose content differs from the
vendored copy is `merge`. After `--apply-safe` it rewrites the manifest from
the plugin's vendored files and preserves executable bits on `factory/bin/*`.

The `factory-update` skill: run the plan, show it, run `--apply-safe` on the
user's yes; for each `merge` file show the project's diff against the new
vendored version and ask keep / take upstream / merge by hand (Claude edits);
run `factory/bin/doctor --fast`; show `git status` and `git diff`; never commit.

## Error handling

| Where | Failure | Outcome |
|---|---|---|
| hook | any exception, git missing | prints nothing, exit 0 |
| hook | manifest unreadable | treated as outdated |
| update-plan | project not a factory install | exits 1, "run /factory-install first" |
| update-plan | config.json invalid JSON | exits 1 naming the file; nothing applied |

## Testing

Stdlib `unittest`, temporary git repos:

- `tests/test_factory_session.py`: not git → no output; non-GitHub origin →
  no output; not installed → install offer; declined → no output; no
  manifest → update offer + option 3; stale hash → update offer; current →
  option 3 only; output is valid hook JSON; a crash path (unreadable
  manifest dir) → no traceback, exit 0.
- `tests/test_factory_update.py`: each group; `--apply-safe` results;
  config merge keeps user values and adds new keys; settings keeps added
  domains; manifest rewritten and then `unchanged` everywhere; exec bits kept;
  no-manifest install → differing files are `merge`.
- `tests/test_factory_manifest.py`: deterministic `vendor_hash`; manifest
  entries equal the vendored files' hashes.

## Out of scope

- Auto-committing installs or updates.
- Changing Superpowers' skills.
- Spec 4.
