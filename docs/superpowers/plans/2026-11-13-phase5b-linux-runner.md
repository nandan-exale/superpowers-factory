# Phase 5b: Linux systemd Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `factory/bin/runner install|uninstall|status` work on Linux through a systemd user timer. The token comes from `secret-tool` or a `0600` file, `doctor` checks the Linux sandbox's tools, and macOS keeps launchd.

**Architecture:**
- **Vendored `runner`:** one function, `platform_name()`, chooses launchd (`Darwin`) or systemd (`Linux`).
  - `systemd_units(runner)` renders `factory-<hash>.service` and `.timer`.
  - `cmd_install`, `cmd_uninstall` and `cmd_status` dispatch on the platform.
  - `read_token(service)` tries the Keychain on macOS. On Linux it tries `secret-tool lookup service <service>`, then `~/.config/factory/claude-token` when it's mode `0600` and owned by the user.
  - On Linux, a tick refuses to start Claude without `bwrap` (bubblewrap) and `socat`.
- **Vendored `doctor`:** on Linux, the runner check FAILs without `bwrap`/`socat`, WARNs on missing linger, a missing token or an inactive timer, and skips the Keychain and launchd checks.
- **README** gains a Linux section.

**Tech Stack:** Python 3.10+ stdlib, `unittest`. `systemctl`, `secret-tool`, `loginctl`, `bwrap` and `socat` are faked in tests.

**Spec:** `docs/superpowers/specs/2026-11-13-phase5-scale-design.md` (section 5b)

**Rules for this plan:**
- Never edit the spec or this plan. Make no git tags. Push nothing but the job branch.
- Each vendored edit in its own commit, then the plugin side with tests and the refreshed `vendor/known-hashes.json` (`scripts/known-hashes`).
- Change nothing in the installed copy (`factory/`, `.claude/` at the repo root).
- No test-only switch in vendored code. Tests load `factory/bin/runner` as a module (`installed_project.load_script`), replace `platform_name` and patch `HOME`/`PATH` in-process, and only then run the Linux paths.
- The token never appears in arguments, files the runner writes, or logs, exactly as on macOS.
- Built after Phase 5a is merged. Anchor every edit on function names.
- Full check: `scripts/check`.

---

### Task 1: Platform switch and the systemd units

**Files:**
- Modify: `vendor/factory/factory/bin/runner`
- Create: `tests/test_runner_linux.py`

Unit name: `factory-<first 12 hex of sha256(str(REPO))>`. Unit texts:

```ini
[Unit]
Description=Software factory runner for <REPO>

[Service]
Type=oneshot
WorkingDirectory=<REPO>
ExecStart=<sys.executable> <REPO>/factory/bin/runner tick
Environment=PATH=<the PATH at install time>
```

```ini
[Unit]
Description=Run the software factory for <REPO> every <n> min

[Timer]
OnBootSec=5min
OnUnitActiveSec=<interval_minutes>min
Persistent=true

[Install]
WantedBy=timers.target
```

- [ ] **Step 1: Write the failing tests.** `tests/test_runner_linux.py`:

```python
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from installed_project import InstalledProject, load_script

FAKE = """#!{python}
import json, os, sys
with open(os.environ["FAKE_RECORD"], "a") as f:
    f.write(json.dumps({{"tool": os.path.basename(sys.argv[0]), "argv": sys.argv[1:]}}) + "\\n")
name = os.path.basename(sys.argv[0]).upper().replace("-", "_")
sys.stdout.write(os.environ.get(f"FAKE_{{name}}_OUT", ""))
sys.exit(int(os.environ.get(f"FAKE_{{name}}_EXIT", "0")))
"""


class LinuxCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.p = InstalledProject(self.tmp)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.bin = self.tmp / "linuxbin"
        self.bin.mkdir()
        for tool in ("systemctl", "secret-tool", "loginctl", "bwrap", "socat"):
            (self.bin / tool).write_text(FAKE.format(python=__import__("sys").executable))
            (self.bin / tool).chmod(0o755)
        self.record = self.tmp / "record.jsonl"
        self.env = {"HOME": str(self.home), "FAKE_RECORD": str(self.record),
                    "PATH": f"{self.bin}{os.pathsep}/usr/bin{os.pathsep}/bin"}
        self.runner = load_script(f"runner_{id(self)}", self.p.root / "factory/bin/runner")
        self.runner.platform_name = lambda: "Linux"

    def call(self, fn, *args, **env):
        out = io.StringIO()
        with mock.patch.dict(os.environ, {**self.env, **env}), contextlib.redirect_stdout(out):
            code = fn(*args)
        return code, out.getvalue()

    def calls(self, tool):
        lines = self.record.read_text().splitlines() if self.record.exists() else []
        return [c["argv"] for c in map(json.loads, lines) if c["tool"] == tool]


class UnitsTest(LinuxCase):
    def test_units_render_from_config(self):
        _, runner = self.runner.load_config()
        service, timer = self.runner.systemd_units(runner)
        self.assertIn("Type=oneshot", service)
        self.assertIn(f"ExecStart={__import__('sys').executable} {self.runner.REPO}/factory/bin/runner tick", service)
        self.assertIn(f"WorkingDirectory={self.runner.REPO}", service)
        self.assertIn(f"OnUnitActiveSec={runner['interval_minutes']}min", timer)
        self.assertIn("Persistent=true", timer)
        self.assertRegex(self.runner.unit_name(), r"^factory-[0-9a-f]{12}$")

    def test_dry_run_prints_both_units_and_changes_nothing(self):
        code, out = self.call(self.runner.cmd_install, True)
        self.assertEqual(code, 0)
        self.assertIn("[Timer]", out)
        self.assertIn("[Service]", out)
        self.assertEqual(self.calls("systemctl"), [])

    def test_install_writes_units_and_enables_the_timer(self):
        code, out = self.call(self.runner.cmd_install, False)
        self.assertEqual(code, 0, out)
        units = self.home / ".config/systemd/user"
        name = self.runner.unit_name()
        self.assertTrue((units / f"{name}.service").is_file())
        self.assertTrue((units / f"{name}.timer").is_file())
        self.assertEqual(self.calls("systemctl"), [["--user", "daemon-reload"],
                                                   ["--user", "enable", "--now", f"{name}.timer"]])

    def test_uninstall_disables_and_deletes(self):
        self.call(self.runner.cmd_install, False)
        code, _ = self.call(self.runner.cmd_uninstall)
        self.assertEqual(code, 0)
        self.assertFalse(any((self.home / ".config/systemd/user").iterdir()))
        self.assertIn(["--user", "disable", "--now", f"{self.runner.unit_name()}.timer"], self.calls("systemctl"))

    def test_status_lists_the_timer_and_the_log(self):
        code, out = self.call(self.runner.cmd_status, FAKE_SYSTEMCTL_OUT="NEXT LEFT UNIT\n")
        self.assertEqual(code, 0)
        self.assertIn("NEXT LEFT UNIT", out)
        self.assertIn("(no runner.log yet)", out)

    def test_other_platforms_refuse(self):
        self.runner.platform_name = lambda: "Windows"
        with self.assertRaises(SystemExit):
            self.call(self.runner.cmd_install, False)
```

- [ ] **Step 2: Run them and see them fail.** `python3 -m unittest tests/test_runner_linux.py -v`

- [ ] **Step 3: Implement.** In `vendor/factory/factory/bin/runner`:

Add after `require_launchd`:

```python
def platform_name():
    return platform.system()


def unit_name():
    return f"factory-{hashlib.sha256(str(REPO).encode()).hexdigest()[:12]}"


def units_dir():
    return Path.home() / ".config" / "systemd" / "user"


def systemd_units(runner):
    service = (f"[Unit]\nDescription=Software factory runner for {REPO}\n\n"
               f"[Service]\nType=oneshot\nWorkingDirectory={REPO}\n"
               f"ExecStart={sys.executable} {FACTORY / 'bin' / 'runner'} tick\n"
               f"Environment=PATH={os.environ.get('PATH', '/usr/bin:/bin')}\n")
    timer = (f"[Unit]\nDescription=Run the software factory for {REPO} every {runner['interval_minutes']} min\n\n"
             f"[Timer]\nOnBootSec=5min\nOnUnitActiveSec={runner['interval_minutes']}min\nPersistent=true\n\n"
             "[Install]\nWantedBy=timers.target\n")
    return service, timer


def systemctl(*args):
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True)


def require_scheduler():
    name = platform_name()
    if name not in ("Darwin", "Linux"):
        die(f"no scheduler for {name}; run `factory/bin/runner tick` from your own scheduler")
    return name


def install_systemd(runner, dry_run):
    service, timer = systemd_units(runner)
    if dry_run:
        sys.stdout.write(f"# {unit_name()}.service\n{service}\n# {unit_name()}.timer\n{timer}")
        return 0
    d = units_dir()
    d.mkdir(parents=True, exist_ok=True)
    JOBS.mkdir(parents=True, exist_ok=True)
    (d / f"{unit_name()}.service").write_text(service)
    (d / f"{unit_name()}.timer").write_text(timer)
    for args in (("daemon-reload",), ("enable", "--now", f"{unit_name()}.timer")):
        res = systemctl(*args)
        if res.returncode != 0:
            die(f"systemctl --user {' '.join(args)} failed: {first_line(res.stderr)}")
    print(f"installed {d / unit_name()}.timer; runs every {runner['interval_minutes']} min. "
          "Run `loginctl enable-linger $USER` so it also runs while you're logged out.")
    return 0
```

Rename the existing `cmd_install`, `cmd_uninstall` and `cmd_status` to `install_launchd(runner, dry_run)`, `uninstall_launchd()` and `status_launchd()`, unchanged except that `install_launchd` takes `runner` instead of calling `load_config()` and keeps its `dry_run` plist output. Then add:

```python
def cmd_install(dry_run):
    _, runner = load_config()
    if dry_run and platform_name() != "Linux":
        return install_launchd(runner, dry_run)
    name = require_scheduler()
    return install_systemd(runner, dry_run) if name == "Linux" else install_launchd(runner, dry_run)


def cmd_uninstall():
    if require_scheduler() == "Darwin":
        return uninstall_launchd()
    systemctl("disable", "--now", f"{unit_name()}.timer")
    for suffix in ("service", "timer"):
        (units_dir() / f"{unit_name()}.{suffix}").unlink(missing_ok=True)
    systemctl("daemon-reload")
    print(f"uninstalled {unit_name()}")
    return 0


def cmd_status():
    if require_scheduler() == "Darwin":
        return status_launchd()
    print(systemctl("list-timers", "--all", f"{unit_name()}.timer").stdout.rstrip())
    lines = LOG.read_text().splitlines()[-10:] if LOG.exists() else ["(no runner.log yet)"]
    print("\n".join(lines))
    return 0
```

Remove `require_launchd()` calls from the renamed launchd functions (the dispatcher already checked). Keep `test_install_outside_macos_refuses` in `tests/test_runner.py` meaningful: it expects a refusal off macOS. Change it to replace `platform_name` with `lambda: "Windows"` in-process (load the runner as `tests/test_runner_linux.py` does), or adjust its expected message to `no scheduler for`. Keep it a refusal test.

Update the module docstring:

```
  runner install [--dry-run]   install the scheduler: a launchd LaunchAgent on macOS, a systemd user timer on Linux
  runner uninstall             remove it
  runner status                scheduler state and the last lines of factory/jobs/runner.log
```

- [ ] **Step 4: Run them and see them pass**, plus `python3 -m unittest tests/test_runner.py -v`.

- [ ] **Step 5: Commit.**

```bash
git add vendor/factory/factory/bin/runner
git commit -m "feat(vendor): runner installs a systemd user timer on Linux"
scripts/known-hashes
git add tests/test_runner_linux.py tests/test_runner.py vendor/known-hashes.json
git commit -m "test: systemd units, install, uninstall, status; refresh known hashes"
```

---

### Task 2: Token on Linux, and the sandbox tools at tick time

**Files:**
- Modify: `vendor/factory/factory/bin/runner` (`read_token`, `cmd_tick`)
- Test: `tests/test_runner_linux.py`

Order on Linux: `secret-tool lookup service <service>` when `secret-tool` is on `PATH` and prints a token; else `~/.config/factory/claude-token` when it exists. If that file's mode isn't exactly `0600` or its owner isn't the current user, the runner refuses: it returns no token and logs `error: ~/.config/factory/claude-token must be mode 600 and yours; run chmod 600 <path>`. The token itself is never logged.

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_runner_linux.py`:

```python
class TokenTest(LinuxCase):
    def token(self, **env):
        with mock.patch.dict(os.environ, {**self.env, **env}):
            return self.runner.read_token("factory-claude-token")

    def write_file_token(self, mode):
        path = self.home / ".config/factory/claude-token"
        path.parent.mkdir(parents=True)
        path.write_text("file-token\n")
        path.chmod(mode)
        return path

    def test_secret_tool_first(self):
        self.write_file_token(0o600)
        self.assertEqual(self.token(FAKE_SECRET_TOOL_OUT="st-token\n"), "st-token")
        self.assertEqual(self.calls("secret-tool"), [["lookup", "service", "factory-claude-token"]])

    def test_file_when_secret_tool_has_nothing(self):
        self.write_file_token(0o600)
        self.assertEqual(self.token(FAKE_SECRET_TOOL_EXIT="1"), "file-token")

    def test_a_file_readable_by_others_is_refused(self):
        self.write_file_token(0o644)
        self.assertIsNone(self.token(FAKE_SECRET_TOOL_EXIT="1"))
        self.assertIn("chmod 600", self.runner.token_problem())

    def test_no_token_anywhere(self):
        self.assertIsNone(self.token(FAKE_SECRET_TOOL_EXIT="1"))


class SandboxToolsTest(LinuxCase):
    def test_missing_bubblewrap_is_named(self):
        (self.bin / "bwrap").unlink()
        with mock.patch.dict(os.environ, self.env):
            self.assertEqual(self.runner.missing_sandbox_tools(), ["bwrap"])
```

- [ ] **Step 2: Run them and see them fail.**

- [ ] **Step 3: Implement.** In `runner`, replace `read_token` with:

```python
TOKEN_FILE = Path("~/.config/factory/claude-token")
SANDBOX_TOOLS = ("bwrap", "socat")
_token_problem = None


def token_problem():
    """Why the last read_token found no usable token file, or None."""
    return _token_problem


def read_keychain(service):
    res = subprocess.run(["security", "find-generic-password", "-s", service, "-w"],
                         capture_output=True, text=True)
    token = res.stdout.strip()
    return token if res.returncode == 0 and token else None


def read_linux_token(service):
    global _token_problem
    _token_problem = None
    if shutil.which("secret-tool"):
        res = subprocess.run(["secret-tool", "lookup", "service", service], capture_output=True, text=True)
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    path = TOKEN_FILE.expanduser()
    if not path.exists():
        return None
    st = path.stat()
    if (st.st_mode & 0o777) != 0o600 or st.st_uid != os.getuid():
        _token_problem = f"{TOKEN_FILE} must be mode 600 and yours; run chmod 600 {path}"
        return None
    return path.read_text().strip() or None


def read_token(service):
    return read_linux_token(service) if platform_name() == "Linux" else read_keychain(service)


def missing_sandbox_tools():
    return [tool for tool in SANDBOX_TOOLS if not shutil.which(tool)]
```

Add `import shutil` at the top.

In `cmd_tick`, where it reads the token and logs `error: no token in Keychain item …`, change the message for Linux:

```python
    token = read_token(runner["keychain_service"])
    if not token:
        where = (token_problem() or f"no token from secret-tool (service {runner['keychain_service']}) "
                 f"or {TOKEN_FILE}") if platform_name() == "Linux" else \
            f"no token in Keychain item {runner['keychain_service']}; run claude setup-token and store it"
        log(f"error: {where}")
        return 1
    if platform_name() == "Linux" and missing_sandbox_tools():
        log(f"error: {', '.join(missing_sandbox_tools())} missing; Claude Code's Linux sandbox needs bubblewrap and socat")
        return 1
```

Update the module docstring's token paragraph to cover Linux: "On Linux the token comes from `secret-tool lookup service <service>`, or from `~/.config/factory/claude-token` with mode 600."

- [ ] **Step 4: Run them and see them pass**, plus `python3 -m unittest tests/test_runner.py -v` (macOS path unchanged).

- [ ] **Step 5: Commit.**

```bash
git add vendor/factory/factory/bin/runner
git commit -m "feat(vendor): runner reads the token from secret-tool or a 0600 file on Linux"
scripts/known-hashes
git add tests/test_runner_linux.py vendor/known-hashes.json
git commit -m "test: Linux token sources and sandbox tools; refresh known hashes"
```

---

### Task 3: Doctor on Linux

**Files:**
- Modify: `vendor/factory/factory/bin/doctor` (`check_runner`)
- Test: `tests/test_runner_linux.py`

On Linux, `check_runner` does the following:
- FAILs for each of `bwrap` and `socat` missing on `PATH`: `<tool> not found; Claude Code's Linux sandbox needs bubblewrap and socat (apt install bubblewrap socat)`.
- WARNs when neither `secret-tool lookup service <service>` nor a `0600` `~/.config/factory/claude-token` gives a token.
- WARNs when `loginctl show-user $USER -p Linger` doesn't print `Linger=yes`: `run loginctl enable-linger $USER so the timer runs while you're logged out`.
- WARNs when `systemctl --user is-active <unit>.timer` isn't `active`: `runner timer not active; run factory/bin/runner install`.
- Skips the Keychain and launchd checks.

Shared checks (runner settings, branch protection) stay.

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_runner_linux.py`:

```python
class DoctorLinuxTest(LinuxCase):
    def setUp(self):
        super().setUp()
        self.doctor = load_script(f"doctor_{id(self)}", self.p.root / "factory/bin/doctor")
        self.doctor.platform_name = lambda: "Linux"
        self.doctor.check_branch_protection = lambda base: []

    def runner_check(self, **env):
        with mock.patch.dict(os.environ, {**self.env, **env}):
            return self.doctor.check_runner()

    def test_missing_sandbox_tools_fail(self):
        (self.bin / "socat").unlink()
        problems = self.runner_check(FAKE_SECRET_TOOL_OUT="t\n", FAKE_LOGINCTL_OUT="Linger=yes\n",
                                     FAKE_SYSTEMCTL_OUT="active\n")
        self.assertIn(("FAIL", "socat not found; Claude Code's Linux sandbox needs bubblewrap and socat "
                               "(apt install bubblewrap socat)"), problems)

    def test_linger_token_and_timer_warn(self):
        problems = self.runner_check(FAKE_SECRET_TOOL_EXIT="1", FAKE_LOGINCTL_OUT="Linger=no\n",
                                     FAKE_SYSTEMCTL_OUT="inactive\n")
        texts = [m for level, m in problems if level == "WARN"]
        self.assertTrue(any("enable-linger" in t for t in texts))
        self.assertTrue(any("no runner token" in t for t in texts))
        self.assertTrue(any("timer not active" in t for t in texts))
        self.assertFalse(any("Keychain" in t or "LaunchAgent" in t for t in texts))

    def test_all_good_is_quiet(self):
        problems = self.runner_check(FAKE_SECRET_TOOL_OUT="t\n", FAKE_LOGINCTL_OUT="Linger=yes\n",
                                     FAKE_SYSTEMCTL_OUT="active\n")
        self.assertEqual(problems, [])
```

- [ ] **Step 2: Run them and see them fail.**

- [ ] **Step 3: Implement.** In `vendor/factory/factory/bin/doctor`:

```python
def platform_name():
    return platform.system()


def unit_name():
    """Must match unit_name() in factory/bin/runner (a test keeps them equal)."""
    return f"factory-{hashlib.sha256(str(REPO).encode()).hexdigest()[:12]}"


def linux_runner_checks(service):
    problems = [fail(f"{tool} not found; Claude Code's Linux sandbox needs bubblewrap and socat "
                     "(apt install bubblewrap socat)") for tool in ("bwrap", "socat") if not shutil.which(tool)]
    token = False
    if shutil.which("secret-tool"):
        res = subprocess.run(["secret-tool", "lookup", "service", service], capture_output=True, text=True)
        token = res.returncode == 0 and bool(res.stdout.strip())
    path = Path("~/.config/factory/claude-token").expanduser()
    if not token and path.exists():
        token = (path.stat().st_mode & 0o777) == 0o600 and path.stat().st_uid == os.getuid()
    if not token:
        problems.append(warn(f"no runner token; store one with secret-tool store --label factory service {service}, "
                             "or in ~/.config/factory/claude-token with chmod 600"))
    user = os.environ.get("USER", "")
    linger = subprocess.run(["loginctl", "show-user", user, "-p", "Linger"], capture_output=True, text=True)
    if "Linger=yes" not in linger.stdout:
        problems.append(warn("run loginctl enable-linger $USER so the timer runs while you're logged out"))
    active = subprocess.run(["systemctl", "--user", "is-active", f"{unit_name()}.timer"], capture_output=True, text=True)
    if active.stdout.strip() != "active":
        problems.append(warn("runner timer not active; run factory/bin/runner install"))
    return problems
```

Add `import platform` (and `from pathlib import Path` if missing).

In `check_runner`, after reading `service`, branch:

```python
    if not service:
        problems.append(fail("factory/config.json has no runner.keychain_service"))
    elif platform_name() == "Linux":
        problems += linux_runner_checks(service)
    elif not shutil.which("security"):
        ...  # the existing macOS branches, unchanged
```

and guard the launchd block at the end with `platform_name() == "Darwin"` instead of `sys.platform == "darwin"`.

Add to `tests/test_runner_linux.py`:

```python
class NamesAgreeTest(LinuxCase):
    def test_runner_and_doctor_name_the_same_unit(self):
        doctor = load_script(f"doctor_names_{id(self)}", self.p.root / "factory/bin/doctor")
        self.assertEqual(doctor.unit_name(), self.runner.unit_name())
```

- [ ] **Step 4: Run them and see them pass**, plus `python3 -m unittest tests/test_doctor.py -v`.

- [ ] **Step 5: Commit.**

```bash
git add vendor/factory/factory/bin/doctor
git commit -m "feat(vendor): doctor checks the Linux runner: sandbox tools, token, linger, timer"
scripts/known-hashes
git add tests/test_runner_linux.py vendor/known-hashes.json
git commit -m "test: doctor on Linux; refresh known hashes"
```

---

### Task 4: README

- [ ] **Step 1:** In `README.md`, rename `## Hands-off running (macOS)` to `## Hands-off running` and add a subsection after the macOS text:

````markdown
### Linux (systemd)

```bash
sudo apt install bubblewrap socat          # Claude Code's Linux sandbox
claude setup-token                         # prints a long-lived token
secret-tool store --label factory service factory-claude-token   # paste it
# or: mkdir -p ~/.config/factory && install -m 600 /dev/stdin ~/.config/factory/claude-token
factory/bin/runner install                 # a systemd user timer every runner.interval_minutes
loginctl enable-linger "$USER"             # keep it running while you're logged out
factory/bin/doctor
```

`factory/bin/runner status` shows the timer and the log; `factory/bin/runner
uninstall` removes it. The runner refuses a token file that isn't mode 600
and yours, and won't start Claude without bubblewrap and socat.
````

Fix any README link to the old heading anchor (`#hands-off-running-macos`).

- [ ] **Step 2: Check and commit.**

```bash
scripts/check
git add README.md
git commit -m "docs: hands-off running on Linux"
```

## For the human after merge

- Run `/factory-update` here.
- Add the `factory` label to the Phase 5c issue.
