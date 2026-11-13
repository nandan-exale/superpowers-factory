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

    def test_state_commit_runs_no_filter_or_signing_program_from_local_config(self):
        filter_ran, gpg_ran = self.tmp / "filter-ran", self.tmp / "gpg-ran"
        fake_gpg = self.tmp / "fake-gpg"
        fake_gpg.write_text(f"#!/bin/sh\ntouch {gpg_ran}\nexit 1\n")
        fake_gpg.chmod(0o755)
        git(self.p.root, "config", "filter.x.clean", f"touch {filter_ran}; cat")
        git(self.p.root, "config", "commit.gpgsign", "true")
        git(self.p.root, "config", "gpg.program", str(fake_gpg))
        self.write(".gitattributes", "* filter=x\n")
        self.write("001-a/job.json", "{}")
        commit = self.runner.state_commit(self.runner.state_files(), "")
        self.assertFalse(filter_ran.exists())
        self.assertFalse(gpg_ran.exists())
        self.assertEqual(git(self.p.root, "show", f"{commit}:001-a/job.json"), "{}")

    def test_symlinks_are_not_saved(self):
        secret = self.tmp / "outside.txt"
        secret.write_text("not job state")
        self.write("001-a/job.json", "{}")
        (self.p.root / "factory/jobs/001-a/link").symlink_to(secret)
        self.assertEqual(self.runner.state_files(), ["001-a/job.json"])

    def test_save_refuses_when_the_clone_could_run_code_through_git(self):
        self.write("001-a/job.json", "{}")
        for key, value in (("filter.x.clean", "cat"), ("credential.helper", "!true")):
            with self.subTest(key=key):
                git(self.p.root, "config", key, value)
                self.assertFalse(self.call(self.runner.save_state))
                self.assertIn(f"sets {key}", (self.p.root / "factory/jobs/runner.log").read_text())
                git(self.p.root, "config", "--unset", key)
        hook = self.p.git_dir / "hooks" / "pre-push"
        hook.parent.mkdir(exist_ok=True)
        hook.write_text("#!/bin/sh\nexit 0\n")
        hook.chmod(0o755)
        self.assertFalse(self.call(self.runner.save_state))
        self.assertEqual(git(self.tmp, "--git-dir", str(self.origin), "branch", "--list", "factory-state"), "")


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

    def test_token_comes_from_the_environment_and_leaves_it(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_OAUTH_TOKEN": "tok"}):
            self.assertEqual(self.runner.ci_token(), "tok")
            self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", os.environ)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
            self.assertIsNone(self.runner.ci_token())

    def test_missing_token_with_work_logs_the_secret_to_add(self):
        base, runner = self.runner.load_config()
        with mock.patch.object(self.runner, "chores"), mock.patch.object(self.runner, "has_work", return_value=True), \
                mock.patch.object(self.runner, "run_claude") as run_claude:
            self.assertEqual(self.runner.tick_body(base, runner, ""), 1)
        run_claude.assert_not_called()
        self.assertIn("CLAUDE_CODE_OAUTH_TOKEN isn't set; add the FACTORY_CLAUDE_TOKEN secret",
                      (self.p.root / "factory/jobs/runner.log").read_text())

    def test_plain_tick_on_github_actions_still_reads_the_platform_token(self):
        base, runner = self.runner.load_config()
        with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}), mock.patch.object(self.runner, "chores"), \
                mock.patch.object(self.runner, "has_work", return_value=True), \
                mock.patch.object(self.runner, "read_token", return_value="tok") as read_token, \
                mock.patch.object(self.runner, "missing_sandbox_tools", return_value=[]), \
                mock.patch.object(self.runner, "run_claude", return_value=(0, 1)) as run_claude:
            self.assertEqual(self.runner.tick_body(base, runner, None), 0)
        read_token.assert_called_once()
        self.assertEqual(run_claude.call_args.args[0], "tok")


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

    def test_check_runner_swaps_token_and_scheduler_checks_for_state_checks(self):
        with mock.patch.object(self.doctor, "platform_name", return_value="Linux"), \
                mock.patch.dict(os.environ, {"PATH": str(self.tmp / "nothing")}):
            messages = [message for _, message in self.doctor.check_runner()]
        self.assertIn("no Actions workflow; /factory-install writes it", messages)
        self.assertFalse([m for m in messages if "token" in m or "timer" in m or "linger" in m or "bwrap" in m], messages)
