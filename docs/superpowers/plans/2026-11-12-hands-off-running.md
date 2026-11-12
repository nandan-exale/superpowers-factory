# Hands-off Running Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `factory/bin/runner` runs `/factory run` headless on a launchd schedule, sandboxed and allowlisted, with the Claude token read from the macOS Keychain, and `doctor` checks the setup.

**Architecture:** A vendored stdlib script, `factory/bin/runner`, with `tick` (lock → preflight → pull → idle check → Keychain token → `claude -p` with `--permission-mode dontAsk --settings factory/runner-settings.json` and a timeout → log) and `install`/`uninstall`/`status` for the LaunchAgent. Sandbox and permission rules live in the vendored `factory/runner-settings.json`, so interactive sessions are unaffected and `strictAllowlist` (ignored in project settings) takes effect.

**Tech Stack:** Python 3.11 stdlib (`fcntl`, `plistlib`, `subprocess`), `unittest`, fake `claude`/`gh`/`security`/`launchctl` scripts.

Spec: `docs/superpowers/specs/2026-11-12-hands-off-running-design.md`.
Run from `/Users/nandanthakur/projects/superpowers-factory`. Commit messages end
with a blank line and the `Co-Authored-By` trailer you were given.

## Verified Claude Code facts (docs, 2026-11)

Sources: code.claude.com/docs/en/{sandboxing,permissions,permission-modes,headless,hooks,authentication}.md

- `sandbox.enabled` (default false), `sandbox.autoAllowBashIfSandboxed` (default true), `sandbox.allowUnsandboxedCommands` (set false to remove the model's escape hatch), `sandbox.network.allowedDomains` (`*.` wildcards), `sandbox.network.strictAllowlist` (deny instead of prompt; **ignored in project settings**, honored from `--settings`). macOS uses Seatbelt, no install.
- Rules: `Bash(git *)`; deny beats allow; `Read(./.env)` relative paths.
- `-p` denies anything needing a prompt; `--permission-mode dontAsk` makes that explicit.
- `claude setup-token` → `CLAUDE_CODE_OAUTH_TOKEN`; `ANTHROPIC_API_KEY` outranks it, so it must be removed from the child env.
- `--output-format json` → `total_cost_usd`, `is_error`, `subtype`, `result`.
- Project Stop hooks run in `-p`; the factory's main checkout stays clean (job state is gitignored), so `stop-hook` doesn't block the orchestrator.

---

## File structure

| File | Change |
|---|---|
| `vendor/factory/factory/bin/runner` | create |
| `vendor/factory/factory/runner-settings.json` | create |
| `vendor/factory/factory/config.json` | add `runner` |
| `vendor/factory/factory/bin/doctor` | `runner` check, executables |
| `tests/installed_project.py` | copy runner files; fake `security`, `launchctl` |
| `tests/test_runner.py` | create |
| `tests/test_doctor.py` | runner tests |
| `scripts/check` | compile `runner` |
| `skills/factory-install/SKILL.md`, `README.md`, the spec | docs |

---

### Task 1: Config, settings file, test fakes

**Files:**
- Modify: `vendor/factory/factory/config.json`
- Create: `vendor/factory/factory/runner-settings.json`
- Create: `vendor/factory/factory/bin/runner` (config loading and CLI skeleton only)
- Modify: `tests/installed_project.py`
- Create: `tests/test_runner.py`

- [ ] **Step 1: Add config and the settings file**

In `vendor/factory/factory/config.json`, after the `"budgets"` line, add:

```json
  "runner": { "interval_minutes": 15, "max_minutes": 120, "keychain_service": "factory-claude-token" },
```

Create `vendor/factory/factory/runner-settings.json`:

```json
{
  "permissions": {
    "allow": [
      "Edit",
      "Write",
      "Bash(factory/bin/job *)",
      "Bash(factory/bin/gate *)",
      "Bash(factory/bin/route *)",
      "Bash(git *)",
      "Bash(gh *)",
      "Bash(bash factory/checks.sh)"
    ],
    "deny": [
      "Read(./.env)",
      "Read(./.env.*)",
      "Read(./secrets/**)",
      "Bash(git push --force *)",
      "Bash(git push -f *)"
    ]
  },
  "sandbox": {
    "enabled": true,
    "autoAllowBashIfSandboxed": true,
    "allowUnsandboxedCommands": false,
    "network": {
      "allowedDomains": ["github.com", "api.github.com", "*.githubusercontent.com"],
      "strictAllowlist": true
    }
  }
}
```

- [ ] **Step 2: Extend the test helper**

In `tests/installed_project.py`:

1. Add `"factory/bin/runner"` and `"factory/runner-settings.json"` to `COPIED`, after `"factory/bin/doctor"`.
2. Add, below `FAKE_GH`:

```python
# Records argv to $FAKE_RECORD (one JSON line per call) when set; exits $FAKE_<NAME>_EXIT (default 0);
# prints $FAKE_<NAME>_OUT when set.
FAKE_TOOL = """#!{python}
import json, os, sys
name = os.path.basename(sys.argv[0]).upper()
record = os.environ.get("FAKE_RECORD")
if record:
    with open(record, "a") as f:
        f.write(json.dumps({{"tool": name.lower(), "argv": sys.argv[1:]}}) + "\\n")
sys.stdout.write(os.environ.get(f"FAKE_{{name}}_OUT", ""))
sys.exit(int(os.environ.get(f"FAKE_{{name}}_EXIT", "0")))
"""
```

3. In `__init__`, after the fake `gh` is written, add:

```python
        for tool in ("security", "launchctl"):
            path = self.fakebin / tool
            path.write_text(FAKE_TOOL.format(python=sys.executable))
            path.chmod(0o755)
```

- [ ] **Step 3: Write the failing config tests**

Create `tests/test_runner.py`:

```python
import json
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from installed_project import InstalledProject, git

FAKE_CLAUDE = """#!{python}
import json, os, sys, time
with open(os.environ["FAKE_RECORD"], "a") as f:
    f.write(json.dumps({{"tool": "claude", "argv": sys.argv[1:],
        "has_token": os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") == "tok-123",
        "has_api_key": "ANTHROPIC_API_KEY" in os.environ,
        "has_base_url": "ANTHROPIC_BASE_URL" in os.environ}}) + "\\n")
time.sleep(float(os.environ.get("FAKE_CLAUDE_SLEEP", "0")))
print(json.dumps({{"type": "result", "subtype": "success", "is_error": False,
                  "total_cost_usd": 1.25, "result": "done"}}))
sys.exit(int(os.environ.get("FAKE_CLAUDE_EXIT", "0")))
"""

# Answers `gh issue list` from $FAKE_ISSUES (JSON list) and everything else with [].
FAKE_GH_QUEUE = """#!{python}
import os, sys
if sys.argv[1:3] == ["issue", "list"]:
    sys.stdout.write(open(os.environ["FAKE_ISSUES"]).read())
else:
    sys.stdout.write("[]")
"""


class RunnerCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.p = InstalledProject(self.tmp)
        self.record = self.tmp / "record.jsonl"
        self.issues = self.tmp / "issues.json"
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.set_issues([])
        for name, text in (("claude", FAKE_CLAUDE), ("gh", FAKE_GH_QUEUE)):
            path = self.p.fakebin / name
            path.write_text(text.format(python=sys.executable))
            path.chmod(0o755)
        self.add_origin()

    def add_origin(self):
        origin = self.tmp / "origin.git"
        git(self.tmp, "init", "-q", "--bare", "-b", "main", str(origin))
        git(self.p.root, "branch", "-M", "main")
        git(self.p.root, "remote", "add", "origin", str(origin))
        git(self.p.root, "push", "-q", "-u", "origin", "main")

    def set_issues(self, issues):
        self.issues.write_text(json.dumps(issues))

    def runner(self, *args, **env):
        full = self.p.env()
        full.update({"FAKE_RECORD": str(self.record), "FAKE_ISSUES": str(self.issues),
                     "HOME": str(self.home), "FAKE_SECURITY_OUT": "tok-123\n",
                     "ANTHROPIC_API_KEY": "must-be-removed", "ANTHROPIC_BASE_URL": "http://x"})
        full.update(env)
        return subprocess.run([sys.executable, str(self.p.root / "factory/bin/runner"), *args],
                              capture_output=True, text=True, cwd=self.p.root, env=full)

    def calls(self, tool):
        if not self.record.exists():
            return []
        return [c for c in map(json.loads, self.record.read_text().splitlines()) if c["tool"] == tool]

    def log_lines(self):
        path = self.p.root / "factory/jobs/runner.log"
        return path.read_text().splitlines() if path.exists() else []

    def edit_config(self, change):
        path = self.p.root / "factory/config.json"
        cfg = json.loads(path.read_text())
        change(cfg)
        path.write_text(json.dumps(cfg))
        self.p.commit_all("config")
        git(self.p.root, "push", "-q", "origin", "main")


class ConfigTest(RunnerCase):
    def test_bad_interval_exits_naming_the_key(self):
        self.edit_config(lambda c: c["runner"].update(interval_minutes=0))
        res = self.runner("tick")
        self.assertEqual(res.returncode, 1)
        self.assertIn("runner.interval_minutes", res.stderr)

    def test_missing_runner_config_exits(self):
        self.edit_config(lambda c: c.pop("runner"))
        res = self.runner("tick")
        self.assertEqual(res.returncode, 1)
        self.assertIn("no runner object", res.stderr)

    def test_bad_arguments_print_usage(self):
        res = self.runner("frobnicate")
        self.assertEqual(res.returncode, 1)
        self.assertIn("Usage:", res.stderr)


if __name__ == "__main__":
    unittest.main()
```

`InstalledProject.commit_all` exists from the project-harness work; if it
does not, add to the helper:

```python
    def commit_all(self, message):
        git(self.root, "add", "-A")
        self.commit(message)
```

- [ ] **Step 4: Run them to verify they fail**

Run: `python3 -m unittest discover -s tests -p 'test_runner.py' -v`
Expected: errors (`factory/bin/runner` doesn't exist, so `InstalledProject` can't copy it).

- [ ] **Step 5: Write the skeleton**

Create `vendor/factory/factory/bin/runner`:

```python
#!/usr/bin/env python3
"""Run the software factory unattended.

Usage:
  runner tick                  one scheduled run: lock, preflight, pull, check the queue, run /factory run headless
  runner install [--dry-run]   install the launchd LaunchAgent that runs `tick` every runner.interval_minutes
  runner uninstall             unload and delete the LaunchAgent
  runner status                LaunchAgent state and the last lines of factory/jobs/runner.log

The Claude token comes from the macOS Keychain item named by
runner.keychain_service (store it with
`security add-generic-password -s <service> -a "$USER" -w`). It is passed to
claude only through its environment, never in arguments, files or logs.
"""

import fcntl
import json
import os
import platform
import plistlib
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FACTORY = REPO / "factory"
JOBS = FACTORY / "jobs"
LOG = JOBS / "runner.log"
RUNS = JOBS / "runs"
SETTINGS = FACTORY / "runner-settings.json"
PROMPT = "/factory run"
STRIPPED_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN")


def die(message):
    print(f"runner: {message}", file=sys.stderr)
    sys.exit(1)


def load_config():
    """(base branch, validated runner config)."""
    cfg = json.loads((FACTORY / "config.json").read_text(encoding="utf-8"))
    runner = cfg.get("runner")
    if not isinstance(runner, dict):
        die("factory/config.json has no runner object (interval_minutes, max_minutes, keychain_service)")
    for key in ("interval_minutes", "max_minutes"):
        value = runner.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            die(f"factory/config.json runner.{key} must be a positive integer, not {value!r}")
    service = runner.get("keychain_service")
    if not isinstance(service, str) or not service.strip():
        die("factory/config.json runner.keychain_service must be a non-empty string")
    return cfg["base_branch"], runner


def main(argv):
    if argv == ["tick"]:
        return cmd_tick()
    if argv in (["install"], ["install", "--dry-run"]):
        return cmd_install(dry_run=len(argv) == 2)
    if argv == ["uninstall"]:
        return cmd_uninstall()
    if argv == ["status"]:
        return cmd_status()
    print(__doc__.strip(), file=sys.stderr)
    return 1


def cmd_tick():
    load_config()
    die("tick: not implemented yet")


def cmd_install(dry_run):
    load_config()
    die("install: not implemented yet")


def cmd_uninstall():
    die("uninstall: not implemented yet")


def cmd_status():
    die("status: not implemented yet")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

The three placeholder `die` calls are replaced in Tasks 2 and 3.

Then: `chmod +x vendor/factory/factory/bin/runner`

- [ ] **Step 6: Run the tests, then the whole suite**

Run: `python3 -m unittest discover -s tests -p 'test_runner.py' -v`
Expected: 3 tests, OK.

Run: `python3 -m unittest discover -s tests -q`
Expected: OK (doctor's healthy test still passes; the new fakes are inert).

- [ ] **Step 7: Commit**

```bash
git add vendor/factory/factory/config.json vendor/factory/factory/runner-settings.json vendor/factory/factory/bin/runner tests/installed_project.py tests/test_runner.py
git commit -m "feat: runner config, sandboxed runner settings and CLI skeleton"
```

---

### Task 2: `runner tick`

**Files:**
- Modify: `vendor/factory/factory/bin/runner`
- Modify: `tests/test_runner.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_runner.py`, before `if __name__`:

```python
class TickTest(RunnerCase):
    WORK = [{"number": 7, "title": "Build the widget"}]

    def test_idle_queue_does_not_call_claude(self):
        res = self.runner("tick")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.calls("claude"), [])
        self.assertTrue(self.log_lines()[-1].endswith(" idle"))

    def test_work_runs_claude_headless_with_token_and_no_api_vars(self):
        self.set_issues(self.WORK)
        res = self.runner("tick")
        self.assertEqual(res.returncode, 0, res.stderr)
        [call] = self.calls("claude")
        self.assertEqual(call["argv"][:4], ["-p", "/factory run", "--output-format", "json"])
        self.assertIn("--permission-mode", call["argv"])
        self.assertEqual(call["argv"][call["argv"].index("--permission-mode") + 1], "dontAsk")
        settings = call["argv"][call["argv"].index("--settings") + 1]
        self.assertTrue(settings.endswith("factory/runner-settings.json"))
        self.assertTrue(call["has_token"])
        self.assertFalse(call["has_api_key"])
        self.assertFalse(call["has_base_url"])
        line = self.log_lines()[-1]
        self.assertRegex(line, r" ran exit=0 \d+s cost=\$1\.25$")
        self.assertNotIn("tok-123", line + json.dumps(call["argv"]))
        runs = list((self.p.root / "factory/jobs/runs").glob("*.json"))
        self.assertEqual(len(runs), 1)
        self.assertEqual(json.loads(runs[0].read_text())["result"], "done")

    def test_token_is_read_from_the_configured_keychain_item(self):
        self.set_issues(self.WORK)
        self.runner("tick")
        [call] = self.calls("security")
        self.assertEqual(call["argv"], ["find-generic-password", "-s", "factory-claude-token", "-w"])

    def test_missing_token_is_an_error(self):
        self.set_issues(self.WORK)
        res = self.runner("tick", FAKE_SECURITY_EXIT="44", FAKE_SECURITY_OUT="")
        self.assertEqual(res.returncode, 1)
        self.assertEqual(self.calls("claude"), [])
        self.assertIn("error: no token in Keychain item factory-claude-token", self.log_lines()[-1])

    def test_dirty_tree_is_skipped_and_untouched(self):
        self.set_issues(self.WORK)
        self.p.write("AGENTS.md", "# Agents\nmine\n")
        res = self.runner("tick")
        self.assertEqual(res.returncode, 0)
        self.assertEqual(self.calls("claude"), [])
        self.assertIn("skipped: uncommitted changes", self.log_lines()[-1])
        self.assertEqual((self.p.root / "AGENTS.md").read_text(), "# Agents\nmine\n")

    def test_other_branch_is_skipped(self):
        git(self.p.root, "checkout", "-q", "-b", "feature")
        res = self.runner("tick")
        self.assertEqual(res.returncode, 0)
        self.assertIn("skipped: on feature, not main", self.log_lines()[-1])

    def test_pull_brings_in_new_commits(self):
        other = self.tmp / "other"
        git(self.tmp, "clone", "-q", str(self.tmp / "origin.git"), str(other))
        (other / "NEW.md").write_text("new\n")
        git(other, "add", "NEW.md")
        git(other, "-c", "user.email=t@e.com", "-c", "user.name=t", "-c", "commit.gpgsign=false",
            "commit", "-q", "-m", "new")
        git(other, "push", "-q", "origin", "main")
        self.runner("tick")
        self.assertTrue((self.p.root / "NEW.md").exists())

    def test_busy_when_locked(self):
        import fcntl
        lock_path = self.p.git_dir / "factory-runner.lock"
        with open(lock_path, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            res = self.runner("tick")
        self.assertEqual(res.returncode, 0)
        self.assertTrue(self.log_lines()[-1].endswith(" busy"))

    def test_timeout_kills_claude(self):
        self.set_issues(self.WORK)
        res = self.runner("tick", FACTORY_RUNNER_MAX_SECONDS="1", FAKE_CLAUDE_SLEEP="10")
        self.assertEqual(res.returncode, 1)
        self.assertRegex(self.log_lines()[-1], r" timeout after \d+s$")

    def test_claude_failure_is_logged_with_exit_code(self):
        self.set_issues(self.WORK)
        res = self.runner("tick", FAKE_CLAUDE_EXIT="3")
        self.assertEqual(res.returncode, 1)
        self.assertIn(" ran exit=3 ", self.log_lines()[-1])

    def test_every_tick_logs_exactly_one_line(self):
        self.runner("tick")
        self.runner("tick")
        self.assertEqual(len(self.log_lines()), 2)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest discover -s tests -p 'test_runner.py' -v`
Expected: the 11 new tests fail (`tick: not implemented yet`).

- [ ] **Step 3: Implement**

In `vendor/factory/factory/bin/runner`, replace `cmd_tick` with:

```python
def stamp():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(line):
    JOBS.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(f"{stamp()} {line}\n")


def git(*args):
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)


def git_path(name):
    return REPO / git("rev-parse", "--git-path", name).stdout.strip()


def first_line(text):
    return (text.strip().splitlines() or ["?"])[0]


def has_work():
    """True if `job queue` has a resume or new row. Daily-budget waits are not work."""
    res = subprocess.run([sys.executable, str(FACTORY / "bin" / "job"), "queue"],
                         cwd=REPO, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(first_line(res.stderr or res.stdout))
    return any(line.split("\t", 1)[0] in {"resume", "new"} for line in res.stdout.splitlines())


def read_token(service):
    res = subprocess.run(["security", "find-generic-password", "-s", service, "-w"],
                         capture_output=True, text=True)
    token = res.stdout.strip()
    return token if res.returncode == 0 and token else None


def run_claude(token, max_seconds):
    """(exit code, stdout) or None on timeout, plus elapsed seconds."""
    env = {k: v for k, v in os.environ.items() if k not in STRIPPED_ENV}
    env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    cmd = ["claude", "-p", PROMPT, "--output-format", "json",
           "--permission-mode", "dontAsk", "--settings", str(SETTINGS)]
    start = time.monotonic()
    proc = subprocess.Popen(cmd, cwd=REPO, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, start_new_session=True)
    try:
        out, _ = proc.communicate(timeout=max_seconds)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        return None, int(time.monotonic() - start)
    return (proc.returncode, out), int(time.monotonic() - start)


def cost_of(output):
    try:
        return f"${json.loads(output)['total_cost_usd']:.2f}"
    except (ValueError, KeyError, TypeError):
        return "?"


def cmd_tick():
    base, runner = load_config()
    lock = open(git_path("factory-runner.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("busy")
        return 0
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if branch != base:
        log(f"skipped: on {branch or '?'}, not {base}")
        return 0
    if git("status", "--porcelain").stdout.strip():
        log("skipped: uncommitted changes")
        return 0
    pull = git("pull", "--ff-only", "-q", "origin", base)
    if pull.returncode != 0:
        log(f"skipped: pull failed: {first_line(pull.stderr)}")
        return 0
    try:
        work = has_work()
    except RuntimeError as exc:
        log(f"error: queue: {exc}")
        return 1
    if not work:
        log("idle")
        return 0
    token = read_token(runner["keychain_service"])
    if not token:
        log(f"error: no token in Keychain item {runner['keychain_service']}; "
            "run claude setup-token and store it")
        return 1
    max_seconds = int(os.environ.get("FACTORY_RUNNER_MAX_SECONDS") or runner["max_minutes"] * 60)
    result, seconds = run_claude(token, max_seconds)
    if result is None:
        log(f"timeout after {seconds}s")
        return 1
    code, out = result
    RUNS.mkdir(parents=True, exist_ok=True)
    (RUNS / f"{stamp().replace(':', '')}.json").write_text(out)
    log(f"ran exit={code} {seconds}s cost={cost_of(out)}")
    return 0 if code == 0 else 1
```

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `python3 -m unittest discover -s tests -p 'test_runner.py' -v`
Expected: 14 tests, OK.

Run: `python3 -m unittest discover -s tests -q`
Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add vendor/factory/factory/bin/runner tests/test_runner.py
git commit -m "feat: runner tick runs /factory run headless when there is work"
```

---

### Task 3: `install`, `uninstall`, `status`

**Files:**
- Modify: `vendor/factory/factory/bin/runner`
- Modify: `tests/test_runner.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_runner.py`, before `if __name__`:

```python
class LaunchAgentTest(RunnerCase):
    def plist(self):
        res = self.runner("install", "--dry-run")
        self.assertEqual(res.returncode, 0, res.stderr)
        return plistlib.loads(res.stdout.encode())

    def test_dry_run_plist(self):
        p = self.plist()
        self.assertTrue(p["Label"].startswith("com.superpowers-factory."))
        self.assertRegex(p["Label"], r"^[a-z0-9.-]+$")
        self.assertEqual(p["ProgramArguments"][1:], [str(self.p.root / "factory/bin/runner"), "tick"])
        self.assertEqual(p["StartInterval"], 15 * 60)
        self.assertTrue(p["RunAtLoad"])
        self.assertEqual(p["WorkingDirectory"], str(self.p.root))
        self.assertEqual(p["StandardOutPath"], str(self.p.root / "factory/jobs/runner.launchd.log"))
        self.assertIn(str(self.p.fakebin), p["EnvironmentVariables"]["PATH"])

    def test_dry_run_changes_nothing(self):
        self.runner("install", "--dry-run")
        self.assertFalse((self.home / "Library").exists())
        self.assertEqual(self.calls("launchctl"), [])

    @unittest.skipUnless(sys.platform == "darwin", "launchd only")
    def test_install_writes_plist_and_bootstraps(self):
        res = self.runner("install")
        self.assertEqual(res.returncode, 0, res.stderr)
        plists = list((self.home / "Library/LaunchAgents").glob("com.superpowers-factory.*.plist"))
        self.assertEqual(len(plists), 1)
        argvs = [c["argv"] for c in self.calls("launchctl")]
        self.assertEqual(argvs[0][0], "bootout")
        self.assertEqual(argvs[-1], ["bootstrap", f"gui/{os.getuid()}", str(plists[0])])

    @unittest.skipUnless(sys.platform == "darwin", "launchd only")
    def test_uninstall_removes_plist(self):
        self.runner("install")
        res = self.runner("uninstall")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(list((self.home / "Library/LaunchAgents").glob("*.plist")), [])

    @unittest.skipUnless(sys.platform == "darwin", "launchd only")
    def test_status_shows_state_and_log_tail(self):
        self.runner("tick")
        res = self.runner("status", FAKE_LAUNCHCTL_EXIT="113")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("not loaded", res.stdout)
        self.assertIn(" idle", res.stdout)

    @unittest.skipIf(sys.platform == "darwin", "non-macOS behavior")
    def test_install_outside_macos_refuses(self):
        res = self.runner("install")
        self.assertEqual(res.returncode, 1)
        self.assertIn("launchd only", res.stderr)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest discover -s tests -p 'test_runner.py' -v`
Expected: the new tests that run on this platform fail (`install: not implemented yet`).

- [ ] **Step 3: Implement**

In `vendor/factory/factory/bin/runner`, replace `cmd_install`, `cmd_uninstall` and `cmd_status` with:

```python
def label():
    slug = re.sub(r"[^a-z0-9]+", "-", str(REPO).lower()).strip("-")
    return f"com.superpowers-factory.{slug}"


def plist_path():
    return Path.home() / "Library" / "LaunchAgents" / f"{label()}.plist"


def domain():
    return f"gui/{os.getuid()}"


def plist_bytes(runner):
    out = str(JOBS / "runner.launchd.log")
    return plistlib.dumps({
        "Label": label(),
        "ProgramArguments": [sys.executable, str(FACTORY / "bin" / "runner"), "tick"],
        "WorkingDirectory": str(REPO),
        "StartInterval": runner["interval_minutes"] * 60,
        "RunAtLoad": True,
        "StandardOutPath": out,
        "StandardErrorPath": out,
        "EnvironmentVariables": {"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
    })


def require_launchd():
    if platform.system() != "Darwin":
        die("launchd only (macOS); elsewhere run `factory/bin/runner tick` from cron or systemd")


def launchctl(*args):
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def cmd_install(dry_run):
    _, runner = load_config()
    data = plist_bytes(runner)
    if dry_run:
        sys.stdout.write(data.decode())
        return 0
    require_launchd()
    path = plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    JOBS.mkdir(parents=True, exist_ok=True)
    launchctl("bootout", f"{domain()}/{label()}")
    path.write_bytes(data)
    res = launchctl("bootstrap", domain(), str(path))
    if res.returncode != 0:
        die(f"launchctl bootstrap failed: {first_line(res.stderr)}")
    print(f"installed {path}; runs every {runner['interval_minutes']} min")
    return 0


def cmd_uninstall():
    require_launchd()
    launchctl("bootout", f"{domain()}/{label()}")
    plist_path().unlink(missing_ok=True)
    print(f"uninstalled {label()}")
    return 0


def cmd_status():
    require_launchd()
    loaded = launchctl("print", f"{domain()}/{label()}").returncode == 0
    path = plist_path()
    print(f"{label()}: {'loaded' if loaded else 'not loaded'}")
    print(f"plist: {path}{'' if path.exists() else ' (missing)'}")
    lines = LOG.read_text().splitlines()[-10:] if LOG.exists() else ["(no runner.log yet)"]
    print("\n".join(lines))
    return 0
```

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `python3 -m unittest discover -s tests -p 'test_runner.py' -v`
Expected: on macOS 19 tests OK, 1 skipped; on Linux the macOS-only tests skip.

Run: `python3 -m unittest discover -s tests -q`
Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add vendor/factory/factory/bin/runner tests/test_runner.py
git commit -m "feat: runner install, uninstall and status for the launchd agent"
```

---

### Task 4: doctor, repo check, install skill, README, spec

**Files:**
- Modify: `vendor/factory/factory/bin/doctor`
- Modify: `tests/test_doctor.py`
- Modify: `scripts/check`
- Modify: `skills/factory-install/SKILL.md`, `README.md`, `docs/superpowers/specs/2026-11-12-hands-off-running-design.md`

- [ ] **Step 1: Write the failing tests**

In `tests/test_doctor.py`, add `"runner"` to the end of `CHECK_NAMES`, and add to `DoctorTest`:

```python
    def runner_settings(self, change):
        path = self.p.root / "factory/runner-settings.json"
        data = json.loads(path.read_text())
        change(data)
        path.write_text(json.dumps(data))

    def test_runner_settings_without_sandbox_fail(self):
        self.runner_settings(lambda d: d["sandbox"].update(enabled=False))
        self.assertFails("runner", "factory/runner-settings.json: sandbox.enabled must be true")

    def test_runner_settings_missing_allow_rule_fail(self):
        self.runner_settings(lambda d: d["permissions"]["allow"].remove("Bash(gh *)"))
        self.assertFails("runner", "factory/runner-settings.json: missing allow rule Bash(gh *)")

    def test_runner_settings_with_escape_hatch_fail(self):
        self.runner_settings(lambda d: d["sandbox"].update(allowUnsandboxedCommands=True))
        self.assertFails("runner", "sandbox.allowUnsandboxedCommands must be false")

    def test_missing_keychain_item_warns(self):
        env_exit = {"FAKE_SECURITY_EXIT": "44"}
        res = self.p.run("doctor", "--fast", extra_env=env_exit)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("WARN runner: no Keychain item factory-claude-token", res.stdout)
```

`InstalledProject.run` must accept `extra_env` (a dict merged over `env()`);
if the current signature differs (it may take `env=`), use that and keep the
test's intent.

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest discover -s tests -p 'test_doctor.py' -v`
Expected: the new tests and `test_healthy_install_passes` (no `PASS runner`) fail.

- [ ] **Step 3: Implement doctor**

In `vendor/factory/factory/bin/doctor`:

1. Add `"factory/bin/runner"` to `EXECUTABLES`.
2. Add after `check_labels`:

```python
RUNNER_ALLOW = ("Bash(factory/bin/job *)", "Bash(factory/bin/gate *)", "Bash(factory/bin/route *)",
                "Bash(git *)", "Bash(gh *)", "Bash(bash factory/checks.sh)")


def check_runner():
    problems = []
    rel = "factory/runner-settings.json"
    path = REPO / rel
    if not path.is_file():
        return [fail(f"{rel} missing")]
    settings = json.loads(path.read_text(encoding="utf-8-sig"))
    sandbox = settings.get("sandbox") or {}
    if sandbox.get("enabled") is not True:
        problems.append(fail(f"{rel}: sandbox.enabled must be true"))
    if sandbox.get("allowUnsandboxedCommands") is not False:
        problems.append(fail(f"{rel}: sandbox.allowUnsandboxedCommands must be false"))
    allow = (settings.get("permissions") or {}).get("allow") or []
    problems += [fail(f"{rel}: missing allow rule {rule}") for rule in RUNNER_ALLOW if rule not in allow]
    cfg = json.loads((REPO / "factory" / "config.json").read_text(encoding="utf-8"))
    service = (cfg.get("runner") or {}).get("keychain_service")
    if not service:
        problems.append(fail("factory/config.json has no runner.keychain_service"))
    elif not shutil.which("security"):
        problems.append(warn("security not found; Keychain token not checked"))
    elif subprocess.run(["security", "find-generic-password", "-s", service],
                        capture_output=True, text=True).returncode != 0:
        problems.append(warn(f"no Keychain item {service}; run claude setup-token and "
                             f"security add-generic-password -s {service} -a \"$USER\" -w"))
    if sys.platform == "darwin" and shutil.which("launchctl"):
        slug = re.sub(r"[^a-z0-9]+", "-", str(REPO).lower()).strip("-")
        label = f"com.superpowers-factory.{slug}"
        if subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{label}"],
                          capture_output=True, text=True).returncode != 0:
            problems.append(warn("runner LaunchAgent not loaded; run factory/bin/runner install"))
    return problems
```

3. Add `("runner", check_runner),` to `CHECKS` before `("checks", check_checks)`.

The `find-generic-password` call has no `-w`, so the secret is never read.

- [ ] **Step 4: Repo check**

In `scripts/check`'s `check_compile`, add `"runner"` to the tuple of bin names.

- [ ] **Step 5: Run every test and the repo check**

Run: `python3 -m unittest discover -s tests -q && scripts/check`
Expected: OK; seven `PASS` lines, exit 0.

- [ ] **Step 6: Docs**

In `skills/factory-install/SKILL.md`:

1. Add `factory/bin/runner factory/runner-settings.json` to the copy loop, and
   `factory/bin/runner` to the `chmod +x` list.
2. Add this bullet after the CI bullet in Step 2 (Adapt):

   ```markdown
   - **Step 2 (Adapt), hands-off running:** in `factory/runner-settings.json`,
     add the package hosts the project's checks need to
     `sandbox.network.allowedDomains` (for example `registry.npmjs.org`,
     `pypi.org` and `files.pythonhosted.org`), found from the lockfiles and
     `factory/checks.sh`. List them for your human partner. Don't loosen
     anything else in that file. Then tell them the runner needs three steps
     they do themselves: (1) make a separate clone of the project for the
     runner, so it never works in the checkout they edit; (2) run
     `claude setup-token`, then
     `security add-generic-password -s factory-claude-token -a "$USER" -w`
     and paste the token at its prompt; (3) in that clone, run
     `factory/bin/runner install`. Never ask for, read or store the token.
   ```

In `README.md`, add before `## PR comments`:

```markdown
## Hands-off running

On macOS, `factory/bin/runner` runs `/factory run` every 15 minutes while
you're logged in, but only when the queue has work. Set it up once:

1. Clone the project a second time for the runner; it skips any run when its
   checkout has uncommitted changes or isn't on the base branch.
2. `claude setup-token`, then
   `security add-generic-password -s factory-claude-token -a "$USER" -w`
   and paste the token.
3. In the runner's clone: `factory/bin/runner install`.

Runs are headless with `--permission-mode dontAsk` and
`factory/runner-settings.json`: commands run in Claude Code's sandbox
(project files only, network limited to GitHub and your package hosts), and
anything not allowed is refused. `factory/bin/runner status` shows the last
runs; `factory/bin/doctor` checks the setup.
```

In `docs/superpowers/specs/2026-11-12-hands-off-running-design.md`, replace
the "Settings merged by /factory-install" subsection with:

```markdown
### Runner settings (factory/runner-settings.json)

Vendored and passed with `--settings`, not merged into the project's
`.claude/settings.json`: interactive sessions stay unsandboxed, and
`sandbox.network.strictAllowlist` (ignored in project settings) applies.
Contents: sandbox enabled, `autoAllowBashIfSandboxed: true`,
`allowUnsandboxedCommands: false`, network `allowedDomains` GitHub hosts plus
the project's package hosts (the install agent adds them), `strictAllowlist:
true`; `permissions.allow` for `Edit`, `Write` and `Bash(...)` rules for
`factory/bin/job`, `gate`, `route`, `git`, `gh`, `bash factory/checks.sh`;
`permissions.deny` for `.env`, `.env.*`, `secrets/**` reads and force pushes.
The runner passes `--permission-mode dontAsk`, so anything else is denied.
Verified against code.claude.com/docs (sandboxing, permissions,
permission-modes, headless, authentication), 2026-11.
```

and in its `doctor` subsection, change "`.claude/settings.json` lacks the
sandbox block or any of the allow rules above" to "`factory/runner-settings.json`
is missing, has the sandbox off or `allowUnsandboxedCommands` not false, or
lacks any of the Bash allow rules above".

- [ ] **Step 7: Run the repo check and commit**

Run: `scripts/check`
Expected: seven `PASS` lines, exit 0.

```bash
git add vendor/factory/factory/bin/doctor tests/test_doctor.py tests/installed_project.py scripts/check skills/factory-install/SKILL.md README.md docs/superpowers/specs/2026-11-12-hands-off-running-design.md
git commit -m "feat: doctor checks the runner; install and README document hands-off running"
```
