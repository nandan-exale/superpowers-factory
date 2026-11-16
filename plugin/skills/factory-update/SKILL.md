---
name: factory-update
description: Use when the user wants to update the software factory installed in the current project to the plugin's current version, or when the session says the installed factory is older than the plugin. Shows every change, keeps the project's adaptations, never commits.
---

# Factory update

Update the factory in the current project from this plugin. The scripts are
in the plugin's `bin/`, `$BIN`, found below.

Announce: "I'm using factory-update to update the software factory here."

## Find the plugin

The plugin's files are two levels above this skill's base directory:

```bash
PLUGIN="<skill base>/../.."
VENDOR="$PLUGIN/vendor/factory"; BIN="$PLUGIN/tools"
```

If `$VENDOR` doesn't exist, this agent has the skill folders without the rest
of the plugin. Stop, and tell your human partner to install the whole plugin:
`npx plugins add nandan-exale/superpowers-factory` for Codex, Cursor or
GitHub Copilot CLI, or `/plugin install superpowers-factory@superpowers-factory`
in Claude Code. Don't download it yourself.

1. Run `"$BIN/factory-update-plan" .` and show the result grouped:
   - `new`, `safe`: will be copied from the plugin;
   - `config`: new keys in `factory/config.json` will be added, existing
     values kept;
   - `settings`: `factory/runner-settings.json` will be replaced with the
     plugin's, keeping the network domains this project added (upstream's own
     domains always follow upstream; one removed here comes back) (if the project
     changed it beyond domains and upstream changed it too, it is a `merge`);
   - `merge`: changed both here and upstream, decided one by one below;
   - `owned`, `unchanged`: left alone.
   - `retired`: files earlier versions installed and this one no longer uses
     (the old `.claude/agents/`), unedited here, so they will be deleted;
   - `retired-edited`: the same, but edited in this project: show the diff
     against `factory/agents/<name>.md` and carry the project's changes into
     that file (the new copy is the one the factory reads), then delete the old
     file.
2. Ask your human partner to go ahead. On yes, run
   `"$BIN/factory-update-plan" . --apply-safe`.
3. For each `merge` file: show `diff -u <project file> <plugin vendor file>`
   (the vendor file is `$VENDOR/<path>`), say in
   one line what upstream changed and what the project changed, and ask:
   keep the project's version, take upstream's, or merge both. For "merge
   both", edit the project file to carry upstream's change into the
   project's version, then show the result. Once the file is settled (any of
   the three answers), run `"$BIN/factory-update-plan" . --resolved <path>`
   so the update stops being offered for it. Don't skip this: until every
   merge is resolved, the next session offers the update again.
4. Create the label that rejection memory needs. `--force` makes this safe when
   it already exists:

   ```bash
   gh label create factory:rejected --color BFD4F2 --force --description "The factory rejected this request; later intakes check new issues against it"
   ```

   If `gh` is missing or the command fails, say so and give the user this
   command to run themselves.
5. Run `factory/bin/doctor --fast` and report any FAIL or WARN.
6. Show `git status` and `git diff --stat`, suggest the message
   `chore: update software factory`, and stop. Don't commit or push.
