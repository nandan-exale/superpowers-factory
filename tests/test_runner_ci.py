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
        self.assertTrue(all((len(l) - len(l.lstrip(" "))) % 2 == 0 for l in text.splitlines()))

    def test_cron_has_a_15_minute_floor(self):
        self.assertEqual(self.runner.cron(5), "*/15 * * * *")
        self.assertEqual(self.runner.cron(30), "*/30 * * * *")
        self.assertEqual(self.runner.cron(120), "0 */2 * * *")

    def test_bad_version_is_refused(self):
        with self.assertRaises(SystemExit):
            self.out(self.runner.cmd_workflow, "latest")
