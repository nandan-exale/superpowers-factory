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
        self.assertEqual(parent, git(other, "rev-parse", "HEAD").strip())
        self.assertIn("002-b/job.json", self.state_files())

    def test_restore_refuses_unsafe_paths(self):
        bad = self.tmp / "bad.tar"
        with tarfile.open(bad, "w") as tar:
            info = tarfile.TarInfo("../escape.txt")
            info.size = 0
            tar.addfile(info, io.BytesIO(b""))
        with self.assertRaises(ValueError):
            self.runner.extract_state(bad.read_bytes(), self.p.root / "factory/jobs")
