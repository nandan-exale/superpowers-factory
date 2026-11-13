# Phase 5c: GitHub Actions Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the factory on a schedule in GitHub Actions. An opt-in workflow runs `factory/bin/runner tick --ci`, which keeps job state on an orphan `factory-state` branch and recreates missing worktrees on the fresh machine.

**Architecture:**
- **Vendored `runner`:**
  - `runner workflow --claude-version X.Y.Z` renders `.github/workflows/factory-runner.yml` from config.
  - `runner tick --ci` skips the lock file (the workflow's concurrency group is the lock) and takes the token from `CLAUDE_CODE_OAUTH_TOKEN`.
  - Around the tick, `restore_state()` copies `factory-state` into `factory/jobs/`. `save_state()` always commits `factory/jobs/` (minus `*.lock` and files over 1 MB) on top of the previous state, using a temporary index, and pushes. A rejected push is retried once on the new parent.
- **Vendored `job`:** `job ensure-worktree <id>` recreates a missing worktree from `origin/<branch>` or `origin/<base>`, and sends the job to `needs-human` if git fails. The factory skill runs it before spawning any agent for a job.
- **Vendored `doctor --ci`:** checks that nothing protects `factory-state` against the runner's pushes, and skips the local scheduler and token checks.
- **Plugin `factory-install` skill:** offers the workflow (off by default), warns on public repos, and tells the user to create the two secrets themselves.

**Tech Stack:** Python 3.10+ stdlib (`tarfile` for restore), `unittest`, git plumbing (`write-tree`, `commit-tree`), GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-13-phase5-scale-design.md` (section 5c)

**Rules for this plan:**
- Never edit the spec or this plan. Make no git tags. Push nothing but the job branch. (Tests push to throwaway bare repos; that's fine.)
- Each vendored edit in its own commit, then the plugin side with tests and the refreshed `vendor/known-hashes.json` (`scripts/known-hashes`).
- Change nothing in the installed copy (`factory/`, `.claude/` at the repo root). Don't add a workflow to this repo's `.github/`.
- The workflow pins `actions/checkout@v4`. It persists the token as `http.<url>.extraheader`, which `risky_local_key()` allows. Newer majors may write `includeIf` config, which the runner refuses.
- "Next run warns" (spec, error table): a failed state push fails the workflow run (a red run in Actions) and uploads `factory/jobs` as an artifact. That red run is the warning.
- Built after Phase 5b is merged; anchor on function names.
- Full check: `scripts/check`.

---

### Task 1: `runner workflow`

**Files:**
- Modify: `vendor/factory/factory/bin/runner`
- Create: `tests/test_runner_ci.py`

- [ ] **Step 1: Write the failing tests.** `tests/test_runner_ci.py`:

```python
import contextlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from installed_project import InstalledProject, git, load_script


class CiCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.p = InstalledProject(self.tmp)
        self.origin = self.tmp / "origin.git"
        git(self.tmp, "init", "-q", "--bare", "-b", "main", str(self.origin))
        git(self.p.root, "branch", "-M", "main")
        git(self.p.root, "remote", "add", "origin", str(self.origin))
        git(self.p.root, "config", "user.email", "ci@example.com")
        git(self.p.root, "config", "user.name", "ci")
        git(self.p.root, "push", "-q", "-u", "origin", "main")
        self.runner = load_script(f"runner_ci_{id(self)}", self.p.root / "factory/bin/runner")

    def out(self, fn, *args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = fn(*args)
        return code, buf.getvalue()


class WorkflowTest(CiCase):
    def test_renders_schedule_permissions_steps_and_timeout(self):
        code, text = self.out(self.runner.cmd_workflow, "2.1.3")
        self.assertEqual(code, 0)
        _, runner = self.runner.load_config()
        for needle in ('cron: "' + self.runner.cron(runner["interval_minutes"]) + '"', "workflow_dispatch:",
                       "group: factory-runner", "cancel-in-progress: false", "contents: write", "issues: write",
                       "pull-requests: write", "actions: read", "actions/checkout@v4", "fetch-depth: 0",
                       "bubblewrap socat", "@anthropic-ai/claude-code@2.1.3", "factory/bin/runner tick --ci",
                       "secrets.FACTORY_CLAUDE_TOKEN", "secrets.FACTORY_GH_TOKEN",
                       f"timeout-minutes: {runner['max_minutes'] + 10}", "upload-artifact"):
            self.assertIn(needle, text)
        self.assertNotIn("\t", text)
        self.assertTrue(all(len(l) - len(l.lstrip(" ")) % 2 == 0 for l in text.splitlines()))

    def test_cron_has_a_15_minute_floor(self):
        self.assertEqual(self.runner.cron(5), "*/15 * * * *")
        self.assertEqual(self.runner.cron(30), "*/30 * * * *")
        self.assertEqual(self.runner.cron(120), "0 */2 * * *")

    def test_bad_version_is_refused(self):
        with self.assertRaises(SystemExit):
            self.out(self.runner.cmd_workflow, "latest")
```

- [ ] **Step 2: Run them and see them fail.** `python3 -m unittest tests/test_runner_ci.py -v`

- [ ] **Step 3: Implement.** In `runner`:

```python
WORKFLOW = """\
# Written by factory/bin/runner workflow. Runs the software factory on a schedule.
name: factory-runner
on:
  schedule:
    - cron: "{cron}"
  workflow_dispatch:
concurrency:
  group: factory-runner
  cancel-in-progress: false
permissions:
  contents: write
  issues: write
  pull-requests: write
  actions: read
jobs:
  tick:
    runs-on: ubuntu-latest
    timeout-minutes: {timeout}
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
          token: ${{{{ secrets.FACTORY_GH_TOKEN }}}}
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
      - name: Sandbox tools
        run: sudo apt-get update -q && sudo apt-get install -y -q bubblewrap socat
      - name: Claude Code
        run: npm install -g @anthropic-ai/claude-code@{claude_version}
      - name: Git identity from the token's user
        env:
          GH_TOKEN: ${{{{ secrets.FACTORY_GH_TOKEN }}}}
        run: |
          login="$(gh api user --jq .login)"
          id="$(gh api user --jq .id)"
          git config user.name "$login"
          git config user.email "$id+$login@users.noreply.github.com"
      - name: Factory tick
        run: python3 factory/bin/runner tick --ci
        env:
          CLAUDE_CODE_OAUTH_TOKEN: ${{{{ secrets.FACTORY_CLAUDE_TOKEN }}}}
          GH_TOKEN: ${{{{ secrets.FACTORY_GH_TOKEN }}}}
      - name: Keep job state that couldn't be pushed
        if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: factory-jobs-${{{{ github.run_id }}}}
          path: factory/jobs
"""


def cron(interval_minutes):
    """GitHub runs schedules at most every 5 min and often late; 15 min is the floor here."""
    n = max(15, interval_minutes)
    return f"*/{n} * * * *" if n < 60 else f"0 */{max(1, n // 60)} * * *"


def cmd_workflow(claude_version):
    if not re.fullmatch(r"\d+\.\d+\.\d+", claude_version or ""):
        die(f"--claude-version must be X.Y.Z (claude --version prints it), not {claude_version!r}")
    _, runner = load_config()
    sys.stdout.write(WORKFLOW.format(cron=cron(runner["interval_minutes"]), timeout=runner["max_minutes"] + 10,
                                     claude_version=claude_version))
    return 0
```

In `main`, add:

```python
        if len(argv) == 3 and argv[:2] == ["workflow", "--claude-version"]:
            return cmd_workflow(argv[2])
```

Docstring line:

```
  runner workflow --claude-version X.Y.Z   print .github/workflows/factory-runner.yml for the Actions runner
```

- [ ] **Step 4: Run them and see them pass.**

- [ ] **Step 5: Commit.**

```bash
git add vendor/factory/factory/bin/runner
git commit -m "feat(vendor): runner workflow renders the GitHub Actions runner workflow"
scripts/known-hashes
git add tests/test_runner_ci.py vendor/known-hashes.json
git commit -m "test: Actions workflow rendering; refresh known hashes"
```

---

### Task 2: State on the `factory-state` branch

**Files:**
- Modify: `vendor/factory/factory/bin/runner`
- Test: `tests/test_runner_ci.py`

- [ ] **Step 1: Write the failing tests.** Append:

```python
class StateTest(CiCase):
    def call(self, fn):
        with mock.patch.dict(os.environ, {"GIT_TERMINAL_PROMPT": "0"}):
            return fn()

    def state_log(self):
        return git(self.tmp, "--git-dir", str(self.origin), "log", "--format=%H %P", "factory-state").splitlines()

    def state_files(self):
        return git(self.tmp, "--git-dir", str(self.origin), "ls-tree", "-r", "--name-only", "factory-state").split()

    def write(self, rel, text):
        path = self.p.root / "factory/jobs" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def test_first_save_creates_an_orphan_branch_without_locks_or_big_files(self):
        self.write("001-a/job.json", "{}")
        self.write("001-a/.lock", "")
        self.write("runs/big.json", "x" * 1_100_000)
        self.assertTrue(self.call(self.runner.restore_state))
        self.assertTrue(self.call(self.runner.save_state))
        self.assertEqual(self.state_files(), ["001-a/job.json"])
        (commit,) = self.state_log()
        self.assertEqual(commit.split(), commit.split()[:1])  # no parent: orphan
        self.assertEqual(git(self.p.root, "status", "--porcelain"), "")  # main's index untouched

    def test_second_save_appends_and_restore_brings_files_back(self):
        self.write("001-a/job.json", "{}")
        self.call(self.runner.restore_state)
        self.call(self.runner.save_state)
        import shutil
        shutil.rmtree(self.p.root / "factory/jobs")
        self.assertTrue(self.call(self.runner.restore_state))
        self.assertEqual((self.p.root / "factory/jobs/001-a/job.json").read_text(), "{}")
        self.write("002-b/job.json", "{}")
        self.call(self.runner.save_state)
        log = self.state_log()
        self.assertEqual(len(log), 2)
        self.assertEqual(log[0].split()[1], log[1].split()[0])  # new commit's parent is the old one

    def test_a_rejected_push_is_retried_on_the_new_parent(self):
        self.write("001-a/job.json", "{}")
        self.call(self.runner.restore_state)
        self.call(self.runner.save_state)
        self.call(self.runner.restore_state)
        other = self.tmp / "other"
        git(self.tmp, "clone", "-q", "-b", "factory-state", str(self.origin), str(other))
        (other / "elsewhere.txt").write_text("x")
        git(other, "add", "elsewhere.txt")
        git(other, "-c", "user.email=o@e.com", "-c", "user.name=o", "commit", "-q", "-m", "someone else")
        git(other, "push", "-q", "origin", "factory-state")
        self.write("002-b/job.json", "{}")
        self.assertTrue(self.call(self.runner.save_state))
        newest, parent = self.state_log()[0].split()
        self.assertEqual(parent, git(other, "rev-parse", "HEAD"))
        self.assertIn("002-b/job.json", self.state_files())

    def test_restore_refuses_unsafe_paths(self):
        bad = self.tmp / "bad.tar"
        with tarfile.open(bad, "w") as tar:
            info = tarfile.TarInfo("../escape.txt")
            info.size = 0
            tar.addfile(info, io.BytesIO(b""))
        with self.assertRaises(ValueError):
            self.runner.extract_state(bad.read_bytes(), self.p.root / "factory/jobs")
```

- [ ] **Step 2: Run them and see them fail.**

- [ ] **Step 3: Implement.** In `runner`, add `import io`, `import tarfile` and:

```python
STATE_BRANCH = "factory-state"
STATE_REF = f"refs/remotes/origin/{STATE_BRANCH}"
STATE_MAX_BYTES = 1_000_000


def git_dir():
    return Path(subprocess.run(["git", "rev-parse", "--absolute-git-dir"], cwd=REPO, capture_output=True,
                               text=True).stdout.strip())


def fetch_state():
    """True when origin has a factory-state branch (now fetched)."""
    heads = git("ls-remote", "--heads", "origin", STATE_BRANCH)
    if heads.returncode != 0:
        raise RuntimeError(first_line(heads.stderr))
    if not heads.stdout.strip():
        return False
    res = git("fetch", "-q", "origin", f"+refs/heads/{STATE_BRANCH}:{STATE_REF}")
    if res.returncode != 0:
        raise RuntimeError(first_line(res.stderr))
    return True


def extract_state(tar_bytes, target):
    """Unpack a `git archive` tar into target; refuse absolute paths, `..` and anything but files and dirs."""
    with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as tar:
        members = tar.getmembers()
        for m in members:
            parts = Path(m.name).parts
            if Path(m.name).is_absolute() or ".." in parts or not (m.isfile() or m.isdir()):
                raise ValueError(f"unsafe path in {STATE_BRANCH}: {m.name}")
        target.mkdir(parents=True, exist_ok=True)
        tar.extractall(target, members=members)


def restore_state():
    """Copy factory-state into factory/jobs. True when restored or when there's nothing to restore."""
    try:
        if not fetch_state():
            return True
    except RuntimeError as exc:
        log(f"error: fetching {STATE_BRANCH}: {exc}")
        return False
    archive = subprocess.run(["git", *GIT_SAFE, "archive", "--format=tar", STATE_REF], cwd=REPO,
                             capture_output=True)
    if archive.returncode != 0:
        log(f"error: reading {STATE_BRANCH}: {first_line(archive.stderr.decode(errors='replace'))}")
        return False
    extract_state(archive.stdout, JOBS)
    return True


def state_files():
    """factory/jobs paths to persist: no lock files, nothing over STATE_MAX_BYTES (big transcripts)."""
    if not JOBS.exists():
        return []
    return [p.relative_to(JOBS).as_posix() for p in sorted(JOBS.rglob("*"))
            if p.is_file() and not p.name.endswith(".lock") and p.stat().st_size <= STATE_MAX_BYTES]


def state_commit(files, parent):
    """A commit of `files` (relative to factory/jobs) on `parent`, built in a temporary index so the
    main checkout's index and tree are untouched."""
    index = git_dir() / "factory-state.index"
    index.unlink(missing_ok=True)
    env = {**os.environ, **GIT_ENV, "GIT_INDEX_FILE": str(index), "GIT_DIR": str(git_dir()),
           "GIT_WORK_TREE": str(JOBS)}

    def g(*args):
        res = subprocess.run(["git", *GIT_SAFE, *args], cwd=JOBS, capture_output=True, text=True, env=env)
        if res.returncode != 0:
            raise RuntimeError(f"git {args[0]}: {first_line(res.stderr)}")
        return res.stdout.strip()

    try:
        for i in range(0, len(files), 200):
            g("add", "-f", "--", *files[i:i + 200])
        tree = g("write-tree")
        return g("commit-tree", tree, *(["-p", parent] if parent else []), "-m", f"factory state {stamp()}")
    finally:
        index.unlink(missing_ok=True)


def save_state():
    """Commit factory/jobs on top of origin's factory-state and push it; one retry after a rejection."""
    JOBS.mkdir(parents=True, exist_ok=True)
    files = state_files()
    for _ in range(2):
        parent = git("rev-parse", "-q", "--verify", STATE_REF).stdout.strip()
        try:
            commit = state_commit(files, parent)
        except RuntimeError as exc:
            log(f"error: saving {STATE_BRANCH}: {exc}")
            return False
        if git("push", "-q", "origin", f"{commit}:refs/heads/{STATE_BRANCH}").returncode == 0:
            git("update-ref", STATE_REF, commit)
            return True
        try:
            fetch_state()
        except RuntimeError as exc:
            log(f"error: fetching {STATE_BRANCH}: {exc}")
            return False
    return False
```

- [ ] **Step 4: Run them and see them pass.**

- [ ] **Step 5: Commit.**

```bash
git add vendor/factory/factory/bin/runner
git commit -m "feat(vendor): runner keeps job state on an orphan factory-state branch"
scripts/known-hashes
git add tests/test_runner_ci.py vendor/known-hashes.json
git commit -m "test: factory-state save, restore and push retry; refresh known hashes"
```

---

### Task 3: `runner tick --ci`

**Files:**
- Modify: `vendor/factory/factory/bin/runner` (`main`, `cmd_tick`)
- Test: `tests/test_runner_ci.py`

`cmd_tick(ci=False)`:
- With `ci`, skip the lock file and take the token from `CLAUDE_CODE_OAUTH_TOKEN` (missing → log `error: CLAUDE_CODE_OAUTH_TOKEN isn't set; add the FACTORY_CLAUDE_TOKEN secret` and return 1). Remove `CLAUDE_CODE_OAUTH_TOKEN` from `os.environ` once read, so nothing but the explicit child env carries it.
- Restore state before the preflight, and save it in a `finally`, even after failures. A failed save makes the tick return 1.
- Everything else is the tick as today. Move the body after the lock into `tick_body(base, runner, ci)` so both paths share it.

- [ ] **Step 1: Write the failing tests.** Append:

```python
FAKE_GH = f"#!{sys.executable}\nimport sys\nsys.stdout.write('[]')\n"


class TickCiTest(CiCase):
    def tick(self, **env):
        fakebin = self.tmp / "cibin"
        fakebin.mkdir(exist_ok=True)
        (fakebin / "gh").write_text(FAKE_GH)
        (fakebin / "gh").chmod(0o755)
        full = {**self.p.env(), "PATH": f"{fakebin}{os.pathsep}{os.environ['PATH']}", **env}
        return subprocess.run([sys.executable, str(self.p.root / "factory/bin/runner"), "tick", "--ci"],
                              cwd=self.p.root, capture_output=True, text=True, env=full)

    def test_idle_ci_tick_saves_state_with_its_log(self):
        res = self.tick(CLAUDE_CODE_OAUTH_TOKEN="tok")
        self.assertEqual(res.returncode, 0, res.stderr)
        files = git(self.tmp, "--git-dir", str(self.origin), "ls-tree", "-r", "--name-only", "factory-state").split()
        self.assertIn("runner.log", files)
        self.assertFalse((self.p.git_dir / "factory-runner.lock").exists())

    def test_state_is_restored_before_the_tick(self):
        self.tick(CLAUDE_CODE_OAUTH_TOKEN="tok")
        import shutil
        shutil.rmtree(self.p.root / "factory/jobs")
        self.tick(CLAUDE_CODE_OAUTH_TOKEN="tok")
        lines = (self.p.root / "factory/jobs/runner.log").read_text().splitlines()
        self.assertEqual(len(lines), 2)  # the first tick's line came back from factory-state
```

(An idle queue never needs the token, so these runs don't reach the token check. The missing-token path is covered by reading the code path in a unit test below.)

```python
    def test_token_comes_from_the_environment_and_leaves_it(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_OAUTH_TOKEN": "tok"}):
            self.assertEqual(self.runner.ci_token(), "tok")
            self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", os.environ)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
            self.assertIsNone(self.runner.ci_token())
```

- [ ] **Step 2: Run them and see them fail.**

- [ ] **Step 3: Implement.** In `runner`:

```python
def ci_token():
    """The token from the workflow's environment, removed from it so only claude's explicit env carries it."""
    return os.environ.pop("CLAUDE_CODE_OAUTH_TOKEN", None) or None
```

Restructure `cmd_tick`:

```python
def cmd_tick(ci=False):
    try:
        base, runner = load_config()
    except ValueError as exc:
        print(f"runner: {exc}", file=sys.stderr)
        log(f"error: config: {exc}")
        return 1
    if not ci:
        lock = open(git_path("factory-runner.lock"), "w")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log("busy")
            return 0
        signal.signal(signal.SIGTERM, on_sigterm)
        return tick_body(base, runner, None)
    signal.signal(signal.SIGTERM, on_sigterm)
    token = ci_token()
    if not restore_state():
        return 1
    code = 1
    try:
        code = tick_body(base, runner, token)
    finally:
        if not save_state():
            log(f"error: {STATE_BRANCH} push failed twice; this run's state is in the workflow artifact")
            code = 1
    return code
```

`tick_body(base, runner, ci_token_value)` holds everything that followed the lock in the old `cmd_tick` (hooks and git config checks, branch, clean tree, pull, `chores()`, `has_work()`, token, Linux sandbox tools, `run_claude`). The one change is the token lookup:

```python
    if ci_token_value is not None or os.environ.get("GITHUB_ACTIONS") == "true":
        token = ci_token_value
        if not token:
            log("error: CLAUDE_CODE_OAUTH_TOKEN isn't set; add the FACTORY_CLAUDE_TOKEN secret")
            return 1
    else:
        token = read_token(runner["keychain_service"])
        ...  # the existing no-token handling, unchanged
```

Pass `None` from the non-CI path. In the CI path, pass `""` (not `None`) when the variable was missing, so the CI branch is taken and the error logged: `code = tick_body(base, runner, token or "")`.

`main`: accept `["tick", "--ci"]`:

```python
        if argv == ["tick"]:
            return cmd_tick()
        if argv == ["tick", "--ci"]:
            return cmd_tick(ci=True)
```

Docstring:

```
  runner tick --ci             the same from GitHub Actions: no lock, token from the environment, state on factory-state
```

- [ ] **Step 4: Run them and see them pass**, plus `python3 -m unittest tests/test_runner.py tests/test_runner_linux.py -v`.

- [ ] **Step 5: Commit.**

```bash
git add vendor/factory/factory/bin/runner
git commit -m "feat(vendor): runner tick --ci restores and saves state around a lock-free tick"
scripts/known-hashes
git add tests/test_runner_ci.py vendor/known-hashes.json
git commit -m "test: tick --ci; refresh known hashes"
```

---

### Task 4: `job ensure-worktree`

**Files:**
- Modify: `vendor/factory/factory/bin/job`, `vendor/factory/.claude/skills/factory/SKILL.md`
- Create: `tests/test_ensure_worktree.py`

Stages that need a worktree: `spec`, `build`, `gate`, `review`, `approve`, `merging`. A `needs-human` job gets one only when its branch exists on origin (feedback would resume it). Other stages: nothing to do.

- [ ] **Step 1: Write the failing tests.** `tests/test_ensure_worktree.py`:

```python
import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from factory_project import FactoryProject, git


class EnsureWorktreeTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = FactoryProject(tmp.name)
        self.job = self.project.load_job()
        self.project.set_issue("Build the widget.", labels=("factory",))
        self.id = self.project.create_job(self.job)

    def set_stage(self, stage):
        job = self.job.load(self.id)
        job["stage"] = stage
        self.job.save(job)
        return job

    def ensure(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.job.cmd_ensure_worktree(self.job.load(self.id))
        return out.getvalue()

    def test_recreated_from_the_pushed_branch(self):
        job = self.set_stage("build")
        git(self.project.repo, "worktree", "add", "-q", "-b", job["branch"], job["worktree"], "origin/main")
        (Path(job["worktree"]) / "w.txt").write_text("work\n")
        git(job["worktree"], "add", "w.txt")
        git(job["worktree"], "commit", "-q", "-m", "work")
        git(job["worktree"], "push", "-q", "origin", job["branch"])
        pushed = git(job["worktree"], "rev-parse", "HEAD")
        git(self.project.repo, "worktree", "remove", "--force", job["worktree"])
        git(self.project.repo, "branch", "-D", job["branch"])
        self.assertIn(f"recreated from origin/{job['branch']}", self.ensure())
        self.assertEqual(git(job["worktree"], "rev-parse", "HEAD"), pushed)

    def test_created_from_base_when_the_branch_was_never_pushed(self):
        job = self.set_stage("spec")
        self.assertIn("created from origin/main", self.ensure())
        self.assertEqual(git(job["worktree"], "rev-parse", "HEAD"), self.project.sha)

    def test_present_and_stages_without_a_worktree_are_left_alone(self):
        self.assertIn("not needed", self.ensure())  # intake
        job = self.set_stage("build")
        Path(job["worktree"]).mkdir(parents=True)
        self.assertIn("present", self.ensure())

    def test_git_failure_sends_the_job_to_needs_human(self):
        self.set_stage("build")
        shutil.rmtree(self.project.repo / ".worktrees", ignore_errors=True)
        (self.project.repo / ".worktrees").write_text("a file where the worktrees directory should be")
        out = self.ensure()
        self.assertIn("needs-human", out)
        self.assertEqual(json.loads((self.job.job_dir(self.id) / "job.json").read_text())["stage"], "needs-human")
```

(Making `.worktrees` a file makes `git worktree add` fail, which is the error path under test. `stop_for_human` posts through the faked `gh`.)

- [ ] **Step 2: Run them and see them fail.**

- [ ] **Step 3: Implement.** In `job`:

```python
WORKTREE_STAGES = {"spec", "build", "gate", "review", "approve", "merging"}


def ensure_worktree(job):
    """'present', 'not needed', 'recreated from origin/<branch>' or 'created from origin/<base>'.
    Raises Refused when git fails."""
    if Path(job["worktree"]).exists():
        return "present"
    if job["stage"] not in WORKTREE_STAGES | {"needs-human"}:
        return "not needed"
    run(["git", "worktree", "prune"])
    pushed = run_net(["git", "ls-remote", "--heads", "origin", job["branch"]]).stdout.strip()
    if not pushed and job["stage"] == "needs-human":
        return "not needed"
    if pushed:
        run_net(["git", "fetch", "origin", f"+refs/heads/{job['branch']}:refs/remotes/origin/{job['branch']}"])
        run(["git", "worktree", "add", "-q", "-B", job["branch"], job["worktree"], f"origin/{job['branch']}"])
        return f"recreated from origin/{job['branch']}"
    run_net(["git", "fetch", "origin", BASE])
    run(["git", "worktree", "add", "-q", "-B", job["branch"], job["worktree"], f"origin/{BASE}"])
    return f"created from origin/{BASE}"


def cmd_ensure_worktree(job):
    try:
        print(f"WORKTREE: {job['id']} {ensure_worktree(job)}")
    except Refused as e:
        stop_for_human(job, f"The job's worktree couldn't be recreated on this machine:\n\n```\n{e}\n```")
```

Usage and `main`:

```
  job ensure-worktree <job>      recreate a missing worktree (fresh CI machines) from the job branch or the base
```

```python
        elif cmd == "ensure-worktree" and len(args) == 1:
            cmd_ensure_worktree(resolve(args[0]))
```

- [ ] **Step 4: Skill.** In `vendor/factory/.claude/skills/factory/SKILL.md` **Spawning agents**, after "Before every spawn, run `factory/bin/job agent <id> <role>`…", add:

```markdown
Before the first spawn for a job in this session (any stage from `spec` on),
run `factory/bin/job ensure-worktree <id>`. It prints `WORKTREE: <id> …`, or
moves the job to `needs-human` (its line says so) when the worktree can't be
recreated: then stop that job. Runs on a fresh machine (GitHub Actions) have
no `.worktrees/` until this recreates them.
```

Add to `tests/test_ensure_worktree.py`:

```python
class SkillWordingTest(unittest.TestCase):
    def test_skill_ensures_worktrees(self):
        text = (Path(__file__).resolve().parents[1] / "vendor/factory/.claude/skills/factory/SKILL.md").read_text()
        self.assertIn("factory/bin/job ensure-worktree <id>", text)
```

- [ ] **Step 5: Run them and see them pass.**

- [ ] **Step 6: Commit.**

```bash
git add vendor/factory/factory/bin/job
git commit -m "feat(vendor): job ensure-worktree recreates worktrees on a fresh machine"
git add vendor/factory/.claude/skills/factory/SKILL.md
git commit -m "feat(vendor): the factory skill ensures a job's worktree before spawning"
scripts/known-hashes
git add tests/test_ensure_worktree.py vendor/known-hashes.json
git commit -m "test: ensure-worktree; refresh known hashes"
```

---

### Task 5: `doctor --ci`

**Files:**
- Modify: `vendor/factory/factory/bin/doctor`
- Test: `tests/test_runner_ci.py`

With `--ci`, `check_runner` keeps the runner-settings checks and replaces the token and scheduler checks with three others:
- FAIL when `gh api repos/{owner}/{repo}/branches/factory-state/protection` succeeds (classic protection on it): `factory-state is protected; the Actions runner must be able to push it`.
- FAIL when `gh api repos/{owner}/{repo}/rules/branches/factory-state` lists any rule of type `update`, `non_fast_forward`, `creation`, `pull_request` or `required_status_checks`: `rules on factory-state block the runner (<types>)`.
- WARN when `.github/workflows/factory-runner.yml` is missing: `no Actions workflow; /factory-install writes it`.

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_runner_ci.py`:

```python
class DoctorCiTest(CiCase):
    def setUp(self):
        super().setUp()
        self.doctor = load_script(f"doctor_ci_{id(self)}", self.p.root / "factory/bin/doctor")
        self.doctor.CI = True
        self.answers = {}
        self.doctor.gh_api = lambda gh, path: self.answers.get(path.rsplit("/", 1)[-1])

    def test_unprotected_state_branch_and_workflow_present_pass(self):
        self.p.write(".github/workflows/factory-runner.yml", "name: factory-runner\n")
        self.assertEqual(self.doctor.ci_state_checks(), [])

    def test_protection_and_blocking_rules_fail(self):
        self.answers = {"protection": {"url": "x"}, "factory-state": [{"type": "non_fast_forward"}]}
        problems = self.doctor.ci_state_checks()
        self.assertIn(("FAIL", "factory-state is protected; the Actions runner must be able to push it"), problems)
        self.assertIn(("FAIL", "rules on factory-state block the runner (non_fast_forward)"), problems)
        self.assertIn(("WARN", "no Actions workflow; /factory-install writes it"), problems)
```

- [ ] **Step 2: Run them and see them fail.**

- [ ] **Step 3: Implement.** In `doctor`, add `CI = False` at module level and:

```python
STATE_BLOCKING = {"update", "non_fast_forward", "creation", "pull_request", "required_status_checks"}


def ci_state_checks():
    problems = []
    gh = shutil.which("gh") or "gh"
    if isinstance(gh_api(gh, "repos/{owner}/{repo}/branches/factory-state/protection"), dict):
        problems.append(fail("factory-state is protected; the Actions runner must be able to push it"))
    rules = gh_api(gh, "repos/{owner}/{repo}/rules/branches/factory-state")
    blocking = sorted({r.get("type") for r in rules if isinstance(r, dict)} & STATE_BLOCKING) if isinstance(rules, list) else []
    if blocking:
        problems.append(fail(f"rules on factory-state block the runner ({', '.join(blocking)})"))
    if not (REPO / ".github" / "workflows" / "factory-runner.yml").is_file():
        problems.append(warn("no Actions workflow; /factory-install writes it"))
    return problems
```

In `check_runner`, after the runner-settings checks and before reading the token service:

```python
    if CI:
        return problems + ci_state_checks()
```

In `main`, add `parser.add_argument("--ci", action="store_true", help="check the GitHub Actions runner instead of a local one")` and, after parsing, `global CI; CI = opts.ci`.

The test stubs `gh_api` by the last path segment: `protection` for the classic check, `factory-state` for the rules check.

- [ ] **Step 4: Run them and see them pass**, plus `python3 -m unittest tests/test_doctor.py -v`.

- [ ] **Step 5: Commit.**

```bash
git add vendor/factory/factory/bin/doctor
git commit -m "feat(vendor): doctor --ci checks the factory-state branch and the workflow"
scripts/known-hashes
git add tests/test_runner_ci.py vendor/known-hashes.json
git commit -m "test: doctor --ci; refresh known hashes"
```

---

### Task 6: `/factory-install` offers the Actions runner

**Files:**
- Modify: `skills/factory-install/SKILL.md`, `README.md`
- Test: `tests/test_factory_uninstall_skill.py` (or a new `tests/test_install_skill_actions.py`)

- [ ] **Step 1: Write the failing test.** `tests/test_install_skill_actions.py`:

```python
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "skills/factory-install/SKILL.md"


class InstallActionsTest(unittest.TestCase):
    def test_offers_the_workflow_off_by_default_with_secrets_and_a_public_repo_warning(self):
        text = SKILL.read_text()
        for needle in ("factory/bin/runner workflow --claude-version", ".github/workflows/factory-runner.yml",
                       "FACTORY_CLAUDE_TOKEN", "FACTORY_GH_TOKEN", "gh repo view --json visibility",
                       "never ask for", "off by default", "factory/bin/doctor --ci"):
            self.assertIn(needle, text)
```

- [ ] **Step 2: Run it and see it fail.**

- [ ] **Step 3: The skill.** In `skills/factory-install/SKILL.md`, add a bullet to **Step 2 (Adapt)**:

````markdown
- **Step 2 (Adapt), GitHub Actions runner (optional, off by default):** ask
  whether to run the factory on a schedule in GitHub Actions. Skip this unless
  they say yes.
  1. `gh repo view --json visibility --jq .visibility`. If it's `PUBLIC`,
     warn: "Scheduled workflows run with this repo's secrets. Forks can't
     reach them, but anyone with write access can change the workflow." Go on
     only if they confirm.
  2. Write the workflow, pinned to the installed Claude Code:

     ```bash
     mkdir -p .github/workflows
     factory/bin/runner workflow --claude-version "$(claude --version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)" \
       > .github/workflows/factory-runner.yml
     ```

  3. Tell them to create two repository secrets themselves (never ask for
     their values, and never run `gh secret set` with a value yourself):
     - `FACTORY_CLAUDE_TOKEN`: the output of `claude setup-token`;
     - `FACTORY_GH_TOKEN`: a fine-grained personal access token (or GitHub
       App token) for this repo only, with Contents, Issues and Pull
       requests read/write and Actions read. `GITHUB_TOKEN` isn't enough:
       pushes and PRs it makes don't trigger the project's CI.

     `gh secret set FACTORY_CLAUDE_TOKEN` prompts for the value, so they can
     paste it there.
  4. Run `factory/bin/doctor --ci` and report any FAIL or WARN. The workflow
     keeps job state on the `factory-state` branch; don't protect it.
````

- [ ] **Step 4: README.** Under `## Hands-off running`, add:

```markdown
### GitHub Actions

`/factory-install` can add `.github/workflows/factory-runner.yml` (off by
default). It runs `factory/bin/runner tick --ci` on a schedule, with your
`FACTORY_CLAUDE_TOKEN` and `FACTORY_GH_TOKEN` secrets. Runners are fresh
machines, so job state lives on an orphan `factory-state` branch that only
the runner writes, and missing worktrees are recreated from their pushed
branches. Work a run didn't push is redone by the next one. If saving state
fails twice, the run goes red and keeps `factory/jobs` as a workflow
artifact. Check the setup with `factory/bin/doctor --ci`.
```

- [ ] **Step 5: Run the test and see it pass**, then `scripts/check`.

- [ ] **Step 6: Commit.**

```bash
git add skills/factory-install/SKILL.md README.md tests/test_install_skill_actions.py
git commit -m "feat: factory-install offers the GitHub Actions runner"
```

## For the human after merge

- Run `/factory-update` here.
- Mark Phases 3–5 done in `docs/superpowers/specs/2026-11-13-roadmap.md` and cut a release.
