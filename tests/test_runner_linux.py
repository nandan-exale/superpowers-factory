import contextlib
import io
import json
import os
import shutil
import signal
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from installed_project import InstalledProject, load_script
from test_runner import RunnerCase

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

    def test_missing_systemctl_is_a_clear_error(self):
        (self.bin / "systemctl").unlink()
        err = io.StringIO()
        for fn, args in ((self.runner.cmd_install, (False,)), (self.runner.cmd_uninstall, ()),
                         (self.runner.cmd_status, ())):
            with contextlib.redirect_stderr(err), self.assertRaises(SystemExit):
                self.call(fn, *args, PATH=str(self.bin))
        self.assertEqual(err.getvalue().count("systemctl not found"), 3)


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

    def test_missing_loginctl_and_systemctl_warn_instead_of_crashing(self):
        (self.bin / "loginctl").unlink()
        (self.bin / "systemctl").unlink()
        problems = self.runner_check(PATH=str(self.bin), FAKE_SECRET_TOOL_OUT="t\n")
        texts = [m for level, m in problems if level == "WARN"]
        self.assertIn("loginctl not found; linger not checked", texts)
        self.assertIn("systemctl not found; the systemd timer can't run", texts)

    def test_all_good_is_quiet(self):
        problems = self.runner_check(FAKE_SECRET_TOOL_OUT="t\n", FAKE_LOGINCTL_OUT="Linger=yes\n",
                                     FAKE_SYSTEMCTL_OUT="active\n")
        self.assertEqual(problems, [])


class NamesAgreeTest(LinuxCase):
    def test_runner_and_doctor_name_the_same_unit(self):
        doctor = load_script(f"doctor_names_{id(self)}", self.p.root / "factory/bin/doctor")
        self.assertEqual(doctor.unit_name(), self.runner.unit_name())


class LinuxTickTest(RunnerCase):
    """cmd_tick in-process on Linux, with a queue that has work."""

    def setUp(self):
        super().setUp()
        self.set_issues([{"number": 7, "title": "Build the widget"}])
        self.linuxbin = self.tmp / "linuxbin"
        self.linuxbin.mkdir()
        for tool in ("secret-tool", "bwrap", "socat"):
            (self.linuxbin / tool).write_text(FAKE.format(python=__import__("sys").executable))
            (self.linuxbin / tool).chmod(0o755)
        # Only git from the system, so a real bwrap or socat on the host can't leak in.
        gitbin = self.tmp / "gitbin"
        gitbin.mkdir()
        (gitbin / "git").symlink_to(shutil.which("git"))
        self.path = os.pathsep.join(map(str, (self.p.fakebin, self.linuxbin, gitbin)))
        self.module = load_script(f"runner_tick_{id(self)}", self.p.root / "factory/bin/runner")
        self.module.platform_name = lambda: "Linux"
        self.addCleanup(signal.signal, signal.SIGTERM, signal.getsignal(signal.SIGTERM))

    def tick(self, **env):
        with mock.patch.dict(os.environ, self.runner_env(PATH=self.path, **env), clear=True):
            return self.module.cmd_tick()

    def token_file(self, text, mode):
        path = self.home / ".config/factory/claude-token"
        path.parent.mkdir(parents=True)
        path.write_text(text)
        path.chmod(mode)

    def test_missing_bubblewrap_skips_with_a_log_line(self):
        (self.linuxbin / "bwrap").unlink()
        self.assertEqual(self.tick(FAKE_SECRET_TOOL_OUT="tok-123\n"), 1)
        self.assertEqual(self.calls("claude"), [])
        self.assertTrue(self.log_lines()[-1].endswith(
            "error: bwrap missing; Claude Code's Linux sandbox needs bubblewrap and socat"))

    def test_open_token_file_is_refused_with_the_chmod_fix(self):
        self.token_file("file-token\n", 0o644)
        self.assertEqual(self.tick(FAKE_SECRET_TOOL_EXIT="1"), 1)
        self.assertEqual(self.calls("claude"), [])
        last = self.log_lines()[-1]
        self.assertIn("must be mode 600 and yours; run chmod 600", last)
        self.assertNotIn("file-token", last)

    def test_private_token_file_reaches_claude_only_through_its_environment(self):
        self.token_file("tok-123\n", 0o600)
        self.assertEqual(self.tick(FAKE_SECRET_TOOL_EXIT="1"), 0)
        [call] = self.calls("claude")
        self.assertTrue(call["has_token"])
        self.assertNotIn("tok-123", json.dumps(call["argv"]))
        self.assertNotIn("tok-123", "\n".join(self.log_lines()))
