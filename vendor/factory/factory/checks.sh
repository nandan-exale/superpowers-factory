#!/usr/bin/env bash
# The repo's checks. Exit 0 only when the branch is fit to review.
#
# The gate runs this script from the main checkout with the job's worktree as
# the working directory. Keep it fast, deterministic and non-interactive: no
# watch modes, no prompts, nothing that rewrites files.
#
# Only the Stop hook sets two variables, so a project can skip slow checks for a
# small change: FACTORY_CHECKS_CONTEXT=stop-hook, and FACTORY_CHANGED_PATHS, the
# changed paths one per line. An empty or unset list means "run everything", and
# the gate never sets either variable. Ignoring both is fine.
#
# INSTALL.md replaces the line below with this project's real commands, e.g.:
#
#   npm ci --prefer-offline
#   npm run lint
#   npm run typecheck
#   npm test -- --run
#   npm run build
set -euo pipefail

echo "factory/checks.sh has no checks yet. Add this repo's test, lint, typecheck and build commands." >&2
exit 1
