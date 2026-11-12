---
name: factory-update
description: Use when the user wants to update the software factory installed in the current project to the plugin's current version, or when the session says the installed factory is older than the plugin. Shows every change, keeps the project's adaptations, never commits.
---

# Factory update

Update the factory in the current project from this plugin. The scripts are
in `bin/` two levels above this skill's base directory
(`<skill base>/../../bin`). Call that `$BIN`.

Announce: "I'm using factory-update to update the software factory here."

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
2. Ask your human partner to go ahead. On yes, run
   `"$BIN/factory-update-plan" . --apply-safe`.
3. For each `merge` file: show `diff -u <project file> <plugin vendor file>`
   (the vendor file is `<skill base>/../../vendor/factory/<path>`), say in
   one line what upstream changed and what the project changed, and ask:
   keep the project's version, take upstream's, or merge both. For "merge
   both", edit the project file to carry upstream's change into the
   project's version, then show the result. Once the file is settled (any of
   the three answers), run `"$BIN/factory-update-plan" . --resolved <path>`
   so the update stops being offered for it. Don't skip this: until every
   merge is resolved, the next session offers the update again.
4. Run `factory/bin/doctor --fast` and report any FAIL or WARN.
5. Show `git status` and `git diff --stat`, suggest the message
   `chore: update software factory`, and stop. Don't commit or push.
