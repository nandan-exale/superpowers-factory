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
