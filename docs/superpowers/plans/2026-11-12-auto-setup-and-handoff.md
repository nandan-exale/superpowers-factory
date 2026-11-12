# Auto Setup and Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The plugin's own SessionStart hook offers `/factory-install` or `/factory-update` where needed and adds the factory as a third execution option in factory projects; an install manifest makes updates safe.

**Architecture:** Plugin-side stdlib scripts share one module, `bin/factory_files.py` (the vendored file list and hashes). `bin/factory-manifest` writes `factory/manifest.json` into a project; `hooks/factory-session` (registered in `hooks/hooks.json`) prints `additionalContext`; `bin/factory-state` records a declined offer; `bin/factory-update-plan` classifies and applies updates; a new `factory-update` skill drives merges with the user.

**Tech Stack:** Python 3.11 stdlib, `unittest`, git.

Spec: `docs/superpowers/specs/2026-11-12-auto-setup-and-handoff-design.md`.
Run from `/Users/nandanthakur/projects/superpowers-factory`. Commit messages end
with a blank line and the `Co-Authored-By` trailer you were given. All plugin
scripts honor `FACTORY_VENDOR_DIR` (default: the plugin's `vendor/factory`) so
tests can stand in a modified "upstream".

---

## File structure

| File | Change |
|---|---|
| `bin/factory_files.py` | create: file list, hashes, manifest data |
| `bin/factory-manifest` | create |
| `bin/factory-state` | create |
| `bin/factory-update-plan` | create |
| `hooks/hooks.json`, `hooks/factory-session` | create |
| `skills/factory-update/SKILL.md` | create |
| `skills/factory-install/SKILL.md`, `README.md` | modify |
| `vendor/factory/factory/bin/doctor` | `files` check requires the manifest |
| `tests/installed_project.py` | write the manifest |
| `scripts/check` | compile and JSON-check the new plugin files |
| `tests/test_factory_manifest.py`, `tests/test_factory_session.py`, `tests/test_factory_update.py` | create |

---

### Task 1: Shared file list and `factory-manifest`

**Files:**
- Create: `bin/factory_files.py`, `bin/factory-manifest`, `tests/test_factory_manifest.py`
- Modify: `scripts/check`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_factory_manifest.py`:

```python
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bin"))

import factory_files as ff  # noqa: E402


class ManifestTest(unittest.TestCase):
    def test_every_listed_file_exists_in_vendor(self):
        for rel in ff.FILES:
            self.assertTrue((ff.VENDOR / rel).is_file(), rel)

    def test_install_skill_copies_every_listed_file(self):
        text = (REPO / "skills/factory-install/SKILL.md").read_text()
        for rel in ff.FILES:
            self.assertIn(rel, text)

    def test_vendor_hash_is_deterministic_and_content_sensitive(self):
        self.assertEqual(ff.vendor_hash(), ff.vendor_hash())
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "factory"
            shutil.copytree(ff.VENDOR, copy)
            self.assertEqual(ff.vendor_hash(copy), ff.vendor_hash())
            (copy / "factory/bin/job").write_text("changed\n")
            self.assertNotEqual(ff.vendor_hash(copy), ff.vendor_hash())

    def test_manifest_records_vendored_hashes(self):
        data = ff.manifest_data()
        self.assertEqual(data["vendor_hash"], ff.vendor_hash())
        self.assertEqual(set(data["files"]), set(ff.FILES))
        for rel in ff.FILES:
            want = hashlib.sha256((ff.VENDOR / rel).read_bytes()).hexdigest()
            self.assertEqual(data["files"][rel], want)

    def test_script_writes_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "factory").mkdir()
            res = subprocess.run([sys.executable, str(REPO / "bin/factory-manifest"), tmp],
                                 capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, res.stderr)
            written = json.loads((Path(tmp) / "factory/manifest.json").read_text())
            self.assertEqual(written, ff.manifest_data())

    def test_script_refuses_without_factory_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = subprocess.run([sys.executable, str(REPO / "bin/factory-manifest"), tmp],
                                 capture_output=True, text=True)
            self.assertEqual(res.returncode, 1)
            self.assertIn("has no factory/ directory", res.stderr)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest discover -s tests -p 'test_factory_manifest.py' -v`
Expected: `ModuleNotFoundError: No module named 'factory_files'`.

- [ ] **Step 3: Implement**

Create `bin/factory_files.py`:

```python
"""The vendored factory files /factory-install copies, and hashes over them."""

import hashlib
import os
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
VENDOR = PLUGIN / "vendor" / "factory"
MANIFEST = "factory/manifest.json"
AGENTS = ("intake", "spec-writer", "builder", "reviewer-code",
          "reviewer-security", "reviewer-ux", "reviewer-ui", "approver")
FILES = (
    ".claude/skills/factory/SKILL.md",
    *(f".claude/agents/{name}.md" for name in AGENTS),
    "factory/config.json",
    "factory/checks.sh",
    "factory/bin/job",
    "factory/bin/gate",
    "factory/bin/route",
    "factory/bin/stop-hook",
    "factory/bin/doctor",
    "factory/bin/runner",
    "factory/runner-settings.json",
    "factory/dashboard.html",
)


def vendor_dir():
    """The vendored factory, or $FACTORY_VENDOR_DIR (tests stand in a changed upstream)."""
    return Path(os.environ.get("FACTORY_VENDOR_DIR") or VENDOR)


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def vendor_hash(vendor=None):
    """One hash over every vendored file's path and content."""
    vendor = Path(vendor or vendor_dir())
    digest = hashlib.sha256()
    for rel in sorted(FILES):
        digest.update(rel.encode() + b"\0" + (vendor / rel).read_bytes() + b"\0")
    return digest.hexdigest()


def manifest_data(vendor=None):
    vendor = Path(vendor or vendor_dir())
    return {"vendor_hash": vendor_hash(vendor),
            "files": {rel: sha256_file(vendor / rel) for rel in FILES}}
```

Create `bin/factory-manifest`:

```python
#!/usr/bin/env python3
"""Write <project>/factory/manifest.json from the plugin's vendored factory files.

Usage: factory-manifest <project>
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from factory_files import MANIFEST, manifest_data  # noqa: E402


def write_manifest(project):
    path = Path(project) / MANIFEST
    path.write_text(json.dumps(manifest_data(), indent=2, sort_keys=True) + "\n")
    return path


def main(argv):
    if len(argv) != 1:
        print(__doc__.strip(), file=sys.stderr)
        return 1
    project = Path(argv[0]).resolve()
    if not (project / "factory").is_dir():
        print(f"factory-manifest: {project} has no factory/ directory", file=sys.stderr)
        return 1
    print(write_manifest(project))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

`chmod +x bin/factory-manifest`

In `scripts/check`:

1. Add `"hooks/hooks.json",` to `JSON_FILES`.
2. In `check_compile`, after the vendored-bin loop, add:

```python
    for rel in ("bin/factory_files.py", "bin/factory-manifest", "bin/factory-state",
                "bin/factory-update-plan", "hooks/factory-session"):
        path = root / rel
        if not path.exists():
            continue  # added by later tasks; JSON and test checks cover their absence
        try:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
        except SyntaxError as exc:
            problems.append(f"{rel}: {exc}")
```

Until Task 2 creates `hooks/hooks.json`, the `json` check would fail, so create
it now with the Task 2 contents:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|clear|compact",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/factory-session\"",
            "async": false
          }
        ]
      }
    ]
  }
}
```

and `hooks/factory-session` as a no-op until Task 2:

```python
#!/usr/bin/env python3
"""SessionStart hook. Implemented in the next task; prints nothing."""

import sys

sys.exit(0)
```

`chmod +x hooks/factory-session`

- [ ] **Step 4: Run tests, suite and repo check**

Run: `python3 -m unittest discover -s tests -p 'test_factory_manifest.py' -v`
Expected: 6 tests, OK.

Run: `git add -A bin hooks scripts/check tests/test_factory_manifest.py && python3 -m unittest discover -s tests -q && scripts/check`
Expected: OK; seven `PASS` lines.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: factory file list, vendor hash and factory-manifest"
```

---

### Task 2: `factory-state` and the SessionStart hook

**Files:**
- Create: `bin/factory-state`, `tests/test_factory_session.py`
- Modify (replace no-op): `hooks/factory-session`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_factory_session.py`:

```python
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bin"))

import factory_files as ff  # noqa: E402

HOOK = REPO / "hooks/factory-session"
STATE = REPO / "bin/factory-state"


def clean_env(**extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "FACTORY_", "CLAUDE_"))}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", **extra)
    return env


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          env=clean_env(), check=True).stdout


class SessionHookTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "project"
        self.root.mkdir()
        git(self.root, "init", "-q")
        git(self.root, "remote", "add", "origin", "https://github.com/o/r.git")

    def install(self, manifest=True):
        for rel in ff.FILES:
            target = self.root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ff.VENDOR / rel, target)
        if manifest:
            (self.root / ff.MANIFEST).write_text(json.dumps(ff.manifest_data()))

    def hook(self, **env):
        res = subprocess.run([sys.executable, str(HOOK)], input="{}", capture_output=True, text=True,
                             env=clean_env(CLAUDE_PROJECT_DIR=str(self.root), **env))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stderr, "")
        if not res.stdout.strip():
            return None
        out = json.loads(res.stdout)
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "SessionStart")
        return out["hookSpecificOutput"]["additionalContext"]

    def test_not_a_git_repo_is_silent(self):
        shutil.rmtree(self.root / ".git")
        self.assertIsNone(self.hook())

    def test_non_github_origin_is_silent(self):
        git(self.root, "remote", "set-url", "origin", "https://gitlab.com/o/r.git")
        self.assertIsNone(self.hook())

    def test_not_installed_offers_install_once(self):
        text = self.hook()
        self.assertIn("/factory-install", text)
        self.assertIn(f'"{STATE}" decline', text)
        self.assertNotIn("/factory-update", text)

    def test_declined_is_silent(self):
        res = subprocess.run([sys.executable, str(STATE), "decline"], cwd=self.root,
                             capture_output=True, text=True, env=clean_env())
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIsNone(self.hook())
        self.assertEqual(git(self.root, "status", "--porcelain"), "")

    def test_reset_brings_the_offer_back(self):
        for cmd in ("decline", "reset"):
            subprocess.run([sys.executable, str(STATE), cmd], cwd=self.root, env=clean_env(), check=True)
        self.assertIn("/factory-install", self.hook())

    def test_missing_manifest_offers_update_and_option_3(self):
        self.install(manifest=False)
        text = self.hook()
        self.assertIn("/factory-update", text)
        self.assertIn("3. Factory", text)

    def test_stale_manifest_offers_update(self):
        self.install()
        data = json.loads((self.root / ff.MANIFEST).read_text())
        data["vendor_hash"] = "0" * 64
        (self.root / ff.MANIFEST).write_text(json.dumps(data))
        self.assertIn("/factory-update", self.hook())

    def test_current_install_offers_option_3_only(self):
        self.install()
        text = self.hook()
        self.assertIn("3. Factory", text)
        self.assertIn("/factory-handoff", text)
        self.assertNotIn("/factory-update", text)
        self.assertNotIn("/factory-install", text)

    def test_unreadable_manifest_counts_as_outdated(self):
        self.install(manifest=False)
        (self.root / ff.MANIFEST).mkdir()
        self.assertIn("/factory-update", self.hook())

    def test_internal_error_prints_nothing(self):
        self.install()
        self.assertIsNone(self.hook(FACTORY_VENDOR_DIR=str(self.root / "no-such-dir")))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest discover -s tests -p 'test_factory_session.py' -v`
Expected: most tests fail (the hook prints nothing; `factory-state` doesn't exist).

- [ ] **Step 3: Implement**

Create `bin/factory-state`:

```python
#!/usr/bin/env python3
"""Stop or restart the plugin's offer to install the factory in this clone.

Usage (inside the project):
  factory-state decline   stop offering /factory-install here
  factory-state reset     offer it again
"""

import subprocess
import sys
from pathlib import Path


def marker():
    res = subprocess.run(["git", "rev-parse", "--git-path", "factory-declined"],
                         capture_output=True, text=True)
    if res.returncode != 0:
        print("factory-state: not inside a git repository", file=sys.stderr)
        sys.exit(1)
    return Path(res.stdout.strip()).resolve()


def main(argv):
    if argv == ["decline"]:
        marker().write_text("declined\n")
        print("factory-state: won't offer /factory-install in this clone again")
        return 0
    if argv == ["reset"]:
        marker().unlink(missing_ok=True)
        print("factory-state: /factory-install will be offered again")
        return 0
    print(__doc__.strip(), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

`chmod +x bin/factory-state`

Replace `hooks/factory-session` with:

```python
#!/usr/bin/env python3
"""SessionStart hook: tell Claude whether to offer the factory, an update, or the factory handoff.

Prints one hook JSON object with additionalContext, or nothing. Never writes files.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "bin"))

STATE = PLUGIN / "bin" / "factory-state"
INSTALL = (
    "superpowers-factory: this GitHub project doesn't have the software factory installed. "
    "Once, early in this session and only if you haven't asked already, ask the user whether to run "
    "/factory-install (it sets up an unattended build pipeline for GitHub issues). If they decline, run "
    f'"{STATE}" decline so you stop asking in this clone.'
)
UPDATE = (
    "superpowers-factory: the software factory installed in this project is older than the plugin. "
    "Once in this session, offer to run /factory-update (it shows every change and never commits)."
)
HANDOFF = (
    "superpowers-factory: this project has the software factory. When superpowers:writing-plans "
    "offers its execution choice, add a third option: \"3. Factory — file this plan as a "
    "factory:planned issue and let the factory build it unattended (/factory-handoff)\". If the user "
    "picks it, invoke the factory-handoff skill. factory/bin/doctor checks the install."
)


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def context(start):
    from factory_files import MANIFEST, vendor_hash

    if git(start, "rev-parse", "--is-inside-work-tree").stdout.strip() != "true":
        return None
    top = Path(git(start, "rev-parse", "--show-toplevel").stdout.strip())
    if "github.com" not in git(top, "remote", "get-url", "origin").stdout:
        return None
    if not (top / "factory" / "bin" / "job").is_file():
        declined = top / git(top, "rev-parse", "--git-path", "factory-declined").stdout.strip()
        return None if declined.exists() else INSTALL
    try:
        installed = json.loads((top / MANIFEST).read_text()).get("vendor_hash")
    except (OSError, ValueError, AttributeError):
        installed = None
    current = vendor_hash()
    return HANDOFF if installed == current else f"{UPDATE}\n\n{HANDOFF}"


def main():
    sys.stdin.read()
    try:
        text = context(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    except Exception:  # a broken plugin hook must never disturb the user's session
        return 0
    if text:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                                 "additionalContext": text}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

`hooks/hooks.json` already holds the registration from Task 1.

- [ ] **Step 4: Run tests and suite**

Run: `python3 -m unittest discover -s tests -p 'test_factory_session.py' -v`
Expected: 10 tests, OK.

Run: `python3 -m unittest discover -s tests -q && scripts/check`
Expected: OK; seven `PASS` lines.

- [ ] **Step 5: Commit**

```bash
git add bin/factory-state hooks/factory-session tests/test_factory_session.py
git commit -m "feat: plugin SessionStart hook offers install, update and factory handoff"
```

---

### Task 3: `factory-update-plan`

**Files:**
- Create: `bin/factory-update-plan`, `tests/test_factory_update.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_factory_update.py`:

```python
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bin"))

import factory_files as ff  # noqa: E402

PLAN = REPO / "bin/factory-update-plan"


class UpdatePlanTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.vendor = Path(tmp.name) / "vendor"
        shutil.copytree(ff.VENDOR, self.vendor)
        self.project = Path(tmp.name) / "project"
        for rel in ff.FILES:
            target = self.project / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.vendor / rel, target)
        (self.project / ff.MANIFEST).write_text(json.dumps(ff.manifest_data(self.vendor)))

    def run_plan(self, *args):
        env = {**os.environ, "FACTORY_VENDOR_DIR": str(self.vendor)}
        res = subprocess.run([sys.executable, str(PLAN), str(self.project), *args],
                             capture_output=True, text=True, env=env)
        groups = dict(reversed(line.split("\t")) for line in res.stdout.splitlines() if "\t" in line)
        return res, groups

    def upstream(self, rel, text):
        (self.vendor / rel).write_text(text)

    def local(self, rel, text):
        (self.project / rel).write_text(text)

    def test_fresh_install_is_all_unchanged_except_special_files(self):
        res, groups = self.run_plan()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(groups["factory/checks.sh"], "owned")
        self.assertEqual(groups["factory/config.json"], "config")
        self.assertEqual(groups["factory/runner-settings.json"], "settings")
        self.assertEqual(groups["factory/bin/job"], "unchanged")

    def test_groups(self):
        self.upstream("factory/bin/route", "# upstream route\n")
        self.upstream("factory/bin/gate", "# upstream gate\n")
        self.local("factory/bin/gate", "# my gate\n")
        self.local(".claude/agents/reviewer-ui.md", "my tailored reviewer\n")
        (self.project / "factory/dashboard.html").unlink()
        _, groups = self.run_plan()
        self.assertEqual(groups["factory/bin/route"], "safe")
        self.assertEqual(groups["factory/bin/gate"], "merge")
        self.assertEqual(groups[".claude/agents/reviewer-ui.md"], "unchanged")
        self.assertEqual(groups["factory/dashboard.html"], "new")

    def test_apply_safe(self):
        self.upstream("factory/bin/route", "# upstream route\n")
        (self.vendor / "factory/bin/route").chmod(0o755)
        self.upstream("factory/bin/gate", "# upstream gate\n")
        self.local("factory/bin/gate", "# my gate\n")
        self.upstream("factory/checks.sh", "# upstream checks\n")
        self.local("factory/checks.sh", "# my checks\n")
        (self.project / "factory/dashboard.html").unlink()
        res, _ = self.run_plan("--apply-safe")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual((self.project / "factory/bin/route").read_text(), "# upstream route\n")
        self.assertTrue(os.access(self.project / "factory/bin/route", os.X_OK))
        self.assertEqual((self.project / "factory/bin/gate").read_text(), "# my gate\n")
        self.assertEqual((self.project / "factory/checks.sh").read_text(), "# my checks\n")
        self.assertTrue((self.project / "factory/dashboard.html").exists())

    def test_config_merge_adds_keys_and_keeps_values(self):
        cfg = json.loads((self.vendor / "factory/config.json").read_text())
        cfg["new_section"] = {"x": 1}
        cfg["budgets"]["new_limit"] = 5
        cfg["concurrency"] = 99
        (self.vendor / "factory/config.json").write_text(json.dumps(cfg))
        mine = json.loads((self.project / "factory/config.json").read_text())
        mine["concurrency"] = 1
        (self.project / "factory/config.json").write_text(json.dumps(mine))
        self.run_plan("--apply-safe")
        merged = json.loads((self.project / "factory/config.json").read_text())
        self.assertEqual(merged["concurrency"], 1)
        self.assertEqual(merged["new_section"], {"x": 1})
        self.assertEqual(merged["budgets"]["new_limit"], 5)

    def test_settings_keep_added_domains(self):
        path = "factory/runner-settings.json"
        mine = json.loads((self.project / path).read_text())
        mine["sandbox"]["network"]["allowedDomains"].append("registry.npmjs.org")
        (self.project / path).write_text(json.dumps(mine))
        upstream = json.loads((self.vendor / path).read_text())
        upstream["permissions"]["deny"].append("Bash(rm -rf /*)")
        (self.vendor / path).write_text(json.dumps(upstream))
        self.run_plan("--apply-safe")
        merged = json.loads((self.project / path).read_text())
        self.assertIn("registry.npmjs.org", merged["sandbox"]["network"]["allowedDomains"])
        self.assertIn("github.com", merged["sandbox"]["network"]["allowedDomains"])
        self.assertIn("Bash(rm -rf /*)", merged["permissions"]["deny"])

    def test_manifest_rewritten_after_apply(self):
        self.upstream("factory/bin/route", "# upstream route\n")
        self.run_plan("--apply-safe")
        manifest = json.loads((self.project / ff.MANIFEST).read_text())
        self.assertEqual(manifest, ff.manifest_data(self.vendor))
        _, groups = self.run_plan()
        self.assertEqual(groups["factory/bin/route"], "unchanged")

    def test_without_manifest_differing_files_are_merge(self):
        (self.project / ff.MANIFEST).unlink()
        self.local("factory/bin/gate", "# my gate\n")
        _, groups = self.run_plan()
        self.assertEqual(groups["factory/bin/gate"], "merge")
        self.assertEqual(groups["factory/bin/route"], "unchanged")

    def test_not_installed_refuses(self):
        (self.project / "factory/bin/job").unlink()
        res, _ = self.run_plan()
        self.assertEqual(res.returncode, 1)
        self.assertIn("run /factory-install first", res.stderr)

    def test_invalid_config_refuses_and_applies_nothing(self):
        self.upstream("factory/bin/route", "# upstream route\n")
        self.local("factory/config.json", "{not json")
        res, _ = self.run_plan("--apply-safe")
        self.assertEqual(res.returncode, 1)
        self.assertIn("factory/config.json", res.stderr)
        self.assertNotEqual((self.project / "factory/bin/route").read_text(), "# upstream route\n")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest discover -s tests -p 'test_factory_update.py' -v`
Expected: failures (the script doesn't exist).

- [ ] **Step 3: Implement**

Create `bin/factory-update-plan`:

```python
#!/usr/bin/env python3
"""Show, and optionally apply, how a project's factory differs from the plugin's.

Usage: factory-update-plan <project> [--apply-safe]

Prints `<group>\t<path>` per vendored file. Groups: new, unchanged, safe,
merge, owned (factory/checks.sh, never touched), config (factory/config.json:
missing keys added, values kept), settings (factory/runner-settings.json:
upstream file, keeping the project's extra network domains).
--apply-safe copies new and safe files, merges config and settings, and
rewrites factory/manifest.json. merge files are left for the user.
"""

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from factory_files import FILES, MANIFEST, manifest_data, sha256_file, vendor_dir  # noqa: E402

OWNED = {"factory/checks.sh"}
CONFIG = "factory/config.json"
SETTINGS = "factory/runner-settings.json"


def fail(message):
    print(f"factory-update-plan: {message}", file=sys.stderr)
    sys.exit(1)


def load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        fail(f"{path}: {exc}")


def load_manifest(project):
    try:
        return json.loads((project / MANIFEST).read_text()).get("files", {})
    except (OSError, ValueError, AttributeError):
        return None


def classify(project, vendor, base):
    rows = []
    for rel in FILES:
        if rel in OWNED:
            rows.append(("owned", rel))
        elif not (project / rel).exists():
            rows.append(("new", rel))
        elif rel == CONFIG:
            rows.append(("config", rel))
        elif rel == SETTINGS:
            rows.append(("settings", rel))
        else:
            upstream, mine = sha256_file(vendor / rel), sha256_file(project / rel)
            was = (base or {}).get(rel)
            if was is None:
                rows.append(("unchanged" if mine == upstream else "merge", rel))
            elif upstream == was:
                rows.append(("unchanged", rel))
            elif mine == was:
                rows.append(("safe", rel))
            else:
                rows.append(("merge", rel))
    return rows


def add_missing(mine, upstream):
    """Add upstream keys the project lacks, recursively; never change a project value."""
    for key, value in upstream.items():
        if key not in mine:
            mine[key] = value
        elif isinstance(mine[key], dict) and isinstance(value, dict):
            add_missing(mine[key], value)
    return mine


def merged_settings(mine, upstream):
    domains = upstream.setdefault("sandbox", {}).setdefault("network", {}).setdefault("allowedDomains", [])
    extra = ((mine.get("sandbox") or {}).get("network") or {}).get("allowedDomains") or []
    domains.extend(d for d in extra if d not in domains)
    return upstream


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2) + "\n")


def apply_safe(project, vendor, rows):
    groups = dict((rel, group) for group, rel in rows)
    # Parse everything first, so a bad file applies nothing.
    config = settings = None
    if groups.get(CONFIG) == "config":
        config = add_missing(load_json(project / CONFIG), load_json(vendor / CONFIG))
    if groups.get(SETTINGS) == "settings":
        settings = merged_settings(load_json(project / SETTINGS), load_json(vendor / SETTINGS))
    for group, rel in rows:
        src, dst = vendor / rel, project / rel
        if group in ("new", "safe"):
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            if rel.startswith("factory/bin/"):
                dst.chmod(0o755)
    if config is not None and config != load_json(project / CONFIG):
        write_json(project / CONFIG, config)
    if settings is not None and settings != load_json(project / SETTINGS):
        write_json(project / SETTINGS, settings)
    write_json(project / MANIFEST, manifest_data(vendor))


def main(argv):
    if not argv or len(argv) > 2 or (len(argv) == 2 and argv[1] != "--apply-safe"):
        print(__doc__.strip(), file=sys.stderr)
        return 1
    project, vendor = Path(argv[0]).resolve(), vendor_dir()
    if not (project / "factory" / "bin" / "job").is_file():
        fail(f"{project} has no factory installed; run /factory-install first")
    rows = classify(project, vendor, load_manifest(project))
    for group, rel in rows:
        print(f"{group}\t{rel}")
    if len(argv) == 2:
        apply_safe(project, vendor, rows)
        print(f"applied: new and safe files copied, config and settings merged, {MANIFEST} rewritten")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

`chmod +x bin/factory-update-plan`

Note: `write_json` for the manifest uses `indent=2` without `sort_keys`, unlike
`factory-manifest`; both produce equal JSON objects, which is what the tests
compare.

- [ ] **Step 4: Run tests and suite**

Run: `python3 -m unittest discover -s tests -p 'test_factory_update.py' -v`
Expected: 9 tests, OK.

Run: `python3 -m unittest discover -s tests -q && scripts/check`
Expected: OK; seven `PASS` lines.

- [ ] **Step 5: Commit**

```bash
git add bin/factory-update-plan tests/test_factory_update.py
git commit -m "feat: factory-update-plan classifies and applies factory updates"
```

---

### Task 4: Skills, doctor, test helper, README

**Files:**
- Create: `skills/factory-update/SKILL.md`
- Modify: `skills/factory-install/SKILL.md`, `README.md`, `vendor/factory/factory/bin/doctor`, `tests/installed_project.py`, `tests/test_doctor.py`

- [ ] **Step 1: Write the failing test**

Add to `DoctorTest` in `tests/test_doctor.py`:

```python
    def test_missing_manifest_fails(self):
        (self.p.root / "factory/manifest.json").unlink()
        self.assertFails("files", "factory/manifest.json missing")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest discover -s tests -p 'test_doctor.py' -v`
Expected: `test_missing_manifest_fails` errors (`FileNotFoundError`: the helper writes no manifest).

- [ ] **Step 3: Implement**

In `tests/installed_project.py`'s `InstalledProject.__init__`, after the
`COPIED` copy loop, add:

```python
        subprocess.run([sys.executable, str(PLUGIN / "bin" / "factory-manifest"), str(self.root)],
                       check=True, capture_output=True)
```

In `vendor/factory/factory/bin/doctor`'s `check_files`, after the SKILL.md
check, add:

```python
    if not (REPO / "factory" / "manifest.json").is_file():
        problems.append(fail("factory/manifest.json missing; run /factory-update to write it"))
```

Create `skills/factory-update/SKILL.md`:

````markdown
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
     plugin's, keeping this project's extra network domains;
   - `merge`: changed both here and upstream, decided one by one below;
   - `owned`, `unchanged`: left alone.
2. Ask your human partner to go ahead. On yes, run
   `"$BIN/factory-update-plan" . --apply-safe`.
3. For each `merge` file: show `diff -u <project file> <plugin vendor file>`
   (the vendor file is `<skill base>/../../vendor/factory/<path>`), say in
   one line what upstream changed and what the project changed, and ask:
   keep the project's version, take upstream's, or merge both. For "merge
   both", edit the project file to carry upstream's change into the
   project's version, then show the result.
4. Run `factory/bin/doctor --fast` and report any FAIL or WARN.
5. Show `git status` and `git diff --stat`, suggest the message
   `chore: update software factory`, and stop. Don't commit or push.
````

In `skills/factory-install/SKILL.md`, add after the **Step 1 (Copy)** bullet:

```markdown
- **Step 1 (Copy), manifest:** right after copying, before adapting any file,
  run `"<skill base>/../../bin/factory-manifest" .`. It records each copied
  file's pristine hash in `factory/manifest.json` (commit it with the
  install), so `/factory-update` can tell your adaptations from upstream
  changes later.
```

In `README.md`, add before `## Hands-off running`:

```markdown
## Automatic setup and updates

With the plugin enabled, a session in any GitHub project starts with a
check:

- no factory: Claude offers `/factory-install` once (decline, and it stops
  asking in that clone; `bin/factory-state reset` brings the offer back);
- factory older than the plugin: Claude offers `/factory-update`, which
  copies what you haven't changed, merges `config.json` keys, keeps your
  `checks.sh`, and walks you through files changed on both sides;
- factory current: when writing-plans asks how to execute a plan, the
  factory is option 3, which files it with `/factory-handoff`.

Nothing is installed, updated or committed without your yes.
```

- [ ] **Step 4: Run every test and the repo check**

Run: `python3 -m unittest discover -s tests -q && scripts/check`
Expected: OK; seven `PASS` lines (the frontmatter check covers the new skill).

- [ ] **Step 5: Commit**

```bash
git add skills/factory-update/SKILL.md skills/factory-install/SKILL.md README.md vendor/factory/factory/bin/doctor tests/installed_project.py tests/test_doctor.py
git commit -m "feat: factory-update skill, manifest at install, doctor requires the manifest"
```
