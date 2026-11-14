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
    factory/agents/intake.md factory/agents/spec-writer.md factory/agents/builder.md \
    factory/agents/reviewer-code.md factory/agents/reviewer-security.md \
    factory/agents/reviewer-ux.md factory/agents/reviewer-ui.md factory/agents/approver.md factory/agents/learner.md \
    factory/lib/runtimes/__init__.py factory/lib/runtimes/claude.py \
    factory/lib/orchestrator/__init__.py factory/lib/orchestrator/agents.py \
    factory/lib/orchestrator/jobcli.py factory/lib/orchestrator/prompts.py \
    factory/lib/orchestrator/readonly.py factory/lib/orchestrator/pipeline.py \
    factory/lib/orchestrator/loop.py factory/bin/orchestrate \
    factory/config.json factory/checks.sh factory/bin/job factory/bin/gate factory/bin/route \
    factory/bin/stop-hook factory/bin/doctor factory/bin/runner factory/runner-settings.json \
    factory/dashboard.html
  do mkdir -p "$(dirname "$f")" && cp "$VENDOR/$f" "$f"; done
  chmod +x factory/checks.sh factory/bin/job factory/bin/gate factory/bin/route \
    factory/bin/stop-hook factory/bin/doctor factory/bin/runner factory/bin/orchestrate
  ```

- **Step 1 (Copy), manifest:** right after copying, before adapting any file,
  run `"<skill base>/../../bin/factory-manifest" .`. It records each copied
  file's pristine hash in `factory/manifest.json` (commit it with the
  install), so `/factory-update` can tell your adaptations from upstream
  changes later.

- **Step 2 (Adapt), labels:** also create the planned, learning, digest,
  revert and risk-ok labels:

  ```bash
  gh label create factory:planned --color 0E8A16 --description "Planned with Superpowers; the factory builds the plan as written"
  gh label create factory:learning --color C5DEF5 --description "Factory-proposed check or rule; add 'factory' to build it"
  gh label create factory:digest --color 0E8A16 --description "Daily factory digest"
  gh label create factory:revert --color B60205 --description "Reverts a factory merge that broke the base branch"
  gh label create factory:risk-ok --color FBCA04 --description "A human reviewed this issue's risky changes; the factory may merge them"
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
  uses only `CLAUDE.md`, change nothing. If `CLAUDE.md` is a symlink to
  `AGENTS.md`, change nothing.

- **Step 2 (Adapt), Stop hook:** register `factory/bin/stop-hook` for
  interactive sessions. It runs `factory/checks.sh` when a session stops
  with changes that haven't passed yet, and blocks the stop once if they
  fail. Merge this into `.claude/settings.json`, creating the file if it
  doesn't exist. Keep every existing key and hook: append to an existing
  `hooks.Stop` list, never replace it. If the file exists but isn't valid
  JSON, stop and show your human partner instead of rewriting it. If a Stop
  hook already runs `factory/bin/stop-hook`, leave it; don't add a second.

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
  `bash factory/checks.sh`. If `.github/workflows/factory-checks.yml` already
  exists, show your human partner the difference and ask before changing it.

- **Step 2 (Adapt), hands-off running:** in `factory/runner-settings.json`,
  add the package hosts the project's checks need to
  `sandbox.network.allowedDomains` (for example `registry.npmjs.org`,
  `pypi.org` and `files.pythonhosted.org`), found from the lockfiles and
  `factory/checks.sh`. List them for your human partner. Don't loosen
  anything else in that file. Dev servers can bind to localhost
  (`allowLocalBinding` is already on), but a tool that needs a Unix socket,
  such as agent-browser, may not work inside the sandbox
  (`sandbox.network.allowUnixSockets` exists but isn't set); say so as a
  known limitation instead of widening it. The runner also needs branch
  protection on the base branch (no force pushes, no deletion): `doctor`
  warns when it's missing, so tell them to enable it on GitHub. Changes to
  `factory/bin/**` and `factory/runner-settings.json` take effect only
  through the base branch, after a merged PR; if Python or `PATH` changes,
  run `factory/bin/runner install` again. Then tell them the runner needs three steps
  they do themselves: (1) make a separate clone of the project for the
  runner, so it never works in the checkout they edit; (2) run
  `claude setup-token`, then
  `security add-generic-password -s factory-claude-token -a "$USER" -w`
  and paste the token at its prompt; (3) in that clone, run
  `factory/bin/runner install`. Never ask for, read or store the token.

- **Step 2 (Adapt), GitHub Actions runner (optional, off by default):** ask
  whether to run the factory on a schedule in GitHub Actions. Skip this unless
  they say yes.
  1. `gh repo view --json visibility --jq .visibility`. If it's `PUBLIC`,
     warn: "Scheduled workflows run with this repo's secrets. Forks can't
     reach them, but anyone with write access can change the workflow." Go on
     only if they confirm.
  2. Write the workflow, pinned to the installed Claude Code:

     ```bash
     mkdir -p .github/workflows
     factory/bin/runner workflow --claude-version "$(claude --version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)" \
       > .github/workflows/factory-runner.yml
     ```

  3. Tell them to create two repository secrets themselves (never ask for
     their values, and never run `gh secret set` with a value yourself):
     - `FACTORY_CLAUDE_TOKEN`: the output of `claude setup-token`;
     - `FACTORY_GH_TOKEN`: a fine-grained personal access token (or GitHub
       App token) for this repo only, with Contents, Issues and Pull
       requests read/write and Actions read. `GITHUB_TOKEN` isn't enough:
       pushes and PRs it makes don't trigger the project's CI.

     `gh secret set FACTORY_CLAUDE_TOKEN` prompts for the value, so they can
     paste it there.
  4. Run `factory/bin/doctor --ci` and report any FAIL or WARN. The workflow
     keeps job state on the `factory-state` branch; don't protect it.

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
