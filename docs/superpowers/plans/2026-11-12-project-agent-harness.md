# Project Agent Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Projects with the factory installed get a cached Stop hook running `factory/checks.sh`, an install health check (`factory/bin/doctor`), a `CLAUDE.md` → `AGENTS.md` import, and a CI workflow running the same checks.

**Architecture:** Two new stdlib scripts in `vendor/factory/factory/bin/` (`stop-hook`, `doctor`) are copied into projects by `/factory-install`, whose skill text gains the wiring steps (settings merge, `CLAUDE.md`, CI, verify with doctor). Tests run both scripts inside a throwaway "installed project" built by a new test helper.

**Tech Stack:** Python 3.11 stdlib, `unittest`, git, bash.

Spec: `docs/superpowers/specs/2026-11-12-project-agent-harness-design.md`.
Run everything from the repo root, `/Users/nandanthakur/projects/superpowers-factory`.
Every commit message ends with a blank line and the `Co-Authored-By` trailer you were given.

**Deviation from the spec's Testing section:** the spec suggests reusing
`tests/factory_project.py`. That helper builds a bare origin and copies only
`job` and `route`; these tests need a fully installed project and no origin,
so a new helper, `tests/installed_project.py`, builds one.

---

## File structure

| File | Responsibility |
|---|---|
| `vendor/factory/factory/bin/stop-hook` (create) | Stop hook for interactive sessions in an installed project. |
| `vendor/factory/factory/bin/doctor` (create) | Install health check. |
| `tests/installed_project.py` (create) | Builds a throwaway installed project; runs its scripts. |
| `tests/test_stop_hook.py` (create) | stop-hook tests. |
| `tests/test_doctor.py` (create) | doctor tests. |
| `scripts/check` (modify) | `compile` check covers the two new scripts. |
| `tests/test_check.py` (modify) | Test for the above. |
| `skills/factory-install/SKILL.md` (modify) | Copy, wire and verify the harness. |
| `README.md` (modify) | Mention `factory/bin/doctor`. |

---

### Task 1: Test helper and `stop-hook`

**Files:**
- Create: `tests/installed_project.py`
- Create: `tests/test_stop_hook.py`
- Create: `vendor/factory/factory/bin/stop-hook`

- [ ] **Step 1: Write the helper**

Create `tests/installed_project.py`:

```python
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


def git(cwd, *args):
    res = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return res.stdout


class InstalledProject:
    """`tmp` is an empty directory; the project is tmp/project, helpers live beside it."""

    def __init__(self, tmp):
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

    def set_checks_result(self, code):
        (self.git_dir / "checks-result").write_text(f"{code}\n")

    def checks_runs(self):
        path = self.git_dir / "checks-runs"
        return len(path.read_text().splitlines()) if path.exists() else 0

    def set_labels(self, names):
        self.labels_file.write_text(json.dumps([{"name": name} for name in names]))

    def env(self, gh=True):
        """Environment for running a factory script: no inherited GIT_*, fake gh or none."""
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env["FAKE_GH_LABELS"] = str(self.labels_file)
        if gh:
            env["PATH"] = f"{self.fakebin}{os.pathsep}{os.environ.get('PATH', '')}"
        else:
            env["PATH"] = "/usr/bin:/bin"
        return env

    def run(self, script, *args, stdin="", gh=True):
        return subprocess.run(
            [sys.executable, str(self.root / "factory" / "bin" / script), *args],
            input=stdin, capture_output=True, text=True, cwd=self.root, env=self.env(gh),
        )
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_stop_hook.py`:

```python
import json
import tempfile
import unittest

from installed_project import InstalledProject

STAMP = "factory-stop-hook.pass"


class StopHookTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.p = InstalledProject(tmp.name)

    def hook(self, payload=None, stdin=None):
        return self.p.run("stop-hook", stdin=stdin if stdin is not None else json.dumps(payload or {}))

    def edit(self, text="edit"):
        self.p.write("AGENTS.md", f"# Agents\n{text}\n")

    def test_clean_tree_skips_checks(self):
        res = self.hook()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.p.checks_runs(), 0)

    def test_passing_checks_allow_stop_and_write_stamp(self):
        self.edit()
        res = self.hook()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.p.checks_runs(), 1)
        self.assertTrue((self.p.git_dir / STAMP).is_file())

    def test_unchanged_state_uses_cache(self):
        self.edit()
        self.hook()
        res = self.hook()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.p.checks_runs(), 1)

    def test_new_edit_after_pass_reruns(self):
        self.edit("a")
        self.hook()
        self.edit("b")
        self.hook()
        self.assertEqual(self.p.checks_runs(), 2)

    def test_untracked_file_changes_key(self):
        self.edit()
        self.hook()
        self.p.write("notes.txt", "new\n")
        self.hook()
        self.assertEqual(self.p.checks_runs(), 2)

    def test_ignored_job_state_does_not_count(self):
        self.p.write("factory/jobs/001-x/job.json", "{}\n")
        self.p.write(".worktrees/001-x/file.txt", "x\n")
        res = self.hook()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.p.checks_runs(), 0)

    def test_failing_checks_block_with_output_tail(self):
        self.p.set_checks_result(1)
        self.edit()
        res = self.hook()
        self.assertEqual(res.returncode, 2)
        self.assertIn("factory/checks.sh failed (exit 1)", res.stderr)
        self.assertIn("checks output line", res.stderr)
        self.assertFalse((self.p.git_dir / STAMP).exists())

    def test_failure_is_not_cached(self):
        self.p.set_checks_result(1)
        self.edit()
        self.hook()
        self.hook()
        self.assertEqual(self.p.checks_runs(), 2)

    def test_second_stop_does_not_block_again(self):
        self.p.set_checks_result(1)
        self.edit()
        res = self.hook({"stop_hook_active": True})
        self.assertEqual(res.returncode, 0)
        self.assertIn("factory/checks.sh failed", res.stderr)

    def test_missing_checks_does_not_block(self):
        (self.p.root / "factory" / "checks.sh").unlink()
        res = self.hook()
        self.assertEqual(res.returncode, 0)
        self.assertIn("factory/checks.sh not found", res.stderr)

    def test_non_object_payload_is_ignored(self):
        self.p.set_checks_result(1)
        self.edit()
        res = self.hook(stdin="[]")
        self.assertEqual(res.returncode, 2, res.stderr)
        self.assertNotIn("Traceback", res.stderr)


if __name__ == "__main__":
    unittest.main()
```

`tests/` is the unittest start directory, so `from installed_project import …`
resolves the same way the existing tests import `factory_project`.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s tests -p 'test_stop_hook.py' -v`
Expected: errors in `setUp` (`vendor/factory/factory/bin/stop-hook` and `doctor` don't exist, so `shutil.copy2` raises `FileNotFoundError`).

- [ ] **Step 4: Implement `stop-hook`, and a placeholder `doctor` so the helper can copy it**

Create `vendor/factory/factory/bin/stop-hook`:

```python
#!/usr/bin/env python3
"""Claude Code Stop hook: don't end a turn while factory/checks.sh fails.

Runs factory/checks.sh when the working tree has changes that haven't passed
yet. The tree state that last passed is remembered in the git dir
(factory-stop-hook.pass), so stopping again without new edits is instant.
Blocks (exit 2) once per failure and never blocks on its own breakage.
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CHECKS = REPO / "factory" / "checks.sh"
STAMP_NAME = "factory-stop-hook.pass"
TAIL = 80


def git(*args, text=True):
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=text)


def note(message):
    print(f"stop-hook: {message}", file=sys.stderr)


def read_payload():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def tree_key():
    """Hash of HEAD, the diff against it, and every untracked, unignored file."""
    digest = hashlib.sha256()
    digest.update(git("rev-parse", "HEAD").stdout.encode())
    digest.update(git("diff", "HEAD", "--binary", text=False).stdout)
    untracked = git("ls-files", "--others", "--exclude-standard", "-z").stdout.split("\0")
    for rel in sorted(filter(None, untracked)):
        digest.update(rel.encode() + b"\0")
        path = REPO / rel
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def stamp_path():
    return REPO / git("rev-parse", "--git-path", STAMP_NAME).stdout.strip()


def main():
    payload = read_payload()
    try:
        status = git("status", "--porcelain")
    except FileNotFoundError:
        note("git not found; skipping checks")
        return 0
    if status.returncode != 0:
        note("not a git repository; skipping checks")
        return 0
    if not status.stdout.strip():
        return 0
    if not CHECKS.is_file():
        note("factory/checks.sh not found; skipping checks")
        return 0
    key = tree_key()
    stamp = stamp_path()
    if stamp.is_file() and stamp.read_text().strip() == key:
        return 0
    try:
        res = subprocess.run(["bash", str(CHECKS)], cwd=REPO, capture_output=True, text=True)
    except OSError as exc:
        note(f"could not run factory/checks.sh: {exc}")
        return 0
    if res.returncode == 0:
        stamp.write_text(key + "\n")
        return 0
    tail = "\n".join((res.stdout + res.stderr).splitlines()[-TAIL:])
    print(f"factory/checks.sh failed (exit {res.returncode}); last lines:\n{tail}", file=sys.stderr)
    if payload.get("stop_hook_active"):
        note("not blocking again; fix this before you finish")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
```

`REPO / <absolute path>` is that absolute path, and `--git-path` output is
relative to `REPO` otherwise, so `stamp_path` is right in both cases.

Create a placeholder `vendor/factory/factory/bin/doctor` (Task 2 replaces it):

```python
#!/usr/bin/env python3
"""Check the factory install. Implemented in the next task."""

import sys

sys.exit(1)
```

Then: `chmod +x vendor/factory/factory/bin/stop-hook vendor/factory/factory/bin/doctor`

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s tests -p 'test_stop_hook.py' -v`
Expected: 11 tests, OK.

- [ ] **Step 6: Commit**

```bash
git add tests/installed_project.py tests/test_stop_hook.py vendor/factory/factory/bin/stop-hook vendor/factory/factory/bin/doctor
git commit -m "feat: add factory/bin/stop-hook, cached Stop hook for installed projects"
```

---

### Task 2: `doctor`

**Files:**
- Modify (replace placeholder): `vendor/factory/factory/bin/doctor`
- Create: `tests/test_doctor.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_doctor.py`:

```python
import json
import shutil
import tempfile
import unittest

from installed_project import LABELS, InstalledProject

CHECK_NAMES = ("config", "agents", "files", "gitignore", "stop-hook", "claude-md", "labels")


class DoctorTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.p = InstalledProject(tmp.name)

    def doctor(self, *args, gh=True):
        return self.p.run("doctor", *args, gh=gh)

    def assertFails(self, name, needle, *args):
        res = self.doctor("--fast", *args)
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn(f"FAIL {name}: ", res.stdout)
        self.assertIn(needle, res.stdout)

    def edit(self, rel, change):
        path = self.p.root / rel
        path.write_text(change(path.read_text(encoding="utf-8")), encoding="utf-8")

    def test_healthy_install_passes(self):
        res = self.doctor("--fast")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        for name in CHECK_NAMES:
            self.assertIn(f"PASS {name}\n", res.stdout)
        self.assertNotIn("checks", res.stdout)

    def test_full_run_includes_checks(self):
        res = self.doctor()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("PASS checks\n", res.stdout)

    def test_failing_checks_fail(self):
        self.p.set_checks_result(3)
        res = self.doctor()
        self.assertEqual(res.returncode, 1)
        self.assertIn("FAIL checks: factory/checks.sh exited 3", res.stdout)
        self.assertIn("checks output line", res.stdout)

    def test_unknown_model_alias_fails(self):
        def change(text):
            cfg = json.loads(text)
            cfg["routing"]["low"]["builder"]["model"] = "gpt"
            return json.dumps(cfg)
        self.edit("factory/config.json", change)
        self.assertFails("config", "routing.low.builder: model 'gpt' not in model_aliases")

    def test_agent_with_model_fails(self):
        self.edit(".claude/agents/builder.md", lambda t: t.replace("name: builder\n", "name: builder\nmodel: opus\n", 1))
        self.assertFails("agents", ".claude/agents/builder.md: sets model")

    def test_unexpected_frontmatter_key_fails(self):
        self.edit(".claude/agents/approver.md", lambda t: t.replace("name: approver\n", "name: approver\ncolor: red\n", 1))
        self.assertFails("agents", ".claude/agents/approver.md: unexpected frontmatter key 'color'")

    def test_missing_agent_fails(self):
        (self.p.root / ".claude/agents/reviewer-ui.md").unlink()
        self.assertFails("agents", ".claude/agents/reviewer-ui.md missing")

    def test_non_executable_script_fails(self):
        (self.p.root / "factory/bin/route").chmod(0o644)
        self.assertFails("files", "factory/bin/route is not executable")

    def test_missing_gitignore_entry_fails(self):
        self.p.write(".gitignore", "/factory/jobs/\n")
        self.assertFails("gitignore", ".worktrees/ is not gitignored")

    def test_missing_stop_hook_fails(self):
        self.p.write(".claude/settings.json", "{}\n")
        self.assertFails("stop-hook", "no Stop hook in .claude/settings.json runs factory/bin/stop-hook")

    def test_claude_md_without_import_fails(self):
        self.p.write("CLAUDE.md", "# Claude\n")
        self.assertFails("claude-md", "CLAUDE.md doesn't import AGENTS.md")

    def test_only_claude_md_passes(self):
        (self.p.root / "AGENTS.md").unlink()
        self.p.write("CLAUDE.md", "# Claude\n")
        res = self.doctor("--fast")
        self.assertEqual(res.returncode, 0, res.stdout)

    def test_missing_label_fails(self):
        self.p.set_labels([name for name in LABELS if name != "factory:planned"])
        self.assertFails("labels", "label 'factory:planned' missing")

    @unittest.skipIf(shutil.which("gh", path="/usr/bin:/bin"), "a real gh is in /usr/bin or /bin")
    def test_missing_gh_warns(self):
        res = self.doctor("--fast", gh=False)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("WARN labels: gh not found; labels not checked", res.stdout)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s tests -p 'test_doctor.py' -v`
Expected: every test FAILS (the placeholder exits 1 with no output).

- [ ] **Step 3: Implement**

Replace `vendor/factory/factory/bin/doctor` with:

```python
#!/usr/bin/env python3
"""Check that the software factory is installed correctly in this project.

Usage: doctor [--fast]

Prints PASS, WARN or FAIL per check and exits 1 on any FAIL. --fast skips
running factory/checks.sh.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
AGENTS = ("intake", "spec-writer", "builder", "reviewer-code",
          "reviewer-security", "reviewer-ux", "reviewer-ui", "approver")
AGENT_KEYS = {"name", "description", "tools"}
EXECUTABLES = ("factory/checks.sh", "factory/bin/job", "factory/bin/gate", "factory/bin/route",
               "factory/bin/stop-hook", "factory/bin/doctor")
LABELS = ("factory", "factory:needs-info", "factory:needs-human", "factory:planned")
TOP_LEVEL_KEY = re.compile(r"^([A-Za-z_-]+):")
CHECKS_TAIL = 20


def fail(message):
    return ("FAIL", message)


def warn(message):
    return ("WARN", message)


def model_entries(cfg):
    for role, entry in cfg.get("agents", {}).items():
        yield f"agents.{role}", entry
    for risk, roles in cfg.get("routing", {}).items():
        for role, entry in roles.items():
            yield f"routing.{risk}.{role}", entry
    for surface, roles in cfg.get("surface_reviewers", {}).items():
        for role, entry in roles.items():
            yield f"surface_reviewers.{surface}.{role}", entry


def check_config():
    cfg = json.loads((REPO / "factory" / "config.json").read_text(encoding="utf-8"))
    aliases = set(cfg.get("model_aliases", []))
    efforts = set(cfg.get("effort_levels", []))
    problems = []
    for where, entry in model_entries(cfg):
        if not isinstance(entry, dict):
            problems.append(fail(f"{where}: expected an object with model and effort"))
            continue
        if entry.get("model") not in aliases:
            problems.append(fail(f"{where}: model {entry.get('model')!r} not in model_aliases"))
        if entry.get("effort") not in efforts:
            problems.append(fail(f"{where}: effort {entry.get('effort')!r} not in effort_levels"))
    return problems


def frontmatter_keys(text):
    """Top-level keys of a leading --- block, or None if there is no closed block."""
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return None
    keys = []
    for line in lines[1:]:
        if line == "---":
            return keys
        match = TOP_LEVEL_KEY.match(line)
        if match:
            keys.append(match.group(1))
    return None


def check_agents():
    problems = []
    for name in AGENTS:
        rel = f".claude/agents/{name}.md"
        path = REPO / rel
        if not path.is_file():
            problems.append(fail(f"{rel} missing"))
            continue
        keys = frontmatter_keys(path.read_text(encoding="utf-8-sig"))
        if keys is None:
            problems.append(fail(f"{rel}: no --- frontmatter block"))
            continue
        allowed = AGENT_KEYS | ({"hooks"} if name == "builder" else set())
        for key in keys:
            if key == "model":
                problems.append(fail(f"{rel}: sets model; factory/config.json sets models at spawn time"))
            elif key not in allowed:
                problems.append(fail(f"{rel}: unexpected frontmatter key {key!r}"))
    return problems


def check_files():
    problems = []
    if not (REPO / ".claude/skills/factory/SKILL.md").is_file():
        problems.append(fail(".claude/skills/factory/SKILL.md missing"))
    for rel in EXECUTABLES:
        path = REPO / rel
        if not path.is_file():
            problems.append(fail(f"{rel} missing"))
        elif not os.access(path, os.X_OK):
            problems.append(fail(f"{rel} is not executable"))
    return problems


def check_gitignore():
    problems = []
    for directory in ("factory/jobs/", ".worktrees/"):
        res = subprocess.run(["git", "check-ignore", "-q", f"{directory}x"], cwd=REPO,
                             capture_output=True, text=True)
        if res.returncode != 0:
            problems.append(fail(f"{directory} is not gitignored"))
    return problems


def check_stop_hook():
    path = REPO / ".claude" / "settings.json"
    if not path.is_file():
        return [fail(".claude/settings.json missing; it must register factory/bin/stop-hook as a Stop hook")]
    settings = json.loads(path.read_text(encoding="utf-8"))
    for group in settings.get("hooks", {}).get("Stop", []):
        for hook in group.get("hooks", []):
            if "factory/bin/stop-hook" in hook.get("command", ""):
                return []
    return [fail("no Stop hook in .claude/settings.json runs factory/bin/stop-hook")]


def check_claude_md():
    has_agents = (REPO / "AGENTS.md").is_file()
    claude = REPO / "CLAUDE.md"
    if not has_agents and not claude.is_file():
        return [fail("neither AGENTS.md nor CLAUDE.md exists")]
    if has_agents and claude.is_file():
        lines = [line.strip() for line in claude.read_text(encoding="utf-8").splitlines()]
        if "@AGENTS.md" not in lines:
            return [fail("CLAUDE.md doesn't import AGENTS.md; add a line @AGENTS.md")]
    return []


def check_labels():
    gh = shutil.which("gh")
    if not gh:
        return [warn("gh not found; labels not checked")]
    res = subprocess.run([gh, "label", "list", "--json", "name", "--limit", "200"], cwd=REPO,
                         capture_output=True, text=True)
    if res.returncode != 0:
        return [warn(f"gh label list failed: {res.stderr.strip()}")]
    names = {label["name"] for label in json.loads(res.stdout)}
    return [fail(f"label {name!r} missing on GitHub") for name in LABELS if name not in names]


def check_checks():
    res = subprocess.run(["bash", str(REPO / "factory" / "checks.sh")], cwd=REPO,
                         capture_output=True, text=True)
    if res.returncode == 0:
        return []
    tail = (res.stdout + res.stderr).splitlines()[-CHECKS_TAIL:]
    return [fail(f"factory/checks.sh exited {res.returncode}; last lines:")] + [fail(line) for line in tail]


CHECKS = [
    ("config", check_config),
    ("agents", check_agents),
    ("files", check_files),
    ("gitignore", check_gitignore),
    ("stop-hook", check_stop_hook),
    ("claude-md", check_claude_md),
    ("labels", check_labels),
    ("checks", check_checks),
]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fast", action="store_true", help="skip running factory/checks.sh")
    opts = parser.parse_args(argv)
    failed = False
    for name, check in CHECKS:
        if opts.fast and name == "checks":
            continue
        try:
            results = check()
        except Exception as exc:  # reported as a FAIL so one broken check can't hide the rest
            results = [fail(f"{type(exc).__name__}: {exc}")]
        if not results:
            print(f"PASS {name}")
        for level, message in results:
            failed = failed or level == "FAIL"
            print(f"{level} {name}: {message}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s tests -p 'test_doctor.py' -v`
Expected: 15 tests, OK (or 14 OK + 1 skipped if a `gh` lives in `/usr/bin` or `/bin`).

- [ ] **Step 5: Run every test**

Run: `python3 -m unittest discover -s tests -q`
Expected: OK.

- [ ] **Step 6: Commit**

```bash
git add vendor/factory/factory/bin/doctor tests/test_doctor.py
git commit -m "feat: add factory/bin/doctor to verify a factory install"
```

---

### Task 3: `scripts/check` compiles the new scripts

**Files:**
- Modify: `scripts/check` (`check_compile`)
- Modify: `tests/test_check.py` (`CheckTest`)

- [ ] **Step 1: Write the failing test**

Add to `CheckTest` in `tests/test_check.py`:

```python
    def test_syntax_error_in_stop_hook_fails(self):
        self.edit("vendor/factory/factory/bin/stop-hook", lambda text: text + "\ndef broken(:\n")
        self.assertFails("compile", "bin/stop-hook:")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest tests.test_check -v` (stage the Task 1–2 files first if
they are not committed: `copy_repo` copies only tracked files.)
Expected: `test_syntax_error_in_stop_hook_fails` FAILS.

- [ ] **Step 3: Implement**

In `scripts/check`, `check_compile`, change

```python
    for name in ("job", "gate", "route"):
```

to

```python
    for name in ("job", "gate", "route", "stop-hook", "doctor"):
```

- [ ] **Step 4: Run the tests and the full check**

Run: `python3 -m unittest tests.test_check -v && scripts/check`
Expected: tests OK; all seven `PASS` lines, exit 0.

- [ ] **Step 5: Commit**

```bash
git add scripts/check tests/test_check.py
git commit -m "feat: compile the new factory scripts in scripts/check"
```

---

### Task 4: Install skill and README

**Files:**
- Modify: `skills/factory-install/SKILL.md`
- Modify: `README.md`

No automated test covers skill prose; Step 3 checks it by reading.

- [ ] **Step 1: Edit `skills/factory-install/SKILL.md`**

1. In the **Step 1 (Copy)** bullet's code block, replace

   ```
       factory/config.json factory/checks.sh factory/bin/job factory/bin/gate factory/bin/route \
       factory/dashboard.html
     do mkdir -p "$(dirname "$f")" && cp "$VENDOR/$f" "$f"; done
     chmod +x factory/checks.sh factory/bin/job factory/bin/gate factory/bin/route
   ```

   with

   ```
       factory/config.json factory/checks.sh factory/bin/job factory/bin/gate factory/bin/route \
       factory/bin/stop-hook factory/bin/doctor factory/dashboard.html
     do mkdir -p "$(dirname "$f")" && cp "$VENDOR/$f" "$f"; done
     chmod +x factory/checks.sh factory/bin/job factory/bin/gate factory/bin/route \
       factory/bin/stop-hook factory/bin/doctor
   ```

2. After the **Step 2 (Adapt), AGENTS.md** bullet (after its code block), insert:

   ````markdown
   - **Step 2 (Adapt), CLAUDE.md:** if the project has `AGENTS.md` and no
     `CLAUDE.md`, create `CLAUDE.md` containing the single line `@AGENTS.md`.
     If it has both and `CLAUDE.md` has no `@AGENTS.md` line, append one. If it
     uses only `CLAUDE.md`, change nothing.

   - **Step 2 (Adapt), Stop hook:** register `factory/bin/stop-hook` for
     interactive sessions. It runs `factory/checks.sh` when a session stops
     with changes that haven't passed yet, and blocks the stop once if they
     fail. Merge this into `.claude/settings.json`, creating the file if it
     doesn't exist. Keep every existing key and hook: append to an existing
     `hooks.Stop` list, never replace it. If the file exists but isn't valid
     JSON, stop and show your human partner instead of rewriting it.

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
     `bash factory/checks.sh`.
   ````

3. Replace the **Step 3 (Verify), item 3** bullet with:

   ```markdown
   - **Step 3 (Verify):** instead of upstream's list, run `factory/bin/doctor`.
     It must exit 0. It checks the config, agent frontmatter (the builder's
     `tools` includes `Skill`, which is expected), files and permissions,
     `.gitignore`, the Stop hook, `CLAUDE.md`, the labels and
     `factory/checks.sh`. Report any `WARN` lines to your human partner.
   ```

4. In **## 2. Tell them how to use it**, add a bullet:

   ```markdown
   - `factory/bin/doctor` checks the install at any time; `--fast` skips the
     project's checks.
   ```

- [ ] **Step 2: Edit `README.md`**

In "## Use it in a project", replace item 1 with:

```markdown
1. In the project, run `/factory-install` once and commit what it adds. It
   also adds a Stop hook that runs `factory/checks.sh` before a session ends,
   a `CLAUDE.md` that imports `AGENTS.md`, and a CI workflow for the same
   checks. `factory/bin/doctor` checks the install at any time. Then start a
   fresh session: the factory's agents only load at session start.
```

- [ ] **Step 3: Read back and check**

Read `skills/factory-install/SKILL.md` top to bottom. Confirm:
- the copy loop and `chmod` list both name `factory/bin/stop-hook` and `factory/bin/doctor`;
- the settings snippet is valid JSON (`python3 -c 'import json; json.loads(open("/dev/stdin").read())'` on it);
- nothing says to commit or overwrite without asking.

Run: `scripts/check`
Expected: all seven `PASS` lines, exit 0.

- [ ] **Step 4: Commit**

```bash
git add skills/factory-install/SKILL.md README.md
git commit -m "docs: factory-install wires the stop hook, CLAUDE.md, CI and doctor"
```
