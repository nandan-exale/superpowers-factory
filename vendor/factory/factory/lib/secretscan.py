"""Scan a job branch's commits for secrets.

bin/job passes the shell runner, the base branch and the allow-list in, so this module reads no config."""

import fnmatch
import re

SECRET_RULES = (
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("aws access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("github token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,}")),
    ("anthropic key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("slack token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("assigned secret", re.compile(r"(api[_-]?key|secret|token|password)\s*[:=]\s*[\"'][^\"']{16,}[\"']", re.I)),
)
HUNK = re.compile(r"^@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def path_matches(path, pattern):
    """fnmatch (whose * also crosses /), plus `**/x` matching `x` at the root. Same as the gate's."""
    return fnmatch.fnmatch(path, pattern) or (pattern.startswith("**/") and fnmatch.fnmatch(path, pattern[3:]))


def added_lines(diff):
    """(path, new line number, text) for every added line of a unified diff.
    Hunk bodies are read by their line counts, so an added line that looks like a header is still scanned,
    and a path git couldn't print plainly is kept as printed rather than skipped."""
    path, line, old_left, new_left = "?", 0, 0, 0
    for text in diff.split("\n"):
        if old_left > 0 or new_left > 0:
            if text.startswith("+"):
                yield path, line, text[1:]
                line, new_left = line + 1, new_left - 1
            elif text.startswith("-"):
                old_left -= 1
            elif text.startswith(" "):
                line, old_left, new_left = line + 1, old_left - 1, new_left - 1
            continue
        if text.startswith("+++ "):
            path = text[6:] if text.startswith("+++ b/") else text[4:]
            continue
        m = HUNK.match(text)
        if m:
            old_left, line, new_left = int(m.group(1) or 1), int(m.group(2)), int(m.group(3) or 1)


def mask(value):
    return f"{value[:4]}… ({len(value)} chars)"


def secret_hits(worktree, run, base, allow):
    """`path:line rule: masked` for each line any branch commit adds that matches a secret rule.
    Every commit is scanned, because a secret deleted in a later commit is still pushed in history."""
    diff = run(["git", "-c", "core.quotePath=false", "log", "-p", "--no-merges", "--no-color", "--no-ext-diff",
                "--format=", "--unified=0", f"origin/{base}..HEAD"], cwd=worktree).stdout
    hits = {}
    for path, n, text in added_lines(diff):
        if any(path_matches(path, pattern) for pattern in allow):
            continue
        for name, rule in SECRET_RULES:
            m = rule.search(text)
            if m:
                hits.setdefault((path, name, m.group(0)), f"{path}:{n} {name}: {mask(m.group(0))}")
                break
    return list(hits.values())
