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
    factory/dashboard.html
  do mkdir -p "$(dirname "$f")" && cp "$VENDOR/$f" "$f"; done
  chmod +x factory/checks.sh factory/bin/job factory/bin/gate factory/bin/route
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

- **Step 3 (Verify), item 3:** the builder's frontmatter `tools` includes
  `Skill`; that is expected.
- **Step 4 (Hand over):** don't commit. Show your human partner the diff
  (`git status` and `git diff`), suggest the message
  `chore: install software factory`, and let them commit and push.

## 2. Tell them how to use it

- Design with `superpowers:brainstorming`, plan with `superpowers:writing-plans`,
  then run `/factory-handoff` instead of executing the plan here.
- Run `/factory run` in a fresh session to build what's queued.
- Ordinary `factory` issues still work as upstream, through intake.
