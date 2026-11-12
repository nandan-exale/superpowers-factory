---
name: factory-install
description: Use when the user wants to set up the software factory (with Superpowers handoff support) in the current project. Copies the vendored factory from this plugin and adapts it to the project.
---

# Factory install

Install the factory from this plugin into the project in the current working
directory. The source is `vendor/factory/` two levels above this skill's base
directory (`<skill base>/../../vendor/factory`). Call it `$VENDOR`.

Announce: "I'm using factory-install to set up the software factory here."

## 0. Superpowers must be installed

Your available skills must include `superpowers:test-driven-development`,
`superpowers:systematic-debugging` and
`superpowers:verification-before-completion`. The factory's builder loads them
for planned jobs. If any is missing, tell your human partner to install
Superpowers and stop.

## 1. Follow the upstream installer, with these overrides

Read `$VENDOR/INSTALL.md` and follow it, with these changes:

- **Step 1 (Copy):** copy from `$VENDOR`, not from GitHub:

  ```bash
  for f in .claude/skills/factory/SKILL.md \
    .claude/agents/intake.md .claude/agents/spec-writer.md .claude/agents/builder.md \
    .claude/agents/reviewer-code.md .claude/agents/reviewer-security.md \
    .claude/agents/reviewer-ux.md .claude/agents/reviewer-ui.md .claude/agents/approver.md \
    factory/config.json factory/checks.sh factory/bin/job factory/bin/gate factory/bin/route \
    factory/bin/stop-hook factory/bin/doctor factory/dashboard.html
  do mkdir -p "$(dirname "$f")" && cp "$VENDOR/$f" "$f"; done
  chmod +x factory/checks.sh factory/bin/job factory/bin/gate factory/bin/route \
    factory/bin/stop-hook factory/bin/doctor
  ```

- **Step 2 (Adapt), labels:** also create the planned label:

  ```bash
  gh label create factory:planned --color 0E8A16 --description "Planned with Superpowers; the factory builds the plan as written"
  ```

- **Step 2 (Adapt), AGENTS.md:** add this paragraph to the Software factory
  section:

  ```markdown
  Issues labeled `factory:planned` were designed with Superpowers and filed
  with `/factory-handoff`. They skip intake and the spec writer: the factory
  copies the committed spec and plan, and the builder carries out the plan.
  ```

- **Step 2 (Adapt), CLAUDE.md:** if the project has `AGENTS.md` and no
  `CLAUDE.md`, create `CLAUDE.md` containing the single line `@AGENTS.md`.
  If it has both and `CLAUDE.md` has no `@AGENTS.md` line, append one. If it
  uses only `CLAUDE.md`, change nothing.

- **Step 2 (Adapt), Stop hook:** register `factory/bin/stop-hook` for
  interactive sessions. It runs `factory/checks.sh` when a session stops
  with changes that haven't passed yet, and blocks the stop once if they
  fail. Merge this into `.claude/settings.json`, creating the file if it
  doesn't exist. Keep every existing key and hook: append to an existing
  `hooks.Stop` list, never replace it. If the file exists but isn't valid
  JSON, stop and show your human partner instead of rewriting it.

  ```json
  {"hooks": {"Stop": [{"hooks": [{"type": "command",
    "command": "\"$CLAUDE_PROJECT_DIR\"/factory/bin/stop-hook", "timeout": 600}]}]}}
  ```

- **Step 2 (Adapt), CI:** if the project's existing CI already runs the
  commands in `factory/checks.sh` on pull requests, add nothing and say so.
  Otherwise create `.github/workflows/factory-checks.yml`: on
  `pull_request` and on `push` to the base branch, check out the code, run
  the toolchain setup steps copied from the project's existing workflows
  (or the stack's standard `actions/setup-*` action if it has none), then
  `bash factory/checks.sh`.

- **Step 3 (Verify):** instead of upstream's list, run `factory/bin/doctor`.
  It must exit 0. It checks the config, agent frontmatter (the builder's
  `tools` includes `Skill`, which is expected), files and permissions,
  `.gitignore`, the Stop hook, `CLAUDE.md`, the labels and
  `factory/checks.sh`. Report any `WARN` lines to your human partner.
- **Step 4 (Hand over):** don't commit. Show your human partner the diff
  (`git status` and `git diff`), suggest the message
  `chore: install software factory`, and let them commit and push.

## 2. Tell them how to use it

- Design with `superpowers:brainstorming`, plan with `superpowers:writing-plans`,
  then run `/factory-handoff` instead of executing the plan here.
- Start a fresh Claude Code session in this project before the first
  `/factory run`: the factory's agents (`builder`, `reviewer-code`, …) only
  load at session start, so this session can't spawn them.
- Ordinary `factory` issues still work as upstream, through intake.
- `factory/bin/doctor` checks the install at any time; `--fast` skips the
  project's checks.
