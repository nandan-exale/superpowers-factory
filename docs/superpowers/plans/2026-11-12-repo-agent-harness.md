# Repo Agent Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give agents working on superpowers-factory one instructions file, one check command, a Stop hook that blocks on failing checks, and CI that runs the same command.

**Architecture:** `scripts/check` (stdlib Python) holds every rule as a function returning a list of problems; `main` prints `PASS`/`FAIL` per check. `scripts/check-hook` wraps it for Claude Code's Stop hook. CI and the hook only call `scripts/check`. `AGENTS.md` documents the rules; `CLAUDE.md` imports it.

**Tech Stack:** Python 3.11 stdlib, `unittest`, git, bash, GitHub Actions.

Spec: `docs/superpowers/specs/2026-11-12-repo-agent-harness-design.md`.

Run everything from the repo root, `/Users/nandanthakur/projects/superpowers-factory`.

---

## File structure

| File | Responsibility |
|---|---|
| `scripts/check` (create) | Every repo rule; CLI with `--root`, `--fast`, `--extra-forbidden-hash`. |
| `scripts/check-hook` (create) | Stop hook wrapper: skip on clean tree, run check, exit 2 on failure once. |
| `tests/test_check.py` (create) | Tests for both scripts, run against throwaway copies of the repo. |
| `.claude/settings.json` (create) | Registers the Stop hook. |
| `.github/workflows/check.yml` (create) | CI running `scripts/check`. |
| `AGENTS.md` (create) | Repo map, invariants, workflow for agents. |
| `CLAUDE.md` (create) | `@AGENTS.md`. |
| `README.md` (modify) | One section pointing contributors at `AGENTS.md` and `scripts/check`. |

---

### Task 1: Check runner with `license` and `json` checks

**Files:**
- Create: `scripts/check`
- Create: `tests/test_check.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_check.py`:

```python
"""Tests for scripts/check and scripts/check-hook, run on copies of this repo."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CHECK = REPO / "scripts" / "check"
CONFIG = "vendor/factory/factory/config.json"


def git(cwd, *args):
    res = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return res.stdout


def copy_repo(dest):
    """Copy the working-tree version of every tracked file into a new, committed git repo."""
    for rel in git(REPO, "ls-files", "-z").split("\0"):
        src = REPO / rel
        if not rel or not src.is_file():
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
    git(dest, "init", "-q")
    git(dest, "add", "-A")
    git(dest, "-c", "user.email=test@example.com", "-c", "user.name=test", "commit", "-q", "-m", "copy")
    return dest


class RepoCopyTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = copy_repo(Path(tmp.name))

    def edit(self, rel, change):
        path = self.root / rel
        path.write_text(change(path.read_text(encoding="utf-8")), encoding="utf-8")

    def edit_config(self, change):
        path = self.root / CONFIG
        cfg = json.loads(path.read_text(encoding="utf-8"))
        change(cfg)
        path.write_text(json.dumps(cfg), encoding="utf-8")


class CheckTest(RepoCopyTest):
    def run_check(self, *extra):
        res = subprocess.run(
            [sys.executable, str(CHECK), "--fast", "--root", str(self.root), *extra],
            capture_output=True, text=True,
        )
        return res.returncode, res.stdout

    def assertFails(self, name, needle, *extra):
        code, out = self.run_check(*extra)
        self.assertEqual(code, 1, out)
        self.assertIn(f"FAIL {name}: ", out)
        self.assertIn(needle, out)

    def test_clean_copy_passes(self):
        code, out = self.run_check()
        self.assertEqual(code, 0, out)
        self.assertNotIn("FAIL", out)
        self.assertIn("PASS license", out)

    def test_missing_notice_fails(self):
        (self.root / "vendor/factory/NOTICE").unlink()
        self.assertFails("license", "vendor/factory/NOTICE is missing or empty")

    def test_unparseable_config_fails(self):
        self.edit(CONFIG, lambda text: text + "}")
        self.assertFails("json", "vendor/factory/factory/config.json")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_check -v`
Expected: 3 errors/failures (`scripts/check` does not exist, so the subprocess exits 2 with "can't open file").

- [ ] **Step 3: Write the runner and the two checks**

Create `scripts/check`:

```python
#!/usr/bin/env python3
"""Check this repo's rules. Prints PASS/FAIL per check and exits 1 on any failure."""

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FACTORY = Path("vendor/factory/factory")
JSON_FILES = (
    ".claude-plugin/plugin.json",
    ".claude-plugin/marketplace.json",
    "vendor/factory/factory/config.json",
)


def check_license(root, opts):
    problems = []
    for rel in ("LICENSE", "vendor/factory/NOTICE"):
        path = root / rel
        if not path.is_file() or not path.read_text(encoding="utf-8").strip():
            problems.append(f"{rel} is missing or empty")
    return problems


def check_json(root, opts):
    problems = []
    for rel in JSON_FILES:
        try:
            json.loads((root / rel).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            problems.append(f"{rel}: {exc}")
    return problems


CHECKS = [
    ("license", check_license),
    ("json", check_json),
]


def run(root, opts):
    failed = False
    for name, check in CHECKS:
        if opts.fast and name == "tests":
            continue
        try:
            problems = check(root, opts)
        except Exception as exc:  # reported as a FAIL so one broken check can't hide the rest
            problems = [f"{type(exc).__name__}: {exc}"]
        if problems:
            failed = True
            for problem in problems:
                print(f"FAIL {name}: {problem}")
        else:
            print(f"PASS {name}")
    return 1 if failed else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO, help="repo to check (default: this repo)")
    parser.add_argument("--fast", action="store_true", help="skip the unit tests")
    parser.add_argument("--extra-forbidden-hash", action="append", default=[], metavar="SHA256",
                        help="add a SHA-256 to the branding check's forbidden set (for tests)")
    opts = parser.parse_args(argv)
    return run(opts.root.resolve(), opts)


if __name__ == "__main__":
    sys.exit(main())
```

Then: `chmod +x scripts/check`

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_check -v`
Expected: 3 tests, OK.

- [ ] **Step 5: Commit**

```bash
git add scripts/check tests/test_check.py
git commit -m "feat: add scripts/check with license and json checks"
```

---

### Task 2: `config` check

**Files:**
- Modify: `scripts/check` (add a function and a `CHECKS` entry)
- Modify: `tests/test_check.py` (add tests to `CheckTest`)

- [ ] **Step 1: Write the failing tests**

Add to `CheckTest`:

```python
    def test_unknown_model_alias_fails(self):
        self.edit_config(lambda cfg: cfg["routing"]["low"]["builder"].update(model="gpt"))
        self.assertFails("config", "routing.low.builder: model 'gpt' not in model_aliases")

    def test_unknown_effort_fails(self):
        self.edit_config(lambda cfg: cfg["surface_reviewers"]["ui"]["ux"].update(effort="huge"))
        self.assertFails("config", "surface_reviewers.ui.ux: effort 'huge' not in effort_levels")

    def test_intake_entry_checked(self):
        self.edit_config(lambda cfg: cfg["agents"].update(intake="fable"))
        self.assertFails("config", "agents.intake: expected an object with model and effort")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_check -v`
Expected: the 3 new tests FAIL (exit 0, no `FAIL config:` line).

- [ ] **Step 3: Implement**

In `scripts/check`, add after `check_json`:

```python
def model_entries(cfg):
    """Yield (where, entry) for every {model, effort} the factory spawns with."""
    for role, entry in cfg.get("agents", {}).items():
        yield f"agents.{role}", entry
    for risk, roles in cfg.get("routing", {}).items():
        for role, entry in roles.items():
            yield f"routing.{risk}.{role}", entry
    for surface, roles in cfg.get("surface_reviewers", {}).items():
        for role, entry in roles.items():
            yield f"surface_reviewers.{surface}.{role}", entry


def check_config(root, opts):
    cfg = json.loads((root / FACTORY / "config.json").read_text(encoding="utf-8"))
    aliases = set(cfg.get("model_aliases", []))
    efforts = set(cfg.get("effort_levels", []))
    problems = []
    for where, entry in model_entries(cfg):
        if not isinstance(entry, dict):
            problems.append(f"{where}: expected an object with model and effort")
            continue
        if entry.get("model") not in aliases:
            problems.append(f"{where}: model {entry.get('model')!r} not in model_aliases")
        if entry.get("effort") not in efforts:
            problems.append(f"{where}: effort {entry.get('effort')!r} not in effort_levels")
    return problems
```

and add `("config", check_config),` to `CHECKS` after `("json", check_json),`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_check -v`
Expected: 6 tests, OK.

- [ ] **Step 5: Commit**

```bash
git add scripts/check tests/test_check.py
git commit -m "feat: check that every model and effort in config.json resolves"
```

---

### Task 3: `frontmatter` check

**Files:**
- Modify: `scripts/check`
- Modify: `tests/test_check.py`

- [ ] **Step 1: Write the failing tests**

Add to `CheckTest`:

```python
    def test_agent_with_model_fails(self):
        self.edit("vendor/factory/.claude/agents/builder.md",
                  lambda text: text.replace("name: builder\n", "name: builder\nmodel: opus\n", 1))
        self.assertFails("frontmatter", "vendor/factory/.claude/agents/builder.md: sets model")

    def test_skill_missing_description_fails(self):
        self.edit("skills/factory-install/SKILL.md",
                  lambda text: "\n".join(l for l in text.splitlines() if not l.startswith("description:")) + "\n")
        self.assertFails("frontmatter", "skills/factory-install/SKILL.md: missing description")

    def test_file_without_frontmatter_fails(self):
        self.edit("vendor/factory/.claude/agents/intake.md", lambda text: "no frontmatter\n" + text)
        self.assertFails("frontmatter", "vendor/factory/.claude/agents/intake.md: no --- frontmatter block")

    def test_nested_model_key_is_ignored(self):
        self.edit("vendor/factory/.claude/agents/approver.md",
                  lambda text: text.replace("tools:", "extra:\n  model: nested\ntools:", 1))
        code, out = self.run_check()
        self.assertEqual(code, 0, out)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_check -v`
Expected: the first 3 new tests FAIL; `test_nested_model_key_is_ignored` passes already.

- [ ] **Step 3: Implement**

In `scripts/check`, add `import re` to the imports, then after `check_config`:

```python
FRONTMATTER_GLOBS = (
    "skills/*/SKILL.md",
    "vendor/factory/.claude/skills/*/SKILL.md",
    "vendor/factory/.claude/agents/*.md",
)
TOP_LEVEL_KEY = re.compile(r"^([A-Za-z_-]+):(.*)$")


def frontmatter_keys(text):
    """Top-level keys of a leading --- block, or None if there is no closed block."""
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return None
    keys = {}
    for line in lines[1:]:
        if line == "---":
            return keys
        match = TOP_LEVEL_KEY.match(line)
        if match:
            keys[match.group(1)] = match.group(2).strip()
    return None


def check_frontmatter(root, opts):
    paths = sorted(path for pattern in FRONTMATTER_GLOBS for path in root.glob(pattern))
    if not paths:
        return ["no skill or agent files found"]
    problems = []
    for path in paths:
        rel = path.relative_to(root)
        keys = frontmatter_keys(path.read_text(encoding="utf-8"))
        if keys is None:
            problems.append(f"{rel}: no --- frontmatter block")
            continue
        for required in ("name", "description"):
            if not keys.get(required):
                problems.append(f"{rel}: missing {required}")
        if "model" in keys:
            problems.append(f"{rel}: sets model; models come from factory/config.json")
    return problems
```

and add `("frontmatter", check_frontmatter),` to `CHECKS` after `config`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_check -v`
Expected: 10 tests, OK.

- [ ] **Step 5: Commit**

```bash
git add scripts/check tests/test_check.py
git commit -m "feat: check skill and agent frontmatter, forbid model keys"
```

---

### Task 4: `compile` check

**Files:**
- Modify: `scripts/check`
- Modify: `tests/test_check.py`

- [ ] **Step 1: Write the failing tests**

Add to `CheckTest`:

```python
    def test_syntax_error_in_route_fails(self):
        self.edit("vendor/factory/factory/bin/route", lambda text: text + "\ndef broken(:\n")
        self.assertFails("compile", "bin/route:")

    def test_bash_syntax_error_in_checks_fails(self):
        self.edit("vendor/factory/factory/checks.sh", lambda text: text + "\nif then\n")
        self.assertFails("compile", "checks.sh:")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_check -v`
Expected: the 2 new tests FAIL.

- [ ] **Step 3: Implement**

In `scripts/check`, add `import subprocess` to the imports, then after `check_frontmatter`:

```python
def check_compile(root, opts):
    problems = []
    for name in ("job", "gate", "route"):
        path = root / FACTORY / "bin" / name
        try:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
        except (OSError, SyntaxError) as exc:
            problems.append(f"bin/{name}: {exc}")
    res = subprocess.run(["bash", "-n", str(root / FACTORY / "checks.sh")], capture_output=True, text=True)
    if res.returncode != 0:
        problems.append(f"checks.sh: {res.stderr.strip()}")
    return problems
```

and add `("compile", check_compile),` to `CHECKS` after `frontmatter`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_check -v`
Expected: 12 tests, OK.

- [ ] **Step 5: Commit**

```bash
git add scripts/check tests/test_check.py
git commit -m "feat: check that factory scripts compile"
```

---

### Task 5: `branding` check

**Files:**
- Modify: `scripts/check`
- Modify: `tests/test_check.py`

The forbidden set holds SHA-256 hashes of lowercase tokens, so neither the
script nor the tests contain the names. The two hashes below are the removed
upstream author name and its domain-style form. `harnessprobe` hashes to
`71bede1bb2ef6494d196e5e2be06c68e0f5352cd3018a4f44179dfbcc21dac5f`.

- [ ] **Step 1: Write the failing tests**

Add to `CheckTest`:

```python
    PROBE_HASH = "71bede1bb2ef6494d196e5e2be06c68e0f5352cd3018a4f44179dfbcc21dac5f"

    def test_forbidden_token_fails(self):
        self.edit("README.md", lambda text: text + "\nSee HarnessProbe.example for more.\n")
        self.assertFails("branding", "README.md: contains a forbidden upstream name",
                         "--extra-forbidden-hash", self.PROBE_HASH)

    def test_token_inside_longer_word_passes(self):
        self.edit("README.md", lambda text: text + "\nharnessprobes\n")
        code, out = self.run_check("--extra-forbidden-hash", self.PROBE_HASH)
        self.assertEqual(code, 0, out)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_check -v`
Expected: `test_forbidden_token_fails` FAILS; `test_token_inside_longer_word_passes` passes already.

- [ ] **Step 3: Implement**

In `scripts/check`, add `import hashlib` to the imports, then after `check_compile`:

```python
# SHA-256 of lowercase tokens that must never appear in a tracked file
# (the removed upstream branding). Hashed so this file doesn't name them.
FORBIDDEN_HASHES = frozenset({
    "5d4b73fc5f7b579c7b5cb3f03d7447df768e8986966bfd491f24605b45826ddb",
    "7061401397abcf81551a89f973b8b519250a7e375304eaaf6add87168ada0de3",
})
TOKEN = re.compile(r"[a-z0-9]+")


def tracked_files(root):
    res = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, text=True, check=True)
    return [rel for rel in res.stdout.split("\0") if rel]


def check_branding(root, opts):
    forbidden = FORBIDDEN_HASHES | set(opts.extra_forbidden_hash)
    problems = []
    for rel in tracked_files(root):
        path = root / rel
        if not path.is_file():
            continue
        text = path.read_bytes().decode("utf-8", errors="ignore").lower()
        if any(hashlib.sha256(token.encode()).hexdigest() in forbidden for token in set(TOKEN.findall(text))):
            problems.append(f"{rel}: contains a forbidden upstream name")
    return problems
```

and add `("branding", check_branding),` to `CHECKS` after `compile`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_check -v`
Expected: 14 tests, OK.

- [ ] **Step 5: Commit**

```bash
git add scripts/check tests/test_check.py
git commit -m "feat: check that no tracked file contains upstream branding"
```

---

### Task 6: `tests` check and a full run on the real repo

**Files:**
- Modify: `scripts/check`

`tests` is the last and slowest check (about 15 s); `--fast` skips it. Every
test in `tests/test_check.py` passes `--fast`, so the suite never recurses.

- [ ] **Step 1: Implement**

In `scripts/check`, after `check_branding`:

```python
def check_tests(root, opts):
    res = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"],
                         cwd=root, capture_output=True, text=True)
    if res.returncode == 0:
        return []
    return ["unit tests failed; last lines of output:"] + res.stderr.strip().splitlines()[-15:]
```

and add `("tests", check_tests),` as the last entry of `CHECKS`.

- [ ] **Step 2: Run the full check on the real repo**

Run: `scripts/check`
Expected: exit 0 and exactly these lines:

```
PASS license
PASS json
PASS config
PASS frontmatter
PASS compile
PASS branding
PASS tests
```

- [ ] **Step 3: Confirm a failing unit test is reported**

Run:

```bash
printf 'import unittest\nclass T(unittest.TestCase):\n    def test_x(self):\n        self.fail("boom")\n' > tests/test_zz_tmp.py
scripts/check; echo "exit=$?"
rm tests/test_zz_tmp.py
```

Expected: `FAIL tests: unit tests failed; …` lines including `boom`, then `exit=1`.

- [ ] **Step 4: Commit**

```bash
git add scripts/check
git commit -m "feat: run the unit tests from scripts/check"
```

---

### Task 7: Stop hook

**Files:**
- Create: `scripts/check-hook`
- Create: `.claude/settings.json`
- Modify: `scripts/check` (`JSON_FILES`)
- Modify: `tests/test_check.py`

- [ ] **Step 1: Write the failing tests**

Add `import os` to the imports of `tests/test_check.py`, add
`HOOK = REPO / "scripts" / "check-hook"` under `CHECK`, and add this class
before the `if __name__` line:

```python
class CheckHookTest(RepoCopyTest):
    def run_hook(self, payload=None, cwd=None):
        env = {**os.environ, "CHECK_HOOK_FAST": "1", "CLAUDE_PROJECT_DIR": str(cwd or self.root)}
        res = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload or {}),
                             capture_output=True, text=True, env=env)
        return res.returncode, res.stderr

    def test_clean_tree_skips(self):
        (self.root / "vendor/factory/NOTICE").write_text("")
        git(self.root, "-c", "user.email=t@e.com", "-c", "user.name=t", "commit", "-qam", "empty notice")
        code, err = self.run_hook()
        self.assertEqual(code, 0, err)
        self.assertEqual(err, "")

    def test_dirty_passing_tree_allows_stop(self):
        self.edit("README.md", lambda text: text + "\nmore\n")
        code, err = self.run_hook()
        self.assertEqual(code, 0, err)

    def test_dirty_failing_tree_blocks(self):
        (self.root / "vendor/factory/NOTICE").unlink()
        code, err = self.run_hook()
        self.assertEqual(code, 2)
        self.assertIn("FAIL license: vendor/factory/NOTICE is missing or empty", err)

    def test_second_stop_does_not_block_again(self):
        (self.root / "vendor/factory/NOTICE").unlink()
        code, err = self.run_hook({"stop_hook_active": True})
        self.assertEqual(code, 0)
        self.assertIn("FAIL license", err)

    def test_outside_git_repo_does_not_block(self):
        with tempfile.TemporaryDirectory() as outside:
            code, err = self.run_hook(cwd=outside)
        self.assertEqual(code, 0)
        self.assertIn("not a git repository", err)
```

`test_clean_tree_skips` commits a violation on purpose: a clean tree must skip
the check even when the check would fail.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_check -v`
Expected: the 5 new tests fail or error (`check-hook` does not exist).

- [ ] **Step 3: Implement the hook**

Create `scripts/check-hook`:

```python
#!/usr/bin/env python3
"""Claude Code Stop hook: block stopping while the tree has changes and scripts/check fails.

Exits 0 on a clean tree, on passing checks, and on the second stop attempt
(stop_hook_active), so it can't loop. Set CHECK_HOOK_FAST=1 to pass --fast.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

CHECK = Path(__file__).resolve().with_name("check")


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        payload = {}
    cwd = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    try:
        status = git(cwd, "status", "--porcelain")
    except FileNotFoundError:
        print("check-hook: git not found; skipping checks", file=sys.stderr)
        return 0
    if status.returncode != 0:
        print("check-hook: not a git repository; skipping checks", file=sys.stderr)
        return 0
    if not status.stdout.strip():
        return 0
    root = git(cwd, "rev-parse", "--show-toplevel").stdout.strip()
    cmd = [sys.executable, str(CHECK), "--root", root]
    if os.environ.get("CHECK_HOOK_FAST") == "1":
        cmd.append("--fast")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0:
        return 0
    failures = [line for line in res.stdout.splitlines() if line.startswith("FAIL ")]
    print("scripts/check failed:\n" + "\n".join(failures), file=sys.stderr)
    if payload.get("stop_hook_active"):
        print("Not blocking again; fix these before you finish.", file=sys.stderr)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
```

Then: `chmod +x scripts/check-hook`

Create `.claude/settings.json`:

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "\"$CLAUDE_PROJECT_DIR\"/scripts/check-hook",
            "timeout": 120
          }
        ]
      }
    ]
  }
}
```

In `scripts/check`, add `".claude/settings.json",` as the first entry of `JSON_FILES`.

- [ ] **Step 4: Run the tests to verify they pass**

`copy_repo` copies only files `git ls-files` lists, and the `json` check now
reads `.claude/settings.json` in the copy, so stage the new files first:

Run: `git add .claude/settings.json scripts/check-hook && python3 -m unittest tests.test_check -v`
Expected: 19 tests, OK.

- [ ] **Step 5: Run the full check**

Run: `scripts/check`
Expected: all seven `PASS` lines, exit 0.

- [ ] **Step 6: Commit**

```bash
git add scripts/check scripts/check-hook .claude/settings.json tests/test_check.py
git commit -m "feat: Stop hook that blocks while scripts/check fails"
```

---

### Task 8: CI workflow

**Files:**
- Create: `.github/workflows/check.yml`

- [ ] **Step 1: Write the workflow**

```yaml
name: check

on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Git identity for tests that commit
        run: |
          git config --global user.email ci@example.com
          git config --global user.name ci
      - run: scripts/check
```

- [ ] **Step 2: Validate it parses and passes the repo check**

Run: `python3 -c "import pathlib; t=pathlib.Path('.github/workflows/check.yml').read_text(); assert 'scripts/check' in t and '\t' not in t; print('ok')"`
Expected: `ok`. (No YAML library is installed; GitHub validates the syntax on push.)

Run: `git add .github/workflows/check.yml && scripts/check --fast`
Expected: six `PASS` lines, exit 0.

- [ ] **Step 3: Commit**

```bash
git commit -m "ci: run scripts/check on push and pull request"
```

---

### Task 9: AGENTS.md, CLAUDE.md, README

**Files:**
- Create: `AGENTS.md`
- Create: `CLAUDE.md`
- Modify: `README.md` (add a section before `## Layout`)

- [ ] **Step 1: Write `AGENTS.md`**

````markdown
# Agent instructions for superpowers-factory

A Claude Code plugin: Superpowers designs a feature, and a vendored software
factory builds each approved plan as one PR. See `README.md` for what users do.

## Map

- `skills/factory-install`, `skills/factory-handoff`: this plugin's skills.
- `vendor/factory/`: the vendored factory, with edits. `factory/bin/job` is the
  job state machine; `factory/config.json` holds models, efforts and routing;
  `.claude/skills/factory` is the orchestrator; `.claude/agents/` the agents.
- `tests/`: stdlib `unittest`. `tests/factory_project.py` builds a throwaway
  project with a bare origin.
- `scripts/check`: every repo rule. `scripts/check-hook`: the Stop hook.
- `docs/superpowers/specs`, `docs/superpowers/plans`: approved designs and plans.

## Invariants

- `factory/bin/job` is the only writer of `job.json`.
- Factory code and scripts use the Python standard library only. Ask before
  adding any dependency.
- No agent or skill frontmatter sets `model`. Models and efforts come from
  `factory/config.json` (`model_aliases`, `effort_levels`, `agents`,
  `routing`, `surface_reviewers`).
- Keep `LICENSE` (GPLv3) and `vendor/factory/NOTICE`. Every commit after the
  unmodified import counts as a modification, so make vendored edits in their
  own commits.
- No upstream branding anywhere; `scripts/check` enforces it.
- Superpowers core is never modified; this plugin only uses its skills.

## Workflow

- Run `scripts/check` before saying work is done. `scripts/check --fast`
  skips the unit tests. The Stop hook runs it for you when the tree has changes.
- New features: `superpowers:brainstorming` → spec in `docs/superpowers/specs`,
  `superpowers:writing-plans` → plan in `docs/superpowers/plans`, then TDD.
- Bug fixes get a regression test in `tests/`.
- Don't commit or push unless asked. Never force-push without confirmation.
````

- [ ] **Step 2: Write `CLAUDE.md`**

```markdown
@AGENTS.md
```

- [ ] **Step 3: Add to `README.md`, before `## Layout`**

```markdown
## Working on this repo

Agents and contributors: read `AGENTS.md`, and run `scripts/check` before
calling a change done. CI runs the same script.

```

- [ ] **Step 4: Run the full check**

Run: `git add AGENTS.md CLAUDE.md README.md && scripts/check`
Expected: all seven `PASS` lines, exit 0.

- [ ] **Step 5: Commit**

```bash
git commit -m "docs: add AGENTS.md and CLAUDE.md for agents working on this repo"
```
