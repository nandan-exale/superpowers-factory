# Phase 1 Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the rough edges from the first real run (no-manifest updates, stale main after merge, one-off network failures) and add `/factory-uninstall` plus a repeatable release process.

**Architecture:** Plugin-side Python scripts in `bin/` and `scripts/` (stdlib only), one new plugin skill, and two small edits to the vendored `vendor/factory/factory/bin/job`. Vendored edits go in their own commits, never mixed with plugin-side files (AGENTS.md rule).

**Tech Stack:** Python 3.11 stdlib, `unittest`, git, gh CLI (faked in tests).

**Spec:** `docs/superpowers/specs/2026-11-13-phase1-hardening-design.md`

**Repo:** `/Users/nandanthakur/projects/superpowers-factory`. Run everything from there. Full check: `scripts/check`. One test file: `python3 -m unittest tests/test_x.py -v` (run from the repo root; tests insert `bin/` and `tests/` on `sys.path` themselves).

Every commit message ends with a blank line and:
`Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`

---

## File map

| File | Change | Responsibility |
|---|---|---|
| `bin/factory_files.py` | modify | `known_hashes()` reader |
| `scripts/known-hashes` | create | generate / `--check` `vendor/known-hashes.json` |
| `vendor/known-hashes.json` | create (generated) | every hash each vendored file has had |
| `bin/factory-update-plan` | modify | no-manifest-entry file matching a known hash → `safe` |
| `scripts/check` | modify | `hashes` check, version-match in `json`, compile new scripts |
| `vendor/factory/factory/bin/job` | modify (2 vendored commits) | `run_net` retries; `sync_main` after merge |
| `tests/factory_project.py` | modify | zero retry waits in tests |
| `bin/factory-uninstall-settings` | create | remove only the factory Stop hook from settings |
| `skills/factory-uninstall/SKILL.md` | create | the uninstall procedure |
| `hooks/factory-session` | modify | mention `/factory-uninstall` |
| `README.md`, `AGENTS.md` | modify | Uninstall and Releasing docs |
| `CHANGELOG.md` | create | 0.1.0 and 0.2.0 history |
| `scripts/release` | create | bump, changelog, check, commit, tag |
| `tests/test_known_hashes.py`, `tests/test_factory_update_known.py`, `tests/test_net_retry.py`, `tests/test_sync_main.py`, `tests/test_factory_uninstall_settings.py`, `tests/test_release.py` | create | tests |

---

### Task 1: Known-hash list and its check

**Files:**
- Modify: `bin/factory_files.py`
- Create: `scripts/known-hashes`, `vendor/known-hashes.json` (generated)
- Modify: `scripts/check`
- Test: `tests/test_known_hashes.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_known_hashes.py`:

```python
import hashlib
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

SCRIPT = REPO / "scripts/known-hashes"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def shallow():
    res = subprocess.run(["git", "rev-parse", "--is-shallow-repository"], cwd=REPO,
                         capture_output=True, text=True)
    return res.stdout.strip() == "true"


class KnownHashesFileTest(unittest.TestCase):
    def test_every_current_vendored_file_is_listed(self):
        data = json.loads((REPO / "vendor/known-hashes.json").read_text())
        for rel in ff.FILES:
            self.assertIn(ff.sha256_file(ff.VENDOR / rel), data[rel], rel)

    @unittest.skipIf(shallow(), "needs full git history")
    def test_history_gives_job_more_than_one_version(self):
        data = json.loads((REPO / "vendor/known-hashes.json").read_text())
        self.assertGreater(len(data["factory/bin/job"]), 1)

    def test_reader_returns_empty_for_a_missing_file(self):
        env = os.environ.get("FACTORY_KNOWN_HASHES")
        os.environ["FACTORY_KNOWN_HASHES"] = "/nonexistent/known.json"
        try:
            self.assertEqual(ff.known_hashes(), {})
        finally:
            if env is None:
                del os.environ["FACTORY_KNOWN_HASHES"]
            else:
                os.environ["FACTORY_KNOWN_HASHES"] = env

    def test_reader_returns_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "k.json"
            path.write_text('{"factory/bin/gate": ["abc"]}')
            os.environ["FACTORY_KNOWN_HASHES"] = str(path)
            try:
                self.assertEqual(ff.known_hashes(), {"factory/bin/gate": ["abc"]})
            finally:
                del os.environ["FACTORY_KNOWN_HASHES"]


class CheckModeTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        shutil.copytree(REPO / "vendor", self.root / "vendor")

    def check(self):
        return subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), "--check"],
                              capture_output=True, text=True)

    def test_check_passes_when_current_versions_are_listed(self):
        res = self.check()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_check_fails_when_a_vendored_file_changed(self):
        path = self.root / "vendor/factory/factory/bin/gate"
        path.write_text(path.read_text() + "# edited\n")
        res = self.check()
        self.assertEqual(res.returncode, 1)
        self.assertIn("factory/bin/gate", res.stdout)

    def test_check_fails_when_the_list_is_missing(self):
        (self.root / "vendor/known-hashes.json").unlink()
        self.assertEqual(self.check().returncode, 1)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest tests/test_known_hashes.py -v`
Expected: errors (`vendor/known-hashes.json` missing, `ff.known_hashes` undefined, script missing).

- [ ] **Step 3: Add the reader to `bin/factory_files.py`**

After the `MANIFEST = ...` line add:

```python
KNOWN_HASHES = PLUGIN / "vendor" / "known-hashes.json"
```

After `vendor_dir()` add:

```python
def known_hashes():
    """{rel: [sha256, ...]}: every version each vendored file has had, from the plugin's history.
    {} when the list is missing or unreadable. $FACTORY_KNOWN_HASHES points elsewhere (tests)."""
    path = Path(os.environ.get("FACTORY_KNOWN_HASHES") or KNOWN_HASHES)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
```

- [ ] **Step 4: Create `scripts/known-hashes`** (then `chmod +x scripts/known-hashes`)

```python
#!/usr/bin/env python3
"""Write vendor/known-hashes.json: the SHA-256 of every version each vendored factory file has had.

/factory-update uses it to recognise an unedited old copy in a project whose manifest
has no entry for a file.

Usage: scripts/known-hashes [--root DIR] [--check]
  --check  don't write; exit 1 if a current vendored file's hash is missing from the list
"""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bin"))

from factory_files import FILES  # noqa: E402

OUT = Path("vendor/known-hashes.json")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def versions(root, rel):
    """Sorted hashes of every committed version of vendor/factory/<rel>, plus the working copy."""
    path = f"vendor/factory/{rel}"
    log = subprocess.run(["git", "log", "--format=%H", "--", path], cwd=root,
                         capture_output=True, text=True, check=True)
    hashes = set()
    for commit in log.stdout.split():
        blob = subprocess.run(["git", "show", f"{commit}:{path}"], cwd=root, capture_output=True)
        if blob.returncode == 0:  # a commit that deleted the file has no blob
            hashes.add(sha(blob.stdout))
    current = root / path
    if current.is_file():
        hashes.add(sha(current.read_bytes()))
    return sorted(hashes)


def generate(root):
    return {rel: versions(root, rel) for rel in sorted(FILES)}


def missing(root):
    """Problems with the list on disk: unreadable, or a current version not in it."""
    try:
        data = json.loads((root / OUT).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"{OUT}: {exc}"]
    problems = []
    for rel in sorted(FILES):
        if sha((root / "vendor/factory" / rel).read_bytes()) not in data.get(rel, []):
            problems.append(f"{rel}: current version isn't in {OUT}; run scripts/known-hashes")
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=REPO)
    parser.add_argument("--check", action="store_true")
    opts = parser.parse_args(argv)
    root = opts.root.resolve()
    if opts.check:
        problems = missing(root)
        for problem in problems:
            print(problem)
        return 1 if problems else 0
    (root / OUT).write_text(json.dumps(generate(root), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Generate the list**

Run: `scripts/known-hashes`
Expected: `wrote vendor/known-hashes.json`.

- [ ] **Step 6: Add the `hashes` check to `scripts/check`**

After `check_compile` add:

```python
def check_hashes(root, opts):
    res = subprocess.run([sys.executable, str(REPO / "scripts" / "known-hashes"), "--root", str(root), "--check"],
                         capture_output=True, text=True)
    if res.returncode == 0:
        return []
    return res.stdout.strip().splitlines() or [res.stderr.strip() or "known-hashes --check failed"]
```

In `CHECKS`, add `("hashes", check_hashes),` right after `("compile", check_compile),`.

In `check_compile`, extend the tuple of plugin scripts to:

```python
    for rel in ("bin/factory_files.py", "bin/factory-manifest", "bin/factory-state",
                "bin/factory-update-plan", "bin/factory-uninstall-settings", "hooks/factory-session",
                "scripts/known-hashes", "scripts/release"):
```

(The loop already skips files that don't exist yet.)

- [ ] **Step 7: Run tests and the full check**

Run: `python3 -m unittest tests/test_known_hashes.py -v` → all PASS.
Run: `scripts/check` → every line PASS, including `PASS hashes`.

- [ ] **Step 8: Commit**

```bash
git add bin/factory_files.py scripts/known-hashes vendor/known-hashes.json scripts/check tests/test_known_hashes.py
git commit -m "feat: known-hash list of every vendored file version"
```

---

### Task 2: `/factory-update` treats unedited old copies as safe

**Files:**
- Modify: `bin/factory-update-plan` (import line ~30, `classify()` ~99-126)
- Test: `tests/test_factory_update_known.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_factory_update_known.py`:

```python
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bin"))
sys.path.insert(0, str(REPO / "tests"))

import factory_files as ff  # noqa: E402
from installed_project import InstalledProject  # noqa: E402

PLAN = REPO / "bin/factory-update-plan"
GATE = "factory/bin/gate"
OLD = "# an old upstream gate\n"


class KnownHashTest(unittest.TestCase):
    """A project without a manifest entry for a file: old upstream copy vs. the project's own edit."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.p = InstalledProject(tmp.name)  # creates <tmp>/project
        (self.p.root / ff.MANIFEST).unlink()
        known = self.tmp / "known.json"
        known.write_text(json.dumps({GATE: [hashlib.sha256(OLD.encode()).hexdigest()]}))
        self.env = {**os.environ, "FACTORY_KNOWN_HASHES": str(known)}

    def plan(self, *args):
        res = subprocess.run([sys.executable, str(PLAN), str(self.p.root), *args],
                             capture_output=True, text=True, env=self.env)
        return res, dict(reversed(line.split("\t")) for line in res.stdout.splitlines() if "\t" in line)

    def test_unedited_old_copy_is_safe(self):
        (self.p.root / GATE).write_text(OLD)
        res, groups = self.plan()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(groups[GATE], "safe")

    def test_edited_copy_is_still_merge(self):
        (self.p.root / GATE).write_text("# my own gate\n")
        _, groups = self.plan()
        self.assertEqual(groups[GATE], "merge")

    def test_missing_list_keeps_merge(self):
        (self.p.root / GATE).write_text(OLD)
        self.env["FACTORY_KNOWN_HASHES"] = str(self.tmp / "nope.json")
        _, groups = self.plan()
        self.assertEqual(groups[GATE], "merge")

    def test_apply_safe_replaces_the_old_copy_and_records_it(self):
        (self.p.root / GATE).write_text(OLD)
        res, _ = self.plan("--apply-safe")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual((self.p.root / GATE).read_bytes(), (ff.VENDOR / GATE).read_bytes())
        manifest = json.loads((self.p.root / ff.MANIFEST).read_text())
        self.assertEqual(manifest["files"][GATE], ff.sha256_file(ff.VENDOR / GATE))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests/test_factory_update_known.py -v`
Expected: `test_unedited_old_copy_is_safe` and `test_apply_safe_...` FAIL (`merge` != `safe`); the other two PASS.

- [ ] **Step 3: Implement**

In `bin/factory-update-plan`, add `known_hashes` to the `from factory_files import (...)` list.

In `classify()`, add as the first line of the body:

```python
    known = known_hashes()
```

and replace

```python
            elif was is None:
                rows.append(("merge", rel))
```

with

```python
            elif was is None:
                # No record of what was installed: an exact old upstream version is unedited.
                rows.append(("safe" if mine in known.get(rel, ()) else "merge", rel))
```

Also update the module docstring line that describes `merge` to add: "A file with no manifest entry that matches a version listed in the plugin's vendor/known-hashes.json is safe."

- [ ] **Step 4: Run tests**

Run: `python3 -m unittest tests/test_factory_update_known.py tests/test_factory_update.py tests/test_factory_update_migrate.py -v`
Expected: all PASS. If `ResolvedCountTest` in `test_factory_update_migrate.py` fails, it's because its `"# old\n"` files now matter only if they're in the known list — they aren't, so it should pass; investigate rather than edit that test.

- [ ] **Step 5: Commit**

```bash
git add bin/factory-update-plan tests/test_factory_update_known.py
git commit -m "fix: factory-update treats unedited old copies as safe without a manifest"
```

---

### Task 3: Retry idempotent network calls in `job` (vendored)

**Files:**
- Modify: `vendor/factory/factory/bin/job` (`run`/`gh` ~81-99, `git()` ~849, fetches at ~1111 and ~1449)
- Modify: `tests/factory_project.py` (`load_job`)
- Test: `tests/test_net_retry.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_net_retry.py`:

```python
import importlib.machinery
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from factory_project import FactoryProject  # noqa: E402


class FakeSubprocess:
    """Stands in for job's `subprocess`: returns the queued exit codes, or raises on "timeout"."""
    TimeoutExpired = subprocess.TimeoutExpired
    CompletedProcess = subprocess.CompletedProcess

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def run(self, cmd, **kw):
        self.calls.append((cmd, kw))
        outcome = self.outcomes.pop(0)
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
        return subprocess.CompletedProcess(cmd, outcome, "", "boom" if outcome else "")


class RetryTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = FactoryProject(tmp.name)
        path = self.project.repo / "factory" / "bin" / "job"
        loader = importlib.machinery.SourceFileLoader(f"job_raw_{id(self)}", str(path))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.job = importlib.util.module_from_spec(spec)
        loader.exec_module(self.job)  # real gh/git helpers, unlike load_job()
        self.job.NET_WAITS = (0, 0, 0)

    def fake(self, *outcomes):
        fake = FakeSubprocess(*outcomes)
        self.job.subprocess = fake
        return fake

    def test_a_failed_fetch_is_retried(self):
        fake = self.fake(1, 0)
        self.job.run_net(["git", "fetch", "origin", "main"])
        self.assertEqual(len(fake.calls), 2)
        self.assertTrue(all(kw.get("timeout") == self.job.NET_TIMEOUT for _, kw in fake.calls))

    def test_three_failures_refuse(self):
        fake = self.fake(1, 1, 1)
        with self.assertRaises(self.job.Refused):
            self.job.run_net(["git", "fetch", "origin", "main"])
        self.assertEqual(len(fake.calls), 3)

    def test_a_timeout_counts_as_a_failure(self):
        fake = self.fake("timeout", "timeout", 0)
        self.job.run_net(["git", "fetch", "origin", "main"])
        self.assertEqual(len(fake.calls), 3)

    def test_unchecked_failure_returns_the_last_result(self):
        self.fake(1, 1, 1)
        self.assertEqual(self.job.run_net(["git", "fetch"], check=False).returncode, 1)

    def test_read_only_gh_is_retried(self):
        fake = self.fake(1, 0)
        self.job.gh("pr", "view", "1", "--json", "state")
        self.assertEqual(len(fake.calls), 2)

    def test_gh_api_get_is_retried(self):
        fake = self.fake(1, 0)
        self.job.gh("api", "--paginate", "--jq", ".[]", "repos/o/r/pulls/1/comments")
        self.assertEqual(len(fake.calls), 2)

    def test_gh_writes_run_once(self):
        for args in (("issue", "create", "--title", "x"), ("pr", "merge", "1", "--squash"),
                     ("api", "repos/o/r/issues", "-f", "title=x"), ("api", "-X", "DELETE", "x"),
                     ("api", "--method=POST", "x")):
            fake = self.fake(1)
            with self.assertRaises(self.job.Refused):
                self.job.gh(*args)
            self.assertEqual(len(fake.calls), 1, args)

    def test_job_git_fetch_and_push_are_retried(self):
        job = {"worktree": str(self.project.repo)}
        for verb in ("fetch", "push"):
            fake = self.fake(1, 0)
            self.job.git(job, verb, "origin", "main")
            self.assertEqual(len(fake.calls), 2, verb)

    def test_job_git_local_commands_run_once(self):
        fake = self.fake(1)
        self.job.git({"worktree": str(self.project.repo)}, "status", check=False)
        self.assertEqual(len(fake.calls), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests/test_net_retry.py -v`
Expected: FAIL/ERROR (`run_net`, `NET_WAITS`, `NET_TIMEOUT` don't exist).

- [ ] **Step 3: Implement in `vendor/factory/factory/bin/job`**

Replace the `gh` function (currently `return run(["gh", *args]).stdout`) and add the helpers right after `run()`:

```python
# Seconds to wait before each attempt of a network call that is safe to repeat; tests use zeros.
NET_WAITS = (0, 2, 5)
NET_TIMEOUT = 120
READ_ONLY_GH = {"view", "list", "status", "checks", "diff"}
GH_API_WRITE_FLAGS = {"-X", "--method", "-f", "-F", "--field", "--raw-field", "--input"}
NET_GIT = {"fetch", "push", "ls-remote"}


def run_net(cmd, cwd=REPO, check=True):
    """run() for a network call that is safe to repeat: each attempt is time-limited, failures retried."""
    for wait in NET_WAITS:
        time.sleep(wait)
        try:
            res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=NET_TIMEOUT)
        except subprocess.TimeoutExpired:
            res = subprocess.CompletedProcess(cmd, 124, "", f"timed out after {NET_TIMEOUT}s")
        if res.returncode == 0:
            return res
    if check:
        raise Refused(f"`{' '.join(cmd)}` failed after {len(NET_WAITS)} attempts: "
                      f"{(res.stderr or res.stdout).strip()}")
    return res


def gh_read_only(args):
    """True for gh calls that only read, so repeating one can't create or change anything."""
    if args[:1] == ("api",):  # gh api defaults to POST once a field is given
        return not any(a.split("=", 1)[0] in GH_API_WRITE_FLAGS or a.startswith("-X") for a in args[1:])
    return len(args) > 1 and args[1] in READ_ONLY_GH


def gh(*args):
    return (run_net if gh_read_only(args) else run)(["gh", *args]).stdout
```

Replace `git()`:

```python
def git(job, *args, check=True):
    runner = run_net if args[:1] and args[0] in NET_GIT else run
    return runner(["git", *args], cwd=job["worktree"], check=check)
```

Change the two main-checkout fetches (in `advance` for intake → spec, and in `cmd_planned`) from `run(["git", "fetch", "origin", BASE])` to `run_net(["git", "fetch", "origin", BASE])`. Leave `run(["git", "push", "origin", "--delete", ...], check=False)` on `run`: it's best-effort and fails every time once GitHub already deleted the branch, so retrying would only add delay.

- [ ] **Step 4: Zero the waits in the test helper**

In `tests/factory_project.py` `load_job()`, after `loader.exec_module(mod)` add:

```python
        mod.NET_WAITS = (0, 0, 0)  # a failing network call in a test must not sleep
```

- [ ] **Step 5: Run tests**

Run: `python3 -m unittest tests/test_net_retry.py -v` → all PASS.
Run: `scripts/known-hashes` (the vendored `job` changed, so its new hash must be listed).
Run: `scripts/check` → all PASS, and the test run isn't noticeably slower than in Task 2.

- [ ] **Step 6: Commit** (vendored file only, then the test files in a second commit)

```bash
git add vendor/factory/factory/bin/job
git commit -m "fix(vendor): retry idempotent git and gh network calls in job"
git add tests/test_net_retry.py tests/factory_project.py vendor/known-hashes.json
git commit -m "test: network retries in job; refresh known hashes"
```

---

### Task 4: Fast-forward the main checkout after a merge (vendored)

**Files:**
- Modify: `vendor/factory/factory/bin/job` (new `sync_main()`, call at end of `cmd_merge` ~1356)
- Test: `tests/test_sync_main.py`, `tests/test_run_fixes.py` (`MergeTest`)

- [ ] **Step 1: Write the failing tests**

`tests/test_sync_main.py`:

```python
import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from factory_project import FactoryProject, git  # noqa: E402


class SyncMainTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = FactoryProject(tmp.name)
        self.job = self.project.load_job()
        other = Path(tmp.name) / "other"
        git(tmp.name, "clone", "-q", str(self.project.origin), str(other))
        git(other, "config", "user.email", "t@example.com")
        git(other, "config", "user.name", "T")
        (other / "merged.txt").write_text("from the PR\n")
        git(other, "add", "merged.txt")
        git(other, "commit", "-q", "-m", "merged PR")
        git(other, "push", "-q", "origin", "main")
        self.remote = git(other, "rev-parse", "HEAD")
        self.before = git(self.project.repo, "rev-parse", "HEAD")

    def sync(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.job.sync_main()
        return out.getvalue()

    def head(self):
        return git(self.project.repo, "rev-parse", "HEAD")

    def test_clean_main_is_fast_forwarded(self):
        out = self.sync()
        self.assertEqual(self.head(), self.remote)
        self.assertNotIn("NOTE", out)

    def test_untracked_files_do_not_block(self):
        (self.project.repo / "scratch.txt").write_text("x\n")
        self.sync()
        self.assertEqual(self.head(), self.remote)

    def test_other_branch_is_left_alone(self):
        git(self.project.repo, "checkout", "-q", "-b", "feature")
        out = self.sync()
        self.assertIn("NOTE: main checkout is on feature, not main; not pulled", out)
        self.assertEqual(self.head(), self.before)

    def test_local_changes_are_left_alone(self):
        spec = next(self.project.repo.glob("docs/superpowers/specs/*.md"))
        spec.write_text("edited\n")
        out = self.sync()
        self.assertIn("NOTE: main checkout has local changes; not pulled", out)
        self.assertEqual(self.head(), self.before)

    def test_diverged_main_is_left_alone(self):
        (self.project.repo / "local.txt").write_text("local\n")
        git(self.project.repo, "add", "local.txt")
        git(self.project.repo, "commit", "-q", "-m", "local")
        local = self.head()
        out = self.sync()
        self.assertIn("NOTE: main can't fast-forward to origin/main; not pulled", out)
        self.assertEqual(self.head(), local)


if __name__ == "__main__":
    unittest.main()
```

Add to `MergeTest` in `tests/test_run_fixes.py`:

```python
    def test_merge_pulls_the_main_checkout(self):
        self.to_approve()
        pulled = []
        self.job.sync_main = lambda: pulled.append(True)
        job = self.merge()
        self.assertEqual(job["stage"], "merged")
        self.assertEqual(pulled, [True])
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests/test_sync_main.py tests/test_run_fixes.py -v`
Expected: `AttributeError: ... has no attribute 'sync_main'` in the new tests; `test_merge_pulls_the_main_checkout` fails with `[] != [True]`.

- [ ] **Step 3: Implement in `vendor/factory/factory/bin/job`**

Add before `def cmd_merge(job):`:

```python
def sync_main():
    """Fast-forward the main checkout to origin/<base> after a merge, when that's safe.
    Otherwise print a NOTE: a stale checkout must never fail a merge that already happened."""
    try:
        branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], check=False).stdout.strip()
        if branch != BASE:
            print(f"NOTE: main checkout is on {branch or 'an unknown branch'}, not {BASE}; not pulled")
        elif run(["git", "status", "--porcelain", "--untracked-files=no"], check=False).stdout.strip():
            print("NOTE: main checkout has local changes; not pulled")
        elif (run_net(["git", "fetch", "origin", BASE], check=False).returncode != 0
              or run(["git", "merge", "--ff-only", "-q", f"origin/{BASE}"], check=False).returncode != 0):
            print(f"NOTE: {BASE} can't fast-forward to origin/{BASE}; not pulled")
    except OSError as e:
        print(f"NOTE: main checkout not pulled: {e}")
```

At the end of `cmd_merge`, after `print(f"{job['id']}: merged PR #{job['pr']}")`, add:

```python
    sync_main()
```

- [ ] **Step 4: Run tests**

Run: `python3 -m unittest tests/test_sync_main.py tests/test_run_fixes.py -v` → all PASS.

- [ ] **Step 5: Commit the vendored change**

```bash
git add vendor/factory/factory/bin/job
git commit -m "fix(vendor): fast-forward the main checkout after a factory merge"
```

- [ ] **Step 6: Regenerate known hashes, run the full check, commit plugin side**

Run: `scripts/known-hashes` then `scripts/check` → all PASS.

```bash
git add vendor/known-hashes.json tests/test_sync_main.py tests/test_run_fixes.py
git commit -m "test: main checkout sync after merge; refresh known hashes"
```

---

### Task 5: `bin/factory-uninstall-settings`

**Files:**
- Create: `bin/factory-uninstall-settings` (`chmod +x`)
- Test: `tests/test_factory_uninstall_settings.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_factory_uninstall_settings.py`:

```python
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "bin/factory-uninstall-settings"
FACTORY_HOOK = {"type": "command", "command": "\"$CLAUDE_PROJECT_DIR\"/factory/bin/stop-hook", "timeout": 600}
OTHER_HOOK = {"type": "command", "command": "scripts/lint"}


class UninstallSettingsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / ".claude").mkdir()
        self.path = self.root / ".claude/settings.json"

    def run_tool(self):
        return subprocess.run([sys.executable, str(TOOL), str(self.root)], capture_output=True, text=True)

    def write(self, data, indent=2):
        self.path.write_text(json.dumps(data, indent=indent) + "\n")

    def read(self):
        return json.loads(self.path.read_text())

    def test_only_the_factory_hook_is_removed(self):
        self.write({"model": "x", "hooks": {"Stop": [{"hooks": [FACTORY_HOOK, OTHER_HOOK]}],
                                            "PreToolUse": [{"hooks": [OTHER_HOOK]}]}})
        res = self.run_tool()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.read(), {"model": "x", "hooks": {"Stop": [{"hooks": [OTHER_HOOK]}],
                                                               "PreToolUse": [{"hooks": [OTHER_HOOK]}]}})

    def test_empty_containers_are_dropped(self):
        self.write({"model": "x", "hooks": {"Stop": [{"hooks": [FACTORY_HOOK]}]}})
        self.run_tool()
        self.assertEqual(self.read(), {"model": "x"})

    def test_key_order_and_indent_are_kept(self):
        self.write({"a": 1, "hooks": {"Stop": [{"hooks": [FACTORY_HOOK]}], "X": []}, "z": 2}, indent=4)
        self.run_tool()
        text = self.path.read_text()
        self.assertEqual(list(json.loads(text)), ["a", "hooks", "z"])
        self.assertIn('\n    "a": 1', text)

    def test_invalid_json_is_refused_and_untouched(self):
        self.path.write_text("{not json")
        res = self.run_tool()
        self.assertEqual(res.returncode, 1)
        self.assertEqual(self.path.read_text(), "{not json")

    def test_nothing_to_do(self):
        self.write({"hooks": {"Stop": [{"hooks": [OTHER_HOOK]}]}})
        before = self.path.read_text()
        res = self.run_tool()
        self.assertEqual(res.returncode, 0)
        self.assertEqual(self.path.read_text(), before)

    def test_missing_file_is_fine(self):
        self.assertEqual(self.run_tool().returncode, 0)
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests/test_factory_uninstall_settings.py -v`
Expected: failures (tool doesn't exist; Python exits 2 "can't open file").

- [ ] **Step 3: Implement `bin/factory-uninstall-settings`**

```python
#!/usr/bin/env python3
"""Remove the factory's Stop hook from a project's .claude/settings.json, and nothing else.

Usage: factory-uninstall-settings <project>
Exits 0 when done or when there's nothing to do; 1 when the file isn't valid JSON (nothing written).
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from factory_files import write_json  # noqa: E402

MARK = "factory/bin/stop-hook"


def is_factory(hook):
    return isinstance(hook, dict) and MARK in str(hook.get("command", ""))


def without_factory(data):
    """(settings without the factory Stop hook, number of hooks removed). Order of keys is kept."""
    hooks = data.get("hooks") if isinstance(data, dict) else None
    stop = hooks.get("Stop") if isinstance(hooks, dict) else None
    if not isinstance(stop, list):
        return data, 0
    removed, groups = 0, []
    for group in stop:
        inner = group.get("hooks") if isinstance(group, dict) else None
        kept = [h for h in inner if not is_factory(h)] if isinstance(inner, list) else inner
        if isinstance(inner, list):
            removed += len(inner) - len(kept)
        if not isinstance(inner, list) or kept or not inner:
            groups.append({**group, "hooks": kept} if isinstance(inner, list) else group)
    if not removed:
        return data, 0
    new_hooks = {k: (groups if k == "Stop" else v) for k, v in hooks.items() if k != "Stop" or groups}
    return {k: (new_hooks if k == "hooks" else v) for k, v in data.items() if k != "hooks" or new_hooks}, removed


def indent_of(text):
    match = re.search(r'\n( +)"', text)
    return len(match.group(1)) if match else 2


def main(argv):
    if len(argv) != 1:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    path = Path(argv[0]) / ".claude" / "settings.json"
    if not path.exists():
        print("factory-uninstall-settings: no .claude/settings.json; nothing to do")
        return 0
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except ValueError as exc:
        print(f"factory-uninstall-settings: {path} isn't valid JSON ({exc}); not changed", file=sys.stderr)
        return 1
    new, removed = without_factory(data)
    if not removed:
        print("factory-uninstall-settings: no factory Stop hook; nothing to do")
        return 0
    write_json(path, new, indent=indent_of(text))
    print(f"factory-uninstall-settings: removed the factory Stop hook from {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 4: Run tests**

Run: `python3 -m unittest tests/test_factory_uninstall_settings.py -v` → all PASS.

- [ ] **Step 5: Commit**

```bash
git add bin/factory-uninstall-settings tests/test_factory_uninstall_settings.py
git commit -m "feat: factory-uninstall-settings removes only the factory Stop hook"
```

---

### Task 6: `/factory-uninstall` skill, session hint, README

**Files:**
- Create: `skills/factory-uninstall/SKILL.md`
- Modify: `hooks/factory-session` (`HANDOFF` string), `README.md`
- Test: `tests/test_factory_session.py` (one new test)

- [ ] **Step 1: Write the failing test**

Append to the test class in `tests/test_factory_session.py` (or a new class at the end of the file):

```python
class UninstallHintTest(unittest.TestCase):
    def test_installed_projects_hear_about_uninstall(self):
        import importlib.machinery
        import importlib.util
        loader = importlib.machinery.SourceFileLoader("factory_session_hint", str(HOOK))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        self.assertIn("/factory-uninstall", mod.HANDOFF)
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests/test_factory_session.py -v` → the new test FAILS.

- [ ] **Step 3: Update `hooks/factory-session`**

Change the end of `HANDOFF` from
`"picks it, invoke the factory-handoff skill. factory/bin/doctor checks the install."`
to
`"picks it, invoke the factory-handoff skill. factory/bin/doctor checks the install; "`
`"/factory-uninstall removes it."`

- [ ] **Step 4: Create `skills/factory-uninstall/SKILL.md`**

````markdown
---
name: factory-uninstall
description: Use when the user wants to remove the software factory from a project. Removes the factory's files, Stop hook, runner and AGENTS.md section; keeps job history and GitHub labels; never commits.
---

# Uninstall the software factory

`$PLUGIN` is this skill's base directory followed by `/../..`. Work from the
project root. Commit nothing. Ask before anything this list doesn't cover.

1. **Installed?** If `factory/bin/job` doesn't exist, say the factory isn't
   installed here and stop.
2. **No jobs in flight.** Run `git worktree list`. If any worktree path is
   under `.worktrees/`, list them, say each job must be finished or rejected
   (`factory/bin/job summary` shows them) before uninstalling, and stop.
3. **Runner.** If `factory/bin/runner status` reports the launchd agent
   installed, run `factory/bin/runner uninstall`.
4. **Files.** The file list is the keys of `files` in `factory/manifest.json`;
   without a manifest, use `FILES` from `$PLUGIN/bin/factory_files.py`.
   Delete each listed file that exists, except `factory/checks.sh` when it
   differs from `$PLUGIN/vendor/factory/factory/checks.sh` (it holds the
   project's own checks: keep it and say so). Delete `factory/manifest.json`.
   Then remove directories left empty under `factory/` and `.claude/`
   (`find factory .claude -type d -empty -delete`), never `factory/jobs/`.
5. **Stop hook.** Run `"$PLUGIN/bin/factory-uninstall-settings" .`. If it
   exits 1, show its message and stop; don't edit the file by hand.
6. **AGENTS.md.** Remove the `## Software factory` section: from that
   heading up to (not including) the next `## ` heading or the end of the
   file. Leave `CLAUDE.md` unchanged.
7. **CI.** If `.github/workflows/factory-checks.yml` exists and its only job
   runs `bash factory/checks.sh` after setup steps, delete it. If it does
   more, show it and ask.
8. **`.gitignore`.** Keep `/factory/jobs/` and `/.worktrees/`: the job
   history stays on disk and must stay out of git.
9. **Stop the offer.** Run `"$PLUGIN/bin/factory-state" decline`, so new
   sessions don't offer `/factory-install` again.
10. **Hand over.** Show `git status` and `git diff --stat`, suggest the
    message `chore: uninstall software factory`, and let them commit. Then
    tell them what was kept and how to remove it themselves:

    ```bash
    rm -rf factory/jobs
    gh label delete factory --yes
    gh label delete factory:needs-info --yes
    gh label delete factory:needs-human --yes
    gh label delete factory:planned --yes
    gh label delete factory:learning --yes
    ```

    `/factory-install` (or `"$PLUGIN/bin/factory-state" reset` to get the
    offer back) reinstalls later.
````

- [ ] **Step 5: README**

In `README.md`, after the `### Keeping the factory up to date` section (before the `---` that precedes `## Configuration`), add:

```markdown
### Removing the factory

Run `/factory-uninstall` in the project. It stops the runner, removes the
factory's files, Stop hook, CI workflow and AGENTS.md section, and shows you
the diff to commit. It keeps `factory/jobs/` (your job history), your own
`factory/checks.sh` and the GitHub labels, and prints the commands to delete
them if you want to. It refuses while a job still has a worktree.
```

In the Commands table under `### Commands`, add a row in the table's existing format for `/factory-uninstall` with the text "Remove the factory from this project (keeps job history and labels)".

- [ ] **Step 6: Run tests and check**

Run: `python3 -m unittest tests/test_factory_session.py -v` → PASS.
Run: `scripts/check` → all PASS (`frontmatter` covers the new skill).

- [ ] **Step 7: Commit**

```bash
git add skills/factory-uninstall/SKILL.md hooks/factory-session tests/test_factory_session.py README.md
git commit -m "feat: /factory-uninstall skill"
```

---

### Task 7: CHANGELOG and the v0.2.0 tag

**Files:**
- Create: `CHANGELOG.md`

- [ ] **Step 1: Write `CHANGELOG.md`**

```markdown
# Changelog

All notable changes to superpowers-factory. Newest first. `scripts/release`
adds each new section.

## [0.2.0] - 2026-11-13

### Added

- Repo agent harness: `scripts/check` (license, JSON, config, frontmatter, compile, branding, tests), a Stop hook and CI.
- Project harness: `factory/bin/doctor`, the cached `factory/bin/stop-hook`, CI and `CLAUDE.md` wiring at install.
- Budgets per job, per hour and per day, with an evidence block in every factory PR.
- Hands-off running on macOS: `factory/bin/runner` with a sandboxed headless session under launchd.
- Auto setup: a SessionStart hook offers `/factory-install`, `/factory-update` and the factory handoff; installs record a manifest.
- `/factory-update` classifies upstream changes and migrates old configs.
- Learning loop: tagged review findings, `job learn`, the learner agent and `factory:learning` issues.
- Ships the agents-best-practices skill (MIT), pinned.

## [0.1.0] - 2026-11-12

### Added

- `/factory-handoff` files a Superpowers spec and plan as a `factory:planned` issue.
- `/factory-install` installs the vendored software factory into a project.
- `job planned` builds handed-off plans as written; reviewers and approver check plan conformance.
- Models and effort for every agent come from `factory/config.json`.
- Trusted PR comments become builder feedback.
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: add CHANGELOG for 0.1.0 and 0.2.0"
```

- [ ] **Step 3: Tag v0.2.0 locally (don't push)**

```bash
git tag -a v0.2.0 caff0c6 -m "Release 0.2.0"
```

The controller reports this tag to the user; pushing tags is their call.

---

### Task 8: `scripts/release` and the version-match check

**Files:**
- Create: `scripts/release` (`chmod +x`)
- Modify: `scripts/check` (`check_json`)
- Test: `tests/test_release.py`, `tests/test_check.py` (one test)

- [ ] **Step 1: Write the failing tests**

`tests/test_release.py`:

```python
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RELEASE = REPO / "scripts/release"

PLUGIN = '{\n  "name": "p",\n  "version": "0.2.0",\n  "keywords": ["a", "b"]\n}\n'
MARKET = '{\n  "name": "p",\n  "plugins": [ { "name": "p", "version": "0.2.0", "source": "./" } ]\n}\n'
CHANGELOG = "# Changelog\n\nIntro.\n\n## [0.2.0] - 2026-11-12\n\n### Added\n\n- old thing\n"
HASHES_STUB = ("import pathlib\npathlib.Path('vendor').mkdir(exist_ok=True)\n"
               "pathlib.Path('vendor/known-hashes.json').write_text('{}\\n')\n")


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


class ReleaseTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.origin = base / "origin.git"
        git(base, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.root = base / "r"
        (self.root / ".claude-plugin").mkdir(parents=True)
        (self.root / "scripts").mkdir()
        (self.root / ".claude-plugin/plugin.json").write_text(PLUGIN)
        (self.root / ".claude-plugin/marketplace.json").write_text(MARKET)
        (self.root / "CHANGELOG.md").write_text(CHANGELOG)
        (self.root / "scripts/known-hashes").write_text(HASHES_STUB)
        self.set_check(0)
        shutil.copy(RELEASE, self.root / "scripts/release")
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "config", "user.email", "t@example.com")
        git(self.root, "config", "user.name", "T")
        git(self.root, "config", "commit.gpgsign", "false")
        git(self.root, "config", "tag.gpgsign", "false")
        git(self.root, "remote", "add", "origin", str(self.origin))
        self.commit("chore: release 0.2.0")
        git(self.root, "tag", "-a", "v0.2.0", "-m", "Release 0.2.0")
        for subject in ("feat: add widget", "fix: stop crash", "docs: explain widget"):
            self.commit(subject)

    def set_check(self, code):
        (self.root / "scripts/check").write_text(f"import sys\nsys.exit({code})\n")

    def commit(self, subject):
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "--allow-empty", "-m", subject)

    def release(self, version):
        return subprocess.run([sys.executable, str(self.root / "scripts/release"), version],
                              cwd=self.root, capture_output=True, text=True, stdin=subprocess.DEVNULL)

    def test_release_bumps_both_versions_without_reformatting(self):
        res = self.release("0.3.0")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        plugin = (self.root / ".claude-plugin/plugin.json").read_text()
        self.assertEqual(plugin, PLUGIN.replace("0.2.0", "0.3.0"))
        market = json.loads((self.root / ".claude-plugin/marketplace.json").read_text())
        self.assertEqual(market["plugins"][0]["version"], "0.3.0")

    def test_changelog_groups_commits_since_the_last_tag(self):
        self.release("0.3.0")
        text = (self.root / "CHANGELOG.md").read_text()
        new = text[text.index("## [0.3.0] - "):text.index("## [0.2.0]")]
        self.assertIn("### Added\n\n- add widget\n", new)
        self.assertIn("### Fixed\n\n- stop crash\n", new)
        self.assertIn("### Changed\n\n- docs: explain widget\n", new)
        self.assertNotIn("release 0.2.0", new)
        self.assertLess(text.index("Intro."), text.index("## [0.3.0]"))

    def test_release_commits_and_tags_but_never_pushes(self):
        res = self.release("0.3.0")
        self.assertEqual(git(self.root, "log", "-1", "--format=%s"), "chore: release 0.3.0")
        self.assertEqual(git(self.root, "tag", "--list", "v0.3.0"), "v0.3.0")
        self.assertEqual(git(self.root, "status", "--porcelain"), "")
        self.assertEqual(git(self.root, "ls-remote", "origin"), "")
        self.assertIn("git push origin main v0.3.0", res.stdout)

    def test_refuses_a_dirty_tree(self):
        (self.root / "x.txt").write_text("x\n")
        res = self.release("0.3.0")
        self.assertEqual(res.returncode, 1)
        self.assertIn("working tree", res.stderr)

    def test_refuses_a_version_that_is_not_higher(self):
        self.assertEqual(self.release("0.2.0").returncode, 1)
        self.assertEqual(self.release("0.1.9").returncode, 1)

    def test_refuses_a_malformed_version(self):
        self.assertEqual(self.release("1.0").returncode, 1)
        self.assertEqual(self.release("v1.0.0").returncode, 1)

    def test_failed_check_leaves_changes_uncommitted(self):
        self.set_check(1)
        self.commit("chore: failing check stub")
        head = git(self.root, "rev-parse", "HEAD")
        res = self.release("0.3.0")
        self.assertEqual(res.returncode, 1)
        self.assertIn("scripts/check failed", res.stderr)
        self.assertEqual(git(self.root, "rev-parse", "HEAD"), head)
        self.assertEqual(git(self.root, "tag", "--list", "v0.3.0"), "")
        self.assertIn("0.3.0", (self.root / ".claude-plugin/plugin.json").read_text())


if __name__ == "__main__":
    unittest.main()
```

Add to `CheckTest` in `tests/test_check.py` (it runs `scripts/check --fast` on a committed copy of this repo at `self.root`):

```python
    def test_mismatched_plugin_and_marketplace_versions_fail(self):
        def change(text):
            data = json.loads(text)
            data["plugins"][0]["version"] = "9.9.9"
            return json.dumps(data, indent=2) + "\n"
        self.edit(".claude-plugin/marketplace.json", change)
        self.assertFails("json", "marketplace.json version 9.9.9")

    def test_stale_known_hashes_fail(self):
        self.edit("vendor/factory/factory/bin/gate", lambda text: text + "# edited\n")
        self.assertFails("hashes", "factory/bin/gate")
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests/test_release.py tests/test_check.py -v`
Expected: release tests fail (script missing); the version test fails (no such check).

- [ ] **Step 3: Version-match in `scripts/check` `check_json`**

Replace `check_json` with:

```python
def check_json(root, opts):
    problems = []
    for rel in JSON_FILES:
        try:
            json.loads((root / rel).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            problems.append(f"{rel}: {exc}")
    if problems:
        return problems
    plugin = json.loads((root / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    market = json.loads((root / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
    for entry in market.get("plugins", []):
        if entry.get("name") == plugin.get("name") and entry.get("version") != plugin.get("version"):
            problems.append(f"marketplace.json version {entry.get('version')} "
                            f"!= plugin.json version {plugin.get('version')}")
    return problems
```

- [ ] **Step 4: Create `scripts/release`**

```python
#!/usr/bin/env python3
"""Cut a plugin release: bump versions, refresh known hashes, write the changelog, check, commit, tag.

Usage: scripts/release X.Y.Z
Never pushes; prints the push command. Opens CHANGELOG.md in $EDITOR when run from a terminal.
"""

import json
import os
import re
import shlex
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_JSON = Path(".claude-plugin/plugin.json")
MARKET_JSON = Path(".claude-plugin/marketplace.json")
CHANGELOG = Path("CHANGELOG.md")
HASHES = Path("vendor/known-hashes.json")
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
VERSION_KEY = re.compile(r'("version"\s*:\s*")[^"]*(")')


class Stop(Exception):
    pass


def git(*args, check=True):
    res = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    if check and res.returncode != 0:
        raise Stop(f"git {' '.join(args)} failed: {res.stderr.strip()}")
    return res.stdout.strip()


def parse(version):
    return tuple(int(part) for part in version.split("."))


def bump(rel, version):
    """Set the one "version" value in a JSON file, leaving its formatting alone."""
    path = ROOT / rel
    text, count = VERSION_KEY.subn(rf"\g<1>{version}\g<2>", path.read_text(encoding="utf-8"))
    if count != 1:
        raise Stop(f"{rel} has {count} version keys, expected 1")
    path.write_text(text, encoding="utf-8")


def subjects():
    """Commit subjects since the latest v* tag (all history when there's none), oldest first."""
    tag = git("describe", "--tags", "--abbrev=0", "--match", "v*", check=False)
    return git("log", "--reverse", "--format=%s", *([f"{tag}..HEAD"] if tag else [])).splitlines()


def section(version, lines, today):
    groups = {"Added": [], "Fixed": [], "Changed": []}
    for subject in lines:
        if not subject or subject.startswith("chore: release"):
            continue
        kind, sep, text = subject.partition(": ")
        kind = kind.split("(")[0].rstrip("!")
        if sep and kind == "feat":
            groups["Added"].append(text)
        elif sep and kind == "fix":
            groups["Fixed"].append(text)
        else:
            groups["Changed"].append(subject)
    out = [f"## [{version}] - {today}", ""]
    for name, items in groups.items():
        if items:
            out += [f"### {name}", "", *(f"- {item}" for item in items), ""]
    return "\n".join(out) + "\n"


def add_section(text, new):
    """Insert before the first released section, after the title and intro."""
    at = text.find("\n## [")
    if at == -1:
        return text.rstrip("\n") + "\n\n" + new
    return text[:at + 1] + new + text[at + 1:]


def script(name):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / name)], cwd=ROOT).returncode


def release(version, editor):
    if not VERSION.match(version):
        raise Stop(f"{version!r} isn't a version like 1.2.3")
    if git("status", "--porcelain"):
        raise Stop("the working tree has changes; commit or stash them first")
    current = json.loads((ROOT / PLUGIN_JSON).read_text(encoding="utf-8"))["version"]
    if parse(version) <= parse(current):
        raise Stop(f"{version} isn't higher than the current {current}")
    if git("tag", "--list", f"v{version}"):
        raise Stop(f"tag v{version} already exists")
    new = section(version, subjects(), date.today().isoformat())
    for rel in (PLUGIN_JSON, MARKET_JSON):
        bump(rel, version)
    if script("known-hashes") != 0:
        raise Stop("scripts/known-hashes failed; the release changes are left uncommitted")
    log = ROOT / CHANGELOG
    log.write_text(add_section(log.read_text(encoding="utf-8") if log.exists() else "# Changelog\n", new),
                   encoding="utf-8")
    if editor:
        subprocess.run([*shlex.split(editor), str(log)], check=False)
    if script("check") != 0:
        raise Stop("scripts/check failed; the release changes are left uncommitted")
    git("add", "--", str(PLUGIN_JSON), str(MARKET_JSON), str(CHANGELOG), str(HASHES))
    git("commit", "-q", "-m", f"chore: release {version}")
    git("tag", "-a", f"v{version}", "-m", f"Release {version}")
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    print(f"Released {version} (commit and tag v{version} are local). Push with:\n"
          f"  git push origin {branch} v{version}")


def main(argv):
    if len(argv) != 1:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    editor = os.environ.get("EDITOR") if sys.stdin.isatty() else None
    try:
        release(argv[0], editor)
    except Stop as exc:
        print(f"release: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 5: Run tests and the full check**

Run: `python3 -m unittest tests/test_release.py tests/test_check.py -v` → all PASS.
Run: `scripts/check` → all PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/release scripts/check tests/test_release.py tests/test_check.py
git commit -m "feat: scripts/release bumps, logs, checks, commits and tags a release"
```

---

### Task 9: Contributor docs and spec touch-ups

**Files:**
- Modify: `AGENTS.md`, `docs/superpowers/specs/2026-11-13-phase1-hardening-design.md`

- [ ] **Step 1: AGENTS.md**

Under `## Workflow`, append:

```markdown
- Edited a vendored file? Run `scripts/known-hashes` and commit
  `vendor/known-hashes.json` with your plugin-side changes (`scripts/check`
  fails until you do).
- Releasing: `scripts/release X.Y.Z` on a clean `main`. It bumps both
  manifests, refreshes the known hashes, adds a CHANGELOG section from the
  commit subjects since the last `v*` tag, runs `scripts/check`, commits and
  tags. It never pushes; it prints the push command.
```

In `## Map`, add lines for `scripts/known-hashes`, `scripts/release`, `vendor/known-hashes.json`, `bin/factory-uninstall-settings` and `skills/factory-uninstall/`, in that section's existing format.

- [ ] **Step 2: Spec touch-ups** (record what the build settled)

In the spec:
- §1: replace "`--check` exits 1 if the file on disk differs from what it would write" with "`--check` exits 1 if a current vendored file's hash is missing from the list (a full comparison would fail in shallow CI clones and repo copies)".
- §3: replace "`git push` (branch push and branch delete)" with "`git push` of the job branch (the best-effort branch delete after a merge stays on `run`: once GitHub has deleted the branch it fails every time)".
- §2/§3: replace "(vendored `job`, same commit as 2)" with "(vendored `job`, its own commit)".

- [ ] **Step 3: Check and commit**

Run: `scripts/check` → all PASS.

```bash
git add AGENTS.md docs/superpowers/specs/2026-11-13-phase1-hardening-design.md
git commit -m "docs: known hashes and releases in AGENTS.md; settle spec details"
```

---

## Done when

- `scripts/check` passes on `main` with the new `hashes` check.
- `vendor/known-hashes.json` lists the current hash of every vendored file.
- A local `v0.2.0` tag exists at caff0c6 (not pushed).
- Nothing is pushed; the controller asks the user before merging or pushing.
