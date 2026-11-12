"""A throwaway project with the vendored factory installed as /factory-install leaves it."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
VENDOR = PLUGIN / "vendor" / "factory"
AGENTS = ("intake", "spec-writer", "builder", "reviewer-code",
          "reviewer-security", "reviewer-ux", "reviewer-ui", "approver")
COPIED = (
    ".claude/skills/factory/SKILL.md",
    *(f".claude/agents/{name}.md" for name in AGENTS),
    "factory/config.json",
    "factory/bin/job",
    "factory/bin/gate",
    "factory/bin/route",
    "factory/bin/stop-hook",
    "factory/bin/doctor",
    "factory/dashboard.html",
)
LABELS = ("factory", "factory:needs-info", "factory:needs-human", "factory:planned")
SETTINGS = {"hooks": {"Stop": [{"hooks": [{
    "type": "command",
    "command": "\"$CLAUDE_PROJECT_DIR\"/factory/bin/stop-hook",
    "timeout": 600,
}]}]}}

# Counts its runs and exits with the code in .git/checks-result (default 0).
# Both files live in .git so they never change the tree the hook hashes.
CHECKS_SH = """#!/usr/bin/env bash
set -u
git_dir="$(git rev-parse --git-dir)"
echo run >> "$git_dir/checks-runs"
echo "checks output line"
exit "$(cat "$git_dir/checks-result" 2>/dev/null || echo 0)"
"""

FAKE_GH = """#!{python}
import os, sys
sys.stdout.write(open(os.environ["FAKE_GH_LABELS"]).read())
"""


def clean_env():
    """Inherited environment minus GIT_*, with the user's git config switched off."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    return env


def git(cwd, *args):
    res = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True,
                         env=clean_env())
    return res.stdout


class InstalledProject:
    """`tmp` is an empty directory; the project is tmp/project, helpers live beside it."""

    def __init__(self, tmp, commit=True):
        tmp = Path(tmp).resolve()
        self.root = tmp / "project"
        self.fakebin = tmp / "fakebin"
        self.labels_file = tmp / "labels.json"
        self.root.mkdir()
        self.fakebin.mkdir()
        for rel in COPIED:
            target = self.root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(VENDOR / rel, target)
        self.write("factory/checks.sh", CHECKS_SH, executable=True)
        self.write(".gitignore", "/factory/jobs/\n/.worktrees/\n")
        self.write(".claude/settings.json", json.dumps(SETTINGS, indent=2) + "\n")
        self.write("AGENTS.md", "# Agents\n")
        self.write("CLAUDE.md", "@AGENTS.md\n")
        gh = self.fakebin / "gh"
        gh.write_text(FAKE_GH.format(python=sys.executable))
        gh.chmod(0o755)
        self.set_labels(LABELS)
        git(self.root, "init", "-q")
        git(self.root, "add", "-A")
        if commit:
            self.commit("install")

    @property
    def git_dir(self):
        return self.root / ".git"

    def write(self, rel, text, executable=False):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        if executable:
            path.chmod(0o755)

    def commit(self, message):
        git(self.root, "-c", "user.email=test@example.com", "-c", "user.name=test",
            "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
            "commit", "-q", "-m", message)

    def commit_all(self, message):
        git(self.root, "add", "-A")
        self.commit(message)

    def set_checks_script(self, text):
        self.write("factory/checks.sh", text, executable=True)

    def set_checks_result(self, code):
        (self.git_dir / "checks-result").write_text(f"{code}\n")

    def checks_runs(self):
        path = self.git_dir / "checks-runs"
        return len(path.read_text().splitlines()) if path.exists() else 0

    def set_labels(self, names):
        self.labels_file.write_text(json.dumps([{"name": name} for name in names]))

    def env(self, gh=True):
        """Environment for running a factory script: no inherited GIT_*, fake gh or none."""
        env = clean_env()
        env["FAKE_GH_LABELS"] = str(self.labels_file)
        if gh:
            env["PATH"] = f"{self.fakebin}{os.pathsep}{os.environ.get('PATH', '')}"
        else:
            env["PATH"] = "/usr/bin:/bin"
        return env

    def run(self, script, *args, stdin="", gh=True, env=None):
        return subprocess.run(
            [sys.executable, str(self.root / "factory" / "bin" / script), *args],
            input=stdin, capture_output=True, text=True, cwd=self.root,
            env={**self.env(gh), **(env or {})},
        )
