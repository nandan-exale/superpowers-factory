---
name: factory-update
description: Use when the user wants to update the software factory installed in the current project to the plugin's current version, or when the session says the installed factory is older than the plugin. Shows every change, keeps the project's adaptations, never commits.
---

# Factory update

Update the factory in the current project from this plugin. The scripts are
in the plugin's `bin/`, `$BIN`, found below.

Announce: "I'm using factory-update to update the software factory here."

## Find the plugin

The plugin's files are two levels above this skill's base directory when the
plugin is installed whole (Claude Code). An agent that installed only the
skill folders (`npx skills add`) doesn't have them, so fetch them:

```bash
PLUGIN="<skill base>/../.."
if [ ! -d "$PLUGIN/vendor/factory" ]; then
  TAG=$(git ls-remote --tags --refs https://github.com/nandan-exale/superpowers-factory 'v*' \
        | sed 's#.*refs/tags/##' | sort -V | tail -1)
  PLUGIN=$(mktemp -d)/superpowers-factory
  git clone --depth 1 --branch "$TAG" https://github.com/nandan-exale/superpowers-factory "$PLUGIN"
fi
VENDOR="$PLUGIN/vendor/factory"; BIN="$PLUGIN/bin"
```

Ask your human partner before the clone: say it downloads the plugin's
release `<TAG>` from GitHub into a temporary folder.

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
4. Run `factory/bin/doctor --fast` and report any FAIL or WARN.
5. Show `git status` and `git diff --stat`, suggest the message
   `chore: update software factory`, and stop. Don't commit or push.
