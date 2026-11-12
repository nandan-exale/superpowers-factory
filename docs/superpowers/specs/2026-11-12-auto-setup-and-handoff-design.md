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
{"vendor_hash": "<hex>", "files": {"factory/bin/job": "<sha256 of the copy as installed>", "...": "..."},
 "settings_core": "<hex>", "settings_domains": ["<allowedDomains as vendored>"]}
```

`settings_core` is the SHA-256 of the canonical JSON (sorted keys) of the
vendored `factory/runner-settings.json` with `sandbox.network.allowedDomains`
removed: the part of that file a project isn't expected to change.
`settings_domains` is the vendored `allowedDomains` list, so a later update
can tell upstream's domains from the ones the project added.

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

0. `FACTORY_RUNNER` is set (the runner marks its unattended `claude -p`
   sessions) → nothing.
1. Not a git work tree, or the host of `origin` isn't `github.com`
   (`https://`, `ssh://` and `git@host:path` forms; case-insensitive; a
   look-alike such as `notgithub.com` doesn't count) → nothing.
2. `factory/bin/job` missing:
   - `<git common dir>/factory-declined` exists → nothing.
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

`factory-state decline` writes `<git common dir>/factory-declined` (in the
git dir, so it never shows in the tree; the common dir, so every linked
worktree of a clone shares one decision); `factory-state reset` removes it.

### /factory-install changes

After copying the vendored files and before adapting them, run
`"<plugin root>/bin/factory-manifest" .`. The manifest is part of the
install diff. Add `factory/manifest.json` to doctor's `files` check.

### /factory-update (new skill) and bin/factory-update-plan

`bin/factory-update-plan <project> [--apply-safe | --resolved <path>]` prints one line per
vendored file, `<group>\t<path>`, then applies when asked. Groups:

| Group | Condition | `--apply-safe` |
|---|---|---|
| `new` | missing in the project | copy in |
| `unchanged` | project copy == vendored copy, or vendored hash == manifest hash | nothing |
| `safe` | vendored changed, project copy == manifest hash | replace |
| `merge` | vendored changed and project copy differs from manifest | nothing (skill handles) |
| `owned` | `factory/checks.sh` | never touched |
| `config` | `factory/config.json` | add keys missing in the project, recursively; never change existing values |
| `settings` | `factory/runner-settings.json`, when everything but `allowedDomains` equals the manifest's `settings_core` (or the vendored file's), or the project customized it, upstream's core is as installed, and the domain list would change | take the vendored file (or, for a customized one, the project's own with only the domains replaced); `allowedDomains` becomes upstream's list followed by the project's extras (its domains not in the manifest's `settings_domains`, or upstream's when absent) |

`factory/runner-settings.json` the project changed beyond domains is `merge`
when upstream changed it too, `unchanged` when upstream didn't and no domain
changes (the customization is kept; a domain upstream added or removed still
flows in, as `settings`), and `merge` when there's no manifest to tell.
Malformed `sandbox`, `network` or `allowedDomains` shapes on either side make
the script exit 1 naming the file, applying nothing.

With no manifest, every existing file whose content differs from the
vendored copy is `merge`. After `--apply-safe` it rewrites the manifest from
the plugin's vendored files and preserves executable bits on `factory/bin/*`.
A `merge` file keeps its old manifest entry (none if it had none), and while
any `merge` remains the manifest keeps its old `vendor_hash` (`"pending"` if
there was none), so the next session still offers the update.

Upstream's own domains always follow upstream (a domain upstream lists that
the project removed comes back); only domains the project added are
preserved.

`--resolved <path>` refuses (exit 1) when the manifest already records the
plugin's current version of the file (nothing pending), or when the file is
`new` or `safe` (an unapplied update that recording would drop); it works
after the user took upstream's version. For the settings file it first
rewrites `allowedDomains` against the old manifest base. It records the plugin's current hash for a file the user has settled (and
`settings_core` and `settings_domains` for the settings file); once no `merge` row
remains it sets `vendor_hash` to the current one. JSON is written as UTF-8
without `\u` escapes.

The `factory-update` skill: run the plan, show it, run `--apply-safe` on the
user's yes; for each `merge` file show the project's diff against the new
vendored version and ask keep / take upstream / merge by hand (Claude edits),
then run `--resolved <path>` (all three answers count as resolved); run `factory/bin/doctor --fast`; show `git status` and `git diff`; never commit.

## Error handling

| Where | Failure | Outcome |
|---|---|---|
| hook | any exception, git missing | prints nothing, exit 0 |
| hook | manifest unreadable | treated as outdated |
| update-plan | project not a factory install | exits 1, "run /factory-install first" |
| update-plan | config.json invalid JSON | exits 1 naming the file; nothing applied |

## Testing

Stdlib `unittest`, temporary git repos:

- `tests/test_factory_session.py`: not git → no output; non-GitHub origin
  (including look-alike hosts) → no output; ssh and scp-style GitHub URLs
  offer; `FACTORY_RUNNER` set → no output; a decline in one worktree silences
  its linked worktrees; not installed → install offer; declined → no output; no
  manifest → update offer + option 3; stale hash → update offer; current →
  option 3 only; output is valid hook JSON; a crash path (unreadable
  manifest dir) → no traceback, exit 0.
- `tests/test_factory_update.py`: each group; `--apply-safe` results;
  config merge keeps user values and adds new keys; settings keeps added
  domains; manifest rewritten and then `unchanged` everywhere; exec bits kept;
  no-manifest install → differing files are `merge`; pending merges survive
  `--apply-safe` and the update is still offered until `--resolved`; settings
  customizations; malformed settings shapes; non-ASCII round trip.
- `tests/test_factory_manifest.py`: deterministic `vendor_hash`; manifest
  entries equal the vendored files' hashes.

## Out of scope

- Auto-committing installs or updates.
- Changing Superpowers' skills.
- Spec 4.
