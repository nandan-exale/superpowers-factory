---
name: factory-uninstall
description: Use when the user wants to remove the software factory from a project. Removes the factory's files, Stop hook, runner and AGENTS.md section; keeps job history and GitHub labels; never commits.
---

# Uninstall the software factory

`$PLUGIN` is this skill's base directory followed by `/../..`. Work from the
project root. Commit nothing. Ask before anything this list doesn't cover.

1. **Installed?** If `factory/bin/job` doesn't exist, say the factory isn't
   installed here and stop.
2. **No jobs in flight.** Run `git worktree list`. If any worktree path is
   under `.worktrees/`, list them, say each job must be finished or rejected
   (`factory/bin/job summary` shows them) before uninstalling, and stop.
3. **Runner.** If `factory/bin/runner status` reports the launchd agent
   installed, run `factory/bin/runner uninstall`.
4. **Files.** The file list is the keys of `files` in `factory/manifest.json`
   that are also in `FILES` from `$PLUGIN/bin/factory_files.py`; delete only
   those. A key that is absolute, has a `..` segment, or isn't in `FILES`:
   never delete it, and list it for the human. Without a manifest, use
   `FILES`. Delete each listed file that exists, except `factory/checks.sh`
   when it differs from `$PLUGIN/vendor/factory/factory/checks.sh` (it holds
   the project's own checks: keep it and say so). Delete
   `factory/manifest.json`. Then remove directories left empty under
   `factory/` and `.claude/`, never `factory/jobs/` or anything in it:
   `find factory .claude -type d -empty -not -path factory/jobs -not -path 'factory/jobs/*' -delete`.
5. **Stop hook.** Run `"$PLUGIN/bin/factory-uninstall-settings" .`. If it
   exits 1, show its message and stop; don't edit the file by hand.
6. **AGENTS.md.** Remove the `## Software factory` section: from that
   heading up to (not including) the next `## ` heading or the end of the
   file. Leave `CLAUDE.md` unchanged.
7. **CI.** If `.github/workflows/factory-checks.yml` exists and its only job
   runs `bash factory/checks.sh` after setup steps, delete it. If it does
   more, show it and ask.
8. **`.gitignore`.** Keep `/factory/jobs/` and `/.worktrees/`: the job
   history stays on disk and must stay out of git.
9. **Stop the offer.** Run `"$PLUGIN/bin/factory-state" decline`, so new
   sessions don't offer `/factory-install` again.
10. **Hand over.** Show `git status` and `git diff --stat`, suggest the
    message `chore: uninstall software factory`, and let them commit. Then
    tell them what was kept and how to remove it themselves:

    ```bash
    rm -rf factory/jobs
    gh label delete factory --yes
    gh label delete factory:needs-info --yes
    gh label delete factory:needs-human --yes
    gh label delete factory:planned --yes
    gh label delete factory:learning --yes
    gh label delete factory:digest --yes
    ```

    `/factory-install` (or `"$PLUGIN/bin/factory-state" reset` to get the
    offer back) reinstalls later.
