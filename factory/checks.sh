#!/usr/bin/env bash
# The repo's checks. Exit 0 only when the branch is fit to review.
#
# The gate runs this script from the main checkout with the job's worktree as
# the working directory. Keep it fast, deterministic and non-interactive: no
# watch modes, no prompts, nothing that rewrites files.
#
# scripts/check runs every repo rule: license, JSON, config, frontmatter,
# compile, branding and the stdlib unit tests. It needs only python3 and git.
set -euo pipefail

python3 scripts/check
